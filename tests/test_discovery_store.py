"""Run with python -m unittest tests.test_discovery_store -v (no network)."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src import discovery


class DiscoveryStoreTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / ".runtime" / "test-tmp"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "records.sqlite"
        self.paper = {
            "content_type": "paper", "title": "Multi-view molecular prediction",
            "url": "https://publisher.example/articles/1?utm_source=feed&edition=online#abstract",
            "source": "Test Journal", "doi": "https://doi.org/10.1234/TEST.1",
            "published_at": "2026-10-21", "collected_at": "2026-11-06T09:00:00+08:00",
            "summary": "A graph and fingerprint fusion method.", "topics": ["多视图与融合"],
        }
        self.news = {
            "content_type": "news", "title": "Molecular toolkit release",
            "url": "https://community.example/releases/1", "source": "Community",
            "published_at": "2026-11-01", "collected_at": "2026-11-06T10:00:00+08:00",
            "summary": "A molecular prediction toolkit.", "topics": ["化学与分子大模型"],
        }

    def put(self, items, origin="seed"):
        return discovery.upsert_items(items, origin=origin, db_path=self.db)

    def query(self, **kwargs):
        return discovery.list_items(db_path=self.db, **kwargs)

    def test_removed_records_leave_library_and_stay_excluded_on_recollection(self):
        from src import library
        paper={**self.paper,'arxiv_id':'2610.12345'}
        self.put([paper,self.news])
        item=self.query(content_type='paper')['items'][0]
        library.update_record(item['id'],{'is_favorite':True,'notes':'Recover this note','reading_status':'reading'},db_path=self.db)
        result=discovery.remove_items([item['id']],'User removed this candidate',db_path=self.db)
        self.assertEqual(result,{'removed':1,'total':1})
        self.assertIsNone(discovery.get_item(item['id'],db_path=self.db))
        self.assertEqual(self.query(content_type='news')['total'],1)
        conn=discovery._connect(self.db)
        row=conn.execute('SELECT payload,aliases,personal_record FROM discovery_removed_items WHERE id=?',(item['id'],)).fetchone()
        self.assertEqual(json.loads(row['payload'])['title'],paper['title'])
        self.assertEqual(json.loads(row['personal_record'])['notes'],'Recover this note')
        self.assertEqual(json.loads(row['personal_record'])['reading_status'],'reading')
        self.assertTrue(json.loads(row['personal_record'])['is_favorite'])
        self.assertGreaterEqual(len(json.loads(row['aliases'])),3)
        conn.close()
        by_doi={**paper,'url':'https://different.example/article','arxiv_id':None}
        by_arxiv={**paper,'url':'https://arxiv.org/abs/2610.12345v2','doi':None}
        repeated=self.put([by_doi,by_arxiv],origin='collected')
        self.assertEqual(repeated,{'inserted':0,'updated':0,'total':1,'skipped_removed':2})
        cited_news={**self.news,'title':'News citing a removed paper','url':'https://news.example/citation','doi':paper['doi']}
        self.assertEqual(self.put([cited_news])['inserted'],1)
        self.assertEqual(discovery.remove_items([item['id']],'Repeat removal',db_path=self.db)['removed'],0)

    def test_daily_new_counts_first_collection_in_beijing_time_not_repeat_runs(self):
        self.put([self.paper])
        repeat = deepcopy(self.paper)
        repeat['collected_at'] = '2026-11-07T09:00:00+08:00'
        new_paper = deepcopy(self.paper)
        new_paper.update(doi='10.1234/new-day', url='https://p.example/new-day',
                         collected_at='2026-11-07T01:00:00+08:00')
        new_news = deepcopy(self.news)
        # UTC November 6 is already November 7 in Beijing.
        new_news['collected_at'] = '2026-11-06T20:00:00Z'
        with patch('src.discovery._now', return_value='2026-11-07T12:00:00+08:00'):
            self.put([repeat, new_paper, new_news], origin='collected')
            self.put([new_paper, new_news], origin='collected')
            facets = discovery.get_facets(self.db)
        self.assertEqual(facets['total'], 3)
        self.assertEqual(facets['today'], '2026-11-07')
        self.assertEqual((facets['new_today'], facets['papers_today'], facets['news_today']), (2, 1, 1))

    def test_combined_filters_and_literal_search(self):
        self.put([self.paper, self.news])
        result = self.query(q="MOLECULAR", content_type="paper", topic="多视图与融合",
                            date_from="2026-10-01", date_to="2026-10-31")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["doi"], "10.1234/test.1")
        self.assertEqual(self.query(q="%", content_type="paper")["total"], 0)
        self.assertEqual(self.query(q="toolkit", content_type="paper")["total"], 0)

    def test_unknown_and_year_only_dates_are_not_fabricated(self):
        unknown = deepcopy(self.paper)
        unknown.update(doi="10.1234/unknown", url="https://p.example/unknown", published_at=None, publication_year=2025)
        year = deepcopy(unknown)
        year.update(doi="10.1234/year", url="https://p.example/year", published_at="2024")
        self.put([unknown, year])
        records = self.query()["items"]
        self.assertTrue(all(item["published_at"] is None for item in records))
        self.assertEqual({item["publication_year"] for item in records}, {2024, 2025})
        self.assertEqual(self.query(date_from="2026-11-06", date_to="2026-11-06")["total"], 0)
        self.assertEqual(self.query(date_basis="collected", date_from="2026-11-06", date_to="2026-11-06")["total"], 2)

    def test_venue_filter_is_distinct_from_collection_platform(self):
        paper = deepcopy(self.paper)
        paper.update(source="Crossref", journal="Journal of Molecular Tests")
        self.put([paper, self.news], origin="collected")
        result = self.query(venue="Journal of Molecular Tests", content_type="paper")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["venue_type"], "journal")
        self.assertEqual(self.query(venue="Crossref")["total"], 0)
        self.assertEqual(discovery.get_facets(self.db)["venues"], ["Journal of Molecular Tests"])

        # Legacy rows already have journal metadata but an older search index.
        conn = discovery._connect(self.db)
        try:
            with conn:
                conn.execute("UPDATE discovery_items SET search_text='legacy index' WHERE content_type='paper'")
        finally:
            conn.close()
        self.assertEqual(self.query(q="journal of molecular tests")["total"], 1)
        self.assertEqual(self.query(venue="Journal of Molecular Tests", q="missing")["total"], 0)

    def test_duplicate_import_doi_and_url_normalization(self):
        self.assertEqual(self.put([self.paper])["inserted"], 1)
        self.assertEqual(self.put([self.paper]), {"inserted": 0, "updated": 0, "total": 1})
        another_source = deepcopy(self.paper)
        another_source.update(url="https://other.example/paper/1", source="Another source", doi="10.1234/test.1")
        self.assertEqual(self.put([another_source])["total"], 1)
        item = self.query()["items"][0]
        self.assertEqual(len(item["id"]), 24)
        self.assertEqual(len(item["source_records"]), 2)
        self.assertEqual(item["url"], "https://publisher.example/articles/1?edition=online")
        no_doi = deepcopy(self.news)
        self.put([no_doi])
        no_doi["url"] += "?utm_medium=share#body"
        self.assertEqual(self.put([no_doi])["total"], 2)

    def test_upsert_retains_first_metadata_and_collection_time(self):
        self.put([self.paper])
        update = deepcopy(self.paper)
        update.update(summary="", source="", topics=["片段与结构层次"], collected_at="2026-11-07T10:00:00+08:00", abstract_text="Original source abstract")
        self.put([update], origin="collected")
        item = self.query()["items"][0]
        self.assertEqual(item["summary"], self.paper["summary"])
        self.assertEqual(item["source"], "Test Journal")
        self.assertEqual(item["collected_at"], self.paper["collected_at"])
        self.assertEqual(item["topics"], ["多视图与融合", "片段与结构层次"])
        self.assertEqual(item["abstract_text"], "Original source abstract")
        self.assertEqual(item["origin"], "collected")
        self.put([self.paper], origin="seed")
        self.assertEqual(self.query()["items"][0]["origin"], "collected")

    def test_repeated_fetch_time_does_not_create_duplicate_evidence(self):
        self.put([self.paper], origin="collected")
        fetched_again = deepcopy(self.paper)
        fetched_again.update(collected_at="2026-11-07T10:00:00+08:00", fetched_at="2026-11-07T10:00:00+08:00")
        self.assertEqual(self.put([fetched_again], origin="collected"), {"inserted": 0, "updated": 0, "total": 1})
        fetched_again.update(collected_at="2026-11-08T10:00:00+08:00", fetched_at="2026-11-08T10:00:00+08:00")
        self.assertEqual(self.put([fetched_again], origin="collected"), {"inserted": 0, "updated": 0, "total": 1})
        stored = self.query()["items"][0]
        self.assertEqual(len(stored["source_records"]), 1)
        self.assertEqual(stored["collected_at"], self.paper["collected_at"])
        fetched_again["summary"] = "A revised source abstract."
        self.assertEqual(self.put([fetched_again], origin="collected")["updated"], 1)
        self.assertEqual(len(self.query()["items"][0]["source_records"]), 2)

    def test_reopened_database_and_paper_news_are_distinct(self):
        self.put([self.paper])
        news_with_doi = deepcopy(self.news)
        news_with_doi["doi"] = self.paper["doi"]
        self.put([news_with_doi])
        self.assertEqual(discovery.get_facets(db_path=self.db)["total"], 2)
        item = self.query(content_type="paper")["items"][0]
        self.assertEqual(discovery.get_item(item["id"], db_path=self.db)["title"], self.paper["title"])
        self.assertIsNone(discovery.get_item("missing", db_path=self.db))

    def test_later_metadata_links_preprint_and_journal_without_losing_evidence(self):
        preprint = deepcopy(self.paper)
        preprint.update(url="https://arxiv.org/abs/2311.04837v1", doi=None, arxiv_id="2311.04837v1")
        self.put([preprint, self.paper])
        self.assertEqual(self.query()["total"], 2)
        linked = deepcopy(self.paper)
        linked["arxiv_id"] = "2311.04837"
        self.put([linked])
        self.assertEqual(self.query()["total"], 1)
        self.assertEqual(len(self.query()["items"][0]["source_records"]), 3)

    def test_date_errors_and_run_history(self):
        for filters in ({"date_from": "2026-02-30"}, {"date_from": "2026-11-06", "date_to": "2026-11-01"}, {"date_basis": "other"}):
            with self.assertRaises(ValueError):
                self.query(**filters)
        for status in ("no_results", "failed"):
            discovery.record_run({"source_id": "test", "source_name": "Test Source", "status": status,
                                  "found": 0, "window_start": "2026-10-07", "window_end": "2026-11-06",
                                  "error": "unavailable" if status == "failed" else ""}, db_path=self.db)
        runs = discovery.list_runs(db_path=self.db)
        self.assertEqual([run["status"] for run in runs], ["failed", "no_results"])
        self.assertEqual(discovery.get_facets(db_path=self.db)["total"], 0)

    def test_seed_file_import_is_idempotent(self):
        seed = self.db.parent / "seed.json"
        seed.write_text(json.dumps({"items": [self.paper, self.news]}), encoding="utf-8")
        self.assertEqual(discovery.import_seed_file(seed, db_path=self.db)["inserted"], 2)
        self.assertEqual(discovery.import_seed_file(seed, db_path=self.db)["inserted"], 0)
        self.assertEqual(self.query()["total"], 2)


if __name__ == "__main__":
    unittest.main()
