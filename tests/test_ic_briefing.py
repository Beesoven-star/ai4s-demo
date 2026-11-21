"""Ranking semantics, evidence integrity, privacy, and provisional review status."""
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

from src.ic_briefing import briefing, event_briefs_by_source, load_snapshot, validate_snapshot


def fixture():
    source = {
        'id': 'news-a', 'title': 'Public technical discussion', 'content_type': 'news',
        'published_at': '2026-11-08', 'url': 'https://example.org/a',
        'organization': 'Media A', 'attention_eligible': True,
    }
    paper = {**source, 'id': 'paper', 'content_type': 'paper', 'attention_eligible': False}
    claim = {'text': 'Draft judgement with public evidence', 'source_ids': ['paper']}
    tech = {
        'id': 'a', 'overview': claim, 'assessment': claim, 'limitations': claim,
        'watch_next': claim, 'paper_ids': ['paper'], 'review_status': 'provisional',
        'scores': [{**claim, 'label': name, 'value': 4} for name in ('bottleneck', 'breadth', 'enablement')],
    }
    return {
        'data_through': '2026-11-14', 'sources': {'news-a': source, 'paper': paper},
        'events': [{'id': 'e1', 'technology_ids': ['a'], 'source_ids': ['news-a']}],
        'technologies': [deepcopy(tech)],
    }


