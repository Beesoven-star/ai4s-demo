"""Collect a bounded set of public molecular-research records without LLM calls.

Examples (run in the project root):
    .venv/Scripts/python.exe scripts/collect_discovery.py --seed-file ../研究样本/首批核验样本.json --seed-only
    .venv/Scripts/python.exe scripts/collect_discovery.py --days 30
    .venv/Scripts/python.exe scripts/collect_discovery.py --days 90 --sources deepmodeling

This is an explicit, single collection run, not a scheduler. It records empty
results separately from source failures and does not initiate push/sync jobs.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urljoin
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.abstract_text import clean_abstract
from src.discovery_lock import FileLock, execution_lock_path

LOCAL_TZ = timezone(timedelta(hours=8))
USER_AGENT = "AI4SResearchWorkbench/0.1 (public metadata; bounded research discovery)"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: Any) -> str:
    parser = _TextParser()
    parser.feed(str(value or ""))
    return re.sub(r"\s+", " ", unescape("".join(parser.parts))).strip()


def parse_date(value: Any, *, target_timezone: timezone | None = None) -> str | None:
    """Convert zoned timestamps when requested. Preserve date-only and unzoned values."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}(?:T|\s|$)", value):
            if target_timezone is None or len(value) == 10:
                return date.fromisoformat(value[:10]).isoformat()
            timestamp = datetime.fromisoformat(value)
        else:
            timestamp = parsedate_to_datetime(value)
        if target_timezone is not None and timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(target_timezone)
        return timestamp.date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def in_window(item: dict, start: date, end: date) -> bool:
    raw = item.get("published_at")
    if raw is None:
        month = item.get("publication_month")
        if month:
            return start.strftime('%Y-%m') <= month <= end.strftime('%Y-%m')
        # Keep undated candidates, clearly marked; date-based queries exclude them.
        return True
    try:
        return start <= date.fromisoformat(raw) <= end
    except (TypeError, ValueError):
        return False


def is_relevant(title: str, summary: str, rules: dict) -> bool:
    text = f"{title} {summary}".casefold()
    domain = any(term.casefold() in text for term in rules["domain_terms"])
    method = any(term.casefold() in text for term in rules["method_terms"])
    return domain and method


def title_has_molecular_task(title: str) -> bool:
    """Crossref fuzzy search also returns biomedical profiling; require a task."""
    text = title.casefold()
    markers = ("molecular representation", "molecular property", "molecular properties", "molecular pretrain", "molecular pre-train", "molecular foundation", "molecule representation", "chemical language", "smiles")
    return any(marker in text for marker in markers)


def _safe_url(value: str) -> str:
    return value if urlparse(value).scheme.lower() in {"http", "https"} else ""


def _feed_value(node: ET.Element, *names: str) -> str:
    for name in names:
        child = node.find(name, NS)
        if child is None and not name.startswith("{") and ":" not in name:
            # RSS 1.0 uses a default namespace; RSS 2.0 usually does not.
            child = next((n for n in node if n.tag.rsplit("}", 1)[-1] == name), None)
        if child is not None:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _feed_markup(node: ET.Element, *names: str) -> str:
    """Retain heading and paragraph boundaries until abstract normalization."""
    for name in names:
        child = node.find(name, NS)
        if child is None and not name.startswith("{") and ":" not in name:
            child = next((n for n in node if n.tag.rsplit("}", 1)[-1] == name), None)
        if child is not None:
            markup = (child.text or "") + "".join(ET.tostring(n, encoding="unicode") for n in child)
            if markup.strip():
                return markup
    return ""


def _journal_venue(item: dict, source: dict) -> None:
    if not (source.get("kind") == "crossref_journal" or source.get("journal_required")):
        return
    if item.get("content_type") != "paper":
        return
    journal = item.get("journal") or source.get("journal_name") or source["name"]
    item.update({"journal": journal, "venue_type": "journal", "venue_name": journal})
    if source.get("issn"):
        item["issn"] = source["issn"]


def _feed_doi(node: ET.Element) -> str | None:
    for child in node:
        if child.tag.rsplit("}", 1)[-1] not in {"identifier", "doi"}:
            continue
        value = "".join(child.itertext()).strip()
        match = re.fullmatch(r"(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)", value, re.I)
        if match:
            return match.group(1)
    return None


