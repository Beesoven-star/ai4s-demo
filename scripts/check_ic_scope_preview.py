"""Read-only HTTP acceptance check for the IC-only preview."""
import json
from pathlib import Path
import sqlite3
from collections import Counter
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

BASE='http://127.0.0.1:8001'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.ic_research import analyze,scope_of
from src.publication_timing import statistics

# The original quality audit is a dated snapshot. Live collection can grow.
with sqlite3.connect(f'file:{(ROOT/"news-data/discovery-ic.sqlite").as_posix()}?mode=ro',uri=True) as conn:
    records=[json.loads(row[0]) for row in conn.execute('SELECT payload FROM discovery_items')]
papers=[item for item in records if item['content_type']=='paper']
news_records=[item for item in records if item['content_type']=='news']
scopes=Counter(scope_of(analyze(item)) for item in papers)
archived_news=sum(item.get('news_scope')=='archive' for item in news_records)
timing=statistics([item for item in papers if scope_of(analyze(item))!='excluded'])
def get(path):
    with urlopen(BASE+path,timeout=15) as response:
        return json.load(response)

assert get('/api/health')['status']=='ok'
assert get('/api/workspace')=={'domain':'ic','reports_enabled':False}
assert get('/api/reports')==[], 'Do not expose old cross-domain reports'
assert get('/api/sections/hackernews')==[], 'Do not mix archived generic HN reports'
documents=get('/api/workdocs')
assert {doc['name'] for doc in documents}=={'当前研究主线与方向.md','AI4S关键核心技术攻关实施方案.docx','以往研究内容.docx'}, documents
facets=get('/api/discovery/facets')
assert facets['domain']=='ic'
assert (facets['papers'],facets['news'],facets['news_candidates'],facets['archived_news'])==(len(papers),len(news_records)-archived_news,len(news_records),archived_news)
assert facets['publication_audit']['counts']==timing['counts']
assert facets['publication_audit']['collection_days']==dict(Counter(item['collected_at'][:10] for item in papers))
for scope,total in {**scopes,'all':len(papers)}.items():
    assert get('/api/discovery/items?'+urlencode({'content_type':'paper','literature_scope':scope,'limit':1}))['total']==total
for period,total in facets['publication_audit']['counts'].items():
    assert get('/api/discovery/items?'+urlencode({'content_type':'paper','literature_scope':'all','publication_period':period,'limit':1}))['total']==total
assert get('/api/discovery/items?content_type=paper&limit=1')['total']==scopes['main']
news=get('/api/discovery/items?content_type=news&limit=100')
assert news['total']==len(news_records)-archived_news and all(item['published_at'] and item['content_type']=='news' for item in news['items'])
assert get('/api/discovery/items?content_type=news&news_scope=archive&limit=1')['total']==archived_news
assert get('/api/discovery/items?content_type=news&news_scope=all&limit=1')['total']==len(news_records)
overview=get('/api/discovery/ic-exploration')
for track in ('ai_for_ic','ic_for_ai','general_ic','unconfirmed'):
    result=get('/api/discovery/items?'+urlencode({'content_type':'paper','research_track':track,'limit':1}))
    assert result['total']==overview['counts'][track], (track,result['total'],overview['counts'][track])
    assert all(item['content_type']=='paper' for item in result['items'])
assert get('/api/discovery/items?content_type=paper&research_track=any_ai&limit=1')['total']==overview['counts']['ai_candidates']
favorites=get('/api/discovery/library')
db=sqlite3.connect(f'file:{(Path(__file__).resolve().parents[1]/"news-data/discovery-ic.sqlite").as_posix()}?mode=ro',uri=True)
expected=db.execute('SELECT COUNT(*) FROM personal_library WHERE is_favorite=1').fetchone()[0]
db.close()
assert favorites['total']==expected
print(json.dumps({'counts':overview['counts'],'report_count':0,'workdocs':len(documents),
    'favorites_preserved':favorites['total'],'api_checks':'passed'},ensure_ascii=True))
