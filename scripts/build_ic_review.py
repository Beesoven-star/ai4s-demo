"""Persist item-level scope decisions after title audit and abstract enrichment.

The numbered references bind to the immutable baseline, never to query ordering.
General archive means outside this round's AI focus, not proof of no AI anywhere.
"""
from pathlib import Path
import json,re,sys
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime/ic-quality-20261114'
papers=json.loads((OUT/'baseline-audit.json').read_text(encoding='utf-8'))['items']
enriched={p['id']:p['abstract_text'] for p in json.loads((OUT/'abstract-enrichment.json').read_text(encoding='utf-8'))['proposed']}
# Positive roles: reviewed titles; ambiguous cases checked against available abstracts.
groups={
 'A1':[0,1,3,4,5,17,19,22,30,32,35,36,37,43,47,56,62,79,81,85,87,88,89,227,331,414,419],
 'A2':[10,12,53,55,57,64,101,105,114,120,122,133,134,137,140,152,237,264,266,271,285,305,326,364,384,385,388,392,398,402],
 'A3':[6,16,41,44,50,61,69,73,103,192,199,217,218,222,251,259,320,372,379,380],
 'A4':[51,228,230,243,261,272,336,368,377,381,394,407,413],
 'A5':[46,104,116,280,389],
 'A6':[29,108,118,123,139,144,151,332,360,401],
 'B1':[14,49,75,95,107,115,124,182,187,191,207,226,229,241,244,246,252,255,257,265,270,273,281,292,295,300,302,318,322,325,328,339,346,347,352,357,358,359,369,411,421],
 'B2':[7,20,71,170,179,183,186,188,196,203,208,224,242,249,269,274,279,286,293,308,338,342,349,361,383,390,409,410],
 'B3':[25,27,93,96,99,102,104,110,113,116,254,362,365,367,370,371,374],
}
selected_background={2,11,15,18,48,58,65,77,100,166,174,180,219,233,315,366,415,418}
excluded={334,351}
outside={13,23,24,28,31,34,38,39,40,42,45,52,66,67,70,74,78,82,90,91,92,94,97,125,127,128,129,130,131,132,135,136,138,141,142,143,145,146,147,148,149,150,153,154,155,156,157,158,159,160,161,162,238,250,253,256,294,301,307,314,327,422}
pending={247,283,284,321,350,387,396,399,417,423}
role_map={}
for topic,indices in groups.items():
    for index in indices:role_map.setdefault(index,[]).append(topic)

def excerpt(text,pattern=None):
    if pattern:
        matches=re.findall(r'[^.!?]*(?:'+pattern+r')[^.!?]*[.!?]?',text,re.I)
        if matches:return max(matches,key=len).strip()[:650]
    return re.split(r'(?<=[.!?])\s+',text)[0][:650]

reviews={}
for index,paper in enumerate(papers):
    abstract=enriched.get(paper['id'],paper.get('abstract_text') or '')
    topics=role_map.get(index,[])
    if index in excluded:decision='excluded';reason='期刊协会信息页，非研究论文。'
    elif topics:
        decision='ai_focus';reason='题名/摘要中存在明确的AI方法或AI计算目标，已区分二者角色。'
        if index==228:reason='AI用于PUF安全攻击与评测，不是生成设计；摘要明确评估LR、SVM、MLP及神经网络等学习攻击。'
    elif index in selected_background:decision='selected_background';topics=['C1'];reason='选作通用IC背景阅读，与AI交叉主线分开展示。'
    elif index in pending:decision='needs_review';reason='研究对象或方法边界仍需进一步核验，暂不作为已确认AI交叉主线。'
    elif index in outside:decision='scope_archive';reason='范围审核：光子/量子/传感/教育等拓展资料，本轮缺少直接AI芯片主线依据。'
    else:decision='general_archive';reason='范围审核：主要对象为常规电路、器件、确定性算法或系统实现，归入扩展背景档案；不表示全文完全没有AI。'
    method_pattern=r'LLM|language model|neural|learning|diffusion|transformer|agent|Bayesian|RAG|CNN|surrogate|AI|inference|CIM'
    method=excerpt(abstract,method_pattern) if abstract else ''
    reviews[paper['id']]={'index':index,'title':paper['title'],'doi':paper.get('doi'),'arxiv_id':paper.get('arxiv_id'),
        'decision':decision,'topic_ids':topics,'reviewed_on':'2026-11-14',
        'basis':'title_abstract' if abstract else 'title_only','reason':reason,
        'title_evidence':paper['title'],'abstract_evidence':method if topics else excerpt(abstract),
        'limitation':'题名范围审核与可用摘要核对，尚未核验全文；AI类为主线候选，不是研究结论的真实性认证。'}
target=ROOT/'resources/ic_paper_review_20261114.json'
target.write_text(json.dumps({'version':'ic-review-20261114-v2','baseline_total':424,'reviews':reviews},ensure_ascii=False,indent=2),encoding='utf-8')
from collections import Counter
print(json.dumps(dict(Counter(r['decision'] for r in reviews.values()))))
