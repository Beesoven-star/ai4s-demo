from datetime import date
import unittest
from unittest.mock import patch
from src.news_sources import collect_feed_history
from scripts.collect_discovery import collect_source


class NewsHistoryTests(unittest.TestCase):
    source = {'kind':'feed','content_type':'news','name':'Test', 'url':'https://example.org/feed/',
              'history_page_url':'https://example.org/feed/?paged={page}','max_feed_pages':4}

    def feed(self, day, identity):
        return f'<rss><channel><item><title>AI chip {identity}</title><link>https://example.org/{identity}</link><pubDate>{day}</pubDate></item></channel></rss>'

    def test_history_stops_after_crossing_window_start_and_retains_real_dates(self):
        calls=[]
        def request(url,*args):
            calls.append(url)
            return self.feed('2026-11-13' if len(calls)==1 else '2026-10-15',len(calls))
        run={}
        items=collect_feed_history(self.source,date(2026,10,16),'2026-11-14',request,1,9999,run)
        self.assertEqual(len(calls),2)
        self.assertEqual(items[1]['published_at'],'2026-10-15')
        self.assertTrue(run['coverage']['reached_window_start'])
        self.assertFalse(run['coverage']['complete'])

    def test_history_failure_is_recorded_without_discarding_front_page(self):
        def request(url,*args):
            if 'paged' in url:raise ValueError('Unavailable')
            return self.feed('2026-11-13','first')
        run={}
        items=collect_feed_history(self.source,date(2026,10,16),'2026-11-14',request,1,9999,run)
        self.assertEqual(len(items),1)
        self.assertEqual(len(run['coverage']['errors']),1)
        self.assertFalse(run['coverage']['reached_window_start'])

    def test_repeated_page_does_not_loop_or_duplicate(self):
        calls=[]
        def request(url,*args):
            calls.append(url)
            return self.feed('2026-11-13','same')
        items=collect_feed_history(self.source,date(2026,10,16),'2026-11-14',request,1,9999,{})
        self.assertEqual(len(calls),2)
        self.assertEqual(len(items),1)

    def test_source_specific_processor_terms_keep_amd_news_but_exclude_financials(self):
        source={**self.source, 'history_page_url':None, 'relevance_mode':'domain_only',
                'domain_terms':['EPYC'], 'title_exclude_patterns':['Financial Results']}
        feed=self.feed('2026-11-10','test').replace('AI chip test','AMD EPYC processor launch')
        with patch('scripts.collect_discovery.request_bytes',return_value=feed):
            self.assertEqual(len(collect_source(source,{'relevance':{'domain_terms':['CMOS']}},date(2026,10,16),date(2026,11,14),'2026-11-14')),1)
        with patch('scripts.collect_discovery.request_bytes',return_value=feed.replace('processor launch','Financial Results')):
            self.assertEqual(collect_source(source,{'relevance':{'domain_terms':['CMOS']}},date(2026,10,16),date(2026,11,14),'2026-11-14'),[])
