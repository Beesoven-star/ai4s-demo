"""Explainable metadata screening for AI + IC; never a full-text verdict."""
from functools import lru_cache
import json
import re
from pathlib import Path

VERSION = 'ic-review-20261114-v2'
TRACKS = {'ai_for_ic':'AI用于芯片设计', 'ic_for_ai':'芯片用于AI计算', 'general_ic':'通用集成电路研究'}
TOPICS = [
    {'id':'A1','track':'ai_for_ic','name':'LLM辅助RTL设计、验证与修复', 'focus':'以生成模型和工具反馈改进RTL生成、验证、调试和代码恢复。'},
    {'id':'A2','track':'ai_for_ic','name':'学习方法辅助综合、物理设计与PPA评估', 'focus':'用学习模型支持逻辑综合、布局布线、时序、功耗和拥塞预测。'},
    {'id':'A3','track':'ai_for_ic','name':'AI辅助模拟与射频电路设计', 'focus':'用学习或生成方法探索电路拓扑、器件尺寸与仿真规格。'},
    {'id':'A4','track':'ai_for_ic','name':'AI辅助器件、制造、测试与安全', 'focus':'用学习方法支持器件建模、工艺检测、故障诊断与安全评估。'},
    {'id':'A5','track':'ai_for_ic','name':'AI辅助芯粒与架构搜索', 'focus':'用学习、智能体或贝叶斯优化探索芯粒与芯片架构设计空间，并优化微架构控制策略。'},
    {'id':'A6','track':'ai_for_ic','name':'AI辅助EDA工具、数据与评测', 'focus':'AI设计智能体、检索问答、基础模型综述和可复用数据工具。'},
    {'id':'B1','track':'ic_for_ai','name':'AI加速器与软硬件协同设计', 'focus':'面向模型训练、推理和神经形态计算设计专用硬件。'},
    {'id':'B2','track':'ic_for_ai','name':'面向AI的存内计算与存储', 'focus':'围绕神经网络工作负载改善存储、计算映射、精度和能效。'},
    {'id':'B3','track':'ic_for_ai','name':'面向AI的芯粒、互连与光子计算', 'focus':'围绕AI计算需求设计芯粒、互连或光子计算系统。'},
    {'id':'C1','track':'general_ic','name':'通用电路、器件与设计基础', 'focus':'保留少量电路实现、传统算法和验证背景资料；不将其当作AI方法研究。'},
]
BY_NAME = {topic['name']:topic for topic in TOPICS}
BY_ID = {topic['id']:topic for topic in TOPICS}

@lru_cache(maxsize=1)
def curated_reviews():
    path=Path(__file__).resolve().parents[1]/'resources/ic_paper_review_20261114.json'
    return json.loads(path.read_text(encoding='utf-8'))['reviews'] if path.exists() else {}

def reviewed_analysis(item,review):
    topic_ids=review['topic_ids']
    tracks=list(dict.fromkeys(BY_ID[t]['track'] for t in topic_ids))
    decision=review['decision']
    scope='main' if decision in {'ai_focus','selected_background'} else 'pending' if decision=='needs_review' else 'excluded' if decision=='excluded' else 'archive'
    evidence=[{'topic_id':t,'track':BY_ID[t]['track'],'field':'title_abstract' if review['basis']=='title_abstract' else 'title',
        'ai_signal':review['title_evidence'],'task_signal':review['abstract_evidence']} for t in topic_ids]
    if not evidence:evidence=[{'topic_id':'范围审核','track':'','field':review['basis'],
        'ai_signal':review['reason'],'task_signal':review['abstract_evidence'] or review['title_evidence']}]
    return {'version':VERSION,'tracks':tracks,'topic_ids':topic_ids,'topics':[BY_ID[t]['name'] for t in topic_ids],
        'evidence':evidence,'status':decision,'scope':scope,'basis':review['basis'],
        'reviewed_on':review['reviewed_on'],'scope_label':{'main':'主文献库','archive':'扩展归档','pending':'研究关联尚不明确','excluded':'非研究记录'}[scope],
        'note':review['reason']+' '+review['limitation']}

