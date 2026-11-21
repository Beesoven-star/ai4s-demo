"""Parser and selection behavior; no network or external packages required."""

from datetime import date
from contextlib import nullcontext, redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect_discovery import collect_source, in_window, is_relevant, main, parse_crossref, parse_feed, title_has_molecular_task


class DiscoveryCollectorTests(unittest.TestCase):
    now = "2026-11-06T12:00:00+08:00"
    rules = {"domain_terms": ["molecular", "smiles"], "method_terms": ["property prediction", "representation", "language model"]}

    def test_rss_abstract_heading_is_not_saved_as_body(self):
        payload = '<rss><channel><item><title>Molecular prediction</title><link>https://example.org/p</link><description><![CDATA[<h2>Abstract</h2><p>Causal molecular prediction.</p>]]></description></item></channel></rss>'
        item = parse_feed(payload, {'name': 'Journal RSS', 'kind': 'feed', 'content_type': 'paper'}, self.now)[0]
        self.assertEqual(item['abstract_text'], 'Causal molecular prediction.')
        self.assertEqual(item['summary'], item['abstract_text'])

    def test_xml_abstract_children_and_jats_heading_keep_boundaries(self):
        payload = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Molecular prediction</title><link href="https://example.org/p"/><summary><div xmlns="http://www.w3.org/1999/xhtml"><h3>Abstract</h3><p>RNA prediction.</p><p>Another paragraph.</p></div></summary></entry></feed>'
        item = parse_feed(payload, {'name': 'Journal Atom', 'kind': 'feed', 'content_type': 'paper'}, self.now)[0]
        self.assertEqual(item['abstract_text'], 'RNA prediction. Another paragraph.')
        response = {'status': 'ok', 'message': {'items': [{'title': ['Molecular prediction'], 'DOI': '10.1234/jats', 'abstract': '<jats:abstract><jats:title>Abstract</jats:title><jats:p>Multi<jats:italic>view</jats:italic> prediction.</jats:p></jats:abstract>'}]}}
        item = parse_crossref(json.dumps(response), {'name': 'Crossref'}, self.now)[0]
        self.assertEqual(item['abstract_text'], 'Multiview prediction.')

    def test_atom_preserves_first_submission_and_has_no_three_item_limit(self):
        entries = "".join(f'''<entry><id>http://arxiv.org/abs/2610.{10000+i}v2</id><title>Molecular representation {i}</title><published>2026-10-10T23:50:00Z</published><updated>2026-11-05T12:00:00Z</updated><summary>Study of molecular property prediction.</summary><link rel="alternate" href="http://arxiv.org/abs/2610.{10000+i}v2"/></entry>''' for i in range(5))
        payload = '<feed xmlns="http://www.w3.org/2005/Atom">' + entries + '</feed>'
        items = parse_feed(payload, {"name": "arXiv", "kind": "arxiv", "content_type": "paper"}, self.now)
        self.assertEqual(len(items), 5)
        self.assertEqual(items[0]["published_at"], "2026-10-10")
        self.assertEqual(items[0]["arxiv_id"], "2610.10000")
        self.assertEqual(items[0]["url"], "https://arxiv.org/abs/2610.10000")

    def test_rss_unknown_date_and_safe_plain_text(self):
        payload = '''<rss><channel><item><title>Molecular language model released</title><link>https://example.org/release</link><description>&lt;p&gt;Molecular property prediction&lt;/p&gt;&lt;script&gt;ignore()&lt;/script&gt;</description><pubDate>unknown</pubDate></item></channel></rss>'''
        item = parse_feed(payload, {"name": "News", "kind": "feed", "content_type": "news"}, self.now)[0]
        self.assertIsNone(item["published_at"])
        self.assertEqual(item["date_kind"], "unknown")
        self.assertNotIn("ignore", item["summary"])

    def test_atom_updated_alone_does_not_become_publication_date(self):
        payload = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>SMILES representation</title><link href="https://example.org/p"/><updated>2026-11-05T12:00:00Z</updated></entry></feed>'''
        item = parse_feed(payload, {"name": "Feed", "kind": "feed", "content_type": "paper"}, self.now)[0]
        self.assertIsNone(item["published_at"])
        self.assertIsNone(item["abstract_text"])
        self.assertEqual(item["summary"], "")

    def test_crossref_partial_year_is_not_fabricated_day(self):
        response = {"status": "ok", "message": {"items": [{"title": ["Molecular property prediction"], "DOI": "10.1234/test", "published": {"date-parts": [[2025]]}, "created": {"date-time": "2026-11-06T12:00:00Z"}}]}}
        item = parse_crossref(json.dumps(response), {"name": "Crossref"}, self.now)[0]
        self.assertIsNone(item["published_at"])
        self.assertEqual(item["publication_year"], 2025)
        self.assertEqual(item["summary"], "")

    def test_window_and_relevance_are_separate_conditions(self):
        start, end = date(2026, 10, 8), date(2026, 11, 6)
        self.assertTrue(in_window({"published_at": "2026-10-08"}, start, end))
        self.assertFalse(in_window({"published_at": "2026-09-01"}, start, end))
        self.assertTrue(in_window({"published_at": None}, start, end))
        self.assertTrue(is_relevant("SMILES language model", "", self.rules))
        self.assertFalse(is_relevant("New large language model", "A general chat application", self.rules))
        self.assertFalse(is_relevant("Molecular dynamics", "Metal alloy simulation", self.rules))

    def test_wrong_response_is_failure_not_empty_success(self):
        with self.assertRaises(ValueError):
            parse_feed('<html><body>Error page</body></html>', {"name": "Bad", "kind": "feed", "content_type": "news"}, self.now)
        with self.assertRaises(ValueError):
            parse_crossref('{"status":"failed"}', {"name": "Bad"}, self.now)
        error_feed = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#bad_query</id><title>Error</title><summary>Invalid search query</summary></entry></feed>'
        with self.assertRaisesRegex(ValueError, "Invalid search query"):
            parse_feed(error_feed, {"name": "arXiv", "kind": "arxiv", "content_type": "paper"}, self.now)

    def test_current_policy_retains_molecular_generation_evaluation(self):
        rules = json.loads((Path(__file__).resolve().parents[1] / 'resources' / 'discovery_sources.json').read_text(encoding='utf-8'))['relevance']
        # Regression: the 2026-11-06 BiB HEDGEHOG record was rejected because
        # its method was molecular generation, rather than representation.
        self.assertTrue(is_relevant(
            'HEDGEHOG: hierarchical evaluation of drug generators through rigorous filtration',
            'Generative molecular models are evaluated against physicochemical constraints.', rules))
        self.assertFalse(is_relevant(
            'Molecular characterization of protein interactions',
            'Generative image models reconstruct microscopy scans.', rules))

    def test_selection_counts_distinguish_filtering_unknown_date_and_duplicates(self):
        entries = [
            ('Molecular representation', 'https://example.org/a', '2026-11-02'),
            ('Molecular representation', 'https://example.org/a', '2026-11-02'),
            ('Molecular characterization', 'https://example.org/no-method', '2026-11-02'),
            ('Molecular representation', 'https://example.org/old', '2026-10-01'),
            ('Molecular representation', 'https://example.org/undated', ''),
        ]
        payload = '<rss><channel>' + ''.join(
            f'<item><title>{title}</title><link>{url}</link><pubDate>{day}</pubDate></item>'
            for title, url, day in entries) + '</channel></rss>'
        info = {}
        with patch('scripts.collect_discovery.request_bytes', return_value=payload.encode()):
            items = collect_source({'kind': 'feed', 'content_type': 'paper', 'name': 'Test Journal', 'url': 'https://example.org/rss'},
                                   {'relevance': self.rules}, date(2026, 11, 1), date(2026, 11, 7), self.now, info)
        self.assertEqual(len(items), 2)
        self.assertEqual(info['selection'], {'parsed': 5, 'date_matched': 4, 'matched': 2,
                                           'rejected_date': 1, 'rejected_relevance': 1,
                                           'undated': 1, 'duplicates_within_source': 1})

    def test_current_policy_covers_standard_molecular_ml_without_accepting_generic_ml(self):
        rules = json.loads((Path(__file__).resolve().parents[1] / 'resources' / 'discovery_sources.json').read_text(encoding='utf-8'))['relevance']
        self.assertTrue(is_relevant('Machine learning predicts solubility from SMILES', '', rules))
        self.assertTrue(is_relevant('Graph neural networks for molecular toxicity prediction', '', rules))
        self.assertFalse(is_relevant('Graph neural networks for traffic forecasting', '', rules))
        self.assertFalse(is_relevant('Synthesis and characterization of chemical compounds', '', rules))

    def test_fuzzy_title_search_rejects_unrelated_molecular_profiling(self):
        self.assertFalse(title_has_molecular_task("Multimodality Molecular Profiling Nominates Targetable Mechanisms in Progressive RV Dysfunction"))
        self.assertTrue(title_has_molecular_task("Multi-view molecular representation learning"))
        self.assertTrue(title_has_molecular_task("Predicting molecular properties with language models"))

    def test_rss1_namespace_and_journal_venue_with_doi(self):
        payload = '''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"><item><title>Molecular representation</title><link>https://example.org/article</link><description>SMILES language model</description><dc:date>2026-11-01</dc:date><dc:identifier>doi:10.1234/rss</dc:identifier><prism:publicationName>Actual Journal</prism:publicationName></item></rdf:RDF>'''
        source = {"name": "Journal feed", "kind": "feed", "content_type": "paper", "journal_required": True, "journal_name": "Configured Journal", "issn": "1234-567X"}
        item = parse_feed(payload, source, self.now)[0]
        self.assertEqual(item["published_at"], "2026-11-01")
        self.assertEqual(item["abstract_text"], "SMILES language model")
        self.assertEqual(item["doi"], "10.1234/rss")
        self.assertEqual(item["venue_type"], "journal")
        self.assertEqual(item["venue_name"], "Actual Journal")
        self.assertEqual(item["issn"], "1234-567X")
        news = parse_feed(payload, {**source, "content_type": "news"}, self.now)[0]
        self.assertNotIn("venue_type", news)
        self.assertNotIn("journal", news)

    def test_official_rss_prism_doi_and_unknown_date_remain_separate(self):
        payload = '''<rss xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"><channel><item><title>Molecular representation</title><link>https://example.org/article</link><prism:doi>10.1234/prism</prism:doi></item></channel></rss>'''
        source = {"name": "Journal feed", "kind": "feed", "content_type": "paper", "journal_required": True, "journal_name": "Configured Journal"}
        item = parse_feed(payload, source, self.now)[0]
        self.assertEqual(item["doi"], "10.1234/prism")
        self.assertEqual(item["venue_name"], "Configured Journal")
        self.assertIsNone(item["published_at"])
        self.assertEqual(item["date_kind"], "unknown")


