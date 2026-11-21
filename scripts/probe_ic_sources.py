"""Read-only source verification; retain public endpoint evidence."""
import concurrent.futures
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urljoin
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime' / 'ic-sources-20261113'
OUT.mkdir(parents=True, exist_ok=True)
JOURNALS = {'jssc':'0018-9200', 'tcad':'0278-0070', 'tvlsi':'1063-8210', 'todaes':'1084-4309'}
URLS = [(f'journal_{key}', 'https://api.crossref.org/journals/'+issn) for key,issn in JOURNALS.items()]
URLS += [('papers_'+key, 'https://api.crossref.org/journals/'+issn+'/works?'+urlencode({
    'filter':'from-pub-date:2026-10-15,until-pub-date:2026-11-13,type:journal-article',
    'rows':100,'sort':'indexed','order':'desc'})) for key,issn in JOURNALS.items()]
URLS += [('spectrum_home','https://spectrum.ieee.org/topic/semiconductors'),
         ('spectrum_feed','https://spectrum.ieee.org/feeds/topic/semiconductors.rss'),
         ('semi_home','https://semiengineering.com/'),
         ('arm_home','https://newsroom.arm.com/'),
         ('mit_home','https://news.mit.edu/topic/microelectronics'),
         ('imec_home','https://www.imec-int.com/en/press')]


def probe(entry):
    name, url = entry
    item = {'id':name,'url':url,'checked_at':datetime.now(timezone(timedelta(hours=8))).isoformat()}
    try:
        with urlopen(Request(url,headers={'User-Agent':'ICResearchWorkbench/0.1 (public metadata verification)'}),timeout=22) as response:
            data=response.read(7_000_001)
            item.update(status=response.status, content_type=response.headers.get('Content-Type'), final_url=response.url, bytes=len(data))
        (OUT/(name+'.raw')).write_bytes(data)
        if name.startswith(('journal_','papers_')):
            message=json.loads(data)['message']
            if name.startswith('journal_'):
                item.update(title=message.get('title'),issn=message.get('ISSN'))
            else:
                item.update(total=message.get('total-results'),returned=len(message.get('items',[])),
                    latest=[{k:p.get(k) for k in ['title','DOI','published-online','published','published-print','issued','container-title']} for p in message.get('items',[])[:4]])
        else:
            text=data.decode('utf-8',errors='replace')
            item['feeds']=[urljoin(item['final_url'],m) for m in re.findall(r'<link\b[^>]*type=["\']application/(?:rss|atom)\+xml["\'][^>]*href=["\']([^"\']+)',text,re.I)]
            item['feeds'] += [urljoin(item['final_url'],m) for m in re.findall(r'<link\b[^>]*href=["\']([^"\']+)["\'][^>]*type=["\']application/(?:rss|atom)\+xml',text,re.I)]
            item['feeds']=list(dict.fromkeys(item['feeds']))
            if 'feed' in name:
                root=ET.fromstring(data)
                entries=root.findall('.//item')
                item['entries']=len(entries)
                item['latest']=[{key:n.findtext(key) for key in ['title','link','pubDate']} for n in entries[:5]]
    except Exception as error:
        item['error']=f'{type(error).__name__}: {error}'
    return item


if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for item in pool.map(probe,URLS):
            results.append(item)
            print(json.dumps(item,ensure_ascii=False),flush=True)
    (OUT/'probes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
