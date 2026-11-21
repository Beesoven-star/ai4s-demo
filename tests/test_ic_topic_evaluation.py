import asyncio
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src import discovery, ic_topic_evaluation as evaluation
from src.ic_briefing import briefing
from src.ic_observations import SHANGHAI


class TopicEvaluationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        temporary = TemporaryDirectory(dir=root)
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / 'evaluation.sqlite'
        evaluation.initialize(self.db)
        self.topic = {'id': 'test-topic', 'name': '评估测试', 'question': '功耗能降低多少？',
                      'status': 'active', 'events': []}

    def add(self, domain, day, evidence):
        outcome = discovery.upsert_items([{
            'title': f'Power measurement from {domain}', 'url': f'https://{domain}/paper', 'source': domain,
            'content_type': 'paper', 'published_at': day, 'abstract_text': evidence,
        }], db_path=self.db)
        self.assertEqual(outcome['inserted'], 1)
        item = next(row for row in discovery.list_items(db_path=self.db)['items'] if row['source'] == domain)
        source = {key: item[key] for key in ('id', 'title', 'url', 'source', 'published_at')}
        self.topic['events'].insert(0, {'id': domain, 'date': day, 'sources': [source]})
        return {'source_id': item['id'], 'excerpt_index': 1}

    def response(self, reference, second=None, *, finding='在给定测试对象上观察到功耗改善。'):
        point = {'text': '比较条件限于作者报告的测试对象。', 'references': [reference]}
        result = {'topic_id': self.topic['id'], 'change': second or reference, 'evaluation': {
            'stage': 'lab',
            'finding': {**point, 'text': finding},
            'limits': point,
            'bottleneck': {**point, 'text': '实测给出了该约束下的功耗改善。', 'score': 5},
            'breadth': None,
            'enablement': None,
        }}
        if second:
            result['evaluation']['breadth'] = {'text': '两个机构完成了不同对象的验证。',
                                               'references': [reference, second], 'score': 5}
            result['evaluation']['enablement'] = {'text': '验证补充了下游设计的性能依据。',
                                                  'references': [second], 'score': 4}
        return {'evaluations': [result]}

    def test_publishes_supported_partial_then_ranks_with_independent_evidence(self):
        first = self.add('first.example', '2026-11-18', 'Measurements show power falls by 12% for the baseline load.')
        cn = ({'base_url': 'https://api.deepseek.com', 'model': 'test'}, 'test')
        when = datetime(2026, 11, 21, 16, tzinfo=SHANGHAI)
        with patch.object(evaluation.ic_topics, 'get_topics', return_value=[self.topic]), \
             patch.object(evaluation, '_now', return_value=when), \
             patch.object(evaluation.analysis_connection, 'credentials', return_value=cn), \
             patch.object(evaluation.analysis_connection, 'complete') as complete:
            complete.return_value = json.dumps(self.response(first))
            self.assertTrue(asyncio.run(evaluation.process_next(self.db)))
            card = evaluation.published_cards(self.db)[self.topic['id']]
            self.assertIsNone(card['total'])
            self.assertEqual([point['id'] for point in card['dimensions']], ['bottleneck'])
            self.assertFalse(asyncio.run(evaluation.process_next(self.db)))
            self.assertEqual(complete.await_count, 1)
            self.assertNotIn(self.topic['id'], {row['id'] for row in evaluation.with_ranked_evaluations(
                briefing(), self.db, topics=[self.topic])['importance_entries']})

            second = self.add('second.example', '2026-11-20', 'A separate study measured a 9% reduction in the test system.')
            complete.return_value = json.dumps(self.response(first, second))
            self.assertTrue(asyncio.run(evaluation.process_next(self.db)))
            card = evaluation.published_cards(self.db)[self.topic['id']]
            self.assertEqual(card['total'], 11)
            ranked = evaluation.with_ranked_evaluations(briefing(), self.db, topics=[self.topic])['importance_entries']
            self.assertIn((self.topic['id'], 11), {(row['id'], row['score']) for row in ranked})
            self.assertEqual([row['rank'] for row in ranked], list(range(1, len(ranked) + 1)))

            third = self.add('third.example', '2026-11-21', 'An independent group examined power limits of the test chip.')
            complete.return_value = json.dumps(self.response(third))
            self.assertTrue(asyncio.run(evaluation.process_next(self.db)))
            self.assertEqual(evaluation.published_cards(self.db)[self.topic['id']], card)

    def test_stage_requires_evidence_of_what_was_actually_done(self):
        proposal = [{'references': [{'quote': 'The team proposes a method for process control.'}]}]
        self.assertEqual(evaluation._stage_label('lab', proposal), '综合公开材料')
        self.assertEqual(evaluation._stage_label('deployment', proposal), '综合公开材料')
        verified = [{'references': [{'quote': 'Measurements show power falls by 12% for the baseline load.'}]}]
        self.assertEqual(evaluation._stage_label('lab', verified), '实验验证')

    def test_unquoted_numbers_and_unmatched_quotes_cannot_publish(self):
        first = self.add('first.example', '2026-11-18', 'Measurements show power falls by 12% for the baseline load.')
        cn = ({'base_url': 'https://api.deepseek.com', 'model': 'test'}, 'test')
        with patch.object(evaluation.ic_topics, 'get_topics', return_value=[self.topic]), \
             patch.object(evaluation.analysis_connection, 'credentials', return_value=cn), \
             patch.object(evaluation.analysis_connection, 'complete') as complete:
            complete.return_value = json.dumps(self.response(first, finding='测试显示功耗改善99%。'))
            self.assertTrue(asyncio.run(evaluation.process_next(self.db)))
            self.assertEqual(evaluation.published_cards(self.db), {})
            self.assertFalse(asyncio.run(evaluation.process_next(self.db)))
            with self.assertRaisesRegex(ValueError, '证据片段'):
                evaluation._reference(evaluation.Reference(**first), {})
            self.assertFalse(evaluation._independent([
                {'organization': 'a', 'event_id': 'single'}, {'organization': 'b', 'event_id': 'single'},
            ]))

