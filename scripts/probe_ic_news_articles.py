from pathlib import Path
import json,re,sys
from probe_ic_quality_sources import probe
from concurrent.futures import ThreadPoolExecutor
URLS=[('ijiwei_article','https://www.ijiwei.com/n/1140239'),
 ('synopsys_article','https://www.synopsys.com/blogs/chip-design/agentic-ai-adoption-paths-chip-design.html'),
 ('zhidx_article','https://zhidx.com/p/610355.html'),('csia_web','https://web.csia.net.cn/'),
 ('csia_article','https://web.csia.net.cn/newsinfo/11385973.html'),('semi_china_new','https://china.semi.org.cn/index.html'),
 ('sia_feed','https://www.semiconductors.org/feed/'),('trendforce_feed','https://www.trendforce.com/news/feed/'),
 ('eetimes_feed','https://www.eetimes.com/feed/')]
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(probe,URLS))
    root=Path(__file__).resolve().parents[1]/'.runtime/ic-quality-20261114/probes'
    (root/'articles-index.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    for entry in results:
        print(json.dumps({k:v for k,v in entry.items() if k not in ('sample_links','feeds')},ensure_ascii=False))
        path=root/(entry['id']+'.raw')
        if path.exists() and entry['id'].endswith('article'):
            raw=path.read_text(encoding='utf-8')
            print('META',re.findall(r'<meta\b[^>]+(?:date|time|title|description)[^>]+>',raw,re.I)[:10])
            print('DATES',re.findall(r'.{0,65}(?:datePublished|发布时间|pubdate|publishDate|article:published|2026-11).{0,100}',raw,re.I)[:9])
