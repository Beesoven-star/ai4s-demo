from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.abstract_text import clean_abstract, clean_stored_abstract
from src import discovery
from scripts.repair_discovery_abstracts import repair_abstracts


class AbstractTextTests(unittest.TestCase):
    def test_publisher_heading_is_removed_without_gluing_body(self):
        self.assertEqual(clean_abstract('<h2>Abstract</h2><p>Causal structure inference.</p><p>A second paragraph.</p>'), 'Causal structure inference. A second paragraph.')
        self.assertEqual(clean_abstract('<div><span class="abstract-title">Abstract</span>RNA interactions.</div>'), 'RNA interactions.')

    def test_namespaced_jats_keeps_structured_abstract_headings(self):
        value = '<jats:abstract><jats:title>Abstract</jats:title><jats:sec><jats:title>Background</jats:title><jats:p>Molecular prediction.</jats:p></jats:sec><jats:sec><jats:title>Methods</jats:title><jats:p>A graph model.</jats:p></jats:sec></jats:abstract>'
        self.assertEqual(clean_abstract(value), 'Background Molecular prediction. Methods A graph model.')

    def test_normal_abstract_words_are_not_removed(self):
        for value in ['Abstract representations improve generalization.', 'Abstraction is useful.', 'We study abstract representations.', 'An abstract model for molecules.']:
            self.assertEqual(clean_abstract(value), value)
            self.assertEqual(clean_stored_abstract(value), value)

    def test_inline_markup_does_not_split_words(self):
        self.assertEqual(clean_abstract('<p>Multi<em>view</em> learning with H<sub>2</sub>O.</p>'), 'Multiview learning with H2O.')

    def test_body_after_a_real_heading_can_legitimately_start_with_abstract(self):
        self.assertEqual(clean_abstract('<h2>Abstract</h2><p>Abstract Syntax Trees encode structures.</p>'), 'Abstract Syntax Trees encode structures.')

    def test_math_and_entities_survive(self):
        self.assertEqual(clean_abstract('We use x < y and p &lt; 0.05, with A &amp; B.'), 'We use x < y and p < 0.05, with A & B.')

    def test_escaped_html_and_hidden_scripts(self):
        self.assertEqual(clean_abstract('&lt;h3&gt;ABSTRACT&lt;/h3&gt;&lt;p&gt;RNA model.&lt;/p&gt;'), 'RNA model.')
        self.assertEqual(clean_abstract('<h3>Abstract</h3><script>ignore()</script><p>Body.</p>'), 'Body.')

    def test_existing_flattened_prefixes_are_repaired_idempotently(self):
        for value, expected in [('AbstractCausal structure.', 'Causal structure.'), ('AbstractRNA is studied.', 'RNA is studied.'), ('Abstract We predict molecules.', 'We predict molecules.'), ('ABSTRACT The model.', 'The model.'), ('abstract: A model.', 'A model.'), ('Abstract π-Stacked radicals.', 'π-Stacked radicals.')]:
            with self.subTest(value=value):
                self.assertEqual(clean_stored_abstract(value), expected)
                self.assertEqual(clean_stored_abstract(expected), expected)


class ExistingAbstractRepairTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.runtime' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'repair.sqlite'
        self.source = {
            'content_type': 'paper', 'title': 'Molecular prediction', 'source': 'Journal feed',
            'url': 'https://example.org/paper', 'doi': '10.1234/source',
            'abstract_text': 'AbstractCausal ' + 'molecular prediction. ' * 90,
            'summary_kind': 'source', 'published_at': '2026-11-05',
            'collected_at': '2026-11-06T12:00:00+08:00',
        }
        self.source['summary'] = self.source['abstract_text'][:1200]

    def test_dry_run_then_repair_preserves_provenance_identity_and_dates(self):
        discovery.upsert_items([self.source], origin='collected', db_path=self.db)
        before = discovery.list_items(db_path=self.db)['items'][0]
        self.assertEqual(repair_abstracts(self.db)['would_update'], 1)
        self.assertEqual(discovery.get_item(before['id'], self.db), before)
        self.assertEqual(repair_abstracts(self.db, apply=True)['updated'], 1)
        after = discovery.get_item(before['id'], self.db)
        self.assertTrue(after['abstract_text'].startswith('Causal '))
        self.assertEqual(after['summary'], after['abstract_text'][:1200])
        for field in ('id', 'url', 'doi', 'published_at', 'collected_at', 'created_at', 'source_records'):
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(repair_abstracts(self.db, apply=True)['updated'], 0)
        self.assertEqual(discovery.upsert_items([self.source], origin='collected', db_path=self.db)['inserted'], 0)
        self.assertEqual(discovery.get_item(before['id'], self.db)['abstract_text'], after['abstract_text'])

    def test_human_summary_and_normal_abstract_prose_are_preserved(self):
        human = deepcopy(self.source)
        human.update(doi='10.1234/human', url='https://example.org/human', summary_kind='human', summary='人工整理的研究简述。')
        normal = deepcopy(self.source)
        normal.update(doi='10.1234/normal', url='https://example.org/normal', abstract_text='Abstract representations improve prediction.', summary='Abstract representations improve prediction.')
        discovery.upsert_items([human, normal], db_path=self.db)
        self.assertEqual(repair_abstracts(self.db, apply=True)['updated'], 1)
        records = discovery.list_items(db_path=self.db)['items']
        self.assertEqual(next(i for i in records if i['doi'].endswith('/human'))['summary'], human['summary'])
        self.assertEqual(next(i for i in records if i['doi'].endswith('/normal'))['abstract_text'], normal['abstract_text'])
