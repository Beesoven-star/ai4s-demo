"""Single-user personal library stored beside acquisition records, never in them."""
import json
from src import discovery as store

STATUSES = {"unread", "reading", "read", "follow_up"}


def update_record(item_id, changes, db_path=None):
    if not isinstance(changes, dict) or set(changes) - {"is_favorite", "notes", "reading_status", "personal_tags"}:
        raise ValueError("个人记录包含不支持的字段")
    if "is_favorite" in changes and not isinstance(changes["is_favorite"], bool):
        raise ValueError("收藏标记必须为布尔值")
    if "notes" in changes and (not isinstance(changes["notes"], str) or len(changes["notes"]) > 20000):
        raise ValueError("备注最多20000字")
    if "reading_status" in changes and changes["reading_status"] not in STATUSES:
        raise ValueError("阅读状态无效")
    if "personal_tags" in changes:
        tags = changes["personal_tags"]
        if not isinstance(tags, list) or len(tags) > 20 or any(not isinstance(t, str) or len(t.strip()) > 50 for t in tags):
            raise ValueError("个人标签最多20个，每个最多50字")
        changes = {**changes, "personal_tags": list(dict.fromkeys(t.strip() for t in tags if t.strip()))}
    conn = store._connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM discovery_items WHERE id=?", (item_id,)).fetchone() is None:
                raise KeyError(item_id)
            row = conn.execute("SELECT * FROM personal_library WHERE item_id=?", (item_id,)).fetchone()
            old = store.personal_record(row)
            new = {**old, **changes}
            if new == old:
                return old
            stamp = store._now()
            new["updated_at"] = stamp
            if new["is_favorite"] and not new["saved_at"]:
                new["saved_at"] = stamp
            conn.execute("""INSERT INTO personal_library
                (item_id,is_favorite,notes,reading_status,personal_tags,saved_at,updated_at)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
                is_favorite=excluded.is_favorite,notes=excluded.notes,reading_status=excluded.reading_status,
                personal_tags=excluded.personal_tags,saved_at=excluded.saved_at,updated_at=excluded.updated_at""",
                (item_id, int(new["is_favorite"]), new["notes"], new["reading_status"],
                 store._json(new["personal_tags"]), new["saved_at"], stamp))
            return new
    finally:
        conn.close()


def list_saved(q="", reading_status=None, topic=None, personal_tag=None, content_type=None,
               limit=20, offset=0, db_path=None):
    if reading_status and reading_status not in STATUSES:
        raise ValueError("阅读状态无效")
    if content_type and content_type not in {"paper", "news"}:
        raise ValueError("资料类型无效")
    if not isinstance(limit, int) or not 1 <= limit <= 100 or not isinstance(offset, int) or offset < 0:
        raise ValueError("分页参数无效")
    where, values = ["l.is_favorite=1"], []
    if q.strip():
        escaped = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("lower(i.search_text || ' ' || l.notes || ' ' || l.personal_tags) LIKE ? ESCAPE '\\'")
        values.append(f"%{escaped}%")
    for column, value in [("l.reading_status", reading_status), ("i.content_type", content_type)]:
        if value:
            where.append(column + "=?")
            values.append(value)
    for column, path, value in [("i.payload", "$.topics", topic), ("l.personal_tags", "$", personal_tag)]:
        if value:
            where.append(f"EXISTS (SELECT 1 FROM json_each({column},'{path}') WHERE value=?)")
            values.append(value)
    base = " FROM discovery_items i JOIN personal_library l ON l.item_id=i.id"
    condition = " WHERE " + " AND ".join(where)
    conn = store._connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*)" + base + condition, values).fetchone()[0]
        rows = conn.execute("SELECT i.payload" + base + condition +
                            " ORDER BY l.saved_at DESC,i.id LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        topics = [r[0] for r in conn.execute("SELECT DISTINCT j.value" + base +
                 ",json_each(i.payload,'$.topics') j WHERE l.is_favorite=1 ORDER BY j.value")]
        tags = [r[0] for r in conn.execute("SELECT DISTINCT j.value FROM personal_library l,"
                "json_each(l.personal_tags) j WHERE l.is_favorite=1 ORDER BY j.value")]
        statuses = {r[0]: r[1] for r in conn.execute(
            "SELECT reading_status,COUNT(*) FROM personal_library WHERE is_favorite=1 GROUP BY reading_status")}
        return {"items": store._with_personal_records(conn, rows), "total": total, "limit": limit, "offset": offset,
                "facets": {"topics": topics, "personal_tags": tags, "status_counts": statuses,
                           "total": sum(statuses.values())}}
    finally:
        conn.close()