def scope_of(analysis):
    return analysis.get('scope') or ('main' if analysis['tracks'] else 'pending')

def scope_matches(payload,scope):
    return int(scope_of(from_payload(payload))==scope)


def latest_paper_dates(papers, today):
    dates = {}
    for paper, scope in papers:
        day = paper.get('published_at')
        if day and day <= today:
            for key in (scope, 'all'):
                dates[key] = max(day, dates.get(key, ''))
    return dates
AI = re.compile(r'\b(?:LLMs?|large language models?|language models?|machine learning|deep learning|neural(?:[- ]network)?s?|reinforcement learning|graph neural|artificial intelligence|generative (?:AI|models?)|AI|DNNs?|CNNs?|neuromorphic|spiking|autoencoders?|GNNs?|bayesian optimization)\b', re.I)
LEARNING = re.compile(r'\b(?:(?:LLMs?|large language models?|language models?)[- ](?:based|guided|driven|assisted|orchestrated|augmented|training)|machine learning(?!\s*(?:\(|applications|workloads))|deep learning|reinforcement learning|graph neural|graph networks?|(?:deep|recurrent|convolutional) neural networks?|(?:using|via|based on).{0,35}neural networks?|neural[- ]network[- ]based|[CD]NN[- ]based|physics[- ]informed|generative (?:AI|models?)|AI[- ](?:aided|assisted|driven|based)|GNNs?|autoencoders?|bayesian optimization|flow matching|XGBoost|knowledge distillation|agentic|multi[- ]agent|transformer[- ]based|fine[- ]tuning|train\w*.{0,25}LLMs?)\b', re.I)
DESIGN = {
    'A1':r'\b(?:RTL|Verilog|HDL|testbenches?|hardware verification)\b',
    'A2':r'\b(?:logic synthesis|physical design|placement|routing|timing prediction|timing analysis|congestion prediction|clock[- ]mesh|clock gating|IR[- ]drop|PPA|electromigration|capacitance extraction|circuit link prediction)\b',
    'A3':r'\b(?:analog|analogue|mixed[- ]signal|RF|radio[- ]frequency|transistor[- ]level|passive device)\b.{0,100}\b(?:design|sizing|topology|generation|extraction|model|optimi)|\b(?:circuit design|sizing|topology).{0,70}\b(?:analog|RF)\b',
    'A4':r'\b(?:device model|device modeling|lithograph\w*|hotspot detection|defect detection|fault diagnosis|fault detection|attack detection|hardware security|logic locking|post[- ]silicon|manufacturing|wafer|yield prediction)\b',
    'A5':r'\b(?:design[- ]space exploration|architecture search|chiplet design|architectural exploration|design space exploration)\b',
}
HARDWARE = re.compile(r'\b(?:accelerators?|ASICs?|SoCs?|FPGA|hardware|chips?|chiplets?|integrated circuits?|CMOS|in[- ]memory|near[- ]memory|compute[- ]in[- ]memory|processing[- ]in[- ]memory|neuromorphic|photonic computing)\b', re.I)
TARGET_AI = re.compile(r'\b(?:neuromorphic|spiking|AI (?:inference|training|workload\w*|chips?|SoCs?|accelerator\w*)|(?:DNNs?|CNNs?|neural[- ]networks?|transformers?|LLMs?|language models?).{0,65}(?:accelerators?|workloads?)|(?:accelerators?|in[- ]memory computing|compute[- ]in[- ]memory|processing[- ]in[- ]memory).{0,100}(?:DNNs?|CNNs?|neural networks?|transformers?|AI|LLMs?)|(?:serving|executing).{0,45}(?:LLMs?|language models?|DNNs?))\b', re.I)
GENERAL_TITLES = {
    'Challenges in the verification of MOSAIX ASIC for ALICE ITS3',
    'A flexible electronics and DAQ system for the Timepix4 ASIC',
    'Chiplet-Escape: An Efficient Obstacle-Avoiding Escape Routing Method for Die-to-Die Interconnections in Chiplet-Based Designs',
    'A 16-Channel Cryo-CMOS Flux Control Pulse Generator ASIC',
    'Integrated Low-Power Self-Coherent Kramers--Kronig Millimeter-Wave Receiver With Nonlinear Analog and Mixed-Signal Computing',
    'An 11.5-Gb/s/pin, 0.4-V Driver-Supply Transmitter With Switched-Coupling Charge-Pump-Based Crosstalk Cancellation for Ultra-Dense Capacitively Coupled Channels',
}


