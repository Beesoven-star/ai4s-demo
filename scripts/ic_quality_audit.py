"""Snapshot baseline and audit source dates without changing the corpus."""
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.ic_research import analyze
OUT=ROOT/'.runtime/ic-quality-20261114'
OUT.mkdir(parents=True,exist_ok=True)
conn=sqlite3.connect(f'file:{(ROOT/"news-data/discovery-ic.sqlite").as_posix()}?mode=ro',uri=True)
backup=OUT/'before.sqlite'
if not backup.exists():
    with sqlite3.connect(backup) as target: conn.backup(target)
conn.close()
# Re-running the baseline export must never replace the original audit cohort.
conn=sqlite3.connect(f'file:{backup.as_posix()}?mode=ro',uri=True)
papers=[json.loads(row[0]) for row in conn.execute("SELECT payload FROM discovery_items WHERE content_type='paper'")]
conn.close()
asof=date(2026,11,14)
start=(asof-timedelta(days=29)).isoformat()
def category(item):
    if not item.get('published_at'):return 'month_only' if item.get('publication_month') else 'unknown'
    if item['published_at']>asof.isoformat():return 'future'
    if item['published_at']>=start:return 'recent_preprint' if item.get('venue_type')=='preprint' else 'recent_published'
    return 'historical_preprint' if item.get('venue_type')=='preprint' else 'historical_published'
report={'as_of':asof.isoformat(),'recent_start':start,'total':len(papers),
    'collected_days':dict(Counter(p.get('collected_at','')[:10] for p in papers)),
    'publication_groups':dict(Counter(category(p) for p in papers)),
    'publication_months':dict(sorted(Counter(p.get('published_at','')[:7] if p.get('published_at') else p.get('publication_month','unknown') for p in papers).items())),
    'abstracts':dict(Counter('available' if p.get('abstract_text') else 'missing' for p in papers)),
    'unconfirmed_by_source':dict(Counter(p['source'] for p in papers if analyze(p)['status']=='unconfirmed')),
    'items':[{**p,'old_analysis':analyze(p),'date_group':category(p)} for p in papers]}
(OUT/'baseline-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['index\tid\tkey\ttitle\tsource\thas_abstract\tpublished\tmonth\told_topics']
for index,p in enumerate(papers):
    lines.append('\t'.join([str(index),p['id'],p.get('doi') or p.get('arxiv_id') or '',p['title'],p['source'],str(bool(p.get('abstract_text'))),p.get('published_at') or '',p.get('publication_month') or '',','.join(analyze(p)['topic_ids'])]))
(OUT/'paper-index.tsv').write_text('\n'.join(lines),encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='items'},ensure_ascii=False,indent=2))