def parse_feed(payload: bytes | str, source: dict, collected_at: str) -> list[dict]:
    root = ET.fromstring(payload)
    atom = root.tag == f"{{{NS['atom']}}}feed"
    if not atom and root.tag.rsplit("}", 1)[-1].lower() not in {"rss", "rdf", "rdf:rdf"}:
        raise ValueError("来源未返回可识别的 Atom/RSS 文档")
    nodes = root.findall("atom:entry", NS) if atom else [n for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "item"]
    publication_timezone = LOCAL_TZ if source["content_type"] == "news" else None
    results = []
    for node in nodes:
        raw_id = _feed_value(node, "atom:id") if atom else ""
        if source["kind"] == "arxiv" and "/api/errors" in raw_id:
            detail = plain_text(_feed_value(node, "atom:summary", "atom:title"))
            raise ValueError("arXiv 返回查询错误: " + detail[:240])
        title = plain_text(_feed_value(node, "atom:title" if atom else "title"))
        if atom:
            links = node.findall("atom:link", NS)
            url = next((n.get("href", "") for n in links if n.get("rel", "alternate") == "alternate"), "")
            raw_date = _feed_value(node, "atom:published")
            # Updated is not silently treated as publication time.
            markup = _feed_markup(node, "atom:summary", "atom:content")
        else:
            url = _feed_value(node, "link")
            raw_date = _feed_value(node, "pubDate", "{http://purl.org/dc/elements/1.1/}date")
            markup = _feed_markup(node, "description", "{http://purl.org/rss/1.0/modules/content/}encoded")
        abstract = clean_abstract(markup) if source["content_type"] == "paper" else plain_text(markup)
        if source["content_type"] == "news":
            words = abstract.split()
            abstract = " ".join(words[:140]) + (" …" if len(words) > 140 else "")
        url = _safe_url(url)
        if not title or not url:
            continue
        published = parse_date(raw_date, target_timezone=publication_timezone)
        item = {
            "title": title, "url": url, "source": source["name"],
            "content_type": source["content_type"], "sample_role": "live",
            "published_at": published, "date_kind": "source_published" if published else "unknown",
            "collected_at": collected_at, "summary": abstract[:1200],
            "abstract_text": abstract or None, "summary_kind": "source",
            "topics": [], "methods": [], "views": [], "relevance": "pending",
            "verification_note": "题名及已提供的摘要来自来源订阅。",
        }
        if not published:
            item["verification_note"] += " 订阅未提供可用的首次发表日期。"
        if source["content_type"] == "news":
            item.update(news_genre=source.get('news_genre', '新闻与研究动态'), date_kind='news_published' if published else 'unknown')
            item['verification_note'] = '收录来源提供的标题和简介。' + ('发表日期取自订阅。' if published else '来源未提供可解析的首次发表日期。')
        if source.get("journal_required") and item["content_type"] == "paper":
            item["journal"] = plain_text(_feed_value(node, "publicationName")) or source.get("journal_name")
        doi = _feed_doi(node)
        if doi:
            item["doi"] = doi
        _journal_venue(item, source)
        if source["kind"] == "arxiv":
            arxiv_id = raw_id.rsplit("/abs/", 1)[-1]
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
            if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})", arxiv_id):
                item["arxiv_id"] = arxiv_id
                item["url"] = f"https://arxiv.org/abs/{arxiv_id}"
            doi = _feed_value(node, "arxiv:doi")
            if doi:
                item["doi"] = doi
            item["date_kind"] = "arxiv_first_submission" if published else "unknown"
            item["authors"] = [n.findtext("atom:name", default="", namespaces=NS) for n in node.findall("atom:author", NS)]
            item["publication_status"] = "preprint_record"
            item["updated_at_source"] = _feed_value(node, "atom:updated") or None
        results.append(item)
    return results


def _crossref_date(record: dict) -> tuple[str | None, str, int | None]:
    year_only = None
    for key in ("published-online", "published", "published-print", "issued"):
        parts = (record.get(key) or {}).get("date-parts", [])
        parts = parts[0] if parts else []
        if parts and isinstance(parts[0], int):
            year_only = year_only or parts[0]
        if len(parts) >= 3:
            try:
                return date(*parts[:3]).isoformat(), f"crossref_{key}", parts[0]
            except (TypeError, ValueError):
                pass
        elif len(parts) == 2 and all(isinstance(p, int) for p in parts) and 1 <= parts[1] <= 12:
            return None, f"crossref_{key}_month", parts[0]
    return None, "year_only" if year_only else "unknown", year_only


