"""Regressions for metadata-role errors found in the active archive review."""
import unittest

from src.ic_research import analyze, curated_reviews


class ArchiveReviewTests(unittest.TestCase):
    def analysis(self, identity):
        review = curated_reviews()[identity]
        return analyze({'id': identity, 'title': review['title'], 'content_type': 'paper'})

    def test_wafer_scale_llm_architecture_is_not_wafer_manufacturing(self):
        result = self.analysis('f857855f5ba68f63626d51a0')
        self.assertEqual(result['scope'], 'main')
        self.assertEqual(result['topic_ids'], ['B1'])

    def test_dnn_workload_is_distinct_from_a_design_learning_method(self):
        scion = self.analysis('4b5b83c662d9023e327fa50e')
        self.assertEqual(scion['tracks'], ['ic_for_ai'])
        rethermal = self.analysis('aeb4a27457c3fdb0ae2e239a')
        self.assertEqual(set(rethermal['tracks']), {'ai_for_ic', 'ic_for_ai'})

    def test_missing_abstract_does_not_hide_title_level_evidence_limit(self):
        result = self.analysis('9abe918c992bafeee7ef19cd')
        self.assertEqual(result['scope'], 'main')
        self.assertEqual(result['basis'], 'title_only')

    def test_ai_chip_used_for_encryption_stays_application_background(self):
        result = self.analysis('d6defd2f527d7d3e08d7bbd8')
        self.assertEqual(result['scope'], 'archive')
        self.assertEqual(result['topic_ids'], [])
        self.assertIn('密码学', result['note'])

    def test_session_overview_can_be_classified_without_becoming_main_paper(self):
        result = self.analysis('8b89d05978b9484cf71d7309')
        self.assertEqual(result['scope'], 'archive')
        self.assertEqual(result['topic_ids'], ['A6'])

    def test_reexamined_old_archived_hardware_paper_is_promoted(self):
        result = self.analysis('49bc33acd0eca8941469b709')
        self.assertEqual(result['scope'], 'main')
        self.assertEqual(result['topic_ids'], ['B1'])

    def test_review_cohort_has_explicit_reasons_and_no_pending_decisions(self):
        cohort = [r for r in curated_reviews().values() if r.get('review_batch') == 'active-archive-20261114']
        self.assertEqual(len(cohort), 243)
        self.assertEqual(sum(r['decision'] == 'ai_focus' for r in cohort), 44)
        for review in cohort:
            self.assertNotIn(review['decision'], ('needs_review', 'excluded'))
            self.assertTrue(review['reason'])
            self.assertTrue(review['research_area'])
            self.assertTrue(review['limitation'])


if __name__ == '__main__':
    unittest.main()
