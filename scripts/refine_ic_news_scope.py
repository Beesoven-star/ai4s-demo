"""Archive peripheral software news without deleting records or personal data."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.discovery import _connect,_write_item
excluded={
 '2527263701bc5a928e4a4f55','94bd668e3bc23fe2c946b5b9','30c2fa774bef0871770771c1',
 '5d4f85306c12518a91b3ef55','67742878475a001e94499f9f','993681af1a85c989a4eecbb8',
 '785274ddfe5c1a6fc427ce95','6a1d978ad4077933eb06934c','4643e2911cfd07a69876d2f3',
 '38732b1f8d85c5447c7613f5','ef7d446f33932614e3264181','3ebb02b4c15e76b7860af5c2',
 'e75108e4681d852997a59d8d',
}
db=_connect(ROOT/'news-data/discovery-ic.sqlite')
review=[]
with db:
    for row in db.execute("SELECT payload FROM discovery_items WHERE content_type='news'").fetchall():
        item=json.loads(row['payload'])
        scope='archive' if item['id'] in excluded else 'main'
        reason='主要涉及GPU软件运维或应用，缺少直接芯片设计、器件、体系结构或半导体产业主线，列为拓展。' if scope=='archive' else '题名及来源简介涉及芯片设计、AI计算软硬件协同、器件或半导体产业，作为新闻候选保留；未认证原文结论。'
        item.update(news_scope=scope,news_scope_reason=reason,news_reviewed_on='2026-11-14')
        _write_item(db,item)
        review.append({k:item.get(k) for k in ('id','title','source','url','published_at','news_scope','news_scope_reason')})
db.close()
(ROOT/'.runtime/ic-quality-20261114/news-scope-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
config_path=ROOT/'resources/discovery_sources_ic.json'
config=json.loads(config_path.read_text(encoding='utf-8'))
for source in config['sources']:
    if source['id']=='nvidia_ic':source['title_exclude_patterns']=['Kubernetes|DSX|Snapshot|Black Hole|Image Generation|Peak GPU Yield|GPUDirect Storage|AI Factory Operations']
    if source['id']=='trendforce_ic':source['title_exclude_patterns']=['AI Assistant|AI Video Generation']
config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'news_candidates':len(review),'main':sum(r['news_scope']=='main' for r in review),'archive':len(excluded),'deleted':0}))