def _crossref_message(payload: bytes | str) -> dict:
    response = json.loads(payload)
    if not isinstance(response, dict) or response.get("status") != "ok" or not isinstance(response.get("message"), dict):
        raise ValueError("Crossref 返回格式异常，不能视为成功的空结果")
    message = response["message"]
    if not isinstance(message.get("items"), list) or any(not isinstance(item, dict) for item in message["items"]):
        raise ValueError("Crossref 返回格式异常，不能视为成功的空结果")
    return message


def parse_crossref(payload: bytes | str, source: dict, collected_at: str) -> list[dict]:
    message = _crossref_message(payload)
    results = []
    for record in message["items"]:
        if source.get('kind') == 'crossref_conference':
            venue = plain_text(' '.join(record.get('container-title') or []))
            if (record.get('type') != 'proceedings-article'
                or not any(re.search(pattern, venue, re.I) for pattern in source['venue_patterns'])
                or any(re.search(pattern, venue, re.I) for pattern in source.get('venue_exclude_patterns', []))):
                continue
        title = plain_text((record.get("title") or [""])[0])
        doi = str(record.get("DOI") or "").strip()
        url = _safe_url(f"https://doi.org/{doi}" if doi else str(record.get("URL") or ""))
        if not title or not url:
            continue
        abstract = clean_abstract(record.get("abstract", ""))
        published, date_kind, year = _crossref_date(record)
        item = {
            "title": title, "url": url, "source": source["name"],
            "journal": plain_text((record.get("container-title") or [""])[0]),
            "content_type": "paper", "sample_role": "live", "doi": doi or None,
            "published_at": published, "publication_year": year, "date_kind": date_kind,
            "collected_at": collected_at, "summary": abstract[:1200],
            "abstract_text": abstract or None, "summary_kind": "source",
            "topics": [], "methods": [], "views": [], "relevance": "pending",
            "authors": [" ".join(filter(None, [a.get("given"), a.get("family")])) for a in record.get("author", [])],
            "verification_note": "由 Crossref 公开元数据采集，原始出处为 DOI 链接；来源范围初筛，尚未核验全文。" + (" 来源未提供摘要。" if not abstract else ""),
        }
        _journal_venue(item, source)
        item['publication_dates'] = {key: record[key].get('date-parts') for key in
            ('published-online', 'published-print', 'published', 'issued') if isinstance(record.get(key), dict)}
        if date_kind.endswith('_month'):
            parts = record[date_kind[len('crossref_'):-len('_month')]]['date-parts'][0]
            item['publication_month'] = f'{parts[0]:04d}-{parts[1]:02d}'
            item['verification_note'] += ' 来源仅提供发表月份，具体日期未知，不计入精确日区间的近期发表数量。'
        if source.get('kind') == 'crossref_journal':
            item['publication_status'] = 'journal_metadata'
            item['publisher'] = record.get('publisher')
        elif source.get('kind') == 'crossref_conference':
            item.pop('journal', None)
            item.update(venue_type='conference', venue_name=venue,
                        publication_status='conference_metadata', publisher=record.get('publisher'))
            # The proceedings title is evidence for edition year; event dates
            # are not evidence for a paper's publication day.
            edition = re.search(r'\b(20\d{2})\b', venue)
            if edition:
                item['conference_year'] = int(edition.group(1))
        results.append(item)
    return results


class _NewsMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('property') or attrs.get('name') or ''] = attrs.get('content', '')


