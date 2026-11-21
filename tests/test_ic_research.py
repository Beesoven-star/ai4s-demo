"""AI method versus AI workload, evidence precision, live filters and isolation."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from src.ic_research import analyze, exploration, matches, TOPICS
from src import discovery, library
from scripts.ic_preview_server import configure_environment


class ICResearchTests(unittest.TestCase):
    def paper(self,title,abstract='',**extra):
        return dict(title=title,abstract_text=abstract,content_type='paper',summary_kind='source',**extra)

    def test_llm_for_rtl_does_not_mean_accelerator_for_llm(self):
        result=analyze(self.paper('AutoC2V: Synthesis-Guided LLM Training for C++-to-Verilog Generation',
            'We train LLMs to generate hardware designs and use inference-time feedback.'))
        self.assertEqual(result['tracks'],['ai_for_ic'])
        self.assertIn('A1',result['topic_ids'])
        self.assertTrue(result['evidence'][0]['ai_signal'])

    def test_llm_serving_does_not_mean_llm_used_as_design_method(self):
        result=analyze(self.paper('HYDRA: A Chiplet Framework for Serving Dynamic LLM Workloads',
            'We present a design space exploration framework for LLM serving on chiplet systems.'))
        self.assertEqual(result['tracks'],['ic_for_ai'])
        self.assertIn('B3',result['topic_ids'])

    def test_same_paper_can_have_both_roles_with_evidence(self):
        result=analyze(self.paper('LLM-guided chiplet design space exploration for DNN accelerators'))
        self.assertEqual(set(result['tracks']),{'ai_for_ic','ic_for_ai'})
        self.assertIn('A5',result['topic_ids'])
        self.assertIn('B3',result['topic_ids'])

    def test_transformer_in_rf_circuit_is_not_language_model(self):
        result=analyze(self.paper('A CMOS Power Amplifier With Interleaved Transformer for Radar'))
        self.assertEqual(result['tracks'],[])

    def test_mentioning_ml_workloads_and_manufacturing_does_not_prove_ai_design(self):
        result=analyze(self.paper('Location-Aware Scheduling for GPUs',
            'To address machine learning (ML) applications, GPUs have transitioned to multi-chip architectures driven by manufacturing constraints.'))
        self.assertNotIn('ai_for_ic',result['tracks'])

    def test_unknown_is_not_declared_non_ai_and_title_evidence_is_preserved(self):
        unknown=analyze(self.paper('A CMOS readout circuit'))
        self.assertEqual(unknown['status'],'unconfirmed')
        known=analyze(self.paper('LLM-Based RTL Bug Localization'))
        self.assertEqual(known['basis'],'title_only')
        self.assertEqual(known['evidence'][0]['field'],'title')

    def test_generated_summary_not_used_as_original_evidence(self):
        result=analyze(dict(title='A readout circuit',content_type='paper',summary_kind='llm',
            abstract_text='LLM-based RTL generation using artificial intelligence.'))
        self.assertEqual(result['tracks'],[])

    def test_selected_background_not_counted_as_ai(self):
        paper=self.paper('Challenges in the verification of MOSAIX ASIC for ALICE ITS3')
        result=analyze(paper)
        self.assertEqual(result['tracks'],['general_ic'])
        self.assertEqual(matches(json.dumps(paper),'any_ai',''),0)
        self.assertEqual(matches(json.dumps(paper),'general_ic','C1'),1)

    def test_live_exploration_filtering_preserves_favorite(self):
        root=Path(__file__).resolve().parents[1]/'.runtime/test-tmp'
        root.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=root) as directory:
            db=Path(directory)/'ic.sqlite'
            first=self.paper('LLM-Based RTL Bug Localization',url='https://example.org/rtl')
            second=self.paper('A CNN Accelerator for In-Memory Computing',url='https://example.org/accelerator')
            discovery.upsert_items([first,second],db_path=db)
            selected=discovery.list_items(research_track='ai_for_ic',db_path=db)
            self.assertEqual(selected['total'],1)
            identity=selected['items'][0]['id']
            library.update_record(identity,{'is_favorite':True,'notes':'Keep'},db_path=db)
            with patch.dict(os.environ,{'DNEWS_RESEARCH_DOMAIN':'ic'}):
                self.assertEqual(discovery.get_item(identity,db_path=db)['library']['notes'],'Keep')
                self.assertIn('A1',discovery.get_item(identity,db_path=db)['ic_ai']['topic_ids'])
                self.assertEqual(discovery.list_items(topic=TOPICS[0]['name'],research_track='ic_for_ai',db_path=db)['total'],0)
                self.assertIn(TOPICS[0]['name'],discovery.get_facets(db)['topics'])
            self.assertEqual(exploration(db)['counts']['total'],2)
            third=self.paper('LLM-guided Analog Circuit Design',url='https://example.org/analog')
            discovery.upsert_items([third],db_path=db)
            self.assertEqual(exploration(db)['counts']['total'],3)
            self.assertEqual(exploration(db)['counts']['ai_for_ic'],0)
            self.assertEqual(exploration(db)['counts']['unconfirmed'],3)
            self.assertEqual(discovery.list_items(literature_scope='main',db_path=db)['total'],0)
            with self.assertRaises(ValueError):
                discovery.list_items(research_track='invalid',db_path=db)

    def test_ic_preview_isolates_archives_documents_config_and_database(self):
        root=Path(__file__).resolve().parents[1]/'.runtime/test-tmp'
        root.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(dir=root) as directory, patch.dict(os.environ,{},clear=False):
            location=Path(directory)
            configure_environment(location)
            self.assertEqual(Path(os.environ['DNEWS_DATA_DIR']),location/'news-data/ic-reports')
            self.assertEqual(Path(os.environ['DNEWS_WORK_DIR']),location/'ongoing_work_ic')
            self.assertEqual(Path(os.environ['DNEWS_DISCOVERY_DB']),location/'news-data/discovery-ic.sqlite')
            self.assertEqual(Path(os.environ['DNEWS_CONFIG']),location/'.runtime/ic-preview-config.json')
            self.assertEqual(list((location/'news-data/ic-reports').iterdir()),[])


if __name__=='__main__':
    unittest.main()
