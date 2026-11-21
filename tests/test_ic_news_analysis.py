import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src import discovery, ic_news_analysis as news, ic_reading_prompts


class NewsAnalysisTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        temp = TemporaryDirectory(dir=root)
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / 'news.sqlite'
        self.config = Path(temp.name) / 'sources.json'
        self.config.write_text('{"sources":[{"url":"https://example.org/feed"}]}', encoding='utf-8')

    def add(self, title, **fields):
        discovery.upsert_items([dict(title=title, url=f'https://example.org/{title}', source='Journal',
                                     content_type='news', **fields)], db_path=self.db)
        return next(item['id'] for item in discovery.list_items(content_type='news', db_path=self.db)['items']
                    if item['title'] == title)

    def test_new_items_use_public_evidence_and_existing_notes_stay_in_place(self):
        old = self.add('old')
        news.initialize(self.db)
        custom = '用一句话说明事件。'
        settings = ic_reading_prompts.save(self.db, 'news', custom)
        key = self.add('new', summary='The manufacturer signed an agreement to test a new power supply.')
        headline = self.add('headline')
        curated = self.add('curated', reading_notes={'basis': 'report', 'points': [{'label': '要点', 'text': '已收录说明。'}]})
        notes = {'news': [{'id': key, 'what': '厂商签署测试协议。', 'why': '不能由短简介推知的技术推断。', 'stage': '简介只披露了测试协议。',
                           'evidence': 'signed an agreement to test a new power supply.'}]}

        async def read(session, item, hosts):
            self.assertEqual(hosts, {'example.org'})
            return {'status': item['reading_basis'], 'text': item['summary']}

        with patch('src.ic_reading_jobs.analysis_connection.credentials',
                   return_value=({'model': 'test', 'base_url': 'https://api.deepseek.com'}, 'test')), \
             patch('src.ic_reading_jobs.analysis_connection.complete', return_value=json.dumps(notes)) as complete, \
             patch('src.ic_news_analysis._read_news', side_effect=read) as source:
            self.assertTrue(asyncio.run(news.process_next(self.db, self.config)))
            source.assert_awaited()
            self.assertEqual({call.args[1]['id'] for call in source.await_args_list}, {key, headline})
            self.assertFalse(asyncio.run(news.process_next(self.db, self.config)))
        sent = complete.call_args.args[0]
        self.assertTrue(sent.startswith(custom + "\n\n"))
        self.assertIn(settings['request_footer'], sent)
        self.assertNotIn(headline, sent)
        self.assertEqual(news.read_notes(key, self.db), {'basis': 'source_intro', 'points': [
            {'label': '发生了什么', 'text': '厂商签署测试协议。'}]})
        for item_id in (old, headline, curated):
            self.assertIsNone(news.read_notes(item_id, self.db))

    def test_public_excerpt_is_used_and_cannot_support_invented_values(self):
        item = {'id': 'id', 'source': 'Journal', 'title': 'New supply', 'content_type': 'news'}
        article = 'The manufacturer signed an agreement to test the 800 V power supply in a lab.'
        page = {'status': 'original', 'text': json.dumps({'article': article}), 'excerpt': 'Feed summary'}
        material = news._material(item, page)
        notes = {'what': '厂商已签署测试协议。', 'why': '该方案采用 800 V 供电。',
                 'stage': '所引原文披露的测试环境是实验室。', 'evidence': 'signed an agreement to test'}
        self.assertEqual(news._validate(notes, material)['basis'], 'report_excerpt')
        with self.assertRaisesRegex(ValueError, '数值'):
            news._validate({**notes, 'why': '该方案采用 820 V 供电。'}, material)
        with self.assertRaisesRegex(ValueError, '引文'):
            news._validate({**notes, 'evidence': 'Mass production started.'}, material)

