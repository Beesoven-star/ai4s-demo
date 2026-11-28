import asyncio
from contextlib import closing
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src import analysis_connection, discovery, ic_automatic, ic_editor, ic_topic_evaluation, ic_topics
from src.ic_observations import classify_for_observation
from src.web import ic_editor as editor_api


class TechnologyTopicsTests(unittest.TestCase):
    excerpt = 'The engineers published results from temperature cycling tests.'

    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        temp = TemporaryDirectory(dir=root)
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / 'topics.sqlite'
        ic_topics.initialize(self.database)

    def source(self, identity, day, title, genre='独立报道'):
        return {'id': identity, 'title': title, 'source': 'Example',
                'url': f'https://example.org/{identity}', 'content_type': 'news',
                'published_at': day, 'news_genre': genre, 'excerpt': self.excerpt}

    def test_legacy_grouping_notes_are_not_displayed_as_event_summaries(self):
        seeded = ic_topics._seeded_topics(ic_topics.public_catalog())['hbm']
        example = next(event for event in seeded['events'] if event['title'] == 'HBM控制功能向基底逻辑迁移')
        self.assertTrue(example['summary'])
        with closing(discovery._connect(self.database)) as db, db:
            db.execute('INSERT INTO ic_technology_topics VALUES (?,?)', ('hbm', json.dumps(seeded)))
        visible = next(event for event in ic_topics.topic_detail('hbm', self.database)['events'] if event['id'] == example['id'])
        self.assertEqual(visible['summary'], '')
        self.assertEqual([source['url'] for source in visible['sources']], [source['url'] for source in example['sources']])

    def proposal(self, *events, topic_id='', name='低温封装互连', evidence=None):
        return ic_topics.Proposal.model_validate({
            'topic_id': topic_id, 'name': name, 'aliases': [],
            'category_id': 'packaging', 'overview': '使用低温材料连接裸片。',
            'question': '连接可靠性如何验证？', 'follow_up': '观察温循和湿热测试。',
            'scope_reason': '跟踪超导量子电路专用封装的低温导热和连接可靠性，与面向 AI 的芯粒封装问题不同。',
            'events': [{'title': title, 'summary': '摘要依据公开资料。', 'source_ids': ids,
                        'evidence_source_id': ids[0], 'evidence': self.excerpt if evidence is None else evidence}
                       for title, ids in events],
        })

    def test_distinct_topic_opens_immediately_cools_and_resumes(self):
        first = self.source('s1', '2026-10-02', 'Lab A announces a low-temperature process')
        found = ic_topics.apply_refresh(self.database, [self.proposal(('材料工艺验证', ['s1']))], {'s1': first}, date(2026, 10, 2))
        self.assertEqual(found[0]['status'], 'active')
        catalog = ic_topics.discovery_catalog(self.database)
        item = {'id': 's1', 'content_type': 'news', 'title': 'Laboratory progress'}
        self.assertEqual([row['id'] for row in classify_for_observation(item, catalog=catalog)['topics']],
                         [found[0]['id']])
        self.assertEqual(ic_topics.apply_refresh(
            self.database, [self.proposal(('重复记录', ['s1']), name='同一进展的不同专题名')],
            {'s1': first}, date(2026, 10, 2)), [])
        key = found[0]['id']
        repeat = self.source('s2', '2026-10-05', first['title'])
        changes = ic_topics.apply_refresh(self.database, [self.proposal(('材料工艺验证', ['s2']), topic_id=key)],
                                          {'s2': repeat}, date(2026, 10, 5))
        self.assertEqual(changes[0]['event_count'], 1)
        self.assertEqual(changes[0]['latest_progress'], '2026-10-02')
        second = self.source('s3', '2026-10-08', 'University B completes cycling tests', '论文')
        changes = ic_topics.apply_refresh(self.database, [self.proposal(('完成温循实验', ['s3']), topic_id=key)],
                                          {'s3': second}, date(2026, 10, 8))
        self.assertEqual(changes[0]['status'], 'active')
        self.assertEqual(ic_topics.apply_refresh(self.database, [self.proposal(('材料工艺验证', ['s1', 's3']), topic_id=key)],
                                                {'s1': first, 's3': second}, date(2026, 10, 8)), [])
        row = next(row for row in ic_topics.get_topics(self.database, date(2026, 11, 8)) if row['id'] == key)
        self.assertEqual(row['status'], 'history')
        later = self.source('s4', '2026-11-09', 'Packaging supplier reports customer validation')
        changes = ic_topics.apply_refresh(self.database, [self.proposal(('供应商发布客户验证', ['s4']), topic_id=key)],
                                          {'s4': later}, date(2026, 11, 9))
        self.assertEqual((changes[0]['id'], changes[0]['previous_status'], changes[0]['status']), (key, 'history', 'active'))
        self.assertEqual(changes[0]['event_count'], 3)
        index_row = next(row for row in ic_topics.topic_index(self.database) if row['id'] == key)
        self.assertEqual(index_row['latest_event']['title'], '供应商发布客户验证')
        self.assertEqual(index_row['latest_event']['sources'], ['Example'])

    def test_unknown_and_reprinted_sources_cannot_open_a_topic(self):
        reprint = self.source('s1', '2026-10-05', 'Retelling a launch', '二手编译')
        changes = ic_topics.apply_refresh(self.database, [self.proposal(
            ('转载', ['s1']), ('无出处', ['fabricated']))], {'s1': reprint}, date(2026, 10, 6))
        self.assertEqual(changes, [])

    def test_stacking_orientation_uses_the_original_title(self):
        title = '三维芯片面对面堆叠热敏感度'
        back = {'title': 'Thermal sensitivity in face-to-back stacking'}
        face = {'title': 'Thermal sensitivity in face-to-face stacking'}
        self.assertEqual(ic_topics._progress_title(title, [back]), '三维芯片面对背堆叠热敏感度')
        self.assertEqual(ic_topics._progress_title(title, [back, face]), title)

    def test_hbm_stage_progress_preserves_event_and_rejects_reprints_or_plans(self):
        event_id = 'pfn-l2000-stack'
        name = ic_topics.topic_detail('hbm', self.database)['name']
        initial = next(event for event in ic_topics.topic_detail('hbm', self.database)['events'] if event['id'] == event_id)
        def apply(identity, day, excerpt, genre='独立报道', evidence=None):
            source = {**self.source(identity, day, f'PFN follow-up {identity}', genre), 'excerpt': excerpt}
            proposal = self.proposal(('PFN 更新样片进展', [identity]), topic_id='hbm', name=name,
                                     evidence=excerpt if evidence is None else evidence)
            proposal.events[0].event_id = event_id
            proposal.events[0].stage_code = 'prototype'
            proposal.events[0].summary = '后续材料描述样片进展。'
            ic_topics.apply_refresh(self.database, [proposal], {identity: source}, date.fromisoformat(day))
            return next(event for event in ic_topics.topic_detail('hbm', self.database)['events'] if event['id'] == event_id)

        quote = 'The company shipped prototype samples to customers.'
        reprint = apply('reprint', '2026-11-24', quote, '转载')
        self.assertIn('reprint', [source['id'] for source in reprint['sources']])
        self.assertEqual(reprint['stage_changes'], [])
        planned = apply('plan', '2026-11-25', 'The company plans to deliver prototype samples next year.')
        self.assertEqual(planned['stage_changes'], [])
        false_quote = apply('false', '2026-11-25', 'The company discussed its project.', evidence=quote)
        self.assertEqual(false_quote['stage_changes'], [])
        advanced = apply('original', '2026-11-26', quote)
        self.assertEqual(advanced['date'], initial['date'])
        self.assertEqual(advanced['title'], initial['title'])
        self.assertEqual(len(advanced['stage_changes']), 1)
        change = advanced['stage_changes'][0]
        self.assertEqual((change['from_stage'], change['to_stage'], change['source_id'], change['evidence']),
                         ('公开计划', '样片或原型', 'original', quote))
        self.assertEqual(apply('original', '2026-11-26', quote)['stage_changes'], [change])
        topic = ic_topics.topic_detail('hbm', self.database)
        self.assertEqual(topic['latest_progress'], '2026-11-26')
        self.assertEqual(topic['events'][0]['id'], event_id)



    def test_existing_parent_accepts_subtopic_progress_and_new_topic_requires_evidence(self):
        new = self.source('new', '2026-11-21', 'A lab verified a new circuit')
        material = {'new': new}
        ungrounded = self.proposal(('新工艺', ['new']), evidence='No such sentence in the source.')
        self.assertEqual(ic_topics.apply_refresh(self.database, [ungrounded], material, date(2026, 11, 21)), [])
        child = self.proposal(('配电设备测试', ['new']), topic_id='power-thermal', name='机柜高压配电')
        changes = ic_topics.apply_refresh(self.database, [child], material, date(2026, 11, 21))
        self.assertEqual([row['id'] for row in changes], ['power-thermal'])
        parent = ic_topics.topic_detail('power-thermal', self.database)
        self.assertEqual(parent['name'], 'AI芯片供电与散热')
        self.assertIn('各级转换损耗和温升', parent['question'])
        self.assertIn('new', {source['id'] for event in parent['events'] for source in event['sources']})

    def test_automatic_topic_can_add_a_verified_vendor_source_outside_hbm(self):
        day = date(2026, 11, 28)
        article = {**self.source('story', day.isoformat(), 'New packaging test'), 'reading_basis': 'excerpt'}
        materials = {'story': article}
        row = self.proposal(('低温封装实验', ['story'])).model_dump()
        event = row['events'][0]
        del event['evidence']
        event['evidence_id'] = 1
        proposals = ic_topics._proposals(json.dumps({'topics': [row, {'events': [{}]}]}), materials)
        original = {**self.source('vendor', day.isoformat(), 'Packaging vendor test'), 'url': 'https://vendor.example/test'}
        quote = 'We tested the package in a temperature cycling experiment.'

        async def assess(inputs, *_):
            return [{'article_id': 'story', 'evidence': {'source_id': inputs[0]['candidates'][0]['source_id'], 'evidence': quote},
                     'summary': '厂商完成温循测试。', 'stage': '厂商实验室测试', 'boundary': '只覆盖所披露的封装方案。',
                     'next_check': '核对温度范围和样本数量。'}]

        with patch('src.ic_automatic._evidence', return_value={'story': {'status': 'excerpt', 'text': self.excerpt}}), \
             patch.object(ic_topics.ic_primary_evidence, 'lookup', return_value={'story': [(original, 'original', quote)]}), \
             patch('src.ic_automatic.assess_primary_sources', side_effect=assess):
            asyncio.run(ic_topics._supplement_proposals(proposals, materials, {}, 'configured', self.database, day, (), {}))
        changes = ic_topics.apply_refresh(self.database, proposals, materials, day)
        topic = ic_topics.topic_detail(changes[0]['id'], self.database)
        self.assertEqual(topic['events'][0]['stage'], '厂商实验室测试')
        self.assertEqual([source['url'] for source in topic['events'][0]['sources']], [article['url'], original['url']])
        self.assertEqual(topic['events'][0]['sources'][1]['verified_excerpt'], quote)

    def test_topic_replay_backfills_older_material_and_merges_an_existing_event(self):
        day = date(2026, 11, 28)
        older = '2026-09-05'
        related = '2026-11-20'
        for url, title, published_at in (
            ('https://lab.example/cooling', 'Liquid‑cooling measured under accelerator load', older),
            ('https://vendor.example/800v', 'Partner statement on 800VDC power delivery', related),
            ('https://news.example/unrelated', 'Cloud platform changes pricing', related),
        ):
            discovery.upsert_items([{'url': url, 'title': title, 'source': 'Example',
                                     'content_type': 'news', 'published_at': published_at,
                                     'summary': self.excerpt}], db_path=self.database)
        with closing(discovery._connect(self.database)) as db:
            items = {row['title']: (row['id'], excerpt) for row, excerpt in ic_topics._stored_materials(db, day)}
        backfill = items['Liquid‑cooling measured under accelerator load'][0]
        duplicate = items['Partner statement on 800VDC power delivery'][0]
        target = 'power-thermal'
        with closing(discovery._connect(self.database)) as db, db:
            seed = ic_topics._seeded_topics(ic_topics.public_catalog())[target]
            seed['question'] = ''
            db.execute('INSERT INTO ic_technology_topics VALUES (?,?)', (target, json.dumps(seed)))
        topic = ic_topics.topic_detail(target, self.database)
        parent = next(event for event in topic['events'] if event['id'] == 'rohm-delta-800v')
        proposal = self.proposal(('加速器液冷实验', [backfill]), ('机柜供电合作', [duplicate]),
                                 topic_id=target, name=topic['name']).model_dump()
        parent_number = next(index for index, event in enumerate(seed['events'], 1) if event['id'] == parent['id'])
        proposal['events'][1]['event_id'] = f'E{parent_number}'
        aliases = {duplicate: 'M1', backfill: 'M2'}
        for event in proposal['events']:
            del event['evidence']
            event['source_ids'] = [aliases[key] for key in event['source_ids']]
            event['evidence_source_id'] = aliases[event['evidence_source_id']]
            event['evidence_id'] = 1
        response = analysis_connection.CompletionText(json.dumps({'topics': [proposal]}),
                                                      usage={}, elapsed_seconds=1, policy={})
        invalid = json.loads(response)
        invalid['topics'][0]['events'][1]['event_id'] = 'E999'
        ic_automatic.initialize(self.database)
        with patch.dict('os.environ', {'DNEWS_DISCOVERY_DB': str(self.database)}):
            identity = editor_api.replay(editor_api.Replay(day=day, topic_id=target))['id']
        entries = {'status': 'published', 'total': 8}
        with patch.object(analysis_connection, 'credentials', return_value=({'base_url': 'https://api.deepseek.com'}, 'test')), \
             patch.object(analysis_connection, 'complete', side_effect=[json.dumps(invalid), response]) as complete, \
             patch.object(ic_topic_evaluation, 'process_next', return_value=entries) as evaluate:
            self.assertTrue(asyncio.run(ic_topics.process_next(self.database)))
            self.assertTrue(asyncio.run(ic_topics.process_next(self.database)))
            self.assertTrue(asyncio.run(ic_topics.process_next(self.database)))
            self.assertFalse(asyncio.run(ic_topics.process_next(self.database)))
            evaluate.assert_awaited_once_with(self.database, topic_id=target, recheck=True)
        self.assertEqual(complete.await_count, 2)
        prompt = complete.await_args.args[0]
        self.assertIn('补查无法定位现有进展', prompt)
        self.assertIn('"id":"M1"', prompt)
        self.assertIn('Liquid‑cooling', prompt)
        self.assertIn('Partner statement on 800VDC power delivery', prompt)
        self.assertNotIn('Cloud platform changes pricing', prompt)
        run = ic_topics.recent_runs(self.database)[0]
        self.assertEqual((run['id'], run['status'], run['reviewed'], run['evaluation']), (identity, 'complete', 2, entries))
        updated = ic_topics.topic_detail(target, self.database)
        self.assertEqual(updated['question'], '')
        events = updated['events']
        self.assertEqual(len(events), len(topic['events']) + 1)
        historical = next(event for event in events if event['id'] == 'progress-' + backfill)
        self.assertEqual(historical['date'], older)
        consolidated = next(event for event in events if event['id'] == parent['id'])
        self.assertEqual(consolidated['date'], parent['date'])
        self.assertIn(duplicate, {source['id'] for source in consolidated['sources']})
        with closing(discovery._connect(self.database)) as db:
            topics = ic_topics._topics(db, ic_topics.public_catalog())
            self.assertEqual(ic_topics._review_candidates(db, topics[target], day, ic_topics.load_catalog()), {})

    def test_collection_schedules_topic_backfill_even_without_recent_candidates(self):
        ic_editor.initialize(self.database)
        ic_automatic.initialize(self.database)
        day = date(2026, 11, 28)
        worker = ic_automatic.ObservationWorker(self.database, 'unused')
        worker.after_collection({'id': 'collector', 'window_end': day.isoformat(), 'status': 'success',
                                 'finished_at': '2026-11-28T08:30:00+08:00', 'inserted': 0, 'runs': []},
                                self.database)
        self.assertTrue(asyncio.run(ic_topics.process_next(self.database)))
        runs = {row['id']: row for row in ic_topics.recent_runs(self.database)}
        self.assertEqual(runs['collector']['status'], 'empty')
        self.assertEqual(runs['collector-review']['mode'], 'review')
        self.assertEqual(runs['collector-review']['status'], 'queued')

    def test_replay_all_topics_without_scheduling_observations(self):
        ic_automatic.initialize(self.database)
        day = date(2026, 11, 28)
        with patch.dict('os.environ', {'DNEWS_DISCOVERY_DB': str(self.database)}):
            identity = editor_api.replay(editor_api.Replay(day=day, topics_only=True))['id']
        self.assertEqual(ic_automatic.recent_runs(self.database), [])
        self.assertTrue(asyncio.run(ic_topics.process_next(self.database)))
        run = ic_topics.recent_runs(self.database)[0]
        self.assertEqual((run['id'], run['mode'], run['topic_count']),
                         (identity, 'review', len(ic_topics.get_topics(self.database))))

    def test_full_review_continues_during_a_single_topics_retry_delay(self):
        day = date(2026, 11, 28)
        identity = ic_topics.enqueue(self.database, day, {'prompt': '', 'version': 'test'}, review=True)
        attempts = []

        def candidates(db, topic, as_of, catalog):
            attempts.append(topic['id'])
            if topic['id'] == 'optics':
                raise ValueError('专题整理结果格式不完整')
            return {}

        with patch.object(ic_topics, '_review_candidates', side_effect=candidates):
            self.assertTrue(asyncio.run(ic_topics.process_next(self.database)))
            self.assertTrue(asyncio.run(ic_topics.process_next(self.database)))
        self.assertEqual(attempts, ['optics', 'chiplet'])
        with closing(discovery._connect(self.database)) as db:
            run = json.loads(db.execute('SELECT payload FROM ic_topic_refreshes WHERE id=?', (identity,)).fetchone()[0])
        self.assertEqual(run['review_delays']['optics']['attempts'], 1)
        self.assertIn('optics', run['pending'])
        self.assertNotIn('chiplet', run['pending'])
