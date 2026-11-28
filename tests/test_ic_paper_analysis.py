import asyncio
from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src import discovery, ic_paper_analysis as analysis, ic_reading_prompts


class PaperAnalysisTests(unittest.TestCase):
    abstract = 'The authors tested seven 28 nm designs and report a 50% reduction in peak current.'

    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        tmp = TemporaryDirectory(dir=root)
        self.addCleanup(tmp.cleanup)
        self.database = Path(tmp.name) / 'paper.sqlite'

    def add(self, slug, text=None):
        discovery.upsert_items([dict(title=slug, url=f'https://example.org/{slug}', source='Journal',
                                     content_type='paper', abstract_text=text)], db_path=self.database)
        return next(item['id'] for item in discovery.list_items(content_type='paper', db_path=self.database)['items']
                    if item['title'] == slug)

    def task(self, key):
        with closing(discovery._connect(self.database)) as db:
            row = db.execute('SELECT status,attempts FROM ic_paper_analysis WHERE item_id=?', (key,)).fetchone()
            return tuple(row) if row else None

    def test_installs_without_backfill_and_enqueues_only_new_abstracts(self):
        old = self.add('historical', self.abstract)
        analysis.initialize(self.database)
        self.assertIsNone(self.task(old))
        blank = self.add('blank')
        self.assertIsNone(self.task(blank))
        self.assertEqual(blank, self.add('blank', self.abstract))
        self.assertEqual(self.task(blank), ('queued', 0))
        fresh = self.add('fresh', self.abstract)
        self.assertEqual(self.task(fresh), ('queued', 0))

    def test_uses_configured_api_and_persists_four_grounded_notes(self):
        analysis.initialize(self.database)
        key = self.add('new', self.abstract)
        settings = ic_reading_prompts.settings(self.database)
        custom = settings['paper']['default_prompt'] + '\n适用范围以“对比条件”开头。'
        ic_reading_prompts.save(self.database, 'paper', custom)
        self.assertEqual(ic_reading_prompts.settings(self.database)['news'], settings['news'])
        result = {'papers': [{'id': key, 'result': '作者报告峰值电流减少50%。',
                              'question': '如何降低峰值电流？', 'method': '对芯片设计进行测试。',
                              'boundary': '评估范围为28 nm设计。', 'evidence': 'a 50% reduction in peak current.'}]}
        with patch('src.ic_reading_jobs.analysis_connection.credentials',
                   return_value=({'model': 'test', 'base_url': 'https://api.deepseek.com'}, 'test')), \
             patch('src.ic_reading_jobs.analysis_connection.complete', return_value=json.dumps(result)) as complete:
            self.assertTrue(asyncio.run(analysis.process_next(self.database)))
        self.assertTrue(complete.call_args.args[0].startswith(custom + "\n\n"))
        self.assertIn(settings['paper']['request_footer'], complete.call_args.args[0])
        self.assertIn(self.abstract, complete.call_args.args[0])
        self.assertEqual(ic_reading_prompts.save(self.database, 'paper', None), settings['paper'])
        notes = analysis.read_notes(key, self.database)
        self.assertEqual(notes['basis'], 'abstract')
        self.assertEqual([point['label'] for point in notes['points']], ['主要发现', '研究问题', '怎么做', '适用范围'])
        self.add('new', self.abstract)
        self.assertEqual(self.task(key), ('ready', 1))

    def test_rejects_numbers_or_quotes_missing_from_abstract(self):
        item = dict(abstract_text=self.abstract)
        fields = dict(result='效率提高52%。', question='如何降低电流？', method='对芯片进行测试。',
                      boundary='结论适用于已测试设计。', evidence='a 50% reduction in peak current.')
        with self.assertRaisesRegex(ValueError, '数值'):
            analysis._validate(fields, item)
        fields.update(result='作者报告峰值电流下降50%。', evidence='No such passage in the abstract')
        with self.assertRaisesRegex(ValueError, '引文'):
            analysis._validate(fields, item)
        fields.update(boundary='评估范围包括7个28 nm设计。', evidence='a 50% reduction in peak current.')
        self.assertEqual(analysis._validate(fields, item)['basis'], 'abstract')

    def test_keeps_a_complete_long_abstract_sentence(self):
        quote = ('The experiment compared loop related synthesis directives with the baseline and measured ' * 3
                 + 'the impact on the number of Pareto-optimal designs.')
        self.assertGreater(len(quote), 300)
        fields = dict(result='作者比较了帕累托最优设计。', question='循环指令如何影响设计结果？',
                      method='对比循环综合指令和基线。', boundary='评估限于文中综合指令。', evidence_id=1)
        self.assertEqual(analysis._validate(fields, {'abstract_text': quote})['basis'], 'abstract')
        with self.assertRaisesRegex(ValueError, '原文编号'):
            analysis._validate({**fields, 'evidence_id': 2}, {'abstract_text': quote})
