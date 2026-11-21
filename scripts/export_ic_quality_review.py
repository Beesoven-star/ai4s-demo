"""Export a dated, read-only audit with no personal notes or credentials."""
from collections import Counter
import csv,json,sqlite3,sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.ic_research import analyze,scope_of,exploration
from src.publication_timing import assess,statistics
db=ROOT/'news-data/discovery-ic.sqlite'
with sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True) as conn:
    items=[json.loads(row[0]) for row in conn.execute('SELECT payload FROM discovery_items')]
papers=[i for i in items if i['content_type']=='paper']
news=[i for i in items if i['content_type']=='news']
asof=date(2026,11,14)
valid=[i for i in papers if scope_of(analyze(i))!='excluded']
counts=exploration(db)['counts']
assert len(papers)==424 and len(news)==77 and counts['main']==207
out=ROOT.parent/'集成电路文献逐条复核_2026-11-14.csv'
fields=['id','title','source','doi','arxiv_id','collected_at','published_at','publication_month','date_kind',
    'publication_group','scope','tracks','topics','review_basis','review_note','abstract_available','abstract_sources','url']
with out.open('w',encoding='utf-8-sig',newline='') as target:
    writer=csv.DictWriter(target,fieldnames=fields);writer.writeheader()
    for paper in papers:
        analysis=analyze(paper)
        writer.writerow({**{k:paper.get(k,'') for k in fields[:9]+['url']},
            'publication_group':assess(paper,asof)['label'],'scope':analysis['scope_label'],
            'tracks':' / '.join(analysis['tracks']),'topics':' / '.join(analysis['topics']),
            'review_basis':analysis['basis'],'review_note':analysis['note'],
            'abstract_available':bool(paper.get('abstract_text')),
            'abstract_sources':' / '.join(p['source'] for p in paper.get('abstract_provenance',[]))})
dates=statistics(valid,asof)
sources=Counter(i['source'] for i in news if i.get('news_scope')!='archive')
archived_sources=Counter(i['source'] for i in news if i.get('news_scope')=='archive')
months=Counter(i.get('published_at','')[:7] if i.get('published_at') else i.get('publication_month','unknown') for i in papers)
table='\n'.join(f'| {source} | {n} | {archived_sources[source]} | '+('本次人工核对，正文直连受限' if any(i.get('verification_mode')=='official_search_listing_manual' for i in news if i['source']==source) else '公开RSS／目录采集，保留来源日期')+' |' for source,n in sources.items())
cross=Counter((scope_of(analyze(p)),assess(p,asof)['kind']) for p in valid)
main_dates='、'.join(f'{label}{cross[("main",key)]}篇' for key,label in [('recent_published','近期正式发表'),('recent_preprint','近期预印本'),('historical','历史资料'),('month_only','仅月份')])
news_export=ROOT.parent/'集成电路新闻逐条复核_2026-11-14.csv'
with news_export.open('w',encoding='utf-8-sig',newline='') as target:
    fields_news=['id','title','source','published_at','collected_at','news_genre','news_scope','news_scope_reason','verification_mode','verification_note','url']
    writer=csv.DictWriter(target,fieldnames=fields_news);writer.writeheader()
    for item in news:writer.writerow({k:item.get(k,'') for k in fields_news})
