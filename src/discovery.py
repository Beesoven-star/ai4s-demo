"""Local discovery records, independent of LLM, fetch and push jobs.

Dates and provenance deliberately stay separate: a missing publication date is
never replaced with an import date. Upserts enrich an existing record and retain
its first metadata, with each distinct source record kept for later inspection.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
LOCAL_TZ = timezone(timedelta(hours=8))
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ARRAY_FIELDS = ("topics", "methods", "views", "tasks")
_RESERVED_FIELDS = {"id", "origin", "created_at", "updated_at", "source_records", "library"}
_OBSERVATION_FIELDS = {"collected_at", "collected_on", "fetched_at", "observed_at", "retrieved_at", "created_at", "updated_at"}


def _now() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _path(db_path=None) -> Path:
    configured = db_path or os.environ.get("DNEWS_DISCOVERY_DB")
    return Path(configured) if configured else ROOT / "news-data" / "discovery.sqlite"


def _connect(db_path=None) -> sqlite3.Connection:
    path = _path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS discovery_items (
            id TEXT PRIMARY KEY,
            content_type TEXT NOT NULL,
            origin TEXT NOT NULL,
            title TEXT NOT NULL,
            published_date TEXT,
            collected_date TEXT NOT NULL,
            search_text TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS discovery_aliases (
            identity_key TEXT PRIMARY KEY,
            item_id TEXT NOT NULL REFERENCES discovery_items(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS discovery_alias_item ON discovery_aliases(item_id);
        CREATE INDEX IF NOT EXISTS discovery_published ON discovery_items(published_date);
        CREATE INDEX IF NOT EXISTS discovery_collected ON discovery_items(collected_date);
        CREATE TABLE IF NOT EXISTS discovery_removed_items (
            id TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            removed_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            aliases TEXT NOT NULL,
            personal_record TEXT
        );
        CREATE TABLE IF NOT EXISTS discovery_removed_aliases (
            identity_key TEXT PRIMARY KEY,
            item_id TEXT NOT NULL REFERENCES discovery_removed_items(id)
        );
        CREATE TABLE IF NOT EXISTS personal_library (
            item_id TEXT PRIMARY KEY REFERENCES discovery_items(id) ON DELETE CASCADE,
            is_favorite INTEGER NOT NULL DEFAULT 0 CHECK(is_favorite IN (0,1)),
            notes TEXT NOT NULL DEFAULT '',
            reading_status TEXT NOT NULL DEFAULT 'unread'
                CHECK(reading_status IN ('unread','reading','read','follow_up')),
            personal_tags TEXT NOT NULL DEFAULT '[]',
            saved_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS discovery_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        """
    )
    return conn


def _validate_date(value: str | None, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError(f"{name} 必须是 YYYY-MM-DD 日期")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} 不是有效日期") from exc
    return value


def _publication_date(raw: Any) -> str | None:
    if not raw:
        return None
    value = str(raw).strip()
    # Preserve the source's calendar date; it may be a date without a time zone.
    if len(value) > 10 and value[10] in "T ":
        value = value[:10]
    return _validate_date(value, "published_at")


def _collection_time(raw: Any) -> str:
    if not raw:
        return _now()
    value = str(raw).strip()
    if _DATE.fullmatch(value):
        # Legacy date-only collection evidence is retained separately; the
        # actual import supplies a real timestamp instead of inventing a time.
        return _now()
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("collected_at 必须为 ISO 8601 时间") from exc
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=LOCAL_TZ)
    return timestamp.isoformat(timespec="seconds")


def normalize_url(raw: str) -> str:
    parts = urlsplit(str(raw).strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("url 必须是 HTTP 或 HTTPS 原文链接")
    if parts.username is not None or parts.password is not None:
        raise ValueError("url 不应包含登录凭据")
    hostname = parts.hostname.lower()
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("url 端口无效") from exc
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port and not ((parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)):
        netloc += f":{port}"
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_"))
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", urlencode(query), ""))


def normalize_doi(raw: Any) -> str | None:
    if not raw:
        return None
    value = unquote(str(raw).strip())
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    if not re.match(r"^10\.\d{4,9}/\S+$", value, re.I):
        raise ValueError("doi 标识无效")
    return value.lower()


def normalize_arxiv(raw: Any) -> str | None:
    if not raw:
        return None
    value = str(raw).strip()
    value = re.sub(r"^arxiv:\s*", "", value, flags=re.I)
    value = re.sub(r"^https?://(?:export\.)?arxiv\.org/(?:abs|pdf)/", "", value, flags=re.I)
    value = re.sub(r"\.pdf$", "", value, flags=re.I)
    value = re.sub(r"v\d+$", "", value)
    if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})", value):
        raise ValueError("arxiv_id 标识无效")
    return value