class JournalCollectorTests(unittest.TestCase):
    now = DiscoveryCollectorTests.now
    start, end = date(2026, 10, 8), date(2026, 11, 6)
    settings = {"relevance": DiscoveryCollectorTests.rules}
    source = {
        "id": "journal", "name": "Configured Journal / Crossref", "kind": "crossref_journal",
        "url": "https://api.crossref.org/journals/1234-567X/works", "issn": "1234-567X",
        "journal_name": "Configured Journal", "content_type": "paper",
    }

    def response(self, titles, total, cursor=None):
        records = [{"title": [title], "DOI": f"10.1234/{index}-{title.replace(' ', '-')}",
                    "container-title": ["Actual Journal"],
                    "published-online": {"date-parts": [[2026, 11, 1]]}}
                   for index, title in enumerate(titles)]
        return json.dumps({"status": "ok", "message": {"items": records, "total-results": total, "next-cursor": cursor}}).encode()

    def collect(self, source=None, run_info=None):
        return collect_source(source or self.source, self.settings, self.start, self.end, self.now, run_info=run_info)

    def test_journal_request_stays_issn_scoped_with_index_cursor_traversal(self):
        info = {}
        with patch("scripts.collect_discovery.request_bytes", return_value=self.response(["Molecular representation"], 1)) as request:
            item = self.collect(run_info=info)[0]
        url = urlparse(request.call_args.args[0])
        params = parse_qs(url.query)
        self.assertEqual(url.path, "/journals/1234-567X/works")
        self.assertEqual(params["rows"], ["100"])
        self.assertEqual(params["cursor"], ["*"])
        self.assertEqual(params["sort"], ["indexed"])
        self.assertEqual(params["order"], ["desc"])
        self.assertEqual(params["filter"], ["from-pub-date:2026-10-08,until-pub-date:2026-11-06,type:journal-article"])
        self.assertNotIn("query.title", params)
        self.assertEqual(item["venue_type"], "journal")
        self.assertEqual(item["venue_name"], "Actual Journal")
        self.assertEqual(item["issn"], "1234-567X")
        self.assertTrue(info["coverage"]["complete"])
        self.assertEqual(info["coverage"]["traversal_sort"], "indexed")
        self.assertEqual(info["coverage"]["window_start"], "2026-10-08")

    def test_journal_cursor_avoids_crossref_http400_publication_sort_constraint(self):
        def crossref_request(url, *_):
            params = parse_qs(urlparse(url).query)
            if "cursor" in params and params.get("sort", [None])[0] in {"issued", "published", "published-print", "published-online"}:
                body = {"status": "failed", "message-type": "validation-failure", "message": [{
                    "type": "sort-criteria-incompatible-with-cursor",
                    "message": "Sorting by [issued,published,published-print,published-online] is not supported when using a cursor",
                }]}
                raise HTTPError(url, 400, "Bad Request", {}, BytesIO(json.dumps(body).encode()))
            return self.response(["Molecular representation"], 1)

        with patch("scripts.collect_discovery.request_bytes", side_effect=crossref_request):
            self.assertEqual(len(self.collect()), 1)

    def test_later_page_can_match_after_irrelevant_first_page(self):
        info = {}
        cursor = "page+/=2"
        payloads = [self.response(["Unrelated clinical trial"], 2, cursor), self.response(["Molecular representation"], 2)]
        with patch("scripts.collect_discovery.request_bytes", side_effect=payloads) as request, patch("scripts.collect_discovery.time.sleep"):
            items = self.collect({**self.source, "rows": 1}, info)
        self.assertEqual(len(items), 1)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(parse_qs(urlparse(request.call_args_list[1].args[0]).query)["cursor"], [cursor])
        self.assertEqual(info["coverage"]["items_fetched"], 2)
        self.assertTrue(info["coverage"]["complete"])

    def test_page_cap_warns_even_when_no_relevant_items(self):
        info = {}
        payloads = [self.response(["Unrelated clinical trial"], 8, "page-2"), self.response(["Unrelated trial followup"], 8, "page-3")]
        with patch("scripts.collect_discovery.request_bytes", side_effect=payloads), patch("scripts.collect_discovery.time.sleep"):
            items = self.collect({**self.source, "max_results": 1, "max_pages": 2}, info)
        self.assertEqual(items, [])
        self.assertEqual(info["coverage"]["stop_reason"], "max_pages_reached")
        self.assertFalse(info["coverage"]["complete"])
        self.assertEqual(info["coverage"]["pages_fetched"], 2)
        self.assertIn("截断", info["coverage_warning"])
        self.assertIn("2/8", info["coverage_warning"])
        self.assertIn("零条相关结果", info["coverage_warning"])

    def test_empty_journal_is_complete_without_warning(self):
        info = {}
        with patch("scripts.collect_discovery.request_bytes", return_value=self.response([], 0)) as request:
            self.assertEqual(self.collect(run_info=info), [])
        self.assertEqual(request.call_count, 1)
        self.assertTrue(info["coverage"]["complete"])
        self.assertEqual(info["coverage"]["total_results"], 0)
        self.assertNotIn("coverage_warning", info)

    def test_cursor_termination_does_not_claim_complete_before_total(self):
        cases = [
            (self.response(["Unrelated trial"], 5), "missing_cursor_before_total"),
            (self.response(["Unrelated trial"], 5, "*"), "repeated_cursor_before_total"),
            (self.response([], 5, "page-2"), "empty_page_before_total"),
        ]
        for payload, reason in cases:
            with self.subTest(reason=reason):
                info = {}
                with patch("scripts.collect_discovery.request_bytes", return_value=payload) as request:
                    self.assertEqual(self.collect(run_info=info), [])
                self.assertEqual(request.call_count, 1)
                self.assertFalse(info["coverage"]["complete"])
                self.assertEqual(info["coverage"]["stop_reason"], reason)
                self.assertIn("不能视为完整扫描", info["coverage_warning"])

    def test_wrong_journal_responses_fail_instead_of_empty_success(self):
        bad_responses = [
            {"status": "failed"},
            {"status": "ok", "message": {"items": []}},
            {"status": "ok", "message": {"items": None, "total-results": 0}},
            {"status": "ok", "message": {"items": [], "total-results": "0"}},
            {"status": "ok", "message": {"items": [], "total-results": False}},
            {"status": "ok", "message": {"items": [None], "total-results": 1}},
        ]
        for response in bad_responses:
            with self.subTest(response=response):
                with patch("scripts.collect_discovery.request_bytes", return_value=json.dumps(response)):
                    with self.assertRaises(ValueError):
                        self.collect()
        with patch("scripts.collect_discovery.request_bytes", side_effect=TimeoutError("source timeout")):
            with self.assertRaises(TimeoutError):
                self.collect()

    def test_journal_source_rejects_global_crossref_endpoint(self):
        with patch("scripts.collect_discovery.request_bytes") as request:
            with self.assertRaisesRegex(ValueError, "ISSN"):
                self.collect({**self.source, "url": "https://api.crossref.org/works"})
        request.assert_not_called()

    def test_main_records_truncated_no_results_and_window(self):
        source = {**self.source, "rows": 1, "max_pages": 1}
        with patch("scripts.collect_discovery.Path.read_text", return_value=json.dumps({**self.settings, "sources": [source]})), \
                patch("scripts.collect_discovery.FileLock", return_value=nullcontext()), \
                patch("scripts.collect_discovery.request_bytes", return_value=self.response(["Unrelated trial"], 8, "next")), \
                patch("src.discovery.upsert_items", return_value={"inserted": 0, "updated": 0}) as upsert, \
                patch("src.discovery.record_run") as record, redirect_stdout(StringIO()):
            result = main(["--config", "mock-journal-sources.json", "--as-of", "2026-11-06", "--days", "30", "--sources", "journal"])
        self.assertEqual(result, 0)
        self.assertEqual(upsert.call_args.args[0], [])
        run = record.call_args.args[0]
        self.assertEqual(run["status"], "no_results")
        self.assertEqual(run["window_start"], "2026-10-08")
        self.assertEqual(run["window_end"], "2026-11-06")
        self.assertFalse(run["coverage"]["complete"])
        self.assertIn("截断", run["coverage_warning"])


if __name__ == "__main__":
    unittest.main()
