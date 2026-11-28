import asyncio
from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src import ic_automatic, ic_editor, ic_primary_evidence


class PrimaryEvidenceTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        folder = TemporaryDirectory(dir=root)
        self.addCleanup(folder.cleanup)
        self.database = Path(folder.name) / 'test.sqlite'
        self.config = Path(folder.name) / 'sources.json'
        ic_editor.initialize(self.database)
        ic_automatic.initialize(self.database)

    def test_configured_index_and_exact_author_abstract(self):
        original = 'https://vendor.example/research/mext-dram-expansion'
        sitemap = 'https://vendor.example/articles.xml'
        requested_doi = 'https://api.crossref.org/works/10.1234/mext'
        self.config.write_text(json.dumps({'sources': [
            {'url': 'https://vendor.example/feed', 'name': 'Example Vendor', 'news_genre': '企业技术博客',
             'primary_evidence': {'sitemap': sitemap, 'mentions': 'mext',
                                  'article_prefixes': ['https://vendor.example/research/']}},
            {'url': 'https://disabled.example/', 'name': 'Disabled', 'enabled': False, 'news_genre': '企业官方公告'},
            {'url': 'https://api.crossref.org/journals/1234-5678/works', 'issn': '1234-5678',
             'name': 'Test journal', 'kind': 'crossref_journal', 'content_type': 'paper'},
        ]}), encoding='utf-8')
        record = {'title': ['A DRAM paper'], 'DOI': '10.1234/mext', 'ISSN': ['1234-5678'],
                  'published-online': {'date-parts': [[2026, 11, 21]]},
                  'abstract': '<p>Our abstract reports a performance comparison under a fixed workload.</p>'}
        article = {'id': 'news', 'title': 'MEXT DRAM expansion', 'url': 'https://news.example/story'}
        material = {'text': 'Read the paper at 10.1234/mext.', 'links': [
            'https://disabled.example/research/mext-dram-expansion',
            'https://vendor.example/unrelated/mext-dram-expansion',
            'https://outsider.example/research/mext-dram-expansion',
        ]}
        html = '<title>MEXT deployment</title><main><p>' + 'DRAM expansion using MEXT in production systems. ' * 4 + '</p></main>'
        html += '<meta property="article:published_time" content="2026-11-21">'
        pages = {sitemap: f'<urlset><url><loc>{original}</loc></url></urlset>', original: html,
                 requested_doi: json.dumps({'status': 'ok', 'message': record})}

        async def read(_session, url, *_limits):
            return pages[url]

        with patch.object(ic_primary_evidence, '_read', side_effect=read) as fetch:
            batch = [(article, material)]
            found = asyncio.run(ic_primary_evidence.lookup(batch, self.config, self.database, '2026-11-28'))
            self.assertEqual({call.args[1] for call in fetch.await_args_list}, set(pages))
            self.assertEqual([(item['url'], status) for item, status, _ in found['news']],
                             [('https://doi.org/10.1234/mext', 'abstract'), (original, 'original')])
            record['ISSN'] = ['0000-0000']
            pages[requested_doi] = json.dumps({'status': 'ok', 'message': record})
            found = asyncio.run(ic_primary_evidence.lookup(batch, self.config, self.database, '2026-11-28'))
            self.assertEqual([status for _, status, _ in found['news']], ['original'])

    def test_primary_assessment_requires_a_verbatim_quote_from_the_matched_source(self):
        quote = 'AMD IT deployed MEXT software on 86 hosts.'
        groups = {'article': {'vendor': {'text': quote}}}
        row = {'article_id': 'article', 'evidence': {'source_id': 'vendor', 'evidence': quote},
               'summary': '厂商披露内部部署。', 'stage': '内部部署', 'next_check': '跟踪外部测试。'}
        self.assertEqual(ic_automatic.verified_primary_source(row, groups)[2], quote)
        row['evidence']['evidence'] = 'AMD IT deployed MEXT software on 128 hosts.'
        self.assertIsNone(ic_automatic.verified_primary_source(row, groups))