def _snippet(text, pattern):
    match = pattern.search(text)
    if not match:
        return ''
    start, end = max(0,match.start()-75), min(len(text),match.end()+140)
    return ('…' if start else '') + text[start:end].strip() + ('…' if end < len(text) else '')


def analyze(item):
    review=curated_reviews().get(item.get('id'))
    if review and review['title']==item.get('title') and item.get('content_type')=='paper':
        return reviewed_analysis(item,review)
    title = str(item.get('title') or '')
    abstract = str(item.get('abstract_text') or '') if item.get('content_type') == 'paper' else str(item.get('summary') or '')
    # Do not treat a generated summary as original paper evidence.
    if item.get('content_type') == 'paper' and item.get('summary_kind') not in (None,'source'):
        abstract = ''
    body = title + '. ' + abstract
    evidence, topic_ids = [], []
    units = [('title',title)] + [('abstract',part) for part in re.split(r'(?<=[.!?])\s+',abstract) if part]
    for topic_id, expression in DESIGN.items():
        task = re.compile(expression, re.I)
        linked = next(((field,text) for field,text in units if LEARNING.search(text) and task.search(text)), None)
        if linked and AI.search(body):
            topic_ids.append(topic_id)
            field, text = linked
            evidence.append({'topic_id':topic_id, 'track':'ai_for_ic', 'field':field,
                'ai_signal':_snippet(text,LEARNING), 'task_signal':_snippet(text,task)})
    title_topics = {entry['topic_id'] for entry in evidence if entry['field']=='title'}
    if title_topics:
        # Avoid routing a clearly titled analog/RTL paper to manufacturing merely
        # because its abstract mentions manufacturing in the background.
        evidence = [entry for entry in evidence if entry['topic_id'] in title_topics]
        topic_ids = [topic_id for topic_id in topic_ids if topic_id in title_topics]
    hardware_link = next(((field,text) for field,text in units if AI.search(text) and TARGET_AI.search(text) and HARDWARE.search(text)), None)
    if hardware_link:
        hardware_field, hardware_text = hardware_link
        hardware_topic = 'B1'
        special = re.compile(r'\b(?:in[- ]memory|near[- ]memory|compute[- ]in[- ]memory|processing[- ]in[- ]memory|memory|memories|ReRAM|memristor|CIM|PIM|chiplets?|interconnect\w*|photonic\w*|silicon photonics|optical (?:neural|comput))\b',re.I)
        category_text = title if special.search(title) else body
        if re.search(r'\b(?:in[- ]memory|near[- ]memory|compute[- ]in[- ]memory|processing[- ]in[- ]memory|memory|memories|ReRAM|memristor|CIM|PIM)\b',category_text,re.I):
            hardware_topic = 'B2'
        if re.search(r'\b(?:chiplets?|interconnect\w*|photonic\w*|silicon photonics|optical (?:neural|comput))\b',category_text,re.I):
            hardware_topic = 'B3'
        topic_ids.append(hardware_topic)
        evidence.append({'topic_id':hardware_topic,'track':'ic_for_ai',
            'field':hardware_field,
            'ai_signal':_snippet(hardware_text,TARGET_AI), 'task_signal':_snippet(hardware_text,HARDWARE)})
    if not topic_ids and title in GENERAL_TITLES:
        topic_ids.append('C1')
        evidence.append({'topic_id':'C1','track':'general_ic','field':'title',
            'ai_signal':'作为通用IC背景资料展示，当前未标注AI方法。', 'task_signal':title})
    tracks = list(dict.fromkeys(BY_ID[topic_id]['track'] for topic_id in topic_ids))
    return {'version':VERSION, 'tracks':tracks, 'topic_ids':topic_ids,
        'topics':[BY_ID[topic_id]['name'] for topic_id in topic_ids], 'evidence':evidence,
        'scope':'archive' if item.get('ingestion_scope')=='archive' else 'pending',
        'scope_label':'扩展归档' if item.get('ingestion_scope')=='archive' else '按题名与摘要归类' if abstract else '按题名归类',
        'status':'background_selected' if tracks==['general_ic'] else 'metadata_candidate' if tracks else 'unconfirmed',
        'basis':'title_abstract' if abstract else 'title_only',
        'note':'作为通用电路背景收录，归类依据为论文题名。' if tracks==['general_ic'] else
            '研究方向依据题名和可用摘要中的方法及任务表述。' if tracks else
            '已收录资料中缺少能说明 AI 方法与研究任务关系的表述。'}


