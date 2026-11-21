"""One-time metadata records verified against official public search/listings.

These are explicitly manual, with unavailable direct-page access disclosed.
No claim of full-text access, no scheduled scraping of blocked endpoints.
"""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.discovery import upsert_items,record_run
now=datetime.now(timezone(timedelta(hours=8))).isoformat()
records=[
 ('csia_search','中国半导体行业协会（CSIA）','2026-11-13','智能算力同比增长146%，专用芯片站上扩容潮头','https://web.csia.net.cn/newsinfo/11392807.html','协会转载的专用AI算力芯片与产业动态。','行业协会转载与动态'),
 ('csia_search','中国半导体行业协会（CSIA）','2026-11-13','横琴再添一家上市企业 一微科技在港交所主板敲钟','https://web.csia.net.cn/newsinfo/11392812.html','涉及机器人专用SLAM SoC及感知、决策、控制芯片产业化。','行业协会转载与动态'),
 ('semi_global_search','SEMI Global','2026-11-04','Worldwide Silicon Wafer Shipments Increase 13.4% Year-on-Year in Q3 2026, SEMI Reports','https://www.semi.org/en/semi-press-release/worldwide-silicon-wafer-shipments-increase-13.4-percent-year-on-year-in-q3-2026-semi-reports','SEMI公布第三季度硅晶圆出货统计，讨论AI及先进封装相关需求。','行业协会公告与统计'),
 ('semi_global_search','SEMI Global','2026-10-27','ChipAgents Expands Full-Stack Agentic AI Across Digital and Analog Chip Design','https://www.semi.org/en/node/176746','会员新闻稿，介绍面向数字与模拟芯片设计的Agentic AI方案，企业效果声明需另行核验。','会员企业新闻稿'),
 ('semi_china_search','SEMI 中国／大半导体产业网','2026-10-30','聚焦光互连与玻璃基挑战——2026 SEMI中国四大委员会及联席会议圆满召开','https://china.semi.org.cn/news/semiPressReleases','官方新闻列表记录：聚焦光互连、玻璃基与封装制造议题，发布日期与10月29日会议日期区分。','行业协会动态'),
]
items=[]
for key,source,day,title,url,summary,genre in records:
    items.append({'title':title,'url':url,'source':source,'content_type':'news','published_at':day,
        'date_kind':'news_published','collected_at':now,'summary':summary,'summary_kind':'human',
        'news_genre':genre,'topics':[],'methods':[],'views':[],'relevance':'pending',
        'verification_mode':'official_search_listing_manual',
        'verification_note':'本次人工核对官方站点公开检索摘录或新闻列表的题名和发布日期；正文直连受限，未作全文核验。简介为人工简述。' + (' 原始出处为官方列表，独立正文链接尚未核验。' if key=='semi_china_search' else '')})
out=ROOT/'.runtime/ic-quality-20261114/verified-official-news-search.json'
out.write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
db=ROOT/'news-data/discovery-ic.sqlite'
result=upsert_items(items,origin='collected',db_path=db)
for source_id in sorted(set(entry[0] for entry in records)):
    entries=[item for row,item in zip(records,items) if row[0]==source_id]
    record_run({'source_id':source_id,'source_name':entries[0]['source']+' · 人工检索核对',
        'started_at':now,'finished_at':now,'window_start':'2026-10-16','window_end':'2026-11-14',
        'status':'success','found':len(entries),'inserted':len(entries) if result['updated']==0 else 0,'updated':0,
        'coverage_warning':'一次性人工核对的官方检索/列表元数据；原文直连受限，尚未启用该站自动采集。'},db_path=db)
print(json.dumps(result))
