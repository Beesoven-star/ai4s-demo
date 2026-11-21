"""Bounded public source discovery and abstract-access probes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urljoin
import json,re,sys
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime/ic-quality-20261114/probes'
OUT.mkdir(parents=True,exist_ok=True)
URLS=[
 ('ijiwei','https://www.ijiwei.com/'),('semi_china','https://www.semi.org.cn/'),
 ('csia','https://www.csia.net.cn/'),('eetimes','https://www.eetimes.com/'),
 ('sia','https://www.semiconductors.org/news-events/latest-news/'),('semi_global','https://www.semi.org/en/news-media-press-releases'),
 ('synopsys','https://www.synopsys.com/blogs/chip-design.html'),('semianalysis','https://semianalysis.com/'),
 ('nvidia','https://developer.nvidia.com/blog/'),('trendforce','https://www.trendforce.com/news/'),
 ('zhidx','https://zhidx.com/'),('semieng_ai','https://semiengineering.com/category/artificial-intelligence/'),
 ('nvidia_feed','https://developer.nvidia.com/blog/feed/'),('semianalysis_feed','https://semianalysis.com/feed/'),
 ('openalex','https://api.openalex.org/works/https://doi.org/10.1109/jssc.2026.3736028'),
]
def probe(pair):
    key,url=pair
    result={'id':key,'url':url}
    try:
        with urlopen(Request(url,headers={'User-Agent':'ICResearchWorkbench/0.1 (bounded public source verification)'}),timeout=18) as response:
            raw=response.read(6_000_001)
            result.update(status=response.status,final_url=response.url,bytes=len(raw),content_type=response.headers.get('Content-Type'))
        (OUT/(key+'.raw')).write_bytes(raw)
        text=raw.decode('utf-8',errors='replace')
        result['feeds']=list(dict.fromkeys(urljoin(result['final_url'],m) for m in re.findall(r'<link\b[^>]*type=["\']application/(?:rss|atom)\+xml["\'][^>]*href=["\']([^"\']+)',text,re.I)+re.findall(r'<link\b[^>]*href=["\']([^"\']+)["\'][^>]*type=["\']application/(?:rss|atom)\+xml',text,re.I)))
        result['sample_links']=list(dict.fromkeys(urljoin(result['final_url'],m) for m in re.findall(r'<a\b[^>]*href=["\']([^"\']+)',text,re.I) if re.search(r'2026|/news/|/n/|/press|/blog|/article|/feed|rss',m,re.I)))[:22]
        if key=='openalex':
            record=json.loads(raw)
            result.update(title=record.get('title'),abstract=bool(record.get('abstract_inverted_index')),date=record.get('publication_date'))
    except Exception as error:result['error']=f'{type(error).__name__}: {error}'[:300]
    return result
if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(probe,URLS))
    (OUT/'index.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for result in results:print(json.dumps(result,ensure_ascii=False))
