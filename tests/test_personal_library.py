"""Acceptance tests: persistence, deduplication, metadata refresh, and isolation."""
import json
import asyncio
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from src import discovery, library


class PersonalLibraryTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'library.sqlite'
        self.paper = dict(content_type='paper', title='RTL design feedback',
                          url='https://example.org/paper', doi='10.1234/rtl',
                          summary='Functional verification', topics=['RTL'])
        discovery.upsert_items([self.paper], db_path=self.db)
        self.id = discovery.list_items(db_path=self.db)['items'][0]['id']

    def patch(self, **changes):
        return library.update_record(self.id, changes, db_path=self.db)

    def listing(self, **filters):
        return library.list_saved(db_path=self.db, **filters)

    def test_repeat_favorite_does_not_reset_notes_status_or_time(self):
        first = self.patch(is_favorite=True, notes='Check testbench', reading_status='reading', personal_tags=['核验'])
        second = self.patch(is_favorite=True)
        self.assertEqual(first, second)
        self.assertEqual(self.listing()['total'], 1)

    def test_cancel_retains_notes_and_readd_restores_record(self):
        first = self.patch(is_favorite=True, notes='Keep this', reading_status='read')
        self.patch(is_favorite=False)
        self.assertEqual(self.listing()['total'], 0)
        detail = discovery.get_item(self.id, db_path=self.db)['library']
        self.assertEqual(detail['notes'], 'Keep this')
        restored = self.patch(is_favorite=True)
        self.assertEqual(restored['saved_at'], first['saved_at'])
        self.assertEqual(restored['reading_status'], 'read')

    def test_recollection_does_not_overwrite_personal_data(self):
        self.patch(is_favorite=True, notes='Personal evidence', reading_status='follow_up')
        discovery.upsert_items([{**self.paper, 'summary': 'New source text', 'topics': ['Physical design']}], origin='collected', db_path=self.db)
        item = discovery.get_item(self.id, db_path=self.db)
        self.assertEqual(item['library']['notes'], 'Personal evidence')
        self.assertEqual(item['library']['reading_status'], 'follow_up')
        self.assertEqual(self.listing(topic='Physical design')['total'], 1)
        conn = discovery._connect(self.db)
        self.assertNotIn('library', json.loads(conn.execute('select payload from discovery_items').fetchone()[0]))
        conn.close()

    def test_filters_search_notes_tags_and_escape_like(self):
        self.patch(is_favorite=True, notes='100% exact_match', reading_status='reading', personal_tags=['评测','评测',' 基线 '])
        self.assertEqual(self.listing(q='100%')['total'], 1)
        self.assertEqual(self.listing(q='exact_')['total'], 1)
        self.assertEqual(self.listing(q='100_')['total'], 0)
        self.assertEqual(self.listing(reading_status='read')['total'], 0)
        self.assertEqual(self.listing(reading_status='reading', topic='RTL', personal_tag='基线', content_type='paper')['total'], 1)
        self.assertEqual(self.listing()['facets']['personal_tags'], ['基线', '评测'])

    def test_record_survives_fresh_python_process(self):
        self.patch(is_favorite=True, notes='跨进程保存', reading_status='follow_up')
        code = "from src import library; import sys; r=library.list_saved(db_path=sys.argv[1]); assert r['total']==1; assert r['items'][0]['library']['reading_status']=='follow_up'"
        result = subprocess.run([sys.executable, '-c', code, str(self.db)], cwd=Path(__file__).resolve().parents[1], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_separate_theme_databases_do_not_share_favorites(self):
        other = Path(self.temp.name) / 'other.sqlite'
        discovery.upsert_items([self.paper], db_path=other)
        self.patch(is_favorite=True)
        self.assertEqual(library.list_saved(db_path=other)['total'], 0)

    def test_later_identity_merge_preserves_both_notes(self):
        preprint = dict(content_type='paper', title='Author preprint', url='https://arxiv.org/abs/2611.12345', arxiv_id='2611.12345')
        discovery.upsert_items([preprint], db_path=self.db)
        other_id = next(p['id'] for p in discovery.list_items(db_path=self.db)['items'] if p['id'] != self.id)
        self.patch(is_favorite=True, notes='Publisher notes', personal_tags=['publisher'])
        library.update_record(other_id, dict(is_favorite=True, notes='Preprint notes', personal_tags=['preprint']), db_path=self.db)
        discovery.upsert_items([{**self.paper, 'arxiv_id':'2611.12345'}], origin='collected', db_path=self.db)
        result = self.listing()
        self.assertEqual(result['total'], 1)
        record = result['items'][0]['library']
        self.assertIn('Publisher notes', record['notes'])
        self.assertIn('Preprint notes', record['notes'])
        self.assertEqual(set(record['personal_tags']), {'publisher','preprint'})

    def test_invalid_inputs_cannot_modify_record(self):
        self.patch(is_favorite=True, notes='Original')
        for changes in [{'notes':None}, {'is_favorite':1}, {'reading_status':None}, {'reading_status':'finished'}, {'personal_tags':['x'*51]}, {'notes':'x'*20001}, {'title':'overwrite'}]:
            with self.assertRaises(ValueError):
                library.update_record(self.id, changes, db_path=self.db)
        self.assertEqual(discovery.get_item(self.id, db_path=self.db)['library']['notes'], 'Original')
        with self.assertRaises(KeyError):
            library.update_record('missing', {'is_favorite':True}, db_path=self.db)

    def test_empty_query_and_pagination(self):
        self.assertEqual(self.listing()['total'], 0)
        self.patch(is_favorite=True)
        self.assertEqual(self.listing(offset=20)['items'], [])
        self.assertEqual(self.listing(offset=20)['total'], 1)
        self.assertEqual(self.listing()['facets']['status_counts'], {'unread':1})

    def api(self, method, path, body=None, query=''):
        # Exercise FastAPI/Pydantic validation without a network or httpx dependency.
        from src.web.app import create_app
        response = []
        async def receive():
            return {'type':'http.request', 'body':json.dumps(body or {}).encode(), 'more_body':False}
        async def send(message):
            response.append(message)
        async def call():
            await create_app()({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1',
                'method':method,'scheme':'http','path':path,'raw_path':path.encode(),
                'query_string':query.encode(),'root_path':'','headers':[(b'content-type',b'application/json')],
                'client':('127.0.0.1',1),'server':('test',80)}, receive, send)
        with patch.dict(os.environ, {'DNEWS_DISCOVERY_DB':str(self.db)}):
            asyncio.run(call())
        status = next(m['status'] for m in response if m['type']=='http.response.start')
        data = json.loads(b''.join(m.get('body',b'') for m in response if m['type']=='http.response.body'))
        return status, data

    def test_api_partial_updates_and_list(self):
        path = f'/api/discovery/items/{self.id}/library'
        status, saved = self.api('PATCH', path, {'is_favorite':True,'notes':'API note','reading_status':'reading'})
        self.assertEqual(status, 200)
        self.assertEqual(self.api('PATCH', path, {'is_favorite':True})[1], saved)
        status, result = self.api('GET','/api/discovery/library',query='reading_status=reading&q=API')
        self.assertEqual(status, 200)
        self.assertEqual(result['items'][0]['library']['notes'], 'API note')

    def test_api_invalid_types_fields_null_and_missing_item(self):
        path = f'/api/discovery/items/{self.id}/library'
        for body in [{'is_favorite':'true'}, {'notes':None}, {'reading_status':None},
                     {'reading_status':'finished'}, {'personal_tags':[1]}, {'title':'overwrite'}]:
            self.assertEqual(self.api('PATCH',path,body)[0], 422, body)
        self.assertEqual(self.api('PATCH','/api/discovery/items/missing/library',{'is_favorite':True})[0], 404)
        self.assertEqual(self.api('GET','/api/discovery/library',query='limit=0')[0], 422)


if __name__ == '__main__':
    unittest.main()