report=f'''# 集成电路资料质量复核与新闻补充

复核截点：2026-11-14（北京时间）；近期窗口：2026-10-16至2026-11-14，含首尾30天。本报告为该批次快照，页面统计按当前日期滚动。

## 1. 424条原始题录何时收录、何时发表

424条是候选题录数量，包含2条非研究信息页，不应全部称为有效研究论文。首次收录日期只有两批：2026-11-10为163条、2026-11-13为261条。批量收录不代表当日发表。

| 来源日期分组 | 数量 | 判断依据 |
|---|---:|---|
| 近期正式发表 | 63 | 有精确来源发表日，落在近30天 |
| 近期预印本 | 38 | arXiv首次提交日落在近30天，不等同正式发表 |
| 历史资料 | 126 | 早于10月16日：125篇预印本、1篇正式文献 |
| 仅月份，发表日待核实 | 195 | IEEE题录仅提供2026年11月，不猜为11月1日 |
| 非研究记录 | 2 | Society Information信息页，保留记录并排除研究数量 |
| 合计 | 424 | 无删除原始记录 |

历史资料主要是2026年较早月份的预印本，并非全部为多年前论文。原始月份分布（含月份精度记录）：{ '；'.join(f'{m}：{n}条' for m,n in sorted(months.items())) }。

主库207篇的时间分布为：{main_dates}。时间分类与研究范围是两个独立维度，不能把全部424条的“近期”数字当作AI主线近期发表数量。

没有用收录日期、文章修改日期或会议举办日期代替发表日。补充摘要时也没有把OpenAlex提供的日期覆盖原出版社仅月份的精度；该日期只作辅助出处保存。

## 2. 为什么原来361篇待核对，本轮如何处理

原实现将“缺少规则命中”“普通电路”“范围拓展”和“确实依据不足”集中显示为AI关联待核对，且197条期刊题录缺摘要，因此361不能直接解释为361篇已逐篇审阅但无法判断。这个汇总方式不足以支持AI研究主线。

本轮先补元数据，再按全部424条题名与可用摘要逐项复核范围，保存ID、题名校验、角色、专题和依据。补充312条摘要：187条来自OpenAlex的DOI精确匹配及题名校验，125条从最初arXiv原始缓存恢复完整摘要。目前414条有摘要，10条缺失（含2条非研究信息页）。OpenAlex公共API说明见[官方文档](https://help.openalex.org/api/)。

| 本轮处理结果 | 数量 | 使用方式 |
|---|---:|---|
| AI交叉主线候选 | 189 | AI用于IC设计105篇，IC用于AI计算86篇；2篇跨两类，去重后189篇 |
| 精选普通电路背景 | 18 | 与AI专题分开，主库合计207篇 |
| 扩展归档 | 205 | 143篇常规背景与62篇范围拓展，不占主库；仍可检索 |
| 待复核 | 10 | 对方法或研究对象仍缺足够把握，不强行认定为AI论文 |
| 非研究记录 | 2 | 信息页排除，未来采集增加同名排除规则 |

例如TopoSizing、AnalogCoder-Pro等补充角色依据；PUF学习攻击资料标明AI用于攻击/安全评测，不混称AI生成设计。新增A6“AI辅助EDA工具、数据与评测”，与生成RTL、物理设计、模拟电路、制造测试、架构搜索分开。

**这些是题名与摘要层面的主题范围审核，尚未逐篇精读全文。** 189篇为AI交叉候选，不是论文结论认证；205篇归档表示本轮缺少直接主线依据，不代表全文绝对不含AI。待复核降至10篇既有补摘要纠正漏分，也有明确范围和信息页排除，不能宣称351篇全部已被证实有AI关联。新采集题录先进入候选待审区，不因出现AI关键词直接进入主库。

逐条结果见同目录《集成电路文献逐条复核_2026-11-14.csv》，含收录日、发表日、日期精度、研究范围、专题、依据和原文链接，不含个人收藏备注。

## 3. 按所提供网站补充新闻

原始新闻候选由13条增至77条（采集增加64条），共14个来源品牌。新增59条通过公开RSS／目录采集；另5条由CSIA与SEMI官方检索摘录/列表人工核对并明确标注限制。随后复核相关性，将12条GPU软件运维/应用及1条AI助手动态归档，**主新闻列表最终保留64条**（比原13条净增51条，其中46条公开渠道采集、5条人工核对）。不是64个独立事件，也不是64篇独立新闻报道，含企业技术博客、市场研究与协会公告。归档13条没有删除，新闻范围可切换“拓展”或“全部候选”。

| 来源 | 主列表条数 | 拓展归档 | 渠道状态 |
|---|---:|---:|---|
{table}

全部77条保留精确来源发布日期，当前范围为2026-10-19至2026-11-14。可复用渠道实际读取公开RSS或目录及文章元数据，仍受当前订阅/目录深度限制，不能保证覆盖完整30天。

- SemiAnalysis旧主站RSS停留在2025年，改为官网链接的newsletter订阅；付费正文未读取。
- TrendForce旧RSS停留在2026年7月，改读官方新闻目录，逐篇核对发布日期。
- 爱集微使用原站published_time字段，不使用create_time、update_time或“几小时前”倒推日期；无日期文章不收录。
- CSIA正文的静态资源访问403或主站超时；SEMI中国与部分SEMI Global直连受限。这3个来源本次合计5条为人工核对，页面明确写明“官方检索／列表、正文直连受限”，没有冒充已接通自动采集。其中SEMI中国一条链接为官方列表，独立正文链接未核验。
- 过滤招投标、股份回购、晚宴等低相关条目；补充排除NVIDIA的Kubernetes、集群运维、黑洞成像、图像生成等应用教程和TrendForce的AI助手动态，防止只因包含GPU或AI就进入主新闻列表。保留的NVIDIA5条偏硬件平台、模型编译/内核与硬件协同、HBM及多GPU推理系统；不是全部都涉及芯片电路设计。企业效果声明不作为已验证研究结论。

新闻逐条记录见《集成电路新闻逐条复核_2026-11-14.csv》。

来源举例：[Synopsys芯片设计博客](https://www.synopsys.com/blogs/chip-design.html)、[NVIDIA技术博客](https://developer.nvidia.com/blog/)、[芯东西](https://zhidx.com/aichip001)、[TrendForce新闻](https://www.trendforce.com/news/)、[SIA新闻与公告](https://www.semiconductors.org/news-events/latest-news/)。受限来源例子：[CSIA官方条目](https://web.csia.net.cn/newsinfo/11392807.html)、[SEMI中国官方列表](https://china.semi.org.cn/news/semiPressReleases)。

## 4. 页面与验证

每日发现新增文献时间核查卡片、日期标签和文献范围筛选，可切换主库、全部原始候选、扩展归档、待复核与非研究记录。点击时间卡片会查阅全部有效候选中的相应日期分组。详情保留发表时间、收录时间、摘要补充出处和范围审核依据。

90项相关单元测试通过；TypeScript检查及前端构建通过。HTTP验收检查文献与新闻范围、日期分组及2条收藏保留；浏览器验收核对时间卡片、待复核和新闻范围。全量旧测试发现过程受现有环境缺少pytest、aiohttp、python-dotenv等依赖影响，未宣称旧系统全量测试通过。个人收藏、备注、阅读状态不参与本轮改写；原分子数据库与旧报告保留隔离。

此次没有启用每日定时采集，没有部署GitHub Pages。接入渠道不等于系统已具备无人值守每日刷新。
'''
target=ROOT.parent/'集成电路资料质量复核与新闻补充_2026-11-14.md'
target.write_text(report,encoding='utf-8')
(ROOT/'.runtime/ic-quality-20261114/after-audit.json').write_text(json.dumps({'counts':counts,'timing':dates,'news_sources':dict(sources),'news_candidates':len(news),'news':sum(sources.values()),'news_archive':sum(archived_sources.values())},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'report':str(target),'csv':str(out),'counts':counts,'timing':dates},ensure_ascii=True))
