"""Read-only IC database audit for the 2026-11-13 source expansion."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
db = sqlite3.connect(f'file:{(ROOT / "news-data/discovery-ic.sqlite").as_posix()}?mode=ro', uri=True)
items = [json.loads(row[0]) for row in db.execute('SELECT payload FROM discovery_items')]
journals = [item for item in items if item.get('publication_status') == 'journal_metadata']
news = sorted([item for item in items if item['content_type'] == 'news'], key=lambda item:item.get('published_at') or '', reverse=True)
recent_papers = sorted([item for item in journals if item.get('published_at')], key=lambda item:item['published_at'], reverse=True)
report = {
    'as_of':'2026-11-13', 'window':{'start':'2026-10-15','end':'2026-11-13'},
    'total':len(items), 'by_source':dict(Counter(item['source'] for item in items)),
    'journal_records':len(journals), 'journal_exact_date':len(recent_papers),
    'journal_month_only':sum(bool(item.get('publication_month')) and not item.get('published_at') for item in journals),
    'journal_exact_last_7_days':sum('2026-11-07' <= item['published_at'] <= '2026-11-13' for item in recent_papers),
    'news_count':len(news), 'news_last_7_days':sum('2026-11-07' <= item['published_at'] <= '2026-11-13' for item in news),
    'personal_favorites':db.execute('SELECT COUNT(*) FROM personal_library WHERE is_favorite=1').fetchone()[0],
    'latest_papers':[{key:item.get(key) for key in ('title','doi','published_at','publication_dates','journal','summary','verification_note')} for item in recent_papers[:8]],
    'news':[{key:item.get(key) for key in ('title','url','published_at','source','news_genre','summary')} for item in news],
}
db.close()
original = sqlite3.connect(f'file:{(ROOT / "news-data/discovery.sqlite").as_posix()}?mode=ro', uri=True)
report['molecular_records'] = original.execute('SELECT COUNT(*) FROM discovery_items').fetchone()[0]
original.close()
out = ROOT / '.runtime/ic-sources-20261113/collection-audit.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({**{key:value for key,value in report.items() if key not in ('latest_papers','news')},
    'latest_papers':[{key:item.get(key) for key in ('title','doi','published_at')} for item in report['latest_papers']],
    'news':[{key:item.get(key) for key in ('title','url','published_at','source')} for item in report['news']]}, ensure_ascii=False, indent=2))