@lru_cache(maxsize=2048)
def from_payload(payload):
    return analyze(json.loads(payload))


def matches(payload, track, topic):
    analysis = from_payload(payload)
    track_ok = not track or (track == 'any_ai' and bool(set(analysis['tracks']) & {'ai_for_ic','ic_for_ai'})) or (track == 'unconfirmed' and scope_of(analysis)=='pending') or track in analysis['tracks']
    return int(track_ok and (not topic or topic in analysis['topic_ids']))


def exploration(db_path=None):
    from src.discovery import _connect, LOCAL_TZ
    from datetime import datetime
    from src.publication_timing import assess
    conn = _connect(db_path)
    try:
        papers = [json.loads(row['payload']) for row in conn.execute("SELECT payload FROM discovery_items WHERE content_type='paper' ORDER BY published_date DESC,collected_date DESC,id")]
    finally:
        conn.close()
    items = []
    for paper in papers:
        analysis = analyze(paper)
        items.append({**{key:paper.get(key) for key in ('id','title','source','url','doi','arxiv_id','published_at','publication_month','publication_year','date_kind','venue_name','journal','collected_at')},
            'abstract_text':(paper.get('abstract_text') or '')[:1000], 'ic_ai':analysis,
            'publication_timing':assess(paper)})
    main=[item for item in items if scope_of(item['ic_ai'])=='main']
    counts = {'total':len(items), 'ai_for_ic':sum('ai_for_ic' in item['ic_ai']['tracks'] for item in main),
        'ic_for_ai':sum('ic_for_ai' in item['ic_ai']['tracks'] for item in main),
        'both':sum('ai_for_ic' in item['ic_ai']['tracks'] and 'ic_for_ai' in item['ic_ai']['tracks'] for item in main),
        'general_ic':sum('general_ic' in item['ic_ai']['tracks'] for item in main),
        'ai_candidates':sum(bool(set(item['ic_ai']['tracks']) & {'ai_for_ic','ic_for_ai'}) for item in main),
        'main':sum(scope_of(item['ic_ai'])=='main' for item in items),
        'archive':sum(scope_of(item['ic_ai'])=='archive' for item in items),
        'excluded':sum(scope_of(item['ic_ai'])=='excluded' for item in items),
        'unconfirmed':sum(scope_of(item['ic_ai'])=='pending' for item in items)}
    topics = [{**topic,'count':sum(topic['id'] in item['ic_ai']['topic_ids'] for item in main)} for topic in TOPICS]
    return {'version':VERSION,'screened_on':datetime.now(LOCAL_TZ).date().isoformat(), 'tracks':TRACKS,'counts':counts,
        'topics':topics,'items':items, 'note':'专题归类依据题名与可用摘要。一篇论文可关联多个专题，资料数量用于浏览文献范围。'}
