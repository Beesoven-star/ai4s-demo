import json,sys,re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
root=Path(__file__).resolve().parents[1]/'.runtime/ic-quality-20261114'
baseline=json.loads((root/'baseline-audit.json').read_text(encoding='utf-8'))['items']
enriched={p['id']:p['abstract_text'] for p in json.loads((root/'abstract-enrichment.json').read_text(encoding='utf-8'))['proposed']}
for raw in sys.argv[1:]:
    index=int(raw);paper=baseline[index];text=enriched.get(paper['id'],paper.get('abstract_text') or '')
    sentences=re.split(r'(?<=[.!?])\s+',text)
    clues=[s for s in sentences if re.search(r'we (?:propos|present|introduc)|this (?:paper|article|work)|neural|learning|LLM|language model|Bayesian|surrogate|intelligence|agent|transformer|CNN|diffusion|reinforcement',s,re.I)]
    print(index,paper['title']);print(' '.join(clues)[:1350] if clues else text[:700])
