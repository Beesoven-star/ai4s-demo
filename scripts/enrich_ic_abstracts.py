"""Recover cached full arXiv abstracts and DOI-matched OpenAlex abstracts."""
from datetime import datetime,timezone,timedelta
from difflib import SequenceMatcher
import json,re,sys,time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime/ic-quality-20261114'

def normalize(title):return re.sub(r'[^a-z0-9]','',title.casefold())
def restore(index):
    words={position:word for word,positions in (index or {}).items() for position in positions}
    return ' '.join(words[p] for p in sorted(words))
def main():
    baseline=json.loads((OUT/'baseline-audit.json').read_text(encoding='utf-8'))['items']
    missing=[p for p in baseline if not p.get('abstract_text') and p.get('doi')]
    proposed,errors=[],[]
    now=datetime.now(timezone(timedelta(hours=8))).isoformat()
    for start in range(0,len(missing),40):
        batch=missing[start:start+40]
        url='https://api.openalex.org/works?'+urlencode({'filter':'doi:'+'|'.join('https://doi.org/'+p['doi'] for p in batch),
            'per_page':100,'select':'id,doi,title,abstract_inverted_index,publication_date,primary_location'})
        cache=OUT/f'openalex-{start//40}.json'
        try:
            if cache.exists():response=json.loads(cache.read_text(encoding='utf-8'))
            else:
                with urlopen(Request(url,headers={'User-Agent':'ICResearchWorkbench/0.1 (public DOI metadata enrichment)'}),timeout=35) as result:response=json.load(result)
                cache.write_text(json.dumps(response,ensure_ascii=False),encoding='utf-8')
                time.sleep(1)
            records={str(r.get('doi','')).lower().removeprefix('https://doi.org/'):r for r in response.get('results',[])}
            count=0
            for paper in batch:
                record=records.get(paper['doi'].lower())
                if not record:continue
                similarity=SequenceMatcher(None,normalize(paper['title']),normalize(record['title'])).ratio()
                if similarity<.92:
                    errors.append({'id':paper['id'],'reason':'title_mismatch','similarity':similarity});continue
                abstract=restore(record.get('abstract_inverted_index'))
                if not abstract:continue
                proposed.append({'id':paper['id'],'doi':paper['doi'],'abstract_text':abstract,
                    'provenance':{'source':'OpenAlex公开题录','url':record['id'],'doi':paper['doi'],'title_match':similarity,
                        'retrieved_at':now,'reported_publication_date':record.get('publication_date'),
                        'publisher_url':(record.get('primary_location') or {}).get('landing_page_url'),
                        'date_note':'OpenAlex报告日期仅作补充线索，不替代出版社仅月份的发表日期。'}})
                count+=1
            print(json.dumps({'batch':start//40,'requested':len(batch),'returned':len(records),'abstracts':count}),flush=True)
        except Exception as error:errors.append({'batch':start//40,'error':str(error)})
    raw=json.loads((ROOT.parent/'研究样本/集成电路/2026-11-10/papers_raw.json').read_text(encoding='utf-8'))
    records=raw.get('items',raw.get('papers',raw.get('records',[]))) if isinstance(raw,dict) else raw
    by_arxiv={str(p.get('arxiv_id')):p for p in records}
    for paper in baseline:
        original=by_arxiv.get(str(paper.get('arxiv_id')))
        if original and len(original.get('abstract_text') or '')>len(paper.get('abstract_text') or ''):
            proposed.append({'id':paper['id'],'arxiv_id':paper['arxiv_id'],'abstract_text':original['abstract_text'],
                'provenance':{'source':'原始arXiv Atom完整摘要缓存','url':paper['url'],'retrieved_at':now,'cached_retrieval':'2026-11-10'}})
    report={'proposed':proposed,'errors':errors,'missing_requested':len(missing)}
    (OUT/'abstract-enrichment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'proposed':len(proposed),'errors':errors,'raw_shape':list(raw)[:5] if isinstance(raw,dict) else 'list'},ensure_ascii=True))
if __name__=='__main__':main()
