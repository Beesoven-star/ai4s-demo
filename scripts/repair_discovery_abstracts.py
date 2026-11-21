"""Repair existing canonical abstracts; keep immutable source records and identities.

The default is a dry run. --apply creates a SQLite backup before changing data.
"""

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.abstract_text import clean_stored_abstract
from src import discovery


def repair_abstracts(db_path=None, apply=False):
    conn = discovery._connect(db_path)
    changed = []
    try:
        with conn:
            rows = conn.execute("SELECT payload FROM discovery_items").fetchall()
            for row in rows:
                item = json.loads(row["payload"])
                original = deepcopy(item)
                abstract = item.get("abstract_text") or ""
                cleaned = clean_stored_abstract(abstract)
                if cleaned != abstract:
                    item["abstract_text"] = cleaned or None
                if item.get("summary_kind") == "source":
                    summary = item.get("summary") or ""
                    item["summary"] = (
                        cleaned[:1200] if abstract and summary == abstract[:1200]
                        else clean_stored_abstract(summary)
                    )
                if item != original:
                    changed.append(item["id"])
                    if apply:
                        item["updated_at"] = discovery._now()
                        discovery._write_item(conn, item)
        return {"checked": len(rows), "updated": len(changed) if apply else 0, "would_update": len(changed), "ids": changed}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = discovery._path(args.db).resolve()
    if not path.is_file():
        parser.error("本地资料数据库不存在")
    backup = None
    if args.apply:
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"abstract-cleanup-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite"
        source = sqlite3.connect(path)
        target = sqlite3.connect(backup)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
    result = repair_abstracts(path, apply=args.apply)
    print(json.dumps({**result, "backup": str(backup) if backup else None}, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
