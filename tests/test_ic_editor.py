import asyncio
from contextlib import closing
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from src import analysis_connection, discovery, ic_automatic, ic_editor, ic_topics
from src.discovery_collection import CollectionService
from src.ic_observation_drafts import build_drafts
from src.ic_observations import load_catalog
from src.web import discovery as discovery_api, ic_editor as editor_api


class ObservationEditorTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        self.folder = TemporaryDirectory(dir=root)
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / 'editor.sqlite'
        ic_editor.initialize(self.database)
        self.items = [dict(id=key, title=f'Acme and Beta show liquid cooling prototype {key}',
                           source=key, url=f'https://example.org/{key}', summary='Source summary',
                           content_type='news', published_at='2026-11-20') for key in ('a', 'b')]
        report = build_drafts(self.items, date(2026, 11, 20), load_catalog())
        ic_editor.stage_batch(report, 'trial', label='test', db_path=self.database)

    def test_edit_merge_and_publish_without_rewriting_old_issues(self):
        edits = {'title': 'Edited daily', 'intro': 'Reviewed together', 'source_reviews': {'a': 'reporting', 'b': 'official'},
                 'entries': [dict(title='One event', summary='Evidence from both', source_ids=['a','b'], topic_ids=['power-thermal'])]}
        with patch.dict('os.environ', {'DNEWS_DISCOVERY_DB': str(self.database), 'DNEWS_RESEARCH_DOMAIN': 'ic'}):
            self.assertEqual(len(editor_api.drafts()['drafts']), 2)
            identity = 'trial-daily'
            request = editor_api.Edits(revision=1, **edits)
            self.assertEqual(editor_api.save(identity, request)['revision'], 2)
            with self.assertRaises(HTTPException) as error:
                editor_api.save(identity, request)
            self.assertEqual(error.exception.status_code, 409)
            with self.assertRaises(ValidationError):
                editor_api.Publish.model_validate({'revision': 2, 'confirm': False})
            self.assertFalse(ic_editor.publications('daily', self.database))
            confirm = editor_api.Publish(revision=2, confirm=True)
            report = editor_api.publish(identity, confirm)
            self.assertEqual([row['id'] for row in report['entries'][0]['sources']], ['a', 'b'])
            self.assertEqual(report['entries'][0]['classification']['topics'][0]['id'], 'power-thermal')
            self.assertEqual(editor_api.publish(identity, confirm), report)
            day = date(2026, 11, 20)
            self.assertEqual(asyncio.run(discovery_api.ic_observations(day))['report']['title'], 'Edited daily')
            self.assertNotEqual(asyncio.run(discovery_api.ic_observations(day, 'original'))['report']['title'], 'Edited daily')

    def test_offline_completion_creates_new_batch_and_is_safe_to_retry(self):
        before = ic_editor.get_draft('trial-daily', self.database)
        discovery.upsert_items([dict(url='https://example.org/new', title='3D-IC prototype', summary='News summary',
                                    content_type='news', source='New', published_at='2026-11-21')], db_path=self.database)
        job = {'id': 'manual', 'status': 'success', 'window_end': '2026-11-21', 'inserted': 1, 'runs': [],
               'finished_at': '2026-11-21T14:00:00+08:00'}
        ic_editor.stage_completed_collection(job, self.database)
        daily = ic_editor.get_draft('manual-daily', self.database)
        self.assertEqual(daily['entries'][0]['topic_ids'], ['chiplet'])
        ic_editor.save_draft(daily['id'], 1, {'title': 'Keep my change'}, self.database)
        ic_editor.stage_completed_collection(job, self.database)
        self.assertEqual(ic_editor.get_draft('manual-daily', self.database)['title'], 'Keep my change')
        self.assertEqual(ic_editor.get_draft('trial-daily', self.database), before)
        self.assertEqual(len(ic_editor.list_drafts(self.database)), 4)

    def test_weekly_publication_keeps_its_own_version(self):
        draft = ic_editor.get_draft('trial-weekly', self.database)
        report = ic_editor.publish_draft(draft['id'], 1, self.database)
        self.assertEqual(report['date_from'], '2026-11-14')
        with patch.dict('os.environ', {'DNEWS_DISCOVERY_DB': str(self.database), 'DNEWS_RESEARCH_DOMAIN': 'ic'}):
            self.assertEqual(editor_api.weekly()['report']['id'], 'trial-weekly')
            self.assertIsNone(editor_api.weekly('original')['report'])

    def test_weekly_archive_groups_rolling_editions_by_natural_week(self):
        def report(identity, day, published_at):
            return {'id': identity, 'title': identity, 'date': day, 'date_from': day, 'published_at': published_at}

        latest = report('current-latest-weekly', '2026-11-22', '2026-11-22T13:00:00+08:00')
        earlier = report('current-initial-weekly', '2026-11-22', '2026-11-22T09:00:00+08:00')
        previous = report('previous-weekly', '2026-11-21', '2026-11-23T13:00:00+08:00')
        same_day_as_original = report('revised-original-weekly', '2026-11-20', '2026-11-23T13:10:00+08:00')
        with patch('src.web.ic_editor.editor.publications', return_value=[latest, earlier, previous, same_day_as_original]):
            current = editor_api.weekly()
            self.assertEqual(current['report']['id'], latest['id'])
            self.assertEqual([(row['date_from'], row['date']) for row in current['editions']], [('2026-11-16', '2026-11-22')])
            self.assertFalse(current['versions'])
            self.assertEqual(editor_api.weekly(earlier['id'])['report'], current['report'])
            self.assertEqual(editor_api.weekly(day=date(2026, 11, 21))['report'], current['report'])
            original = editor_api.weekly('original')
            self.assertEqual(original['selected_version'], 'original')
            self.assertFalse(original['versions'])
            self.assertIsNone(editor_api.weekly(day=date(2026, 11, 15))['report'])

    def test_daily_archive_uses_latest_version_for_each_date(self):
        legacy = {'selected_day': '2026-11-21', 'today': '2026-11-21',
                  'editions': [{'date': '2026-11-20', 'title': 'Original daily'}], 'report': None}
        latest = {'id': 'latest', 'date': '2026-11-21', 'title': 'Latest daily', 'published_at': '2026-11-21T14:00:00+08:00'}
        earlier = {**latest, 'id': 'earlier', 'title': 'Earlier daily', 'published_at': '2026-11-21T08:00:00+08:00'}
        result = ic_editor.daily_with_editions(legacy, [latest, earlier])
        self.assertEqual(result['editions'], [{'date': '2026-11-21', 'title': 'Latest daily'}, *legacy['editions']])
        self.assertEqual(result['report'], latest)
        self.assertEqual(ic_editor.daily_with_editions(legacy, [latest, earlier], 'earlier')['report'], earlier)

    def test_legacy_daily_rewrites_are_folded_but_remain_addressable(self):
        day = '2026-11-21'
        source = {'id': 'one-article'}
        reports = [
            {'id': 'latest', 'date': day, 'title': 'Latest wording', 'published_at': day + 'T13:37',
             'entries': [{'source': source, 'sources': [source]}]},
            {'id': 'rewrite', 'date': day, 'title': 'Earlier wording', 'published_at': day + 'T12:10',
             'entries': [{'source': source}]},
        ]
        legacy = {'today': day, 'selected_day': day, 'editions': [], 'report': None}
        archive = ic_editor.daily_with_editions(legacy, reports)
        self.assertEqual([row['id'] for row in archive['versions']], ['latest'])
        self.assertEqual(archive['report']['id'], 'latest')
        self.assertEqual(ic_editor.daily_with_editions(legacy, reports, 'rewrite')['report']['id'], 'rewrite')

    def test_collection_creates_automatic_editions_and_keeps_manual_publication(self):
        ic_automatic.initialize(self.database)
        CollectionService(self.database)
        discovery.upsert_items([
            dict(url='https://example.org/ddr6', title='DDR6 preview', summary='DDR6 preview, not a final specification.',
                 content_type='news', source='Example', published_at='2026-11-21')
        ], db_path=self.database)
        worker = ic_automatic.ObservationWorker(self.database, 'unused config')
        ic_automatic.save_prompt(self.database, '优先新技术')
        identity = ic_automatic.replay(self.database, date(2026, 11, 21))
        daily = ic_editor.get_draft(identity + '-daily', self.database)
        source_id = daily['candidates'][0]['id']
        entry = dict(title='DDR6 规格预览', summary='标准草案阶段。', source_ids=[source_id],
                     topic_ids=['hbm'], category_ids=['memory'])
        edition = dict(title='DDR6', intro='规格预览。', entries=[entry],
                       change={'source_id': source_id, 'evidence': 'DDR6 preview'})
        result = {'daily': edition, 'weekly': edition, 'topic_suggestions': [],
                  'source_reviews': [{'source_id': source_id, 'kind': 'reporting', 'evidence': 'Fabricated quote'}]}
        raw = analysis_connection.CompletionText(json.dumps(result), usage={'total_tokens': 42}, elapsed_seconds=1, policy={})
        with patch('src.ic_automatic.analysis_connection.credentials', return_value=({'base_url': 'https://api.deepseek.com'}, 'test')), \
             patch('src.ic_automatic.analysis_connection.complete', return_value=raw), \
             patch('src.ic_automatic._evidence', return_value={source_id: {'status': 'excerpt', 'text': 'DDR6 preview'}}):
            self.assertTrue(asyncio.run(worker.process_next()))
        report = ic_editor.publications('daily', self.database)[0]
        self.assertEqual(report['id'], identity + '-daily')
        self.assertEqual(report['entries'][0]['classification']['topics'], [])
        self.assertEqual(report['entries'][0]['sources'][0]['news_genre'], '来源性质待确认')
        self.assertEqual(ic_editor.published_source_check(source_id, self.database), {'status': 'excerpt', 'genre': None})
        self.assertIsNone(ic_editor.published_source_check('unknown-source', self.database))
        self.assertEqual(ic_editor.publications('weekly', self.database)[0]['id'], identity + '-weekly')
        self.assertEqual(ic_automatic.recent_runs(self.database)[0]['status'], 'published')
        self.assertIsNone(ic_editor.get_draft('trial-daily', self.database)['published_at'])

    def test_retired_hbm_weekly_is_unlisted_and_new_evidence_updates_the_topic(self):
        ic_automatic.initialize(self.database)
        CollectionService(self.database)
        day = '2026-11-21'
        stamp = f'{day}T14:30:00+08:00'
        archived = {'id': 'legacy-hbm_weekly', 'kind': ic_editor.HBM_WEEKLY, 'date': day,
                    'date_from': '2026-11-15', 'published_at': stamp, 'title': '历史 HBM 周报',
                    'entries': [{'comparison': {'route': 'ssd'}}]}
        pending = {'id': 'pending-hbm_weekly', 'kind': ic_editor.HBM_WEEKLY, 'status': 'queued',
                   'attempts': 0, 'date': day, 'draft_ids': ['pending-hbm_weekly'], 'available_at': stamp}
        with closing(discovery._connect(self.database)) as db, db:
            db.execute('INSERT INTO ic_editor_drafts VALUES (?, ?, 2, ?, ?)',
                       (archived['id'], stamp, stamp, json.dumps(archived)))
            db.execute('INSERT INTO ic_editor_publications VALUES (?, ?, ?, ?, ?)',
                       (archived['id'], archived['kind'], day, stamp, json.dumps(archived)))
            db.execute('INSERT INTO ic_auto_runs VALUES (?, ?, ?, ?, ?)',
                       (pending['id'], pending['status'], stamp, stamp, json.dumps(pending)))
        ic_automatic.initialize(self.database)
        self.assertEqual(ic_automatic.recent_runs(self.database)[0]['status'], 'cancelled')

        quote = 'AMD IT deployed MEXT on 86 engineering hosts.'
        discovery.upsert_items([dict(url='https://example.org/mext', title='AMD MEXT deployment', summary=quote,
                                    content_type='news', source='Example', published_at=day)], db_path=self.database)
        worker = ic_automatic.ObservationWorker(self.database, 'unused config')
        job = {'id': 'new-evidence', 'status': 'success', 'window_end': day, 'inserted': 1,
               'finished_at': stamp, 'runs': []}
        ids = worker.after_collection(job, self.database)
        self.assertEqual(ids, ['new-evidence-daily', 'new-evidence-weekly'])
        ic_automatic.replay(self.database, date.fromisoformat(day))
        self.assertFalse(any(run['kind'] == ic_editor.HBM_WEEKLY and run['status'] != 'cancelled'
                             for run in ic_automatic.recent_runs(self.database) if 'kind' in run))
        key = ic_editor.get_draft(ids[0], self.database)['candidates'][0]['id']
        proposal = {'topics': [{'topic_id': 'hbm', 'name': 'HBM 与 AI 存储层次协同', 'overview': '内存分层。',
                                'question': '怎样扩容？', 'follow_up': '跟踪延迟。',
                                'events': [{'title': 'AMD 内部部署 MEXT', 'summary': '在工程主机部署。',
                                            'source_ids': [key], 'evidence_source_id': key, 'evidence_id': 1}]}]}
        result = analysis_connection.CompletionText(json.dumps(proposal), usage={}, elapsed_seconds=1, policy={})
        with patch.object(analysis_connection, 'credentials', return_value=({'base_url': 'https://api.deepseek.com'}, 'test')), \
             patch.object(analysis_connection, 'complete', return_value=result):
            self.assertTrue(asyncio.run(ic_topics.process_next(self.database)))
        timeline = ic_topics.topic_detail('hbm', self.database)['events']
        source = next(source for event in timeline for source in event['sources'] if source['id'] == key)
        self.assertEqual(source['verified_excerpt'], quote)
        self.assertEqual(ic_editor.publications(ic_editor.HBM_WEEKLY, self.database), [archived])
        with patch.dict('os.environ', {'DNEWS_DISCOVERY_DB': str(self.database)}):
            weekly = editor_api.weekly(version=archived['id'])
            self.assertIsNone(weekly['report'])
            self.assertEqual(weekly['selected_version'], 'original')

    def test_automatic_editions_require_substantive_updates_and_reuse_assessments(self):
        ic_automatic.initialize(self.database)
        CollectionService(self.database)
        worker = ic_automatic.ObservationWorker(self.database, 'not used')
        day = '2026-11-21'

        def add(slug, title, summary):
            discovery.upsert_items([dict(url=f'https://example.org/{slug}', title=title, summary=summary,
                                         content_type='news', source=slug, published_at=day)], origin='collected', db_path=self.database)
            return next(row['id'] for row in discovery.list_items(db_path=self.database)['items'] if row['title'] == title)

        def stage(identity, cutoff=day, partial=False):
            job = {'id': identity, 'status': 'partial' if partial else 'success', 'window_end': cutoff,
                   'finished_at': '2026-11-21T14:30:00+08:00', 'inserted': 0, 'runs': []}
            worker.after_collection(job, self.database)

        def evidence(candidates, *_):
            return {key: {'status': 'excerpt', 'text': row['summary']} for key, row in candidates.items()}

        def edition(key, title, quote):
            return {'title': title, 'intro': title, 'entries': [{'title': title, 'summary': title, 'source_ids': [key]}],
                    'change': {'source_id': key, 'evidence': quote}}

        def respond(**editions):
            return analysis_connection.CompletionText(json.dumps(editions), usage={}, elapsed_seconds=1, policy={})

        first_fact = 'The company confirms a laboratory prototype of the optical switch.'
        first = add('initial', 'Optical switch prototype', first_fact)
        first_edition = edition(first, '光交换机完成实验室样机', first_fact)
        connection = ({'base_url': 'https://api.deepseek.com'}, 'test')
        with patch('src.ic_automatic.analysis_connection.credentials', return_value=connection), \
             patch('src.ic_automatic._evidence', side_effect=evidence), \
             patch('src.ic_automatic.ic_topics.enqueue'), \
             patch('src.ic_automatic.analysis_connection.complete') as complete:
            complete.return_value = respond(daily=first_edition, weekly=first_edition)
            stage('first')
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertEqual(complete.await_count, 1)
            self.assertEqual(ic_automatic.recent_runs(self.database)[0]['status'], 'published')

            stage('same-content', partial=True)
            self.assertTrue(asyncio.run(worker.process_next()))
            ic_automatic.save_prompt(self.database, '用另一种写法')
            ic_automatic.replay(self.database, date.fromisoformat(day))
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertEqual(ic_automatic.recent_runs(self.database)[0]['status'], 'unchanged')
            stage('only-window-shift', cutoff='2026-11-22')
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertEqual(complete.await_count, 1)

            add('copy', 'Syndicated announcement about the optical switch', first_fact)
            stage('same-text')
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertEqual(complete.await_count, 1)

            add('duplicate', 'A different outlet reports the same prototype event',
                'The vendor announced a lab prototype for its optical switching equipment.')
            complete.return_value = respond(daily=None, weekly=None)
            stage('other-report')
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertEqual(complete.await_count, 2)
            self.assertEqual(ic_automatic.recent_runs(self.database)[0]['status'], 'unchanged')
            self.assertEqual(ic_automatic.recent_runs(self.database)[0]['publications'], [])
            stage('same-duplicate')
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertEqual(complete.await_count, 2)

            new_fact = 'The switch has been installed and tested in a production data center.'
            # The same stored article can acquire a materially different introduction.
            update = add('initial', 'Optical switch prototype', new_fact)
            self.assertEqual(update, first)
            complete.return_value = respond(daily=edition(update, '光交换机完成实际部署验证', new_fact),
                                            weekly=None)
            stage('installation')
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertEqual(complete.await_count, 3)
            self.assertIn('光交换机完成实验室样机', complete.call_args.args[0])
            reports = ic_editor.publications('daily', self.database)
            self.assertEqual([row['id'] for row in reports], ['installation-daily', 'first-daily'])
            self.assertNotEqual(reports[0]['automation']['material_change'], reports[1]['automation']['material_change'])
            archive = ic_editor.daily_with_editions(
                {'today': day, 'selected_day': day, 'editions': [], 'report': None}, reports)
            self.assertEqual([row['id'] for row in archive['versions']], ['installation-daily', 'first-daily'])
            self.assertEqual([row['id'] for row in ic_editor.publications('weekly', self.database)], ['first-weekly'])

            falsified = add('unfounded', 'Optical network test follow-up', 'This article discusses an optical network.')
            complete.return_value = respond(daily=edition(falsified, '无出处的进展', 'This invented quote is absent.'),
                                            weekly=None)
            stage('unsupported')
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertIn('引文与来源材料不符', ic_automatic.recent_runs(self.database)[0]['error'])
            self.assertEqual(len(ic_editor.publications('daily', self.database)), 2)

    def test_weekly_updates_same_issue_and_preserves_its_main_thread(self):
        ic_automatic.initialize(self.database)
        worker = ic_automatic.ObservationWorker(self.database, 'unused')

        def add(slug, day, summary):
            discovery.upsert_items([dict(url=f'https://example.org/{slug}', title=slug, summary=summary,
                                         content_type='news', source='Example', published_at=day)], db_path=self.database)
            return next(row['id'] for row in discovery.list_items(db_path=self.database)['items'] if row['title'] == slug)

        def stage(identity, day):
            job = {'id': identity, 'status': 'success', 'window_end': day, 'inserted': 1,
                   'finished_at': f'{day}T16:00:00+08:00', 'runs': []}
            drafts = ic_editor.stage_completed_collection(job, self.database, kinds=('weekly',))
            ic_automatic.enqueue(self.database, drafts)
            return ic_editor.get_draft(drafts[0], self.database)

        def response(key, headline, *, target=None):
            report = {'title': headline, 'intro': headline, 'change': {'source_id': key, 'evidence_id': 1},
                      'entries': [{'title': headline, 'summary': headline, 'source_ids': [key], 'update_entry': target}]}
            return analysis_connection.CompletionText(json.dumps({'weekly': report}), usage={}, elapsed_seconds=1, policy={})

        old = add('sunday', '2026-11-22', 'The chip was demonstrated in a closed laboratory.')
        first = add('monday', '2026-11-23', 'The company began a laboratory prototype test.')
        with patch.object(analysis_connection, 'credentials', return_value=({'base_url': 'https://api.deepseek.com'}, 'test')), \
             patch.object(analysis_connection, 'complete', return_value=response(first, '本周主线')) as complete, \
             patch.object(ic_automatic, '_evidence', side_effect=lambda candidates, *_: {
                 key: {'status': 'excerpt', 'text': item['summary']} for key, item in candidates.items()}):
            monday = stage('monday', '2026-11-23')
            self.assertEqual((monday['date_from'], monday['week_end']), ('2026-11-23', '2026-11-29'))
            self.assertNotIn(old, {item['id'] for item in monday['candidates']})
            self.assertTrue(asyncio.run(worker.process_next()))
            initial, = ic_editor.publications('weekly', self.database)

            extra = add('wednesday', '2026-11-25', 'An independent tester published latency observations.')
            complete.return_value = response(extra, '额外的延迟观测')
            stage('wednesday', '2026-11-25')
            self.assertTrue(asyncio.run(worker.process_next()))
            updated, = ic_editor.publications('weekly', self.database)
            self.assertEqual((updated['id'], updated['title'], updated['intro']),
                             (initial['id'], '本周主线', '本周主线'))
            self.assertEqual(updated['entries'][0], initial['entries'][0])
            self.assertEqual(updated['coverage_through'], '2026-11-25')
            self.assertIn('previous.entries', complete.call_args.args[0])

            stage('older-replay', '2026-11-24')
            self.assertTrue(asyncio.run(worker.process_next()))
            self.assertEqual(complete.await_count, 2)
            self.assertEqual(ic_editor.publications('weekly', self.database), [updated])

            correction = add('friday', '2026-11-27', 'The company completed validation of the first prototype.')
            complete.return_value = response(correction, '原型完成验证', target=1)
            stage('friday', '2026-11-27')
            self.assertTrue(asyncio.run(worker.process_next()))
            latest, = ic_editor.publications('weekly', self.database)
            self.assertEqual(latest['title'], initial['title'])
            self.assertEqual(latest['entries'][0]['source']['id'], correction)
            self.assertEqual(latest['entries'][1], updated['entries'][1])

            next_week = add('next-monday', '2026-11-30', 'Another manufacturer reported an installation.')
            complete.return_value = response(next_week, '下周主线')
            stage('next-monday', '2026-11-30')
            self.assertTrue(asyncio.run(worker.process_next()))
        reports = ic_editor.publications('weekly', self.database)
        self.assertEqual([(row['date_from'], row['date']) for row in reports],
                         [('2026-11-30', '2026-12-06'), ('2026-11-23', '2026-11-29')])

    def test_daily_publishes_with_a_numbered_excerpt_when_weekly_is_invalid(self):
        ic_automatic.initialize(self.database)
        day = '2026-11-21'
        excerpt = 'The company disclosed an optical switch deployed at its first data center.'
        discovery.upsert_items([dict(url='https://example.org/numbered', title='Optical switch deployment',
                                     summary=excerpt, content_type='news', source='Example', published_at=day)],
                               db_path=self.database)
        worker = ic_automatic.ObservationWorker(self.database, 'unused')
        job = {'id': 'numbered', 'status': 'success', 'window_end': day, 'inserted': 1,
               'finished_at': f'{day}T14:30:00+08:00', 'runs': []}
        drafts = ic_editor.stage_completed_collection(job, self.database, kinds=('daily', 'weekly'))
        ic_automatic.enqueue(self.database, drafts)
        key = ic_editor.get_draft(drafts[0], self.database)['candidates'][0]['id']
        reference = {'source_id': key, 'evidence_id': 1}
        edition = {'title': '光交换样机部署', 'intro': '来自已入库的报道。', 'change': reference,
                   'entries': [{'title': '光交换机部署', 'summary': '厂商披露了首个部署。', 'source_ids': [key]}]}
        response = {'daily': edition, 'weekly': {**edition, 'change': {**reference, 'evidence_id': 99}},
                    'source_reviews': [{'source_id': key, 'kind': 'reporting', 'evidence': None}]}
        raw = analysis_connection.CompletionText(json.dumps(response), usage={}, elapsed_seconds=1, policy={})
        evidence = {key: {'status': 'excerpt', 'text': excerpt}}
        with patch.object(analysis_connection, 'credentials', return_value=({'base_url': 'https://api.deepseek.com'}, 'test')), \
             patch.object(analysis_connection, 'complete', return_value=raw) as complete, \
             patch.object(ic_automatic, '_evidence', return_value=evidence):
            self.assertTrue(asyncio.run(worker.process_next()))
            prompt = complete.call_args.args[0]
        self.assertIn('change_excerpts', prompt)
        self.assertIn(excerpt, prompt)
        self.assertEqual(len(ic_editor.publications('daily', self.database)), 1)
        self.assertFalse(ic_editor.publications('weekly', self.database))
        run = ic_automatic.recent_runs(self.database)[0]
        self.assertEqual(run['status'], 'queued')
        self.assertEqual(run['publications'], ['numbered-daily'])
        self.assertEqual(set(run['edition_errors']), {'weekly'})

    def test_original_article_can_reuse_single_source_summary_only(self):
        automation = {'prompt_version': 'test', 'generated_at': '2026-11-20T10:00:00+08:00',
                      'collection_partial': False, 'topic_suggestions': [],
                      'sources': {key: {'status': 'original', 'note': ''} for key in ('a', 'b')}}
        single = dict(title='Cooling prototype', summary='The publisher describes a prototype.',
                      boundary='No throughput figure was reported.', source_ids=['a'], topic_ids=[])
        combined = {**single, 'source_ids': ['a', 'b']}
        def changes(entry):
            return {'title': 'Cooling', 'intro': 'A prototype is described.', 'entries': [entry], 'source_reviews': {}}
        ic_editor.publish_automatic({'trial-daily': changes(single), 'trial-weekly': changes(combined)}, automation, self.database)
        check = ic_editor.published_source_check('a', self.database)
        self.assertEqual(check['status'], 'original')
        self.assertEqual(check.get('summary'), single['summary'])
        self.assertEqual(check.get('boundary'), single['boundary'])
        self.assertNotIn('summary', ic_editor.published_source_check('b', self.database))

    def test_paper_generation_reads_experimental_conditions_from_stored_abstract(self):
        abstract = 'The method was evaluated on seven 28 nm designs. It reduced peak current under the reported baseline.'
        discovery.upsert_items([dict(url='https://example.org/paper', title='Circuit timing',
                                     summary='Peak current decreased.', abstract_text=abstract, content_type='paper',
                                     source='Journal', published_at='2026-11-21')], db_path=self.database)
        paper = discovery.list_items(content_type='paper', db_path=self.database)['items'][0]
        candidate = {'content_type': 'paper', 'summary': 'Peak current decreased.'}
        self.assertEqual(ic_automatic._paper_evidence({paper['id']: candidate}, self.database),
                         {paper['id']: {'status': 'abstract', 'text': abstract}})
