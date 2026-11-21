"""Archive identified out-of-scope candidates from this import only."""
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.discovery import _connect

root = Path(__file__).resolve().parents[1]
db = _connect(root / 'news-data/discovery-ic.sqlite')
checks = {
    '10.1109/jssc.2026.3730756':'新任副编辑介绍，不是研究论文',
    '10.1145/3806057':'机械CAD参数化模型重建，不属于当前集成电路主题',
    'https://www.imec-int.com/en/press/noak-new-spin-imec-and-hasselt-university-raises-eu5-million-industrialize-next-generation':'钙钛矿-硅叠层太阳能技术融资，非当前集成电路主题',
}
excluded = []
for row in db.execute('SELECT payload FROM discovery_items'):
    item = json.loads(row['payload'])
    reason = checks.get(item.get('doi')) or checks.get(item['url'])
    if not reason:
        continue
    if not item.get('created_at','').startswith('2026-11-13'):
        raise RuntimeError('Refusing to change a record outside this import')
    personal = db.execute('SELECT * FROM personal_library WHERE item_id=?', (item['id'],)).fetchone()
    if personal is not None:
        raise RuntimeError('Refusing to remove a record with personal metadata')
    aliases = [dict(r) for r in db.execute('SELECT * FROM discovery_aliases WHERE item_id=?',(item['id'],))]
    excluded.append({'reason':reason, 'record':item, 'aliases':aliases})
if excluded:
    archive = root / '.runtime/ic-sources-20261113/quality-exclusions.json'
    previous = json.loads(archive.read_text(encoding='utf-8')) if archive.exists() else []
    if {entry['record']['id'] for entry in previous} & {entry['record']['id'] for entry in excluded}:
        raise RuntimeError('A previously excluded record reappeared; inspect before modifying it')
    archive.write_text(json.dumps(previous + excluded, ensure_ascii=False, indent=2), encoding='utf-8')
    with db:
        for entry in excluded:
            db.execute('DELETE FROM discovery_items WHERE id=?',(entry['record']['id'],))
print(json.dumps({'archived_and_excluded':len(excluded)}))
db.close()
