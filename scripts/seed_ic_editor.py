"""Import already generated observation drafts into the local editor."""

import argparse
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ic_editor import initialize, stage_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path, nargs='+')
    parser.add_argument('--db', type=Path, default=ROOT / 'news-data/discovery-ic.sqlite')
    args = parser.parse_args()
    reports = [json.loads(path.read_text(encoding='utf-8')) for path in args.reports]
    initialize(args.db)
    for report in reports:
        identity = f'trial-{report["as_of"]}'
        ids = stage_batch(report, identity, label='11 月试跑 · 已有资料', db_path=args.db)
        print(', '.join(ids))


if __name__ == '__main__':
    main()
