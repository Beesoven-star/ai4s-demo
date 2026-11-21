"""Enable verified public metadata channels from the user's source list."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'resources/discovery_sources_ic.json'
config=json.loads(path.read_text(encoding='utf-8'))
backup=ROOT/'.runtime/ic-quality-20261114/sources-before.json'
if not backup.exists():backup.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
extra=[
 {'id':'eetimes_ic','name':'EE Times','kind':'feed','url':'https://www.eetimes.com/feed/','homepage':'https://www.eetimes.com/','news_genre':'专业媒体报道'},
 {'id':'nvidia_ic','name':'NVIDIA Technical Blog','kind':'feed','url':'https://developer.nvidia.com/blog/feed/','homepage':'https://developer.nvidia.com/blog/','news_genre':'企业技术博客',
  'title_include_patterns':['GPU|CUDA|NVLink|Blackwell|Rubin|chip|memory|DGX|Tensor|cuDLA|wafer|FP64|supply.chain|hardware|AI.Factory'],
  'title_exclude_patterns':['Kubernetes|DSX|Snapshot|Black Hole|Image Generation|Peak GPU Yield|GPUDirect Storage|AI Factory Operations']},
 {'id':'semianalysis_ic','name':'SemiAnalysis','kind':'feed','url':'https://newsletter.semianalysis.com/feed','homepage':'https://semianalysis.com/','news_genre':'行业研究与分析（部分付费）',
  'title_include_patterns':['GPU|TPU|ASIC|HBM|chip|semiconductor|memory|NVIDIA|AMD|Intel|TSMC|packaging|interconnect|wafer|AI.Factory']},
 {'id':'trendforce_ic','name':'TrendForce 集邦咨询','kind':'html_news','url':'https://www.trendforce.com/news/','homepage':'https://www.trendforce.com/news/','news_genre':'产业新闻与市场研究',
  'article_url_pattern':r'^https://www\.trendforce\.com/news/\d{4}/\d{2}/\d{2}/[^/]+/$','max_articles':25,'title_exclude_patterns':['AI Assistant|AI Video Generation']},
 {'id':'ijiwei_ic','name':'爱集微（集微网）','kind':'html_news','url':'https://www.ijiwei.com/','homepage':'https://www.ijiwei.com/','news_genre':'专业媒体报道',
  'article_url_pattern':r'^https://www\.ijiwei\.com/n/\d+$','max_articles':26,'title_exclude_patterns':['【中标】|【预成交】|【招标】|回购股份|回购A股|业绩预告']},
 {'id':'synopsys_ic','name':'Synopsys 芯片设计博客','kind':'html_news','url':'https://www.synopsys.com/blogs/chip-design.html','homepage':'https://www.synopsys.com/blogs/chip-design.html','news_genre':'企业技术博客',
  'article_url_pattern':r'^https://www\.synopsys\.com/blogs/chip-design/(?!category\.)[^/]+\.html$','max_articles':14},
 {'id':'zhidx_ic','name':'芯东西／智东西','kind':'html_news','url':'https://zhidx.com/aichip001','homepage':'https://zhidx.com/aichip001','news_genre':'专业媒体报道',
  'article_url_pattern':r'^https://zhidx\.com/p/\d+\.html$','max_articles':22},
 {'id':'sia_ic','name':'SIA 美国半导体行业协会','kind':'html_news','url':'https://www.semiconductors.org/news-events/latest-news/','homepage':'https://www.semiconductors.org/news-events/latest-news/','news_genre':'行业协会公告与统计',
  'article_url_pattern':r'^https://www\.semiconductors\.org/(?:former-secretary|sia-urges|global-semiconductor-sales|professors-from|year-to-date-global)[^/]+/$','max_articles':12,'title_exclude_patterns':['Keynote|Awards Dinner']},
]
for source in extra:
    source.update(content_type='news',enabled=True,relevance_mode='domain_only',require_exact_date=True,
        verification='2026-11-14：实际读取官方公开订阅或目录、核对文章题名和首次发布日期。',
        metadata_note='仅保留公开来源简介并链接原文；当前目录/订阅条目有限，不代表完整历史。企业博客、行业研究与独立媒体分开标注。')
    if source['id']=='semianalysis_ic':source['metadata_note']+=' 付费部分未读取，不作为已核验全文。'
ids={s['id'] for s in extra}
config['sources']=[s for s in config['sources'] if s['id'] not in ids]+extra
terms=config['relevance']['domain_terms']+['GPU','HBM','DRAM','NAND','NVLink','CUDA','芯片','半导体','集成电路','晶圆','封装','存储','算力','存算','EDA','英伟达','台积电','光刻','互连']
config['relevance']['domain_terms']=list(dict.fromkeys(terms))
for source in config['sources']:
    if source['kind']=='crossref_journal' and 'Society Information' not in source.setdefault('title_exclude_patterns',[]):source['title_exclude_patterns'].append('Society Information')
path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'new_sources':[s['id'] for s in extra]}))