def parse_imec_article(payload, url, source, collected_at):
    text = payload.decode('utf-8') if isinstance(payload, bytes) else payload
    metadata = _NewsMetadata()
    metadata.feed(text)
    visible = plain_text(text)
    match = re.search(r'Published on\s*:\s*(\d{1,2}) ([A-Za-z]+) (\d{4})', visible)
    months = {name: i for i,name in enumerate(('January','February','March','April','May','June','July','August','September','October','November','December'), 1)}
    published = None
    if match and match[2] in months:
        published = date(int(match[3]), months[match[2]], int(match[1])).isoformat()
    heading = re.search(r'<h1\b[^>]*>(.*?)</h1>', text, re.I | re.S)
    title = plain_text(heading[1] if heading else metadata.meta.get('og:title') or '')
    description = plain_text(metadata.meta.get('og:description') or metadata.meta.get('description') or '')
    if not title or not published:
        raise ValueError('imec 文章缺少可核验的题名或 Published on 首次发布日期')
    return {'title':title, 'url':url, 'source':source['name'], 'content_type':'news',
            'published_at':published, 'date_kind':'news_published', 'collected_at':collected_at,
            'summary':description[:1200], 'abstract_text':description[:1200] or None, 'summary_kind':'source',
            'news_genre':'研究机构公告', 'topics':[], 'methods':[], 'views':[], 'relevance':'pending',
            'verification_note':'日期和简介来自 imec 的公开公告。文中进展和计划由 imec 披露。'}


def _collect_imec(source, collected_at, timeout, max_bytes, run_info):
    if source['url'] != 'https://www.imec-int.com/en/reading-room?type=press':
        raise ValueError('imec 来源需使用已核验的官方新闻目录')
    listing = request_bytes(source['url'], timeout, max_bytes).decode('utf-8')
    # Public Next.js page includes the visible article list as serialized data.
    paths = list(dict.fromkeys(re.findall(r'/en/press/[A-Za-z0-9][A-Za-z0-9_-]*', listing)))
    if not paths:
        raise ValueError('imec 目录没有返回可识别的公开文章链接，需检查页面结构')
    maximum = int(source.get('max_articles', 10))
    if not 1 <= maximum <= 30:
        raise ValueError('imec 每次读取上限应在1至30篇之间')
    items, errors = [], []
    for path in paths[:maximum]:
        url = urljoin('https://www.imec-int.com', path)
        time.sleep(.3)
        try:
            items.append(parse_imec_article(request_bytes(url, timeout, max_bytes), url, source, collected_at))
        except Exception as error:
            errors.append(f'{url}: {type(error).__name__}: {error}')
    if run_info is not None:
        run_info['coverage'] = {'visible_article_links':len(paths), 'articles_read':len(items),
            'max_articles':maximum, 'article_errors':errors, 'complete':False}
        run_info['coverage_warning'] = f'imec 仅检查当前目录前{min(maximum,len(paths))}篇可见公告，不保证完整历史。' + (f' {len(errors)}篇读取失败。' if errors else '')
    if errors and not items:
        raise ValueError('imec 文章读取全部失败: ' + errors[0][:250])
    return items


