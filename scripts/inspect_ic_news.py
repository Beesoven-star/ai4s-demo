from pathlib import Path
from urllib.parse import urljoin
import json,re,sys
sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parents[1]/'.runtime/ic-quality-20261114/probes'
index=json.loads((root/'index.json').read_text(encoding='utf-8'))
for entry in index:
    if entry['id'] in ('zhidx','trendforce'):print(entry['id'],entry.get('sample_links',[])[:10])
for key in ('synopsys','sia','ijiwei','zhidx'):
    raw=(root/(key+'.raw')).read_text(encoding='utf-8')
    links=re.findall(r'href=["\']([^"\']+)',raw,re.I)
    if key=='synopsys':links=[x for x in links if '/blogs/chip-design/' in x and 'category.' not in x and x.endswith('.html')]
    elif key=='sia':links=[x for x in links if 'semiconductors.org/' in x and any(term in x for term in ('global-semiconductor','professor','rice','permitting'))]
    elif key=='zhidx':links=[x for x in links if re.search(r'p/\d+|/news/\d+',x)]
    else:links=[x for x in links if re.search(r'/n/\d+',x)]
    print(key,list(dict.fromkeys(links))[:16])
