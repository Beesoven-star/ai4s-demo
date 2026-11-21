"""Regression checks for collection dates, review scopes and news evidence."""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from src import discovery, library
from src.ic_research import analyze, curated_reviews, scope_of
from src.news_sources import parse_article, collect_html
from src.publication_timing import assess

class ICQualityTests(unittest.TestCase):
    def test_recent_boundary_preprint_and_ingestion_are_distinct(self):
        def kind(**item):return assess(item,date(2026,11,14))['kind']
        self.assertEqual(kind(published_at='2026-10-16'),'recent_published')
        self.assertEqual(kind(published_at='2026-11-14',venue_type='preprint'),'recent_preprint')
        self.assertEqual(kind(published_at='2026-10-15',collected_at='2026-11-14'),'historical')
        self.assertEqual(kind(publication_month='2026-11',collected_at='2026-11-14'),'month_only')
        self.assertEqual(kind(collected_at='2026-11-14'),'unknown')
        self.assertEqual(kind(published_at='2026-11-15'),'future')

    def test_review_is_bound_to_identity_and_title_and_new_items_stay_pending(self):
        identity,review=next((i,r) for i,r in curated_reviews().items() if r['title'].startswith('TopoSizing'))
        item={'id':identity,'title':review['title'],'content_type':'paper'}
        self.assertEqual(analyze(item)['topic_ids'],['A3'])
        self.assertEqual(scope_of(analyze(item)),'main')
        self.assertEqual(scope_of(analyze({**item,'title':'New LLM-based RTL design'})),'pending')
        self.assertEqual(scope_of(analyze({'title':'LLM-Based RTL Bug Localization','content_type':'paper'})),'pending')

    def test_scope_and_precision_filters_preserve_personal_records(self):
        reviews=curated_reviews()
        selected=[]
        for decision in ('ai_focus','general_archive','needs_review','excluded'):
            identity,review=next((i,r) for i,r in reviews.items() if r['decision']==decision)
            selected.append({'id':identity,'title':review['title'],'content_type':'paper',
                'url':'https://example.org/'+identity,'publication_month':'2026-11','collected_at':'2026-11-14'})
        root=Path(__file__).resolve().parents[1]/'.runtime/test-tmp'
        root.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=root) as directory, patch.dict('os.environ',{'DNEWS_RESEARCH_DOMAIN':'ic'}):
            db=Path(directory)/'test.sqlite'
            discovery.upsert_items(selected,db_path=db)
            # Upserts derive stable identities; bind our test reviews to those identities.
            actual=discovery.list_items(content_type='paper',literature_scope='all',db_path=db)['items']
            by_title={r['title']:r for r in reviews.values()}
            test_reviews={i['id']:by_title[i['title']] for i in actual}
            with patch('src.ic_research.curated_reviews',return_value=test_reviews):
                from src.ic_research import from_payload
                from_payload.cache_clear()
                first=discovery.list_items(content_type='paper',db_path=db)
                self.assertEqual(first['total'],1)
                identity=first['items'][0]['id']
                library.update_record(identity,{'is_favorite':True,'notes':'Keep review note','reading_status':'reading'},db_path=db)
                for scope in ('archive','pending','excluded'):
                    self.assertEqual(discovery.list_items(literature_scope=scope,db_path=db)['total'],1)
                self.assertEqual(discovery.list_items(literature_scope='all',publication_period='month_only',db_path=db)['total'],3)
                self.assertEqual(discovery.list_items(literature_scope='all',date_from='2026-11-01',db_path=db)['total'],0)
                self.assertEqual(discovery.list_items(literature_scope='all',date_from='2026-11-01',date_basis='collected',db_path=db)['total'],4)
                record=discovery.get_item(identity,db_path=db)['library']
                self.assertTrue(record['is_favorite'])
                self.assertEqual(record['notes'],'Keep review note')
                self.assertEqual(record['reading_status'],'reading')
                from_payload.cache_clear()

    def test_news_uses_publication_not_modified_or_event_date(self):
        html='<h1>AI chip design</h1><script type="application/ld+json">'+json.dumps({
            '@type':'NewsArticle','datePublished':'2026-11-09','dateModified':'2026-11-14',
            'event':{'startDate':'2026-12-01'}})+'</script>'
        item=parse_article(html,'https://example.org/article',{'name':'Official blog','news_genre':'企业技术博客'},'2026-11-14')
        self.assertEqual(item['published_at'][:10],'2026-11-09')
        self.assertEqual(item['content_type'],'news')
        self.assertEqual(item['news_genre'],'企业技术博客')
        with self.assertRaises(ValueError):
            parse_article('<h1>Event</h1><meta property="article:modified_time" content="2026-11-14">','https://example.org/a',{'name':'Test'},'2026-11-14')

    def test_news_archives_remain_accessible_and_do_not_pollute_main_news(self):
        root=Path(__file__).resolve().parents[1]/'.runtime/test-tmp'
        root.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=root) as directory, patch.dict('os.environ',{'DNEWS_RESEARCH_DOMAIN':'ic'}):
            db=Path(directory)/'test.sqlite'
            discovery.upsert_items([
                {'title':'AI chip design','url':'https://example.org/chip','content_type':'news','news_scope':'main'},
                {'title':'GPU cluster operations','url':'https://example.org/ops','content_type':'news','news_scope':'archive'},
            ],db_path=db)
            self.assertEqual(discovery.list_items(content_type='news',db_path=db)['total'],1)
            self.assertEqual(discovery.list_items(content_type='news',news_scope='all',db_path=db)['total'],2)
            archive=discovery.list_items(content_type='news',news_scope='archive',db_path=db)
            self.assertEqual(archive['total'],1)
            self.assertIsNotNone(discovery.get_item(archive['items'][0]['id'],db_path=db))
            facets=discovery.get_facets(db)
            self.assertEqual((facets['news'],facets['news_candidates'],facets['archived_news']),(1,2,1))

    def test_ijiwei_original_publish_field_and_bounded_same_host_collection(self):
        html='<h1>芯片设计新闻</h1><script>{"create_time":"20261101080000","published_time":"20261113120000","update_time":"20261114090000"}</script>'
        self.assertEqual(parse_article(html,'https://www.ijiwei.com/n/123',{'name':'爱集微'},'2026-11-14')['published_at'][:10],'2026-11-13')
        source={'name':'Test','url':'https://www.ijiwei.com/','article_url_pattern':r'/n/\d+','max_articles':1}
        calls=[]
        def request(url,*args):
            calls.append(url)
            return (('<a href="/n/123">one</a><a href="https://other.org/n/2">offsite</a><a href="/n/456">two</a>') if url==source['url'] else html).encode()
        info={}
        with patch('time.sleep'):
            items=collect_html(source,'2026-11-14',request,10,10000,info)
        self.assertEqual(len(items),1)
        self.assertEqual(calls,['https://www.ijiwei.com/','https://www.ijiwei.com/n/123'])
        self.assertEqual(info['coverage']['links_found'],2)
        self.assertFalse(info['coverage']['complete'])

if __name__=='__main__':unittest.main()
