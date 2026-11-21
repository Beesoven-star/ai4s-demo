"""Import the reviewed, bounded October/November news backfill.

The candidate list is a frozen RSS snapshot. Do not rerun to reclassify later
collections or restore removed records. Original feed publication dates remain.
"""
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.discovery import upsert_items, record_run, list_runs, _now

OUT=ROOT/'.runtime/news-backfill-20261114'
DB=ROOT/'news-data/discovery-ic.sqlite'

REJECT={
    9:'泛科学评论，缺少具体芯片研究信息',
    11:'诉讼新闻，本轮优先技术与研究进展',31:'诉讼评论，本轮优先技术与研究进展',33:'诉讼回应，本轮优先技术与研究进展',
    19:'博客索引汇总',50:'博客索引汇总',101:'博客索引汇总',136:'博客索引汇总',
    52:'IP产品宣传，与后续电子书宣传主题重叠',59:'通用工程智能体介绍，摘要缺少具体芯片任务',
    70:'人才与教育话题',77:'泛科学评论',78:'量子计算方向，偏离当前AI与IC主线',
    89:'设备订货广告',97:'数据中心选址电子书宣传',100:'图像算法介绍，缺少直接芯片贡献',
    109:'人才与教育话题',111:'与11月4日网络安全报道题名高度重复，保留较早条目',
    113:'活动周年宣传',114:'杂志目录',115:'自动驾驶软件仿真，缺少直接芯片贡献',
    117:'GPU软件算子实现，作为本轮外围内容跳过',130:'工具手册宣传',132:'采购服务广告',146:'电子书宣传',
}


def main():
    if (OUT/'import-result.json').exists():raise RuntimeError('Dated import already applied')
    candidates=json.loads((OUT/'new-candidates.json').read_text(encoding='utf-8'))
    if len(candidates)!=147 or candidates[14]['title']!='Why Chip Design AI Benchmarks Must Go Beyond Functional Correctness':
        raise RuntimeError('Review indices no longer match frozen candidates')
    selected=[]; decisions=[]
    for i,item in enumerate(candidates):
        decisions.append({'id':item['id'],'title':item['title'],'url':item['url'],'published_at':item['published_at'],
                          'decision':'skip' if i in REJECT else 'include',
                          'reason':REJECT.get(i,'题名与来源简介涉及芯片设计、计算架构、器件、制造测试或半导体产业。')})
        if i in REJECT:continue
        item=dict(item)
        item.update(news_scope='main',news_reviewed_on='2026-11-14',
                    news_scope_reason='按题名和公开来源简介复核，涉及集成电路研究或产业；未逐条核验全文结论。')
        text=item.get('summary','')
        if re.search(r'\bSponsored\b|Advertorial',text,re.I):item['news_genre']='企业供稿／赞助内容'
        elif item['title'].startswith('Chip Industry Technical Paper Roundup:') or re.search(r'\([^)]*(?:University|TU Munich|imec|ASU|SNU|NUS|UC Berkeley|Argonne|UT Austin)[^)]*\)',item['title'],re.I):
            item['news_genre']='研究动态报道（链接原研究）'
        item['verification_note']='历史补采；首次发布日期依据原站RSS pubDate，题名及来源简介已作范围复核。未将收录日替代发表日；仅保留公开简介，原文结论需另行核验。'
        selected.append(item)
    staging=sqlite3.connect(OUT/'staging.sqlite')
    amd=[json.loads(row[0]) for row in staging.execute('SELECT payload FROM discovery_items') if json.loads(row[0])['source']=='AMD 官方新闻']
    for item in amd:
        item.update(news_scope='main',news_reviewed_on='2026-11-14',news_scope_reason='官方处理器技术公告；企业自述，区别于独立验证。')
    selected.extend(amd)
    cadence_url='https://www.cadence.com/en_US/home/company/newsroom/press-releases/pr/2026/cadence-introduces-maestro-a-domain-specialized-ai-model.html'
    selected.append({'title':'Cadence Introduces Maestro, a Domain-Specialized AI Model Portfolio to Revolutionize Agentic Chip and System Design',
                     'url':cadence_url,'source':'Cadence 官方公告','content_type':'news','published_at':'2026-10-26',
                     'collected_at':_now(),'date_kind':'news_published','news_genre':'企业官方公告',
                     'summary':'Cadence发布面向芯片与系统设计智能体的Maestro专用AI模型组合，介绍其与EDA工具及强化学习反馈的集成方式。公告中的效果描述属于企业自述。',
                     'summary_kind':'manual','news_scope':'main','news_reviewed_on':'2026-11-14',
                     'verification_note':'人工通过公开网页检索读取官方公告，核对标题与页面26 Oct 2026发布日期；直连采集受限，未宣称已启用该站自动采集。',
                     'verification_source':cadence_url})
    result=upsert_items(selected,origin='collected',db_path=DB)
    for source_id,name in [('semieng_ic','Semiconductor Engineering'),('eetimes_ic','EE Times'),('amd_news_ic','AMD 官方新闻')]:
        runs=[r for r in list_runs(20,db_path=OUT/'staging.sqlite') if r['source_id']==source_id and r['status']=='success']
        if not runs:continue
        run=dict(runs[0]);run.pop('id',None)
        amount=sum(x['source']==name for x in selected)
        run.update(source_name=name+' · 历史补采与范围复核',found=amount,inserted=amount,updated=0,
                   coverage_warning=(run.get('coverage_warning','')+' 本轮经题名和来源简介范围复核后导入，剔除广告及外围资料。'))
        record_run(run,db_path=DB)
    record_run({'source_id':'cadence_manual','source_name':'Cadence 官方公告 · 人工核对',
                'started_at':_now(),'finished_at':_now(),'window_start':'2026-10-16','window_end':'2026-11-14',
                'status':'success','found':1,'inserted':1,'updated':0,
                'coverage_warning':'单篇官方公告人工核对，尚未启用此站自动采集。'},db_path=DB)
    report={'result':result,'reviewed_candidates':len(candidates),'skipped':len(REJECT),
            'selected_by_source':dict(Counter(x['source'] for x in selected)),
            'new_before_nov10':sum(x['published_at']<'2026-11-10' for x in selected),'decisions':decisions}
    (OUT/'import-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='decisions'},ensure_ascii=True))


if __name__=='__main__':main()
