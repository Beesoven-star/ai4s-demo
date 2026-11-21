import unittest

from src.ic_paper_notes import paper_reading_notes


class PaperReadingNotesTests(unittest.TestCase):
    def test_edited_notes_lead_with_the_result(self):
        notes = paper_reading_notes({
            'id': '31ec70f80d57605a3ff6fd94', 'content_type': 'paper', 'abstract_text': 'Available',
        })
        self.assertEqual(notes['basis'], 'abstract')
        self.assertEqual([point['label'] for point in notes['points']], ['主要发现', '研究问题', '怎么做', '适用范围'])
        self.assertIn('50.6%', notes['points'][0]['text'])

    def test_extracts_author_sentences_without_rewriting_them(self):
        method = 'We propose a configurable timing method for circuit design.'
        result = 'Evaluation results show an average latency reduction of 12%.'
        notes = paper_reading_notes({'content_type': 'paper', 'abstract_text': f'{method} {result}'})
        self.assertEqual(notes['basis'], 'abstract_excerpt')
        self.assertEqual([point['text'] for point in notes['points']], [result, method])

    def test_title_only_and_generated_summaries_do_not_get_author_result_labels(self):
        claimed_result = 'Evaluation results show an average latency reduction of 12%.'
        self.assertIsNone(paper_reading_notes({'content_type': 'paper', 'summary': claimed_result}))
        self.assertIsNone(paper_reading_notes({'content_type': 'paper', 'summary_kind': 'human', 'abstract_text': claimed_result}))
        self.assertIsNone(paper_reading_notes({'content_type': 'news', 'abstract_text': claimed_result}))

    def test_prefers_a_quantified_validation_result(self):
        measurement = 'Industrial validation demonstrates an average peak-current reduction of 50.57%.'
        abstract = f'{measurement} Results show the design is suitable for some practical applications.'
        notes = paper_reading_notes({'content_type': 'paper', 'abstract_text': abstract})
        self.assertEqual(notes['points'][0]['text'], measurement)
