"""Apply validated abstract additions while retaining first collection dates."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.discovery import _connect,_write_item,_now
path=ROOT/'.runtime/ic-quality-20261114/abstract-enrichment.json'
proposals=json.loads(path.read_text(encoding='utf-8'))['proposed']
db=_connect(ROOT/'news-data/discovery-ic.sqlite')
changed=0
with db:
    for proposal in proposals:
        row=db.execute('SELECT payload FROM discovery_items WHERE id=?',(proposal['id'],)).fetchone()
        if row is None:raise RuntimeError('Baseline item missing')
        item=json.loads(row['payload'])
        if proposal.get('doi') and item.get('doi')!=proposal['doi']:raise RuntimeError('DOI mismatch')
        if proposal.get('arxiv_id') and item.get('arxiv_id')!=proposal['arxiv_id']:raise RuntimeError('arXiv mismatch')
        if len(proposal['abstract_text'])<=len(item.get('abstract_text') or ''):continue
        item.update(abstract_text=proposal['abstract_text'],summary=proposal['abstract_text'][:1200],summary_kind='source',abstract_truncated=False,updated_at=_now())
        item.setdefault('abstract_provenance',[]).append(proposal['provenance'])
        item['verification_note']=(item.get('verification_note') or '').replace('页面摘要最多展示140个英文词，完整摘要见原始出处。','')
        item['verification_note']+=' 已补充可获取的完整摘要，来源见摘要出处；发表日期保留原来源精度。'
        _write_item(db,item);changed+=1
db.close()
print(json.dumps({'enriched_records':changed,'collection_dates':'preserved','personal_records':'unchanged'}))