def _strings(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("分类与标签必须为字符串数组")
    result = []
    for item in raw:
        if isinstance(item, str) and item.strip() and item.strip() not in result:
            result.append(item.strip())
    return result


def _prepare(record: dict, origin: str) -> tuple[dict, list[str], dict]:
    if not isinstance(record, dict):
        raise ValueError("每条资料必须为对象")
    if origin not in {"seed", "collected"}:
        raise ValueError("origin 必须为 seed 或 collected")
    raw = deepcopy(record)
    item = {k: v for k, v in deepcopy(record).items() if k not in _RESERVED_FIELDS}
    kind = item.get("content_type")
    if kind not in {"paper", "news"}:
        raise ValueError("content_type 必须为 paper 或 news")
    item["title"] = str(item.get("title") or "").strip()
    if not item["title"]:
        raise ValueError("title 不能为空")
    item["url"] = normalize_url(item.get("url") or item.get("link") or "")
    item["source"] = str(item.get("source") or "未提供来源").strip()
    if item.get("journal"):
        item.setdefault("venue_name", item["journal"])
        item.setdefault("venue_type", "journal")
    item["origin"] = origin
    item["sample_role"] = item.get("sample_role") or ("live" if origin == "collected" else "reference_sample")
    publication = item.get("published_at")
    if publication and re.fullmatch(r"\d{4}", str(publication).strip()):
        item["publication_year"] = int(publication)
        item["date_kind"] = "year_only"
        publication = None
    item["published_at"] = _publication_date(publication)
    item["collected_at"] = _collection_time(item.get("collected_at") or item.get("fetched_at"))
    item["date_kind"] = item.get("date_kind") or ("source_publication" if item["published_at"] else "unknown")
    item["summary"] = str(item.get("summary") or "")
    item["summary_kind"] = item.get("summary_kind") or ("human" if origin == "seed" else "source")
    item["abstract_text"] = item.get("abstract_text") or None
    item["verification_note"] = str(item.get("verification_note") or "")
    item["relevance"] = item.get("relevance") or "unreviewed"
    for field in _ARRAY_FIELDS:
        item[field] = _strings(item.get(field))

    doi = item.get("doi")
    arxiv = item.get("arxiv_id")
    if kind == "paper":
        parts = urlsplit(item["url"])
        if not doi and parts.hostname in {"doi.org", "dx.doi.org"}:
            doi = parts.path.lstrip("/")
        if not arxiv and parts.hostname in {"arxiv.org", "export.arxiv.org"}:
            arxiv = item["url"].split("?", 1)[0]
    item["doi"] = normalize_doi(doi)
    item["arxiv_id"] = normalize_arxiv(arxiv)
    # News can cite a paper DOI, but remains a distinct news record.
    aliases = [f"{kind}:url:{item['url']}"]
    if kind == "paper":
        if item["doi"]:
            aliases.insert(0, f"paper:doi:{item['doi']}")
        if item["arxiv_id"]:
            aliases.insert(1 if item["doi"] else 0, f"paper:arxiv:{item['arxiv_id']}")
    item["source_record_id"] = raw.get("id")
    provenance = {"origin": origin, "record": raw}
    return item, aliases, provenance


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _evidence_signature(provenance: dict) -> str:
    # Re-fetching the same source changes observation times, not the evidence.
    # Keep the first complete raw snapshot; store another only for changed
    # source content. Publication dates remain part of this comparison.
    comparable = deepcopy(provenance)
    if isinstance(comparable.get("record"), dict):
        comparable["record"] = {key: value for key, value in comparable["record"].items() if key not in _OBSERVATION_FIELDS}
    return _json(comparable)


def _merge(existing: dict, incoming: dict, provenance: dict | None = None) -> dict:
    merged = deepcopy(existing)
    formal_upgrade = (incoming.get('publication_status') in {'journal_metadata', 'conference_metadata'}
                       and existing.get('venue_type') == 'preprint')
    # Keep the first nonempty metadata. New sources may enrich missing fields;
    # their complete differing records remain available in source_records.
    for key, value in incoming.items():
        if key in _RESERVED_FIELDS or key in _OBSERVATION_FIELDS:
            continue
        if key in _ARRAY_FIELDS:
            merged[key] = list(dict.fromkeys(_strings(merged.get(key)) + _strings(value)))
        elif _is_empty(merged.get(key)) and not _is_empty(value):
            merged[key] = deepcopy(value)
    if incoming.get("origin") == "collected":
        merged["origin"] = "collected"
        merged["sample_role"] = "live"
    if formal_upgrade:
        merged['preprint_first_submitted_at'] = existing.get('published_at')
        for key in ('source','url','journal','venue_name','venue_type','publication_status','published_at',
                    'publication_year','publication_month','date_kind','publication_dates','publisher','conference_year'):
            merged[key] = deepcopy(incoming.get(key))
        if incoming.get('abstract_text'):
            merged['abstract_text'] = incoming['abstract_text']
            merged['summary'] = incoming.get('summary', incoming['abstract_text'])
    merged.setdefault("collected_at", incoming.get("collected_at") or _now())
    records = merged.setdefault("source_records", [])
    if provenance and all(_evidence_signature(entry) != _evidence_signature(provenance) for entry in records):
        records.append(provenance)
    return merged


def _write_item(conn: sqlite3.Connection, item: dict) -> None:
    search_text = " ".join(
        str(item.get(field) or "")
        for field in ("title", "summary", "abstract_text", "source", "journal", "venue_name", "conference_year", "track", "doi", "arxiv_id", "topics", "methods", "views", "tasks")
    ).lower()
    collected_day = datetime.fromisoformat(item["collected_at"]).astimezone(LOCAL_TZ).date().isoformat()
    conn.execute(
        """INSERT INTO discovery_items
        (id,content_type,origin,title,published_date,collected_date,search_text,payload,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET content_type=excluded.content_type,
        origin=excluded.origin,title=excluded.title,published_date=excluded.published_date,
        collected_date=excluded.collected_date,search_text=excluded.search_text,
        payload=excluded.payload,updated_at=excluded.updated_at""",
        (item["id"], item["content_type"], item["origin"], item["title"], item.get("published_at"), collected_day,
         search_text, _json(item), item["created_at"], item["updated_at"]),
    )


def upsert_items(items, origin="seed", db_path=None) -> dict:
    inserted = updated = skipped_removed = 0
    conn = _connect(db_path)
    try:
        with conn:
            for raw in items:
                incoming, aliases, provenance = _prepare(raw, origin)
                placeholders = ",".join("?" for _ in aliases)
                if conn.execute(f"SELECT 1 FROM discovery_removed_aliases WHERE identity_key IN ({placeholders}) LIMIT 1",aliases).fetchone():
                    skipped_removed += 1
                    continue
                rows = conn.execute(
                    f"""SELECT DISTINCT i.* FROM discovery_items i
                    JOIN discovery_aliases a ON a.item_id=i.id
                    WHERE a.identity_key IN ({placeholders}) ORDER BY i.created_at,i.id""", aliases,
                ).fetchall()
                if rows:
                    existing = json.loads(rows[0]["payload"])
                    item = _merge(existing, incoming, provenance)
                    # A later record can connect a preprint and a DOI record.
                    # Preserve all metadata/provenance and aliases in one item.
                    for duplicate in rows[1:]:
                        other = json.loads(duplicate["payload"])
                        item = _merge(item, other)
                        for evidence in other.get("source_records", []):
                            item = _merge(item, {}, evidence)
                        conn.execute("UPDATE discovery_aliases SET item_id=? WHERE item_id=?", (item["id"], other["id"]))
                        _merge_personal_records(conn, item["id"], other["id"])
                        conn.execute("DELETE FROM discovery_items WHERE id=?", (other["id"],))
                    if _json(item) != _json(existing) or len(rows) > 1:
                        item["updated_at"] = _now()
                        _write_item(conn, item)
                        updated += 1
                else:
                    stamp = _now()
                    item = incoming
                    item["id"] = hashlib.sha256(aliases[0].encode("utf-8")).hexdigest()[:24]
                    item["created_at"] = item["updated_at"] = stamp
                    item["source_records"] = [provenance]
                    _write_item(conn, item)
                    inserted += 1
                for identity in aliases:
                    conn.execute("INSERT OR IGNORE INTO discovery_aliases(identity_key,item_id) VALUES (?,?)", (identity, item["id"]))
            total = conn.execute("SELECT COUNT(*) FROM discovery_items").fetchone()[0]
        result = {"inserted": inserted, "updated": updated, "total": total}
        if skipped_removed:
            result['skipped_removed'] = skipped_removed
        return result
    finally:
        conn.close()


def remove_items(item_ids, reason, db_path=None) -> dict:
    """Move explicitly selected records out of the active library, reversibly.

    Identity exclusions stop subsequent collection from silently restoring them.
    All metadata, aliases and any personal record stay in a local recovery table.
    """
    if not isinstance(reason,str) or not reason.strip():
        raise ValueError('移出资料需要说明原因')
    identities=list(dict.fromkeys(str(identity) for identity in item_ids))
    conn=_connect(db_path)
    removed=0
    try:
        with conn:
            for identity in identities:
                row=conn.execute('SELECT payload FROM discovery_items WHERE id=?',(identity,)).fetchone()
                if row is None:
                    continue
                aliases=[entry[0] for entry in conn.execute('SELECT identity_key FROM discovery_aliases WHERE item_id=?',(identity,))]
                personal=conn.execute('SELECT * FROM personal_library WHERE item_id=?',(identity,)).fetchone()
                conn.execute('INSERT INTO discovery_removed_items(id,reason,removed_at,payload,aliases,personal_record) VALUES (?,?,?,?,?,?)',
                    (identity,reason.strip(),_now(),row['payload'],_json(aliases),_json(dict(personal)) if personal else None))
                conn.executemany('INSERT INTO discovery_removed_aliases(identity_key,item_id) VALUES (?,?)',[(alias,identity) for alias in aliases])
                conn.execute('DELETE FROM discovery_items WHERE id=?',(identity,))
                removed+=1
            total=conn.execute('SELECT COUNT(*) FROM discovery_items').fetchone()[0]
        return {'removed':removed,'total':total}
    finally:
        conn.close()


def import_seed_file(path, db_path=None) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data.get("items") if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise ValueError("样本文件必须包含 items 数组")
    return upsert_items(records, origin="seed", db_path=db_path)


def personal_record(row=None):
    if row is None:
        return {"is_favorite": False, "notes": "", "reading_status": "unread", "personal_tags": [], "saved_at": None, "updated_at": None}
    return {"is_favorite": bool(row["is_favorite"]), "notes": row["notes"],
            "reading_status": row["reading_status"], "personal_tags": json.loads(row["personal_tags"]),
            "saved_at": row["saved_at"], "updated_at": row["updated_at"]}


def _merge_personal_records(conn, target, duplicate):
    """Identity reconciliation must preserve notes from both old records."""
    other = conn.execute("SELECT * FROM personal_library WHERE item_id=?", (duplicate,)).fetchone()
    if other is None:
        return
    current = conn.execute("SELECT * FROM personal_library WHERE item_id=?", (target,)).fetchone()
    if current is None:
        conn.execute("UPDATE personal_library SET item_id=? WHERE item_id=?", (target, duplicate))
        return
    latest = max([current, other], key=lambda r: r["updated_at"])
    notes = list(dict.fromkeys(r["notes"] for r in [current, other] if r["notes"]))
    tags = list(dict.fromkeys(json.loads(current["personal_tags"]) + json.loads(other["personal_tags"])))
    saved = [r["saved_at"] for r in [current, other] if r["saved_at"]]
    conn.execute("""UPDATE personal_library SET is_favorite=?,notes=?,reading_status=?,
        personal_tags=?,saved_at=?,updated_at=? WHERE item_id=?""",
        (int(current["is_favorite"] or other["is_favorite"]), "\n\n—— 合并资料的备注 ——\n\n".join(notes),
         latest["reading_status"], _json(tags), min(saved) if saved else None, _now(), target))


def _with_personal_records(conn, rows):
    items = [json.loads(row["payload"]) for row in rows]
    if not items:
        return items
    records = {r["item_id"]: r for r in conn.execute(
        "SELECT * FROM personal_library WHERE item_id IN (" + ",".join("?" for _ in items) + ")",
        [item["id"] for item in items])}
    for item in items:
        item["library"] = personal_record(records.get(item["id"]))
        if os.environ.get('DNEWS_RESEARCH_DOMAIN') == 'ic':
            from src.ic_research import analyze
            item['ic_ai'] = analyze(item)
            from src.publication_timing import assess
            item['publication_timing'] = assess(item)
    return items


def list_items(q="", content_type=None, topic=None, date_from=None, date_to=None,
               date_basis="published", origin=None, limit=20, offset=0, db_path=None, venue=None, publication_kind=None, research_track=None, literature_scope=None, publication_period=None, news_scope=None) -> dict:
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")
    if date_from and date_to and date_from > date_to:
        raise ValueError("起始日期不能晚于结束日期")
    if date_basis not in {"published", "collected"}:
        raise ValueError("date_basis 必须为 published 或 collected")
    if content_type not in {None, "", "paper", "news"}:
        raise ValueError("content_type 必须为 paper 或 news")
    if origin not in {None, "", "seed", "collected"}:
        raise ValueError("origin 必须为 seed 或 collected")
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit 必须在 1 至 100 之间")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 不能为负数")
    clauses, values = [], []
    if news_scope not in {None,'','main','all','archive'}:
        raise ValueError('新闻范围无效')
    if not news_scope and os.environ.get('DNEWS_RESEARCH_DOMAIN')=='ic' and content_type=='news':news_scope='main'
    if news_scope and news_scope!='all':
        clauses.extend(["content_type='news'","COALESCE(json_extract(payload,'$.news_scope'),'main')=?"])
        values.append(news_scope)
    if research_track not in {None,'','any_ai','ai_for_ic','ic_for_ai','general_ic','unconfirmed'}:
        raise ValueError('研究主线无效')
    from src.ic_research import BY_NAME, matches as ic_matches, scope_matches
    from src.publication_timing import matches as period_matches, LABELS
    if literature_scope not in {None,'','main','all','archive','pending','excluded'}:
        raise ValueError('文献范围无效')
    if publication_period and publication_period not in LABELS:
        raise ValueError('发表时间分类无效')
    if not literature_scope and os.environ.get('DNEWS_RESEARCH_DOMAIN')=='ic' and content_type=='paper':
        literature_scope='all' if research_track=='unconfirmed' else 'main'
    if literature_scope and literature_scope!='all':
        clauses.extend(["content_type='paper'",'ic_scope_matches(payload,?)=1'])
        values.append(literature_scope)
    if publication_period:
        clauses.extend(["content_type='paper'",'publication_period_matches(payload,?)=1'])
        values.append(publication_period)
        if literature_scope!='excluded':
            clauses.append("ic_scope_matches(payload,'excluded')=0")
    ic_topic = BY_NAME.get(str(topic)) if topic else None
    if research_track or ic_topic:
        clauses.append('ic_research_matches(payload,?,?)=1')
        clauses.append("content_type='paper'")
        values.extend([research_track or '', ic_topic['id'] if ic_topic else ''])
    if publication_kind:
        if publication_kind not in {'journal','conference','preprint'}:
            raise ValueError('出版形式无效')
        clauses.append("json_extract(payload,'$.venue_type')=?")
        values.append(publication_kind)
    if q and str(q).strip():
        search = str(q).strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # Include venue metadata on older records without rebuilding their text index.
        clauses.append("(search_text LIKE ? ESCAPE '\\' OR lower(COALESCE(json_extract(payload,'$.journal'),'') || ' ' || COALESCE(json_extract(payload,'$.venue_name'),'')) LIKE ? ESCAPE '\\')")
        values.extend([f"%{search}%", f"%{search}%"])
    if venue and str(venue).strip():
        clauses.append("COALESCE(NULLIF(json_extract(payload,'$.venue_name'),''), json_extract(payload,'$.journal'))=?")
        values.append(str(venue).strip())
    for field, value in (("content_type", content_type), ("origin", origin)):
        if value:
            clauses.append(f"{field}=?")
            values.append(value)
    if topic and str(topic).strip() and not ic_topic:
        clauses.append("EXISTS (SELECT 1 FROM json_each(discovery_items.payload,'$.topics') WHERE value=?)")
        values.append(str(topic).strip())
    date_column = "published_date" if date_basis == "published" else "collected_date"
    if date_from:
        clauses.append(f"{date_column}>=?")
        values.append(date_from)
    if date_to:
        clauses.append(f"{date_column}<=?")
        values.append(date_to)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    conn = _connect(db_path)
    try:
        conn.create_function('ic_research_matches',3,ic_matches,deterministic=True)
        conn.create_function('ic_scope_matches',2,scope_matches,deterministic=True)
        conn.create_function('publication_period_matches',2,period_matches)
        total = conn.execute("SELECT COUNT(*) FROM discovery_items" + where, values).fetchone()[0]
        rows = conn.execute(
            "SELECT payload FROM discovery_items" + where + f" ORDER BY {date_column} DESC,created_at DESC,id LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
        return {"items": _with_personal_records(conn, rows), "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


def get_item(item_id, db_path=None) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT payload FROM discovery_items WHERE id=?", (str(item_id),)).fetchone()
        return _with_personal_records(conn, [row])[0] if row else None
    finally:
        conn.close()


def get_facets(db_path=None) -> dict:
    today = _now()[:10]
    conn = _connect(db_path)
    try:
        totals = conn.execute("""SELECT COUNT(*) AS total,
            COALESCE(SUM(content_type='paper'),0) AS papers,
            COALESCE(SUM(content_type='news'),0) AS news,
            COALESCE(SUM(origin='seed'),0) AS seed,
            COALESCE(SUM(origin='collected'),0) AS collected,
            COALESCE(SUM(collected_date=?),0) AS new_today,
            COALESCE(SUM(collected_date=? AND content_type='paper'),0) AS papers_today,
            COALESCE(SUM(collected_date=? AND content_type='news'),0) AS news_today
            FROM discovery_items""", (today, today, today)).fetchone()
        topics = conn.execute("""SELECT DISTINCT j.value FROM discovery_items i,
            json_each(i.payload,'$.topics') j ORDER BY j.value""").fetchall()
        venues = conn.execute("""SELECT DISTINCT
            COALESCE(NULLIF(json_extract(payload,'$.venue_name'),''), json_extract(payload,'$.journal')) AS venue
            FROM discovery_items ORDER BY venue""").fetchall()
        result = {**dict(totals), "today": today, "topics": [row[0] for row in topics], "venues": [row[0] for row in venues if row[0]]}
        if os.environ.get('DNEWS_RESEARCH_DOMAIN') == 'ic':
            from src.ic_research import TOPICS, TRACKS, analyze, scope_of
            from src.publication_timing import statistics
            from collections import Counter
            papers=[json.loads(row[0]) for row in conn.execute("SELECT payload FROM discovery_items WHERE content_type='paper'")]
            scopes=Counter(scope_of(analyze(paper)) for paper in papers)
            result.update(domain='ic', topics=[topic['name'] for topic in TOPICS], research_tracks=TRACKS)
            valid=[paper for paper in papers if scope_of(analyze(paper))!='excluded']
            audit=statistics(valid)
            audit['collection_days']=dict(sorted(Counter(paper.get('collected_at','')[:10] for paper in papers).items()))
            result.update(literature_scopes=dict(scopes),publication_audit=audit,
                main_papers=scopes['main'],archive_papers=scopes['archive'],pending_papers=scopes['pending'],excluded_papers=scopes['excluded'])
            archived=conn.execute("SELECT COUNT(*) FROM discovery_items WHERE content_type='news' AND json_extract(payload,'$.news_scope')='archive'").fetchone()[0]
            result.update(news_candidates=result['news'],archived_news=archived,news=result['news']-archived)
        return result
    finally:
        conn.close()


def record_run(run, db_path=None) -> int:
    data = deepcopy(run)
    if data.get("status") not in {"success", "no_results", "failed"}:
        raise ValueError("采集状态必须为 success、no_results 或 failed")
    if not data.get("source_id") or not data.get("source_name"):
        raise ValueError("采集记录需要来源 ID 和名称")
    data["started_at"] = _collection_time(data.get("started_at"))
    data["finished_at"] = _collection_time(data.get("finished_at"))
    for field in ("found", "inserted", "updated"):
        data[field] = int(data.get(field) or 0)
        if data[field] < 0:
            raise ValueError("采集计数不能为负数")
    for field in ("window_start", "window_end"):
        data[field] = _validate_date(data.get(field), field)
    data["error"] = str(data.get("error") or "")
    conn = _connect(db_path)
    try:
        with conn:
            cursor = conn.execute("INSERT INTO discovery_runs(started_at,payload) VALUES (?,?)", (data["started_at"], _json(data)))
            return cursor.lastrowid
    finally:
        conn.close()


def list_runs(limit=10, db_path=None) -> list[dict]:
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit 必须在 1 至 100 之间")
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT id,payload FROM discovery_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**json.loads(row["payload"]), "id": row["id"]} for row in rows]
    finally:
        conn.close()
