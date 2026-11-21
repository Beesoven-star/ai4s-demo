"""Publication precision, source separation and saved-record preservation."""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.collect_discovery import collect_source, in_window, parse_crossref, parse_feed, parse_imec_article
from src import discovery, library
from src.news_sources import parse_article


class ICSourceTests(unittest.TestCase):
    now = '2026-11-13T20:00:00+08:00'
    journal = dict(name='IC Journal', kind='crossref_journal', content_type='paper',
                   issn='0018-9200', url='https://api.crossref.org/journals/0018-9200/works',
                   journal_name='IC Journal', relevance_mode='dedicated_journal',
                   title_exclude_patterns=['^editorial'])

    def payload(self, **fields):
        return json.dumps({'status':'ok', 'message':{'items':[
            dict(title=['A cryogenic pulse generator'], DOI='10.1234/ic', **fields)], 'total-results':1}})

    def test_online_date_wins_over_future_print_issue(self):
        item = parse_crossref(self.payload(**{'published-online':{'date-parts':[[2026,11,12]]},
                'published-print':{'date-parts':[[2027,3,31]]}}), self.journal, self.now)[0]
        self.assertEqual(item['published_at'], '2026-11-12')
        self.assertEqual(item['publication_status'], 'journal_metadata')

    def test_month_precision_is_not_fabricated_or_replaced_by_print_day(self):
        item = parse_crossref(self.payload(**{'published-online':{'date-parts':[[2026,11]]},
                'published-print':{'date-parts':[[2027,3,31]]}}), self.journal, self.now)[0]
        self.assertIsNone(item['published_at'])
        self.assertEqual(item['publication_month'], '2026-11')
        self.assertTrue(in_window(item, date(2026,11,7), date(2026,11,13)))
        self.assertFalse(in_window(item, date(2026,12,1), date(2026,12,31)))

    def test_specialist_journal_accepts_circuit_research_without_ai_keyword(self):
        settings = {'relevance':{'domain_terms':['chip'], 'method_terms':['language model']}}
        with patch('scripts.collect_discovery.request_bytes', return_value=self.payload().encode()):
            items = collect_source(self.journal, settings, date(2026,11,1), date(2026,11,13), self.now)
        self.assertEqual(len(items), 1)
        with patch('scripts.collect_discovery.request_bytes', return_value=json.dumps({
            'status':'ok','message':{'total-results':1,'items':[{'title':['Editorial'], 'DOI':'10.1234/editorial'}]}}).encode()):
            self.assertEqual(collect_source(self.journal, settings, date(2026,11,1), date(2026,11,13), self.now), [])

    def test_news_requires_publication_date_but_not_ai_method(self):
        source = dict(name='Official news', kind='feed', content_type='news', url='https://example.org/feed',
                      relevance_mode='domain_only', require_exact_date=True)
        settings = {'relevance':{'domain_terms':['chiplet'], 'method_terms':['language model']}}
        body = '<rss><channel><item><title>Chiplet requirements released</title><link>https://example.org/news</link>{}</item></channel></rss>'
        with patch('scripts.collect_discovery.request_bytes', return_value=body.format('<pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate>').encode()):
            self.assertEqual(len(collect_source(source, settings, date(2026,11,1), date(2026,11,13), self.now)), 1)
        with patch('scripts.collect_discovery.request_bytes', return_value=body.format('').encode()):
            self.assertEqual(collect_source(source, settings, date(2026,11,1), date(2026,11,13), self.now), [])

    def test_servethehome_ddr6_passes_beijing_day_and_keyword_filters(self):
        config_path = Path(__file__).resolve().parents[1] / 'resources/discovery_sources_ic.json'
        settings = json.loads(config_path.read_text(encoding='utf-8'))
        source = next(source for source in settings['sources'] if source['id'] == 'servethehome_ic')
        rss = b'''<rss><channel><item>
            <title>JEDEC previews DDR6</title><link>https://example.org/ddr6</link>
            <pubDate>Fri, 20 Nov 2026 23:40:12 +0000</pubDate>
        </item></channel></rss>'''
        previous_day, beijing_day = date(2026, 11, 20), date(2026, 11, 21)
        with patch('scripts.collect_discovery.request_bytes', return_value=rss):
            self.assertEqual(collect_source(source, settings, previous_day, previous_day, self.now), [])
            selected = collect_source(source, settings, beijing_day, beijing_day, self.now)
        self.assertEqual([item['published_at'] for item in selected], ['2026-11-21'])

    def test_news_html_converts_zoned_dates_and_preserves_unzoned_dates(self):
        for value, expected in (
            ('2026-11-20T23:40:12Z', '2026-11-21'),
            ('2026-11-21T00:30:00+09:00', '2026-11-20'),
            ('2026-11-20T23:40:12', '2026-11-20'),
            ('2026-11-20', '2026-11-20'),
        ):
            with self.subTest(value=value):
                html = f'<h1>Memory update</h1><meta property="article:published_time" content="{value}">'
                item = parse_article(html, 'https://example.org/memory', {'name': 'News'}, self.now)
                self.assertEqual(item['published_at'], expected)

    def test_imec_uses_visible_first_publication_not_other_timestamps(self):
        html = '<meta property="og:title" content="Chiplets"><meta property="og:description" content="Interoperable devices"><p>Updated 13 November 2026</p><p>Published on: 12 November 2026</p><script>Published on: 11 November 2026</script>'
        item = parse_imec_article(html, 'https://www.imec-int.com/en/press/chiplets', {'name':'imec'}, self.now)
        self.assertEqual(item['published_at'], '2026-11-12')
        self.assertEqual(item['news_genre'], '研究机构公告')
        with self.assertRaises(ValueError):
            parse_imec_article(html.replace('Published on: 12 November 2026', ''), item['url'], {'name':'imec'}, self.now)

    def test_news_rss_retains_only_short_excerpt(self):
        payload = '<rss><channel><item><title>Chip</title><link>https://example.org/news</link><description>' + 'word '*500 + '</description></item></channel></rss>'
        item = parse_feed(payload, {'kind':'feed','content_type':'news','name':'News'}, self.now)[0]
        self.assertLessEqual(len(item['abstract_text'].split()), 141)

    def test_semiconductor_word_does_not_override_explicit_out_of_scope_rule(self):
        source = dict(name='imec', kind='feed', content_type='news', url='https://example.org/feed',
            relevance_mode='domain_only', body_exclude_patterns=['solar technology'])
        body = b'<rss><channel><item><title>Silicon solar technology</title><link>https://example.org/solar</link></item></channel></rss>'
        with patch('scripts.collect_discovery.request_bytes', return_value=body):
            self.assertEqual(collect_source(source, {'relevance':{'domain_terms':['silicon']}}, date(2026,11,1), date(2026,11,13), self.now), [])

    def test_journal_upgrade_preserves_preprint_identity_and_personal_notes(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=root) as folder:
            db = Path(folder) / 'ic.sqlite'
            preprint = dict(title='Circuit design', url='https://arxiv.org/abs/2610.12345', arxiv_id='2610.12345',
                doi='10.1234/ic', content_type='paper', source='arXiv', venue_type='preprint',
                published_at='2026-10-01', date_kind='arxiv_first_submission')
            discovery.upsert_items([preprint], db_path=db)
            item = discovery.list_items(db_path=db)['items'][0]
            library.update_record(item['id'], {'is_favorite':True,'notes':'Keep reading','reading_status':'reading'}, db_path=db)
            published = parse_crossref(self.payload(**{'published':{'date-parts':[[2026,11]]}}), self.journal, self.now)[0]
            discovery.upsert_items([published], origin='collected', db_path=db)
            result = discovery.list_items(publication_kind='journal', db_path=db)
            upgraded = result['items'][0]
            self.assertEqual(result['total'], 1)
            self.assertEqual(upgraded['id'], item['id'])
            self.assertEqual(upgraded['preprint_first_submitted_at'], '2026-10-01')
            self.assertIsNone(upgraded['published_at'])
            self.assertEqual(upgraded['library']['notes'], 'Keep reading')
            self.assertEqual(upgraded['library']['reading_status'], 'reading')
            self.assertTrue(upgraded['library']['is_favorite'])
            self.assertEqual(discovery.list_items(publication_kind='preprint', db_path=db)['total'], 0)
            self.assertEqual(discovery.list_items(date_from='2026-11-01', db_path=db)['total'], 0)
            with self.assertRaises(ValueError):
                discovery.list_items(publication_kind='fake', db_path=db)


if __name__ == '__main__':
    unittest.main()