def request_bytes(url: str, timeout: int = 15, max_bytes: int = 6000000) -> bytes:
    if not _safe_url(url):
        raise ValueError("采集地址必须使用 HTTP(S)")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml,application/rss+xml,application/json,text/xml;q=0.9,*/*;q=0.5"})
    for attempt in range(2):
        try:
            with urlopen(request, timeout=timeout) as response:
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ValueError("来源响应超出本轮读取上限")
                return data
        except HTTPError as error:
            if attempt == 0 and error.code in {429, 502, 503, 504}:
                time.sleep(2)
                continue
            raise
        except (URLError, TimeoutError):
            if attempt == 0:
                time.sleep(1)
                continue
            raise
    raise RuntimeError("无法读取来源")


def _collect_crossref_journal(source: dict, start: date, end: date, collected_at: str,
                              timeout: int, max_bytes: int, run_info: dict) -> list[dict]:
    issn = str(source.get("issn") or "").strip().upper()
    endpoint = str(source.get("url") or "").rstrip("/")
    if not re.fullmatch(r"\d{4}-\d{3}[\dX]", issn) or endpoint != f"https://api.crossref.org/journals/{issn}/works":
        raise ValueError("期刊来源需要有效 ISSN 及对应的 Crossref /journals/{issn}/works 地址")
    rows = int(source.get("rows", source.get("max_results", 100)))
    max_pages = int(source.get("max_pages", 3))
    if not 1 <= rows <= 1000 or not 1 <= max_pages <= 100:
        raise ValueError("期刊分页 rows 必须在 1 至 1000 之间，max_pages 必须在 1 至 100 之间")
    coverage = {
        "issn": issn, "window_start": start.isoformat(), "window_end": end.isoformat(),
        "traversal_sort": "indexed",
        "rows": rows, "max_pages": max_pages, "pages_fetched": 0,
        "items_fetched": 0, "total_results": None, "complete": False, "stop_reason": "in_progress",
    }
    run_info["coverage"] = coverage
    items = []
    cursor = "*"
    used_cursors = set()
    for page in range(max_pages):
        if page:
            time.sleep(1)
        params = {
            "filter": f"from-pub-date:{start.isoformat()},until-pub-date:{end.isoformat()},type:journal-article",
            # Crossref rejects publication-date sorts when a cursor is used.
            "sort": "indexed", "order": "desc", "rows": rows, "cursor": cursor,
        }
        # Record partial progress even if a later request or response fails.
        coverage["stop_reason"] = "request_or_response_failed"
        payload = request_bytes(endpoint + "?" + urlencode(params), timeout, max_bytes)
        message = _crossref_message(payload)
        total = message.get("total-results")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0 or (total == 0 and message["items"]):
            raise ValueError("Crossref 期刊响应缺少有效 total-results，不能判定覆盖范围")
        batch = message["items"]
        coverage.update({"pages_fetched": page + 1, "items_fetched": coverage["items_fetched"] + len(batch), "total_results": total})
        items.extend(parse_crossref(payload, source, collected_at))
        if coverage["items_fetched"] >= total:
            coverage.update({"complete": True, "stop_reason": "total_results_reached"})
            break
        used_cursors.add(cursor)
        next_cursor = message.get("next-cursor")
        if not batch:
            coverage["stop_reason"] = "empty_page_before_total"
            break
        if not isinstance(next_cursor, str) or not next_cursor.strip():
            coverage["stop_reason"] = "missing_cursor_before_total"
            break
        if next_cursor in used_cursors:
            coverage["stop_reason"] = "repeated_cursor_before_total"
            break
        cursor = next_cursor
    else:
        coverage["stop_reason"] = "max_pages_reached"
    if not coverage["complete"]:
        reason = {
            "max_pages_reached": f"达到每源 {max_pages} 页的读取上限，结果已截断",
            "empty_page_before_total": "尚未读完总数即返回空页",
            "missing_cursor_before_total": "尚未读完总数但未返回后续游标",
            "repeated_cursor_before_total": "后续游标重复，已停止重复请求",
        }[coverage["stop_reason"]]
        run_info["coverage_warning"] = (
            f"{reason}；本轮仅读取期刊日期窗口内 {coverage['items_fetched']}/{coverage['total_results']} 条元数据，"
            "不能视为完整扫描；零条相关结果也不代表窗口内没有相关论文。"
        )
    return items


def _collect_crossref_conference(source, start, end, collected_at, timeout, max_bytes, run_info):
    if source.get('url') != 'https://api.crossref.org/works' or not source.get('venue_patterns'):
        raise ValueError('会议来源需要 Crossref works 接口及会议名称校验规则')
    rows, pages = int(source.get('rows', 100)), int(source.get('max_pages', 2))
    if not 1 <= rows <= 1000 or not 1 <= pages <= 10 or end.year - start.year > 2:
        raise ValueError('会议检索需要有界分页，日期范围最多跨三个年份')
    coverage = {'complete': False, 'queries': [], 'items_fetched': 0, 'venue_matched': 0}
    run_info['coverage'] = coverage
    items = []
    for year in range(start.year, end.year + 1):
        query = {'year': year, 'pages_fetched': 0, 'items_fetched': 0, 'total_results': None}
        coverage['queries'].append(query)
        for page in range(pages):
            if coverage['items_fetched']:
                time.sleep(3)
            params = {'query.container-title': f"{year} {source['conference_query']}",
                      'filter': f'from-pub-date:{start.isoformat()},until-pub-date:{end.isoformat()},type:proceedings-article',
                      'rows': rows, 'offset': page * rows}
            payload = request_bytes(source['url'] + '?' + urlencode(params), timeout, max_bytes)
            message = _crossref_message(payload)
            batch = message['items']
            query.update(pages_fetched=page+1, total_results=message.get('total-results'))
            query['items_fetched'] += len(batch)
            coverage['items_fetched'] += len(batch)
            matches = parse_crossref(payload, source, collected_at)
            items.extend(matches)
            coverage['venue_matched'] += len(matches)
            if len(batch) < rows:
                break
    run_info['coverage_warning'] = (
        f"会议题录采用有界检索，读取 {coverage['items_fetched']} 条候选，"
        f"其中 {coverage['venue_matched']} 条通过会议名称校验；不代表完整论文集，零结果也不代表该会议没有论文。")
    return items


def collect_source(source: dict, settings: dict, start: date, end: date, collected_at: str,
                   run_info: dict | None = None) -> list[dict]:
    timeout = int(settings.get("timeout_seconds", 15))
    max_bytes = int(settings.get("max_response_bytes", 6000000))
    kind = source["kind"]
    items = []
    if kind == "arxiv":
        query = source["query"] + f" AND submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]"
        params = {"search_query": query, "start": 0, "max_results": source.get("max_results", 50), "sortBy": "submittedDate", "sortOrder": "descending"}
        items = parse_feed(request_bytes(source["url"] + "?" + urlencode(params), timeout, max_bytes), source, collected_at)
    elif kind == "crossref":
        for index, query in enumerate(source["queries"]):
            if index:
                time.sleep(1)
            # Keep Crossref's relevance order within the date range. Sorting by
            # newest first can crowd out the intended task with generic matches.
            params = {"query.title": query, "filter": f"from-pub-date:{start.isoformat()},until-pub-date:{end.isoformat()},type:journal-article", "rows": source.get("max_results", 35)}
            items.extend(parse_crossref(request_bytes(source["url"] + "?" + urlencode(params), timeout, max_bytes), source, collected_at))
    elif kind == "crossref_journal":
        items = _collect_crossref_journal(source, start, end, collected_at, timeout, max_bytes, run_info if run_info is not None else {})
    elif kind == 'crossref_conference':
        items = _collect_crossref_conference(source, start, end, collected_at, timeout, max_bytes, run_info if run_info is not None else {})
    elif kind == "feed":
        from src.news_sources import collect_feed_history
        items = collect_feed_history(source, start, collected_at, request_bytes, timeout, max_bytes,
                                     run_info if run_info is not None else {})
    elif kind == 'imec_newsroom':
        items = _collect_imec(source, collected_at, timeout, max_bytes, run_info)
    elif kind == 'html_news':
        from src.news_sources import collect_html
        items = collect_html(source,collected_at,request_bytes,timeout,max_bytes,run_info if run_info is not None else {})
    else:
        raise ValueError(f"未支持的来源类型: {kind}")
    selected = {}
    selection = {
        "parsed": len(items), "date_matched": 0, "matched": 0,
        "rejected_date": 0, "rejected_relevance": 0,
        "undated": 0, "duplicates_within_source": 0,
    }
    for item in items:
        if not in_window(item, start, end):
            selection["rejected_date"] += 1
            continue
        selection["date_matched"] += 1
        if not item.get("published_at"):
            selection["undated"] += 1
        mode = source.get('relevance_mode', 'domain_and_method')
        body = (item['title'] + ' ' + (item.get('abstract_text') or item['summary'])).casefold()
        if mode == 'dedicated_journal' and source['kind'] == 'crossref_journal':
            relevant = True
        elif mode == 'domain_only':
            relevant = any(t.casefold() in body for t in source.get('domain_terms', settings['relevance']['domain_terms']))
        else:
            relevant = is_relevant(item["title"], item.get("abstract_text") or item["summary"], settings["relevance"])
        if any(re.search(pattern, item['title'], re.I) for pattern in source.get('title_exclude_patterns', [])):
            relevant = False
        if any(re.search(pattern, body, re.I) for pattern in source.get('body_exclude_patterns', [])):
            relevant = False
        if source.get('body_include_patterns') and not any(re.search(pattern, body, re.I) for pattern in source['body_include_patterns']):
            relevant = False
        if source.get('title_include_patterns') and not any(re.search(pattern,item['title'],re.I) for pattern in source['title_include_patterns']):
            relevant = False
        if source.get('require_exact_date') and not item.get('published_at'):
            relevant = False
        if not relevant or (source.get("require_title_task_match") and not title_has_molecular_task(item["title"])):
            selection["rejected_relevance"] += 1
            continue
        key = (item.get("doi") or item.get("arxiv_id") or item["url"]).casefold()
        if key in selected:
            selection["duplicates_within_source"] += 1
        if key not in selected or len(item.get("abstract_text") or "") > len(selected[key].get("abstract_text") or ""):
            if source.get('initial_literature_scope') == 'archive' and item['content_type'] == 'paper':
                item['ingestion_scope'] = 'archive'
            selected[key] = item
    selection["matched"] = len(selected)
    if run_info is not None:
        run_info["selection"] = selection
    return list(selected.values())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--as-of", type=date.fromisoformat, help="固定检索截止日 YYYY-MM-DD；默认北京时间今天")
    parser.add_argument("--sources", nargs="+", help="来源 ID，可从配置中选择一个或多个已启用来源")
    parser.add_argument("--db", type=Path, help="覆盖本地 SQLite 路径")
    parser.add_argument("--config", type=Path, default=ROOT / "resources" / "discovery_sources.json")
    parser.add_argument("--seed-file", type=Path)
    parser.add_argument("--seed-only", action="store_true", help="仅导入指定历史核验样本，不联网")
    parser.add_argument("--progress", action="store_true", help="输出来源开始事件，供网页任务进度读取")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 3660:
        parser.error("--days 必须在 1 到 3660 之间")
    if args.seed_only and not args.seed_file:
        parser.error("--seed-only 需要 --seed-file")
    from src.discovery import import_seed_file, _path

    db = str(args.db.resolve()) if args.db else None
    if args.seed_file:
        imported = import_seed_file(str(args.seed_file.resolve()), db_path=db)
        print(json.dumps({"seed_import": imported}, ensure_ascii=False))
    if args.seed_only:
        return 0
    settings = json.loads(args.config.read_text(encoding="utf-8"))
    sources = [s for s in settings["sources"] if s.get("enabled", True)]
    if args.sources:
        wanted = set(args.sources)
        unknown = wanted - {s["id"] for s in sources}
        if unknown:
            parser.error("未知或未启用的来源: " + ", ".join(sorted(unknown)))
        sources = [s for s in sources if s["id"] in wanted]
    end = args.as_of or datetime.now(LOCAL_TZ).date()
    start = end - timedelta(days=args.days - 1)
    try:
        with FileLock(execution_lock_path(_path(db))):
            return run_sources(sources, settings, start, end, db, progress=args.progress)
    except BlockingIOError as error:
        print(str(error), file=sys.stderr)
        return 2


def run_sources(sources, settings, start, end, db=None, *, progress=False):
    from src.discovery import record_run, upsert_items

    failures = 0
    for source in sources:
        if progress:
            print(json.dumps({"event": "source_started", "source_id": source["id"]}), flush=True)
        run = {"source_id": source["id"], "source_name": source["name"], "started_at": datetime.now(LOCAL_TZ).isoformat(), "window_start": start.isoformat(), "window_end": end.isoformat(), "found": 0, "inserted": 0, "updated": 0, "error": None}
        try:
            items = collect_source(source, settings, start, end, run["started_at"], run_info=run)
            result = upsert_items(items, origin="collected", db_path=db)
            run.update({"found": len(items), "inserted": result["inserted"], "updated": result["updated"], "status": "success" if items else "no_results"})
            if result.get('skipped_removed'):
                run['skipped_removed']=result['skipped_removed']
                run['coverage_warning']=' '.join(filter(None,[run.get('coverage_warning'),f"跳过 {result['skipped_removed']} 条此前已从文库移出的记录。又一次采集不会重新收录这些记录。"]))
        except Exception as error:
            failures += 1
            # Public URLs only; no credentials are read by this collector.
            run.update({"status": "failed", "error": f"{type(error).__name__}: {error}"[:600]})
        if source.get("metadata_note"):
            run["coverage_warning"] = " ".join(filter(None, [run.get("coverage_warning"), str(source["metadata_note"])]))
        run["finished_at"] = datetime.now(LOCAL_TZ).isoformat()
        record_run(run, db_path=db)
        print(json.dumps(run, ensure_ascii=False), flush=True)
    return 1 if failures == len(sources) and sources else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
