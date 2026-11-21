"""Collect or replay IC sources, then write reviewable daily and weekly drafts."""

import argparse
from contextlib import closing
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.collect_discovery import run_sources
from src.ic_observation_drafts import build_drafts, render_markdown
from src.ic_observations import SHANGHAI, load_catalog, today_in_shanghai


def read_inputs(database, start, end, *, reference=False):
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('BEGIN')
        if reference:
            records = connection.execute('SELECT payload FROM discovery_items WHERE published_date BETWEEN ? AND ?',
                                         (start.isoformat(), end.isoformat())).fetchall()
        else:
            records = connection.execute('SELECT payload FROM discovery_items').fetchall()
        identities = dict(connection.execute('SELECT identity_key, item_id FROM discovery_aliases'))
        runs = [] if reference else [json.loads(row[0]) for row in connection.execute('SELECT payload FROM discovery_runs ORDER BY id')]
    return [json.loads(row[0]) for row in records], identities, runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--replay-db', type=Path, help='Read an existing collection batch without fetching again')
    mode.add_argument('--sources', nargs='+', help='One or more enabled IC collection source IDs')
    parser.add_argument('--as-of', type=date.fromisoformat, default=date.fromisoformat(today_in_shanghai()))
    parser.add_argument('--library', type=Path, default=ROOT / 'news-data/discovery-ic.sqlite')
    parser.add_argument('--config', type=Path, default=ROOT / 'resources/discovery_sources_ic.json')
    parser.add_argument('--output', type=Path, help='New directory for the local draft and collection evidence')
    args = parser.parse_args()
    if args.as_of > date.fromisoformat(today_in_shanghai()):
        parser.error('The draft date has not arrived in Asia/Shanghai')

    if args.sources:
        settings = json.loads(args.config.read_text(encoding='utf-8'))
        source_map = {row['id']: row for row in settings['sources'] if row.get('enabled', True)}
        missing = set(args.sources) - source_map.keys()
        if missing:
            parser.error(f'Unknown or disabled sources: {", ".join(sorted(missing))}')
        sources = [source_map[key] for key in dict.fromkeys(args.sources)]

    start = args.as_of - timedelta(days=6)
    # Read only the published metadata newer than the duplicate comparison horizon.
    reference, library_aliases, _ = read_inputs(args.library, start - timedelta(days=3), args.as_of, reference=True)
    catalog = load_catalog()
    stamp = datetime.now(SHANGHAI).strftime('%Y%m%d-%H%M%S-%f')
    folder = args.output or ROOT / '.runtime/ic-observation-drafts' / f'{args.as_of}-{stamp}'
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    collection_code = 0
    if args.sources:
        database = folder / 'collection.sqlite'
        collection_code = run_sources(sources, settings, start, args.as_of, db=str(database), progress=True)
    else:
        database = args.replay_db
    items, batch_aliases, runs = read_inputs(database, start, args.as_of)
    known = {item_id for alias, item_id in batch_aliases.items() if alias in library_aliases}
    report = build_drafts(items, args.as_of, catalog, reference=reference, known_ids=known, source_runs=runs)
    report['mode'] = 'collected' if args.sources else 'replayed'
    (folder / 'drafts.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (folder / 'observations.md').write_text(render_markdown(report), encoding='utf-8')
    print(json.dumps({'draft_dir': str(folder), 'mode': report['mode'], 'window_items': report['in_window'],
                      'daily_items': len(report['daily']['entries']), 'weekly_items': len(report['weekly']['entries']),
                      'possible_duplicates': len(report['possible_event_duplicates'])}, ensure_ascii=False))
    return collection_code


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
