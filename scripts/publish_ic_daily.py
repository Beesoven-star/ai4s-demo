"""Publish a dated IC daily observation from a reviewed JSON draft."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ic_observations import save_daily_edition
from src.ic_research import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('draft', help='UTF-8 JSON draft path, or - to read standard input')
    parser.add_argument('--db', type=Path, default=ROOT / 'news-data/discovery-ic.sqlite')
    args = parser.parse_args()
    draft = json.loads(sys.stdin.buffer.read().decode('utf-8') if args.draft == '-' else Path(args.draft).read_text(encoding='utf-8'))
    ids = {entry['source_id'] for entry in draft['entries']}
    items = {}
    with sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        for identity in ids:
            row = connection.execute('SELECT payload FROM discovery_items WHERE id=?', (identity,)).fetchone()
            if row is None:
                parser.error(f'Source is not in the IC library: {identity}')
            item = json.loads(row[0])
            if item['content_type'] == 'paper':
                item['ic_ai'] = analyze(item)
            items[identity] = item
    try:
        report = save_daily_edition(draft, items)
    except (FileExistsError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(f"Published {report['date']} ({len(report['entries'])} entries)")


if __name__ == '__main__':
    main()
