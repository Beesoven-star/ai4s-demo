"""Apply the bounded metadata review of the 243 active archived papers.

Uses the saved active-item snapshot and DOI/title-validated abstract proposals.
Does not recollect, remove, or recover records. Decisions are a dated editorial
review, not keyword predictions or full-text validation.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.discovery import _connect, _write_item, _now
from src.ic_research import analyze, curated_reviews, from_payload

BATCH = ROOT / '.runtime/archive-review-20261114'
REVIEW_PATH = ROOT / 'resources/ic_paper_review_20261114.json'

# Each tuple records the actual role of learning or the AI workload, rather
# than treating every occurrence of "AI", "transformer", or "learning" alike.
PROMOTE = {
    3: (['B1'], '分析H100和Wormhole的物理约束，并针对FlashAttention提出wave-aware clustering；属于AI内核与硬件协同优化。'),
    42: (['B3'], '针对Physical-AI加速器的512位NoC路由器验证冗余可靠性，并给出完整AI计算tile的GEMM结果。'),
    61: (['B2'], '综述光电阻变存储及其在神经形态、光学存内计算系统中的集成，作为AI存储方向综述收录。'),
    67: (['A4', 'B3'], 'OptoSynthesizer包含physical-AI辅助逆向设计与光刻环节，并面向光子张量核和AI互连；不把全部布局布线算法都称为AI。'),
    75: (['A4'], 'PRISM训练可微制造模型并优化光子器件掩模，属于学习方法辅助制造；仅审核当前在库预印本。'),
    103: (['B1'], '深度学习传感融合模型直接驱动28nm异构处理器及卷积加速器设计，给出多种感知任务测量结果。'),
    110: (['B3'], 'THz-TSI研究3D集成的高带宽无线互连，摘要明确以AI/HPC系统带宽和延迟为目标。'),
    128: (['A1'], 'SmootHDL使用贝叶斯优化选择结构多样的HDL测试程序，检测FPGA综合编译器错误。'),
    205: (['B2'], '6T/11T存内计算电路实现二值神经网络卷积，AI是硬件运行的工作负载。'),
    206: (['A3'], '神经网络近似非线性电路元件散射方程，双参数波数字滤波器改善学习表示；属于学习辅助电路建模。'),
    207: (['B1'], '题名明确研究用于穿戴式边缘计算的可拉伸神经形态电路；按题名收录，摘要尚未获取。'),
    208: (['B1'], '可重构晶体管实现逻辑、突触和神经元，联合设计输入选择与脉冲神经网络硬件。'),
    210: (['A1'], '训练专用LLM生成SystemVerilog断言，RTL作为双向数据合成与验证依据。'),
    211: (['A3'], '图Transformer预测模拟电路寄生参数，并通过版图后仿真验证预测网表。'),
    212: (['A1'], 'LLM自动构造子系统RTL的UVM环境与激励，属于设计验证自动化。'),
    213: (['A3'], 'UNCHARTED用图神经网络模拟模拟电路瞬态行为，并以反向传播执行尺寸与逆向设计。'),
    214: (['A4'], 'DeTrojan用图神经网络对门级硬件木马进行检测和定位。'),
    215: (['B3'], '针对硅光子近传感器加速器联合训练ViT并建模实测硬件噪声，AI是光子系统计算对象。'),
    216: (['B2'], 'IGZO eDRAM大容量片上缓冲与KV缓存映射共同改善LLM推理访存。'),
    217: (['A6'], '评测电路网表GNN的持续学习、节点分类与连边预测，属于EDA学习模型基准。'),
    218: (['A5', 'B3'], 'Chiplet-NAS以TPE搜索神经网络与2.5D芯粒方案，联合优化精度、延迟和能耗。'),
    219: (['A6'], 'MuaLLM以多模态LLM、RAG和电路文献库辅助设计问答，包含检索与推理评测数据。'),
    220: (['A2'], '物理信息贝叶斯优化用于2.5D芯粒供电网络去耦电容布局，属于学习辅助物理设计。'),
    221: (['B2'], 'SpAct-NDP联合近数据处理与GPU架构优化稀疏激活LLM推理。'),
    222: (['A2'], '题名明确以贝叶斯优化和强化学习执行VLSI约束调优；按题名收录，摘要尚未获取。'),
    223: (['A3'], 'MOSTAR联合GNN子结构识别与分阶段贝叶斯优化完成模拟电路尺寸设计。'),
    224: (['A1'], '题名明确是LLM辅助电路验证综述；按题名收录为综述资料，摘要尚未获取。'),
    225: (['B2'], 'SCION仿真电荷型存内计算非理想性并评估DNN精度；DNN是工作负载，不是用于设计电路的学习模型。'),
    226: (['A1'], 'AutoVeriFix使用Python参考模型和自动测试反馈修复LLM生成的Verilog功能错误。'),
    227: (['A4'], 'SCPrompt联合RTL语义压缩和LLM推理检测硬件木马。'),
    228: (['A3'], 'MOTIF-RF学习射频片上变压器代理模型，采用频域迁移学习并支持逆向设计。'),
    229: (['B2'], 'SMOOTH以硬件信号和细粒度缓冲分配改善端侧LLM片上存储管理。'),
    230: (['B2'], 'SHyLA面向LLM数据特征设计3D堆叠NVM/DRAM混合存储架构。'),
    231: (['B2'], 'HybridSpec联合混合键合存储、异构架构与推测解码加速LLM服务。'),
    232: (['B2'], 'DCC为机器学习内核联合优化Host/PIM数据布局与编译，目标为近存AI计算。'),
    233: (['B1'], 'WaferBRAIN联合事件表示、路由、存储与拓扑设计晶圆级神经形态计算架构。'),
    234: (['B3'], 'COMET针对真实DNN/LLM的细粒度DMA流量联合优化芯粒通信与存储映射。'),
    235: (['A5'], 'Athena以在线强化学习协调预取器与片外预测器，属于学习辅助微架构策略优化，而非AI模型推理加速器。'),
    236: (['B1'], 'LiLo利用Intel CPU片上加速单元支持压缩LLM推理，属于AI软硬件协同执行。'),
    237: (['B1'], 'WATOS联合探索LLM训练策略和晶圆级计算架构；wafer-scale指计算集成规模，不是AI辅助晶圆制造。'),
    239: (['A2', 'B1'], 'ReThermal以DNN加速热仿真，并联合静态/动态调度优化晶圆级LLM训练的温度与吞吐。'),
    240: (['B2'], '2nm SRAM面向CPU/GPU/NPU缓存及边缘AI；作为AI计算存储器件实现收录，不把存储单元设计称作AI算法。'),
    241: (['B2'], '双DRAM/单逻辑3D近存计算芯片减少GEMM时间，面向边缘LLM工作负载。'),
    242: (['B1'], 'ANP-OT实现片上迁移学习的神经形态嗅觉处理器，并报告芯片级能效与疾病识别结果。'),
}

RETAIN = {
    2: ('芯片教育', 'learning指学习和教学活动，研究沉浸式芯片设计教育，不是训练AI模型辅助设计。'),
    7: ('探测器读出电路', '研究Mini-ICAL探测器的NINO模拟前端读出，未以AI方法或神经网络工作负载为研究对象。'),
    30: ('通用IC背景', 'AI是大功率3D集成供电需求的背景，本文综述供电方法，未建立专门AI工作负载或学习方法证据。'),
    40: ('通用IC背景', '阻变存储物理紧凑模型可服务神经形态应用，但当前摘要的贡献是开关机理建模，不是具体神经网络计算系统。'),
    59: ('通用IC背景', '硅光子DFT与制造变化测试适用于多类电路；光学神经网络是应用之一，不据此把测试方法标为AI辅助设计。'),
    88: ('通用IC背景', '低温eDRAM/CAM研究近似搜索和匹配线，ML缩写在此不构成machine learning方法证据。'),
    127: ('通用IC背景', '研究掩码实现的碰撞型侧信道分析；对深度学习攻击的背景引用不等于本文提出学习模型。'),
    140: ('系统应用背景', '主要是无人机导航与CPU负载分配，摘要未给出新的AI芯片设计或专用AI计算架构。'),
    147: ('混沌加密应用', '神经网络结构用于产生混沌吸引子和医学图像加密，主要目标不是AI学习/推理硬件。'),
    156: ('微流控方法借鉴', '确实使用深度强化学习，但优化对象是阀阵列微流控生物芯片的液路，不是电子集成电路。'),
    163: ('系统应用背景', '研究通用CPU/GPU实时任务划分，AI应用需求不等于提出新的AI芯片或AI辅助设计方法。'),
    166: ('系统应用背景', '研究推理共置时内核与网卡追踪，主要贡献为软件系统诊断，保留为应用背景。'),
    179: ('通用IC背景', '使用二进制粒子群搜索射频结构；保留为传统启发式优化背景，未将粒子群直接等同于学习模型。'),
    180: ('通用IC背景', 'Ising退火处理器求解SAT，AI是SAT潜在应用，摘要未验证神经网络训练/推理或AI辅助设计。'),
    182: ('通用IC背景', '机器学习在PUF安全性评测中作为攻击者；本文器件贡献不等于AI用于芯片设计。'),
    194: ('通用IC背景', 'VLIW编译调度以YOLOv5等验证性能，主要为通用编译方法，保留作AI部署背景。'),
    204: ('微流控方法借鉴', '对象为连续流微流控生物芯片及流体异常检测，不能因biochip关键词归入电子AI芯片主线。'),
    209: ('专题综述与会议背景', '题名标明Special Research Session，是LLM/EDA专题场次概览；作为方向背景保留，区别于独立研究论文。'),
    238: ('AI芯片扩展应用', 'CROSS将现有TPU用于同态加密，实际工作负载是密码学；与AI芯片有关，但不属于AI训练/推理或AI辅助设计主线。'),
}


def retained_area(title, decision):
    if decision == 'general_archive':
        return '通用IC背景'
    patterns = [
        (r'educat|curriculum', '芯片教育'),
        (r'microfluid|droplet|biochip', '微流控方法借鉴'),
        (r'quantum|qubit|superconduct|cryo|qfusion|reversible logic|QDP:', '量子与低温电路背景'),
        (r'astronom|exoplanet|SPIRIT|Observatory|Space Mission|interferometry', '天文与空间光子应用'),
        (r'phononic|acoustic wave|solitary wave', '声子器件背景'),
        (r'sensor|sensing|imaging|detector|ISFET|microbial', '传感与读出背景'),
        (r'photon|laser|optical|Bragg|emitter', '通用光子器件背景'),
    ]
    return next((area for pattern, area in patterns if re.search(pattern, title, re.I)), '通用IC背景')


def apply():
    original = json.loads((BATCH / 'archive-before.json').read_text(encoding='utf-8'))
    if len(original) != 243:
        raise RuntimeError('Unexpected audit cohort')
    data = json.loads(REVIEW_PATH.read_text(encoding='utf-8'))
    if data.get('archive_review_20261114'):
        raise RuntimeError('This dated audit has already been applied')
    (BATCH / 'reviews-before.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    proposals = json.loads((BATCH / 'abstract-proposals.json').read_text(encoding='utf-8'))['proposals']
    proposals = {p['id']: p for p in proposals}
    decisions = []
    for index, raw in enumerate(original):
        item = dict(raw)
        if item['id'] in proposals:
            item['abstract_text'] = proposals[item['id']]['abstract_text']
        abstract = item.get('abstract_text') or ''
        previous = data['reviews'].get(item['id'], {})
        if index in PROMOTE:
            topics, reason = PROMOTE[index]
            decision, area = 'ai_focus', 'AI与集成电路交叉'
        else:
            decision = previous.get('decision', 'general_archive')
            area, reason = RETAIN.get(index, (retained_area(item['title'], decision), ''))
            if not reason:
                reason = f'研究对象为{area}，保留作拓展阅读；题名与可用摘要未建立本篇以AI辅助芯片设计或AI训练/推理计算为核心的依据。'
            topics = ['A6'] if index == 209 else ['C1'] if area == '通用IC背景' else []
        sentences = re.split(r'(?<=[.!?])\s+', abstract)
        # Keep the existing exact evidence when it is still valid; otherwise
        # retain the original abstract opening, never an invented quotation.
        evidence = previous.get('abstract_evidence', '')
        if index in PROMOTE or not evidence or evidence not in abstract:
            evidence = next((s for s in sentences if re.search(r'LLM|neural|learning|Bayesian|AI|FlashAttention|GEMM|DNN|SRAM|physical-AI', s, re.I)), sentences[0] if abstract else '')
        review = {
            'index': previous.get('index', index), 'title': item['title'],
            'doi': item.get('doi'), 'arxiv_id': item.get('arxiv_id'),
            'decision': decision, 'topic_ids': topics, 'reviewed_on': '2026-11-14',
            'basis': 'title_abstract' if abstract else 'title_only',
            'reason': reason, 'title_evidence': item['title'],
            'abstract_evidence': evidence, 'research_area': area,
            'review_batch': 'active-archive-20261114',
            'limitation': '基于题名与可获取原始摘要的范围复核，未逐篇核验全文。' if abstract else '仅基于题名进行范围复核，尚未获取摘要或核验全文。',
        }
        data['reviews'][item['id']] = review
        decisions.append({'id': item['id'], 'title': item['title'], 'before': 'archive',
                          'after': 'main' if index in PROMOTE else 'archive', **review})
    summary = {'reviewed': len(decisions), 'promoted': len(PROMOTE),
               'retained': len(decisions)-len(PROMOTE), 'abstracts_added': len(proposals),
               'basis': dict(Counter(x['basis'] for x in decisions))}
    data['archive_review_20261114'] = summary
    db = _connect(ROOT / 'news-data/discovery-ic.sqlite')
    try:
        before = {r['id']: json.loads(r['payload']) for r in db.execute('SELECT id,payload FROM discovery_items')}
        for item in original:
            if before.get(item['id'], {}).get('title') != item['title']:
                raise RuntimeError('Active audit record missing or identity changed')
        with db:
            for proposal in proposals.values():
                item = dict(before[proposal['id']])
                if item.get('doi') != proposal['doi']:
                    raise RuntimeError('Abstract DOI identity mismatch')
                if item.get('abstract_text'):
                    raise RuntimeError('Refusing to overwrite an existing abstract')
                item.update(abstract_text=proposal['abstract_text'], summary=proposal['abstract_text'][:1200],
                            summary_kind='source', abstract_truncated=False, updated_at=_now())
                item.setdefault('abstract_provenance', []).append(proposal['provenance'])
                _write_item(db, item)
            after = {r['id']: json.loads(r['payload']) for r in db.execute('SELECT id,payload FROM discovery_items')}
            if before.keys() != after.keys():
                raise RuntimeError('Audit must not add or remove identities')
            for identity, item in before.items():
                for field in ('published_at','publication_month','publication_year','date_kind','collected_at','doi','arxiv_id'):
                    if item.get(field) != after[identity].get(field):
                        raise RuntimeError(f'Identity/date changed: {field}')
        REVIEW_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        curated_reviews.cache_clear()
        from_payload.cache_clear()
        counts = Counter(analyze(x)['scope'] for x in after.values() if x.get('content_type') == 'paper')
        if counts != {'main': 252, 'archive': 199}:
            raise RuntimeError(f'Unexpected final paper scopes: {counts}')
        summary['final_paper_scopes'] = dict(counts)
        (BATCH / 'audit-result.json').write_text(json.dumps({'summary':summary,'decisions':decisions}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=True))
    finally:
        db.close()


if __name__ == '__main__':
    apply()
