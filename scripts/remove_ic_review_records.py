"""One-time removal of the 18 pending papers and two information records."""
from collections import Counter
import json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.discovery import _connect,remove_items
from src.discovery_lock import FileLock,execution_lock_path
from src.ic_research import analyze,scope_of

db_path=ROOT/'news-data/discovery-ic.sqlite'
output=ROOT/'.runtime/ic-library-removal-20261114'
output.mkdir(parents=True,exist_ok=True)
with FileLock(execution_lock_path(db_path)):
    conn=_connect(db_path)
    papers=[json.loads(r[0]) for r in conn.execute("SELECT payload FROM discovery_items WHERE content_type='paper'")]
    targets=[item for item in papers if scope_of(analyze(item)) in {'pending','excluded'}]
    scopes=Counter(scope_of(analyze(item)) for item in papers)
    if not targets and conn.execute('SELECT COUNT(*) FROM discovery_removed_items').fetchone()[0]>=20:
        print(json.dumps({'removed':0,'already_applied':True}));conn.close();sys.exit(0)
    assert scopes=={'main':207,'archive':205,'pending':18,'excluded':2},dict(scopes)
    backup=output/'before.sqlite'
    if not backup.exists():
        with sqlite3.connect(backup) as destination:conn.backup(destination)
    manifest=[{'id':item['id'],'title':item['title'],'scope':scope_of(analyze(item))} for item in targets]
    (output/'removed-records.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    conn.close()
    result=remove_items([item['id'] for item in targets],'用户要求移出18篇待复核资料及2条非研究记录（2026-11-14）',db_path=db_path)
    with sqlite3.connect(db_path) as check:
        remaining=[json.loads(r[0]) for r in check.execute("SELECT payload FROM discovery_items WHERE content_type='paper'")]
        assert Counter(scope_of(analyze(item)) for item in remaining)=={'main':207,'archive':205}
        assert len(remaining)==412
    print(json.dumps({**result,'papers':412,'main':207,'archive':205,'backup':str(backup)},ensure_ascii=True))
