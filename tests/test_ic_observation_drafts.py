from datetime import date
import unittest

from src.ic_observation_drafts import build_drafts, render_markdown
from src.ic_observations import load_catalog


def source(identity, title, day='2026-11-20', *, kind='news', **fields):
    return {'id': identity, 'title': title, 'published_at': day, 'content_type': kind,
            'source': 'Example', 'url': f'https://example.org/{identity}', **fields}


class ObservationDraftTests(unittest.TestCase):
    def test_daily_uses_publication_day_even_when_the_most_recent_issue_is_earlier(self):
        items = [source('one', 'AIラック向け800V直流給電'), source('two', 'Chiplet prototype', None),
                 source('three', 'Old chiplet research', '2026-11-14')]
        report = build_drafts(items, date(2026, 11, 21), load_catalog(), known_ids={'one'})
        self.assertEqual(report['daily']['entries'], [])
        self.assertEqual(report['latest_dated_sample']['date'], '2026-11-20')
        self.assertEqual(report['outside_window'], 1)
        self.assertEqual(len(report['undated']), 1)
        self.assertEqual(report['already_in_library'], 1)
        self.assertEqual(report['weekly']['entries'][0]['classification']['topics'][0]['id'], 'power-thermal')

    def test_same_event_suggestions_retain_the_articles_for_editorial_review(self):
        items = [source('one', 'Acme and Beta show liquid cooling prototype'),
                 source('two', 'Acme and Beta detail liquid cooling prototype')]
        report = build_drafts(items, date(2026, 11, 20), load_catalog())
        self.assertEqual(len(report['possible_event_duplicates']), 1)
        self.assertEqual(len(report['daily']['entries']), 2)
        self.assertTrue(all(entry['possible_duplicate'] for entry in report['entries']))

    def test_paper_draft_reads_the_abstract_and_retains_source_links(self):
        result = 'Results show that the measured prototype improves latency by 12%.'
        paper = source('paper', 'Research on physical design', kind='paper', abstract_text=result,
                       summary_kind='source', reading_notes={'basis': 'abstract', 'points': []})
        report = build_drafts([paper], date(2026, 11, 20), load_catalog())
        self.assertEqual(report['entries'][0]['reading_basis'], 'abstract_excerpt')
        self.assertEqual(report['entries'][0]['paper_points'][0]['text'], result)
        self.assertIn('https://example.org/paper', render_markdown(report))
        self.assertIn('摘要原句', render_markdown(report))