class BriefingTests(unittest.TestCase):
    def test_window_is_inclusive_and_uses_publication_not_collection(self):
        data = fixture()
        data['sources']['news-a']['published_at'] = '2026-11-07'
        data['sources']['news-a']['collected_at'] = '2026-11-14'
        self.assertIsNone(briefing(7, data)['technologies'][0]['attention_rank'])
        data['sources']['news-a']['published_at'] = '2026-11-08'
        self.assertEqual(briefing(7, data)['technologies'][0]['attention']['source_count'], 1)
        data['sources']['news-a']['published_at'] = '2026-11-15'
        self.assertIsNone(briefing(7, data)['technologies'][0]['attention_rank'])
        data['sources']['news-a']['published_at'] = None
        self.assertIsNone(briefing(30, data)['technologies'][0]['attention_rank'])

    def test_same_media_and_same_event_are_not_inflated_by_repeated_urls(self):
        data = fixture()
        data['sources']['news-b'] = {**data['sources']['news-a'], 'id': 'news-b', 'url': 'https://example.org/b'}
        data['events'][0]['source_ids'] += ['news-a', 'news-b']
        attention = briefing(30, data)['technologies'][0]['attention']
        self.assertEqual((attention['source_count'], attention['event_count'], attention['covered_days']), (1, 1, 1))
        self.assertEqual(attention['news_count'], 2)

    def test_official_only_stays_unranked_and_does_not_boost_a_tie(self):
        data = fixture()
        data['sources']['news-a']['attention_eligible'] = False
        result = briefing(30, data)['technologies'][0]
        self.assertIsNone(result['attention_rank'])
        self.assertEqual(result['attention']['news_count'], 1)
        self.assertEqual(result['attention']['event_count'], 0)
        self.assertEqual(result['importance_rank'], 1)

    def test_hotspots_rank_events_by_independent_media_then_report_date(self):
        data = fixture()
        base = data['sources']['news-a']
        for identity, organization, published, eligible in [
            ('repeat-a', 'Media A', '2026-11-09', True),
            ('news-b', 'Media B', '2026-11-10', True),
            ('official', 'Vendor', '2026-11-14', False),
            ('recent', 'Media A', '2026-11-13', True),
            ('older', 'Media A', '2026-11-07', True),
        ]:
            data['sources'][identity] = {
                **base, 'id': identity, 'organization': organization,
                'published_at': published, 'attention_eligible': eligible,
            }
        data['events'][0]['source_ids'] += ['repeat-a', 'news-b', 'official']
        data['technologies'].append({**deepcopy(data['technologies'][0]), 'id': 'b'})
        data['events'][0]['technology_ids'].append('b')
        for identity, source in [('e3', 'recent'), ('e2', 'recent'),
                                 ('e4', 'news-a'), ('e5', 'official'), ('e6', 'older')]:
            data['events'].append({'id': identity, 'technology_ids': ['a'], 'source_ids': [source]})

        result = briefing(7, data)
        events = {e['id']: e for e in result['events']}
        self.assertEqual(result['event_attention_order'], ['e1', 'e2', 'e3', 'e4'])
        self.assertEqual([events[key]['attention_rank'] for key in result['event_attention_order']], [1, 2, 3, 4])
        self.assertEqual(events['e1']['attention'], {
            'source_count': 2, 'source_ids': ['news-b', 'repeat-a', 'news-a'], 'latest_reported_at': '2026-11-10',
        })
        self.assertIsNone(events['e5']['attention_rank'])
        self.assertIn('e6', briefing(30, data)['event_attention_order'])
        self.assertEqual(result['importance_order'], ['a', 'b'])

    def test_papers_cannot_be_used_as_attention_events(self):
        data = fixture()
        data['events'][0]['source_ids'] = ['paper']
        with self.assertRaisesRegex(ValueError, 'Papers'):
            briefing(30, data)

    def test_equal_scores_receive_consecutive_ranks(self):
        data = fixture()
        for ident in ('b', 'c'):
            data['technologies'].append({**deepcopy(data['technologies'][0]), 'id': ident})
        data['events'][0]['technology_ids'] = ['a', 'b', 'c']
        data['technologies'][2]['scores'][0]['value'] = 3
        data['sources']['news-b'] = {**data['sources']['news-a'], 'id': 'news-b', 'organization': 'Media B'}
        data['events'].append({'id': 'e2', 'technology_ids': ['c'], 'source_ids': ['news-b']})
        by_id = {t['id']: t for t in briefing(30, data)['technologies']}
        self.assertEqual([by_id[i]['importance_rank'] for i in ('a', 'b', 'c')], [1, 2, 3])
        self.assertEqual([by_id[i]['attention_rank'] for i in ('a', 'b', 'c')], [2, 3, 1])

    def test_invalid_evidence_scores_and_human_review_fail_closed(self):
        for change in ('missing_ref', 'bad_score', 'fake_review'):
            data = fixture()
            if change == 'missing_ref':
                data['technologies'][0]['overview'] = {'text': 'No evidence', 'source_ids': ['missing']}
            elif change == 'bad_score':
                data['technologies'][0]['scores'][0]['value'] = 6
            else:
                data['technologies'][0]['review_status'] = 'reviewed'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_snapshot(data)

    def test_windows_do_not_mutate_snapshot_or_importance(self):
        data = load_snapshot()
        original = deepcopy(data)
        seven, thirty = briefing(7, data), briefing(30, data)
        self.assertEqual(data, original)
        self.assertEqual([(t['id'], t['importance_rank']) for t in seven['technologies']],
                         [(t['id'], t['importance_rank']) for t in thirty['technologies']])
        self.assertEqual(seven['window']['date_from'], '2026-11-14')
        self.assertEqual(thirty['window']['date_from'], '2026-10-22')
        for bad in (0, 14, 31, '7', True):
            with self.subTest(days=bad), self.assertRaises(ValueError):
                briefing(bad, data)

    def test_edition_has_cited_drafts_and_no_private_fields(self):
        data = load_snapshot()
        validate_snapshot(data)
        self.assertEqual(len(data['technologies']), 6)
        self.assertTrue(all(t['review_status'] == 'provisional' and t['reviewed_by'] is None for t in data['technologies']))
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(set(value) & {'library', 'notes', 'source_records', 'api_key', 'service_url'})
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        inspect(data)

    def test_weekly_highlights_point_to_dated_events_with_evidence(self):
        result = briefing(7)
        events = {event['id']: event for event in result['events']}
        highlights = result['weekly_highlights']
        self.assertTrue(highlights)
        self.assertTrue(all(events[entry['event_id']]['window_source_ids'] for entry in highlights))
        self.assertTrue(result['weekly_story']['research_question'])
        self.assertTrue(all(entry['reading_question'] for entry in highlights))
        invalid = load_snapshot()
        invalid['weekly_highlights'][0]['event_id'] = 'missing-event'
        with self.assertRaisesRegex(ValueError, 'Invalid weekly highlight event'):
            validate_snapshot(invalid)
        invalid = load_snapshot()
        invalid['weekly_highlights'][0]['reading_question'] = ''
        with self.assertRaisesRegex(ValueError, 'Weekly highlight explanation is missing'):
            validate_snapshot(invalid)

    def test_event_summary_is_shared_by_related_news_sources(self):
        snapshot = load_snapshot()
        by_source = event_briefs_by_source(snapshot)
        event = next(event for event in snapshot['events'] if event['id'] == 'lambda-cpo')
        expected = next(entry for entry in snapshot['weekly_highlights'] + snapshot.get('article_briefs', []) if entry['event_id'] == event['id'])
        for source_id in event['source_ids']:
            brief = by_source[source_id][0]
            self.assertEqual(brief['what_happened'], expected['what_happened'])
            self.assertEqual({source['id'] for source in brief['sources']}, set(event['source_ids']))
        self.assertTrue(set(by_source) <= {source_id for source_id, source in snapshot['sources'].items()
                                           if source['content_type'] == 'news'})

    def test_hot_event_can_appear_before_a_formal_technology_topic_exists(self):
        data = fixture()
        data['events'][0]['technology_ids'] = []
        result = briefing(7, data)
        self.assertEqual(result['event_attention_order'], ['e1'])
        self.assertEqual(result['attention_order'], [])
        self.assertEqual(result['technologies'][0]['attention']['event_ids'], [])

    def test_backfill_groups_announcements_and_separates_event_and_reporting_dates(self):
        edition = briefing(7)
        events = {event['id']: event for event in edition['events']}
        sources = edition['sources']
        ucie = events['ucie-memory']
        self.assertEqual(ucie['occurred_at'], '2026-11-12')
        self.assertEqual([sources[sid]['source'] for sid in ucie['window_source_ids']], ['Jon Peddie Research'])
        marvell = events['marvell-memory']
        self.assertEqual([sources[sid]['source'] for sid in marvell['window_source_ids']
                          if sources[sid]['attention_eligible']], ['The Register'])
        self.assertEqual(sum(sources[sid]['news_genre'] == '同稿分发' for sid in marvell['source_ids']), 1)
        self.assertTrue(all(not source['attention_eligible'] for source in sources.values()
                            if source['news_genre'] in ('有赞助披露的采访', '二手编译', '厂商供稿', '厂商问答')))


class BriefingEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_domain_isolation_and_invalid_window(self):
        from fastapi import HTTPException
        from src.web.discovery import ic_briefing
        with patch.dict(os.environ, {'DNEWS_RESEARCH_DOMAIN': 'ic'}):
            self.assertEqual((await ic_briefing(days=7))['window']['days'], 7)
            with self.assertRaises(HTTPException) as error:
                await ic_briefing(days=14)
            self.assertEqual(error.exception.status_code, 422)
        with patch.dict(os.environ, {'DNEWS_RESEARCH_DOMAIN': ''}):
            with self.assertRaises(HTTPException) as error:
                await ic_briefing(days=30)
            self.assertEqual(error.exception.status_code, 404)

    async def test_discovery_detail_reuses_public_event_summary_in_ic_only(self):
        from src.web.discovery import discovery_item
        item_id = '24b9f05db2f055aabcf4efd1'
        with patch('src.discovery.get_item', side_effect=lambda identity: {'id': identity, 'content_type': 'news', 'title': 'CPO test item'}):
            with patch.dict(os.environ, {'DNEWS_RESEARCH_DOMAIN': 'ic'}):
                detail = await discovery_item(item_id)
                self.assertEqual(detail['event_briefs'][0]['event_id'], 'lambda-cpo')
            with patch.dict(os.environ, {'DNEWS_RESEARCH_DOMAIN': ''}):
                self.assertNotIn('event_briefs', await discovery_item(item_id))


if __name__ == '__main__':
    unittest.main()
