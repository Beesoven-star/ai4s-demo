"""Rebuild the 2026-11-20 IC briefing from the curated, read-only library.

Editorial judgements below are agent-assisted drafts, never human approval.
Only explicitly selected public fields enter the versioned snapshot.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ic_briefing import SNAPSHOT_PATH, validate_snapshot
from src.discovery import normalize_url
from src.ic_paper_notes import paper_reading_notes
from scripts.ic_news_backfill_20261120 import COUNTED_KINDS, END, EVENTS as BACKFILL_EVENTS, NEWS, START


def claim(text, *source_ids):
    return {'text': text, 'source_ids': list(source_ids)}


def score(label, value, text, *source_ids):
    return {**claim(text, *source_ids), 'label': label, 'value': value}


# Publisher coverage is deliberately provisional. Corporate/association releases,
# vendor webinars, promotional sessions and limited official lists do not count
# as independent media attention, even if hosted by a media brand.
EVENTS = [
    ('rtl-bench', 'RTL评测从功能正确走向PPA与真实流程', ['rtl'], ['2774217a470785e1672fa9e8', '09195c36351e4873ecbf5bdb'], '技术讨论', '两篇材料共同讨论AI设计评测范围，合为一个议题，不当作两个独立突破。'),
    ('rtl-physics', '以物理工具反馈约束设计智能体', ['rtl'], ['dbaf06ff9e99692a4667f41a', '7f9444b0ae8d9d1be3fdbc9d'], '技术讨论', '媒体观点与企业方法建议关联到同一议题；企业博客不计入媒体机构数。'),
    ('cadence-maestro', 'Cadence发布Maestro设计模型组合', ['rtl'], ['d9c9cfe63d6750181552ad75'], '企业发布', '仅有官方简述，效果为企业自述，不计媒体覆盖；简介未明确模拟设计范围，不向该方向扩展归类。'),
    ('chipagents', 'ChipAgents数字／模拟设计方案与演示', ['rtl', 'analog'], ['24c81d058c8857aa22b27e41', '103e0884fb9d2d33d6033f82'], '企业方案', 'SEMI会员新闻稿与EE Times厂商网络研讨会合并；发布平台不同不等于独立报道。'),
    ('analog-design', 'AI辅助模拟电路设计的流程与约束', ['analog'], ['8f64592a14c42b684015a968', '285eb402bcdf2b6250368ac9'], '技术讨论', '同机构、同日的模拟／RF设计观点合为一个讨论议题。'),
    ('pim-inference', '近存计算用于缓解AI推理数据搬运', ['pim'], ['6a342d8fa359881c5f7afa48', '5cdd8006d9375cfe9e59c2b5'], '技术进展', '综合观点与产品流片报道围绕近存推理关联；产品性能预测尚未独立验证。'),
    ('pim-security', '3D存内计算的多租户安全映射', ['pim'], ['07fbcacf4e5413f3d4673ad9'], '研究摘介', '仅有研究摘介，不把它当作独立复现。'),
    ('pim-pcm', 'PCM模拟存储密度与精度权衡', ['pim'], ['18a6d6761c5b3a090f59b9c4'], '研究摘介', '原型结果为来源转述，尚未核验全文和硬件数据。'),
    ('pim-meeting', '存算一体产业大会预告', ['pim'], ['92aa190df139c7c613f79bf4'], '会议预告', '只证明会议预告发布，不证明11月20日大会已举办或技术落地；承办方宣传不计媒体覆盖。'),
    ('hbm-wall', 'AI推理的存储墙与HBM字节效率', ['hbm'], ['eb46439080619f4a7c505c69', 'ee68dcea31edefe50deed62c', '52f41d96df5dfcc41c4add07'], '技术讨论', '媒体简介与企业技术博客共同关联存储层次议题；不以企业博客抬高媒体覆盖。'),
    ('hbm-controller', 'HBM控制功能向基底逻辑迁移', ['hbm'], ['c8f51837097654657782e677'], '研究摘介', '讨论HBM控制器分区，不等同于产品大规模应用。'),
    ('hbm-thermal', 'DRAM-on-GPU堆叠的热设计空间', ['hbm', 'chiplet'], ['883dee8726b5f1d4e4881c84'], '研究摘介', '来源描述封装级热仿真；不能改写为已流片验证。'),
    ('interposer', 'imec推进硅中介层平台与开放PDK', ['chiplet'], ['e6dd821c3c594d418f4b7509'], '机构公告', '公开平台进展来自机构自身公告，不视为第三方技术验证。'),
    ('chiplet-system', '芯粒扩展中的系统约束与协同设计', ['chiplet'], ['9ef5433ffd0ca2dbecc53331', '51bbaa370e367e257706c1bd', 'b7e7eb296678650652d551ab'], '技术讨论', '多芯粒系统限制与工程观点合为一个讨论议题。'),
    ('chiplet-meta', '面向AI工作负载的芯粒开发节奏', ['chiplet'], ['ee6ec89839eb9f1c9f2b75ed'], '厂商演讲', 'EE Times承载企业演讲，不计独立媒体关注。'),
    ('optics-roadmap', 'AI带宽需求推动光互连路线讨论', ['optics'], ['6a6861bb894abcdb6781d38f', 'be79049f7ea3daa8d45b315b', 'ced077b5caa881aa7f4ff93e'], '技术讨论', '路线图、行业观点与采访关联为一个议题，避免按文章数制造多个突破。'),
    ('optics-test', 'CPO规模化测试与良率成本', ['optics'], ['b6fbd715047b092b6a578a24', '537588d0606c6ddf1216068c', '328fdf1670fbbf200480e897'], '工程约束', '光纤对准、封装及测试成本合为一个工程议题。'),
    ('optics-modulator', '面向AI互连的硅光调制器研究', ['optics'], ['be926e0150024d8ea9a9ad7d'], '研究摘介', '器件实验摘介不能代表完整链路或封装的系统级能效。'),
]

TECHNOLOGIES = [
    {
        'id': 'rtl', 'name': 'LLM辅助RTL生成与验证', 'track': 'ai_for_ic', 'topic_ids': ['A1', 'A6'],
        'tagline': '从生成代码走向工具反馈与可验证质量',
        'overview': claim('让模型生成或修复RTL，再用仿真、综合及验证工具检查结果，目标是减少设计迭代中的人工工作。现有资料同时涉及生成、验证环境与评测方法。', '9bbc7038db3f1fa234f5b94c', '8d17507365a589198532247e'),
        'assessment': claim('建议优先跟进工具反馈闭环与评测可信度。AutoC2V摘要描述综合反馈训练，RTLRepairBench提示评分语义会改变结论；因此价值应结合功能、PPA和工具预算判断。当前材料支持这一研究路径，尚不能证明可自主完成生产级芯片设计。', '9bbc7038db3f1fa234f5b94c', '199b013bceeb4f0168d36428', '2774217a470785e1672fa9e8'),
        'limitations': claim('重置与首周期语义、测试覆盖以及规格使用方式均可能影响通过率。只看一次编译或一个总分不足以评价可靠性；本版未阅读全文或复现实验。', '199b013bceeb4f0168d36428'),
        'watch_next': claim('观察是否公开工具链、测试语义、失败案例与等预算基线，以及生成后验证和PPA能否同时改善。', '199b013bceeb4f0168d36428', '9bbc7038db3f1fa234f5b94c'),
        'scores': [score('瓶颈价值', 4, '涉及生成、调试及验证的迭代负担，但当前证据仍以受限任务和摘要为主。', '9bbc7038db3f1fa234f5b94c', '8d17507365a589198532247e'), score('影响范围', 4, '可覆盖RTL生成、修复及验证环境等多个数字设计环节；不外推到全部EDA。', '8d17507365a589198532247e', '199b013bceeb4f0168d36428'), score('带动作用', 5, '工具反馈与可复核评测可作为后续设计智能体的共同基础；这是潜力判断。', '09195c36351e4873ecbf5bdb', 'dbaf06ff9e99692a4667f41a')],
        'paper_ids': ['9bbc7038db3f1fa234f5b94c', '199b013bceeb4f0168d36428', '8d17507365a589198532247e'],
        'maturity': '已见研究框架与企业方案，本版材料未提供生产部署记录。',
    },
    {
        'id': 'analog', 'name': 'AI辅助模拟与RF电路设计', 'track': 'ai_for_ic', 'topic_ids': ['A3'],
        'tagline': '把电路理解与仿真反馈接到优化过程',
        'overview': claim('利用模型理解电路拓扑、生成网表或调整尺寸，并借助仿真反馈搜索满足规格的设计。SAFTAC与TopoSizing分别提供训练反馈和拓扑理解的研究线索。', '9b19413eaab062e47b015aff', 'f5447a6635537e0217fb4cbd'),
        'assessment': claim('值得跟进的重点是模型是否理解电路约束，以及仿真反馈能否减少无效搜索。两个摘要给出不同的实现路径，适合对照研究；厂商方案与研讨会则说明这一方向正在被产品化讨论，但不作为效果认证。', '9b19413eaab062e47b015aff', 'f5447a6635537e0217fb4cbd', '103e0884fb9d2d33d6033f82'),
        'limitations': claim('摘要中的收益依赖电路类型、工艺及仿真设置；没有证据表明可直接跨工艺、跨拓扑复用。规格满足也不自动等于版图后或硅上可用。', 'f5447a6635537e0217fb4cbd', '9b19413eaab062e47b015aff'),
        'watch_next': claim('观察跨拓扑与跨工艺测试、调用及仿真预算、版图后结果，以及公开数据能否支撑复现。', 'f5447a6635537e0217fb4cbd', '9b19413eaab062e47b015aff'),
        'scores': [score('瓶颈价值', 4, '电路拓扑、尺寸与性能耦合使自动化困难，反馈优化具有直接价值。', '9b19413eaab062e47b015aff'), score('影响范围', 3, '材料覆盖若干模拟电路任务，跨工艺和更广电路类型的证据不足。', 'f5447a6635537e0217fb4cbd'), score('带动作用', 4, '仿真数据、拓扑知识与约束搜索可支撑后续模拟设计工具。', 'f5447a6635537e0217fb4cbd', '9b19413eaab062e47b015aff')],
        'paper_ids': ['9b19413eaab062e47b015aff', 'f5447a6635537e0217fb4cbd'],
        'maturity': '论文摘要描述仿真实验，厂商访谈介绍工具流程。本版材料未提供企业方案的实测结果。',
    },
    {
        'id': 'pim', 'name': '面向AI的存内与近存计算', 'track': 'ic_for_ai', 'topic_ids': ['B2'],
        'tagline': '减少数据搬运，同时处理精度与可编程性',
        'overview': claim('将部分运算放到存储阵列内部或存储附近，以降低AI任务的数据搬运负担。这里同时跟踪数字近存架构和模拟存内阵列，两者的精度、工艺和软件条件不同。', '5838a15333e5c6dceecf735e', '701dbfcc431daef8569f0bab'),
        'assessment': claim('其重要性来自存储与计算间的数据搬运限制。近期材料包含近存推理讨论、产品流片报道和温度鲁棒性研究，表明必须把架构、器件及软件一起考虑；流片报道中的性能预测不能当作实测提升。', '6a342d8fa359881c5f7afa48', '5cdd8006d9375cfe9e59c2b5', '701dbfcc431daef8569f0bab'),
        'limitations': claim('模拟路线存在温漂与精度约束，近存路线仍受负载映射和软件支持限制；跨论文的TOPS/W或时延不能直接混排。现有材料没有提供统一的独立系统复测。', '701dbfcc431daef8569f0bab', '6a342d8fa359881c5f7afa48'),
        'watch_next': claim('优先观察真实模型的端到端能耗、精度与吞吐，非理想因素补偿的成本，以及可运行的软件接口。', '701dbfcc431daef8569f0bab', '5838a15333e5c6dceecf735e'),
        'scores': [score('瓶颈价值', 5, '直接面向AI计算的数据搬运与存储墙，具有改变运算位置的潜力。', '6a342d8fa359881c5f7afa48', '701dbfcc431daef8569f0bab'), score('影响范围', 4, '材料覆盖DNN、边缘推理和多种存储路线，实际适用范围仍依赖负载。', '5838a15333e5c6dceecf735e', '5cdd8006d9375cfe9e59c2b5'), score('带动作用', 4, '可牵引器件、架构及映射软件协同，但尚未形成统一成熟接口。', '6a342d8fa359881c5f7afa48', '701dbfcc431daef8569f0bab')],
        'paper_ids': ['5838a15333e5c6dceecf735e', '701dbfcc431daef8569f0bab'],
        'maturity': '仿真、原型及产品流片报道并存；路线成熟度不同',
    },
    {
        'id': 'hbm', 'name': 'HBM与AI存储层次协同', 'track': 'ic_for_ai', 'topic_ids': ['B2'],
        'tagline': '在带宽、容量、供电与热约束间协同设计',
        'overview': claim('围绕AI工作负载设计高带宽存储层次，关注控制器分区、存储堆叠与计算侧的协同。相比只追求带宽，容量利用和热设计同样需要评估。', 'eb46439080619f4a7c505c69', 'b5a2f3ff9c508e15c44ec0f5'),
        'assessment': claim('应把HBM视为存储、互连、供电和软件共同约束的问题。库内材料讨论控制功能迁移、DRAM-on-GPU热设计与字节效率，适合形成系统评价；企业博客提供方法线索，不能替代中立比较。', 'c8f51837097654657782e677', '883dee8726b5f1d4e4881c84', 'ee68dcea31edefe50deed62c'),
        'limitations': claim('3D堆叠可能改变热设计和供电条件。NMC-HBM摘要给出电气与系统仿真框架，未证明所有工作负载受益，也不能据此认定已有规模化部署。', 'b5a2f3ff9c508e15c44ec0f5', '883dee8726b5f1d4e4881c84'),
        'watch_next': claim('跟进同负载下的有效带宽、容量利用、系统能耗及温度，核查控制器迁移收益是否覆盖新增复杂度。', 'b5a2f3ff9c508e15c44ec0f5', 'c8f51837097654657782e677'),
        'scores': [score('瓶颈价值', 5, '长上下文和并发使存储压力变化，带宽之外的容量与系统约束具有共性。', 'eb46439080619f4a7c505c69'), score('影响范围', 5, '从推理到存储层次及GPU-HBM协同涉及多个关键系统环节；属于潜在影响评价。', 'eb46439080619f4a7c505c69', 'b5a2f3ff9c508e15c44ec0f5'), score('带动作用', 4, '控制器、堆叠及软件协同能带动多环节改进，但当前例证较局部。', 'c8f51837097654657782e677', 'ee68dcea31edefe50deed62c')],
        'paper_ids': ['b5a2f3ff9c508e15c44ec0f5'],
        'maturity': 'HBM是既有平台；所评新架构主要为研究与技术讨论',
    },
    {
        'id': 'chiplet', 'name': '面向AI的芯粒与3D集成', 'track': 'ic_for_ai', 'topic_ids': ['B3'],
        'tagline': '扩展系统能力，也把难题带到封装与协同层',
        'overview': claim('通过多个芯粒、中介层或3D堆叠构建AI系统，技术评价需同时考虑接口、原型验证、热与供电。机构平台进展与工程观点提供了不同层次的线索。', 'e6dd821c3c594d418f4b7509', '9ef5433ffd0ca2dbecc53331'),
        'assessment': claim('价值在于将计算和存储扩展问题转化为可协同设计的系统问题。imec公告关注中介层及PDK，行业材料讨论多芯粒扩展边界；这支持持续跟踪平台开放性和工程可组合性，而非仅用芯粒数量判断先进程度。', 'e6dd821c3c594d418f4b7509', '51bbaa370e367e257706c1bd', '9ef5433ffd0ca2dbecc53331'),
        'limitations': claim('更多芯粒并不自动带来更高系统效率，工具速度、共享资源和热设计都可能成为限制。当前公告与讨论不足以验证跨厂商即插即用或量产良率。', '51bbaa370e367e257706c1bd', '883dee8726b5f1d4e4881c84'),
        'watch_next': claim('跟进开放PDK、系统原型、跨芯粒接口与热验证，并在相同负载下比较系统收益和集成代价。', 'e6dd821c3c594d418f4b7509', '9ef5433ffd0ca2dbecc53331'),
        'scores': [score('瓶颈价值', 4, '针对AI系统扩展和集成约束，当前资料以平台与局部验证为主。', 'e6dd821c3c594d418f4b7509', '9ef5433ffd0ca2dbecc53331'), score('影响范围', 5, '同时涉及计算、存储、接口、封装与工具协同，有广泛系统影响潜力。', 'b7e7eb296678650652d551ab', '51bbaa370e367e257706c1bd'), score('带动作用', 5, '开放中介层及PDK可能成为多种系统设计的共用底座；落地程度仍待核查。', 'e6dd821c3c594d418f4b7509')],
        'paper_ids': ['a90a0079837bc7d1607c46b6', '631fc4bbd8b63ecee0b80d69'],
        'maturity': '机构平台、系统方案与研究架构并存；未认证量产能力',
    },
    {
        'id': 'optics', 'name': 'AI光互连与共封装光学', 'track': 'ic_for_ai', 'topic_ids': ['B3'],
        'tagline': '用光扩展互连，同时面对测试与封装成本',
        'overview': claim('将光连接引入AI系统互连，并通过硅光或共封装光学缩短电连接路径，目标是缓解带宽密度与能耗压力。器件、封装和系统架构的进展需要分别看待。', '6a6861bb894abcdb6781d38f', '631fc4bbd8b63ecee0b80d69'),
        'assessment': claim('建议同时关注互连效率与可制造性。库内材料覆盖路线讨论、光调制器研究，以及CPO对准、测试与封装成本；这些线索表明“器件更快”还不足以证明整个AI系统更划算。', 'be926e0150024d8ea9a9ad7d', 'b6fbd715047b092b6a578a24', '328fdf1670fbbf200480e897'),
        'limitations': claim('光纤对准、连接耐久及光电联合测试可能影响规模化。APEX摘要给出特定DNN负载下的架构评价，不能等同于完整CPO产品的量产性能。', 'b6fbd715047b092b6a578a24', '631fc4bbd8b63ecee0b80d69'),
        'watch_next': claim('观察链路或系统级能耗是否计入光源与控制，测试成本与良率是否透明，以及动态负载下的重配置开销。', '537588d0606c6ddf1216068c', '631fc4bbd8b63ecee0b80d69'),
        'scores': [score('瓶颈价值', 5, '直接面向AI互连的带宽与能耗压力，存在改变连接路径的潜力。', '6a6861bb894abcdb6781d38f', '631fc4bbd8b63ecee0b80d69'), score('影响范围', 4, '涉及AI互连和光电集成，但不同距离、负载及封装的可用性仍有差异。', '631fc4bbd8b63ecee0b80d69', '328fdf1670fbbf200480e897'), score('带动作用', 4, '可带动器件、封装与测试发展，规模化约束使评估保持保守。', 'b6fbd715047b092b6a578a24', '537588d0606c6ddf1216068c')],
        'paper_ids': ['631fc4bbd8b63ecee0b80d69'],
        'maturity': '本版材料涵盖器件研究、架构评估和产业讨论，公开结果的范围限于各自的实验条件。',
    },
]

EXCLUDED_ATTENTION = {
    '103e0884fb9d2d33d6033f82': '厂商网络研讨会，与SEMI会员新闻稿关联，不作为独立媒体报道。',
    '92aa190df139c7c613f79bf4': '承办方会议预告，不计独立媒体关注。',
    'ee6ec89839eb9f1c9f2b75ed': '企业代表演讲，媒体承载不等于独立报道。',
}

WEEKLY_STORY = {
    'question': '从光刻材料到服务器，怎样判断进展离量产还有多远？',
    'overview': 'TECH+ 报道 JSR 韩国 EUV 光刻胶工厂已竣工。THE ELEC 跟进了 PFN 推理芯片的 3D 堆叠流片计划，ServeTheHome 则在 SC26 拍到了搭载下一代 Xeon 封装的液冷刀片。三条消息分别给出了材料供货、芯片制造和系统集成的阶段线索。',
    'research_question': '后续可核对光刻胶批次一致性和客户验证、DRAM 与逻辑堆叠后的带宽和温度，以及刀片长时间满载时的冷却与整机功耗。',
}

WEEKLY_HIGHLIGHTS = [
    {
        'event_id': 'jsr-mor-korea',
        'reading_question': '光刻胶工厂竣工后，何时能稳定供货？',
        'what_happened': 'JSR 在说明会确认韩国金属氧化物光刻胶工厂已竣工。TECH+ 报道称，JSR 计划于 2027 年初启动量产。',
        'why_it_matters': '这是面向 EUV 工艺的材料供给进展。客户使用前还要验证不同批次是否稳定，以及材料与各自产线的曝光和后续工艺是否匹配。',
        'evidence_stage': '企业确认厂房竣工。投产时间是计划，合格供货待披露。',
        'watch_next': '看客户验证、批次一致性及稳定出货的公开记录。',
    },
    {
        'event_id': 'pfn-l2000-stack',
        'reading_question': '把 DRAM 叠到逻辑裸片上，什么时候能看到实测？',
        'what_happened': 'PFN 与 SEMIFIVE 公布 MN-Core L2000 联合开发方案，将 DRAM 垂直堆叠到逻辑裸片上。THE ELEC 跟进了方案，thebell 采访了 SEMIFIVE 负责人。计划于 2027 年第一季度提交流片。',
        'why_it_matters': '缩短存储连接提供了增加带宽的路径，也让供电、热和堆叠良率成为同一设计问题。',
        'evidence_stage': '方案已公开，流片和带宽属于企业计划与目标。',
        'watch_next': '看样片是否如期产出，以及相同推理负载下的有效带宽、功耗和温度。',
    },
    {
        'event_id': 'bull-rapids-sc26',
        'reading_question': '展会上的液冷刀片，能看到哪些实物证据？',
        'what_happened': 'ServeTheHome 在 SC26 拍到 Bull 的刀片样机，可看到英特尔 Diamond Rapids 封装、双路节点及液冷接头的布局。',
        'why_it_matters': '实物照片让人看到服务器如何安排处理器、内存和冷却部件。可用性还需看实际运行条件下的温度与维护数据。',
        'evidence_stage': '记者现场见到实物，照片能确认部件布局。',
        'watch_next': '看整机交付、持续负载测试和现场维护表现。',
    },
]

ARTICLE_BRIEFS = [
    {
        'event_id': 'rohm-delta-800v',
        'reading_question': '把 800V 直流引到机柜边，能否减少供电损耗？',
        'what_happened': '台达电子日本公司与罗姆签署基本协议，准备共同明确 AI 数据中心 800V 直流供电的系统需求。TECH+ 报道解释了高功率机柜的配电与电压转换。',
        'why_it_matters': '提高配电电压会改变配线和转换环节的负担，也给功率半导体的选型带来新的约束。这条进展给「AI 芯片供电与散热」候选专题增加了机柜层面的案例。',
        'evidence_stage': '双方已签署基本协议。系统实测与部署结果待公布。',
        'watch_next': '看试点负载下的端到端效率、散热和可靠性。',
    },
    {
        'event_id': 'azure-emib',
        'reading_question': '微软选定 EMIB 后，先进封装离交付还有多远？',
        'what_happened': '微软和英特尔公布长期合作，计划为 Azure 自研芯片采用 EMIB。Tom’s Hardware 核对了披露范围，芯片型号、晶圆工艺及部署日期仍待公布。',
        'why_it_matters': '云服务商公开表态采用封装方案，使芯粒互连有了可以跟踪的客户案例。能否按时交付，还要看具体器件、验证与封装产能。',
        'evidence_stage': '双方公布采用计划。具体产品与交付规模待披露。',
        'watch_next': '看首个采用该封装的器件、封装测试及交付进度。',
    },
    {
        'event_id': 'lambda-cpo',
        'reading_question': '集群里的光互连，能省电也能好维护吗？',
        'what_happened': 'Lambda 披露在加拿大魁北克园区用 NVIDIA 共封装光学交换机连接逾一万张 Blackwell Ultra GPU，ServeTheHome 和 TechTarget 均报道了这次部署。',
        'why_it_matters': '共封装光学进入实际交换网络。评估重点从光器件本身延伸到整网功耗、故障率与现场维修。',
        'evidence_stage': '部署方披露，另有独立媒体报道',
        'watch_next': '看其他客户能否复现，以及整网功耗是否包含光源和控制开销。',
    },
    {
        'event_id': 'ucie-memory',
        'reading_question': '同一个封装里，算力芯粒和存储可以怎么接？',
        'what_happened': 'UCIe 联盟发布 4.0 版芯粒互连规范，增加了用于封装内存储连接的 UCIe.mem。Jon Peddie Research 随后分析了协议变化和系统设计影响。',
        'why_it_matters': 'UCIe.mem 给封装内存储连接提供了开放接口，影响 SoC 与存储逻辑裸片的组合方式。',
        'evidence_stage': '联盟发布规范，本期有专业媒体解读',
        'watch_next': '看不同厂商器件能否在参考板上互操作，以及整套系统的测试和验证结果。',
    },
    {
        'event_id': 'titania-dimc',
        'reading_question': '推理时，能少在存储和计算单元之间搬几次数据吗？',
        'what_happened': 'Axelera AI 公布面向数据中心推理的 Titania 芯粒架构。在其披露的设计中，数字存内计算、LPDDR6 和可编程 RISC-V 计算集成在同一封装。',
        'why_it_matters': 'Titania 将数字存内计算用于面向机房的推理芯粒，提供了一条减少数据搬运的设计路线。',
        'evidence_stage': '产品架构披露与媒体分析',
        'watch_next': '看相同模型与精度下的整机能耗、吞吐和软件适配。',
    },
]


def build(database=ROOT / 'news-data/discovery-ic.sqlite', output=SNAPSHOT_PATH):
    conn = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        records = {x['id']: x for row in conn.execute('SELECT payload FROM discovery_items') if (x := json.loads(row[0]))}
    finally:
        conn.close()
    ids_by_url = {normalize_url(item['url']): item['id'] for item in records.values()}
    backfill_ids = {key: ids_by_url.get(normalize_url(url))
                    for key, _, _, _, _, _, url, _, _ in NEWS}
    missing_news = [key for key, ident in backfill_ids.items() if ident is None]
    if missing_news:
        raise ValueError(f'Run scripts/ic_news_backfill_20261120.py first. Missing: {missing_news}')
    reviewed_sources = {backfill_ids[key]: (author, kind, summary, note)
                        for key, _, _, author, kind, _, _, summary, note in NEWS}
    events = [
        {'id': eid, 'title': title, 'technology_ids': tids,
         'source_ids': [backfill_ids[key] for key in keys], 'kind': kind,
         'grouping_note': note, 'occurred_at': day, 'date_basis': '来源发布日期'}
        for eid, title, tids, keys, kind, day, note in BACKFILL_EVENTS
    ] + [
        {'id': eid, 'title': title, 'technology_ids': tids, 'source_ids': sids, 'kind': kind,
         'grouping_note': note, 'occurred_at': None, 'date_basis': '来源发布日期'}
        for eid, title, tids, sids, kind, note in EVENTS
    ]

    technologies = deepcopy(TECHNOLOGIES)
    by_tech = {tech['id']: tech for tech in technologies}

    def cite(tech, field, update, *keys):
        entry = by_tech[tech][field]
        entry['text'] = f"{entry['text']} {update}"
        entry['source_ids'].extend(backfill_ids[key] for key in keys)

    def revise_score(tech, index, update, *keys):
        entry = by_tech[tech]['scores'][index]
        entry['text'] = update
        entry['source_ids'].extend(backfill_ids[key] for key in keys)

    cite('optics', 'assessment', 'Lambda 项目提供了规模化网络部署案例，媒体补充了可换光源、维修和功耗预算的分析。Marvell 的光内存池仍处于另一条产品路线的联合开发阶段。', 'lambda-official', 'lambda-sth', 'lambda-techtarget', 'marvell-official')
    cite('optics', 'watch_next', '跟进不同客户部署的故障率、现场维修耗时及整网功耗对比。', 'lambda-techtarget')
    by_tech['optics']['maturity'] = '网络交换有客户披露的生产部署案例。跨机架光内存共享仍在联合开发'
    revise_score('optics', 2, '规模部署为封装、测试和维修协同提供了工程案例。可复制性与长期运维成本仍待更多客户数据，带动作用评为4。', 'lambda-sth', 'lambda-techtarget')

    cite('hbm', 'assessment', '本周光内存池与封装内存储链路提供了扩充容量的不同路径。评估应区分片上 HBM、CXL 扩容和远端共享的带宽、延迟与用途。美光 3D DRAM 时间表属于企业展望。', 'marvell-register', 'ucie-official', 'micron-trendforce', 'micron-summit')
    cite('hbm', 'assessment', 'THE ELEC 另报道三星在 HBM5 上探索先分别制造存储和外围逻辑晶圆、再键合的路线。该消息来自产业人士，设计细节和量产时间待三星公开确认。', 'samsung-dram-elec')
    cite('hbm', 'watch_next', 'PFN 的方案将 DRAM 叠在逻辑裸片上，可作为不同存储集成路线的对照。优先比较样片的有效带宽、功耗和温度。', 'pfn-3dic-official', 'pfn-3dic-thebell')
    revise_score('hbm', 1, '片上高带宽、封装内连接和机架级内存扩容都影响系统设计。AI 存储研发投入与制造转化成本进一步支持影响范围5分。', 'marvell-register', 'ucie-jpr', 'micron-eetimes')
    by_tech['hbm']['maturity'] = 'HBM 有既有商用平台。所列光内存池及 3D DRAM 路线处于开发或路线讨论阶段'

    cite('chiplet', 'assessment', 'UCIe 4.0 将规范覆盖延伸到封装内存储连接。Titania 提供了专用推理芯粒的设计示例，现阶段可据此跟踪验证板、跨厂商互操作和系统签核。', 'ucie-official', 'ucie-jpr', 'titania-jpr')
    cite('chiplet', 'assessment', '微软为 Azure 自研芯片公开提出采用 EMIB 的计划，增加了可以跟踪的客户案例。芯片型号、晶圆工艺和实际交付时间待披露。', 'emib-intel', 'emib-toms')
    cite('chiplet', 'watch_next', '新收录的 PFN 项目提供了可跟踪的流片时间。车载 ACIR 文件则提供了不同厂商芯粒组合时的错误报告、启动和供电管理要求，可作为系统验证的对照。', 'pfn-3dic-official', 'asra-acir-imec')
    revise_score('chiplet', 2, '开放中介层、PDK 和 UCIe.mem 形成可复用的技术基础，带动作用评为5。跨厂商器件组合和量产验证仍需实证。', 'ucie-official', 'ucie-jpr')
    by_tech['chiplet']['maturity'] = '已有开放标准、机构平台和厂商设计。本版材料未提供跨厂商量产互操作的测试结果。'

    cite('pim', 'assessment', 'Titania 后续报道把数字存内计算的适用场景扩展到机房推理。Raptor 采访提供另一条堆叠 DRAM 路线线索，两者都需要统一负载下的端到端比较。', 'titania-jpr', 'titania-official', 'raptor-interview')
    revise_score('pim', 1, '覆盖边缘到机房推理的设计目标，实际影响范围受负载、精度和软件支持约束，初评4。', 'titania-jpr')
    by_tech['pim']['maturity'] = '已有原型，也有产品披露和架构计划。Titania、Raptor 的材料以路线介绍为主，缺少同负载下的独立性能对照。'

    cite('rtl', 'assessment', '新增厂商访谈强调由工程师检查结果、根据反馈迭代。相关展会预告也提及硬件辅助验证。两项材料仅支持继续跟踪工具链，当前评分仍主要依据已有研究与可复核评测。', 'chipnexus-interview', 'synopsys-sc26')
    cite('analog', 'assessment', '新增 ChipNexus 访谈提供了工具接入与人工评估的工程线索。下一步优先核对跨工艺结果和仿真误差，再判断影响范围。', 'chipnexus-interview')

    needed = {sid for event in events for sid in event['source_ids']}
    for tech in technologies:
        needed.update(tech['paper_ids'])
        for c in [tech['overview'], tech['assessment'], tech['limitations'], tech['watch_next'], *tech['scores']]:
            needed.update(c['source_ids'])
    missing = needed - records.keys()
    if missing:
        raise ValueError(f'Missing curated evidence: {sorted(missing)}')
    sources = {}
    for sid in sorted(needed):
        raw = records[sid]
        source = {k: raw.get(k) for k in ('id', 'content_type', 'title', 'source', 'url', 'published_at', 'publication_month', 'venue_type', 'news_genre')}
        source['excerpt'] = raw.get('abstract_text') or raw.get('summary') or ''
        if raw['content_type'] == 'paper':
            source['evidence_kind'] = '原始摘要' if raw.get('abstract_text') else '已收录摘要或简介' if source['excerpt'] else '论文题录'
        else:
            source['evidence_kind'] = '报道简述' if raw.get('summary_kind') == 'human' else '来源简介'
        if (notes := paper_reading_notes(raw)) and notes['basis'] == 'abstract' and notes['points']:
            source['reading_takeaway'] = notes['points'][0]['text']
        media = raw['source'] in ('Semiconductor Engineering', 'EE Times') and sid not in EXCLUDED_ATTENTION
        source['organization'] = raw['source']
        source['attention_eligible'] = raw['content_type'] == 'news' and media
        source['attention_note'] = EXCLUDED_ATTENTION.get(sid) or ('按媒体机构计入本期覆盖。来源简介提供报道线索，稿件的署名、赞助或转载关系需要原文信息才能区分。' if media else '论文或企业／机构自述不计媒体覆盖；保留为技术线索。')
        if sid in reviewed_sources:
            author, kind, summary, note = reviewed_sources[sid]
            source.update(
                author=author, news_genre=kind, excerpt=summary, evidence_kind='原文核对简述',
                attention_eligible=kind in COUNTED_KINDS, attention_note=note,
            )
        sources[sid] = source
    in_period = [source for sid, source in sources.items() if sid in reviewed_sources
                 and START <= (source.get('published_at') or '') <= END]
    result = {
        'schema_version': 1, 'edition': '2026-11-20-manufacturing-and-integration', 'prepared_on': '2026-11-21', 'data_through': END,
        'title': '集成电路热点与技术观察',
        'backfill': {'date_from': START, 'date_to': END, 'reviewed_in_window': len(in_period),
                     'counted_in_window': sum(s['attention_eligible'] for s in in_period)},
        'coverage': {'library_papers': sum(x['content_type'] == 'paper' for x in records.values()),
            'library_news': sum(x['content_type'] == 'news' for x in records.values()),
            'selected_news': sum(x['content_type'] == 'news' for x in sources.values()),
            'selected_papers': sum(x['content_type'] == 'paper' for x in sources.values())},
        'attention_label': '热点关注度 · 来源覆盖初榜',
        'attention_method': '按媒体机构数、合并后的讨论或事件数、媒体报道覆盖天数依次降序，完全相同则并列。11月15日至20日的新增材料依据原站稿件核对，署名报道和实质技术分析计入媒体覆盖。同稿分发、二手编译、厂商内容及含赞助披露的采访作为背景呈现。',
        'importance_method': '瓶颈价值、影响范围、带动作用各计 1–5 分，等权合计 15 分，按总分排序并连续编号。每项分数链接到本版引用的论文摘要、标准文件、报道或披露。',
        'limitations': ['固定资料快照，统计以媒体稿件的原站发布日期为准。对较早事件的本周解读仍可计报道覆盖。',
            '热点榜统计本期选入的独立事件与讨论，允许收录尚无正式技术专题的进展。技术重要性榜沿用六个已评价方向。',
            '媒体采访和厂商披露用于了解技术路线。性能和商业化日期按报道中的发布方口径理解。',
            '同一新闻可关联多个方向，跨方向计数宜分别阅读。'],
        'weekly_story': deepcopy(WEEKLY_STORY),
        'weekly_highlights': deepcopy(WEEKLY_HIGHLIGHTS),
        'article_briefs': deepcopy(ARTICLE_BRIEFS),
        'events': events,
        'technologies': [{**t, 'review_status': 'provisional', 'reviewed_by': None, 'reviewed_on': None,
            'evidence_status': {
                'rtl': '论文摘要提供评测结果，媒体与厂商材料补充工具流程。结果适用于材料描述的任务和预算。',
                'analog': '论文摘要、技术报道和厂商访谈提供方法线索。现有对比限于各资料所列的工艺与实验条件。',
                'pim': '论文摘要、产品披露与采访覆盖不同层级。性能比较需要对齐负载、精度和系统边界。',
                'hbm': '材料包含公开规范、产业报道和厂商路线。不同存储方案的带宽、延迟和容量口径分别理解。',
                'chiplet': '标准文件和机构公告说明接口要求，报道与厂商披露说明项目阶段。系统互操作取决于具体实现与测试条件。',
                'optics': '客户披露支持交换网络已部署，媒体补充了维修和功耗讨论。长期故障率与整网实测功耗在本版材料中未见。',
            }[t['id']]} for t in technologies],
        'sources': sources,
    }
    validate_snapshot(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'technologies': len(technologies), 'events': len(events), **result['coverage'], **result['backfill']}, ensure_ascii=False))
    return result


if __name__ == '__main__':
    build()
