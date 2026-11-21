"""Conference identity, date precision, bounded coverage and personal records."""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.collect_discovery import collect_source, parse_crossref
from src import discovery, ic_research, library


class ConferenceTests(unittest.TestCase):
    source = dict(name='DAC', kind='crossref_conference', content_type='paper',
                  url='https://api.crossref.org/works', conference_query='Design Automation Conference',
                  venue_patterns=[r'\bdesign automation conference\b'],
                  venue_exclude_patterns=['workshop', 'asia'], rows=2, max_pages=1,
                  initial_literature_scope='archive')
    now = '2026-11-14T12:00:00+08:00'

    def payload(self, *records):
        return json.dumps(dict(status='ok', message={'items':list(records), 'total-results':2000}))

    def record(self, **fields):
        return {'title':['AI-assisted circuit placement'], 'DOI':'10.1234/dac',
                'type':'proceedings-article', 'container-title':['2026 Design Automation Conference'],
                'published':{'date-parts':[[2026, 7]]},
                'event':{'start':{'date-parts':[[2026, 7, 20]]}}, **fields}

    def test_reject_fuzzy_matches_workshops_and_wrong_record_types(self):
        payload = self.payload(self.record(), self.record(**{'container-title':['Optical Design Automation II']}),
            self.record(**{'container-title':['Design Automation Conference Workshop']}),
            self.record(type='journal-article'),
            self.record(**{'container-title':['Asia and South Pacific Design Automation Conference']}))
        items = parse_crossref(payload, self.source, self.now)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['venue_type'], 'conference')
        self.assertEqual(items[0]['conference_year'], 2026)
        self.assertIsNone(items[0]['published_at'])
        self.assertEqual(items[0]['publication_month'], '2026-07')

    @patch('scripts.collect_discovery.request_bytes')
    def test_partial_search_is_not_reported_as_complete_and_new_items_archive(self, request):
        request.return_value = self.payload(self.record())
        info = {}
        items = collect_source(self.source, {'relevance':{'domain_terms':['circuit'], 'method_terms':['placement']}},
            date(2026,1,1), date(2026,11,14), self.now, info)
        self.assertEqual(len(items), 1)
        self.assertFalse(info['coverage']['complete'])
        self.assertTrue(info['coverage_warning'])
        self.assertEqual(ic_research.scope_of(ic_research.analyze(items[0])), 'archive')
        self.assertIn('offset=0', request.call_args.args[0])

    def test_conference_upgrade_by_doi_preserves_identity_and_notes(self):
        root = Path(__file__).resolve().parents[1]/'.runtime'/'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=root) as folder:
            db = Path(folder)/'test.sqlite'
            old = {'content_type':'paper', 'title':'AI-assisted circuit placement', 'url':'https://arxiv.org/abs/2601.12345',
                   'doi':'10.1234/dac', 'arxiv_id':'2601.12345','venue_type':'preprint',
                   'published_at':'2026-01-10', 'collected_at':self.now}
            discovery.upsert_items([old], db_path=db)
            item = discovery.list_items(db_path=db)['items'][0]
            library.update_record(item['id'], {'is_favorite':True,'notes':'Read section 3','reading_status':'reading'}, db_path=db)
            formal = parse_crossref(self.payload(self.record()),self.source,self.now)[0]
            result = discovery.upsert_items([formal], origin='collected', db_path=db)
            self.assertEqual(result['inserted'], 0)
            saved = discovery.get_item(item['id'], db_path=db)
            self.assertEqual(saved['venue_type'], 'conference')
            self.assertEqual(saved['preprint_first_submitted_at'], '2026-01-10')
            self.assertEqual(saved['library']['notes'], 'Read section 3')
            self.assertEqual(saved['library']['reading_status'], 'reading')
            self.assertIsNone(saved['published_at'])


if __name__ == '__main__':
    unittest.main()
