"""Verify evidence selection, trustworthy citations and durable analysis jobs."""
import asyncio
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from src import analysis_connection as connection, discovery
from src.research_analysis import AnalysisService, Filters, export_markdown, news_analysis, select, validate_report, prompt_for
from src.analysis_evidence import CitationValidationError, evidence_catalog, original_quote, report_claims


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'.runtime'/'test-tmp'
        root.mkdir(parents=True,exist_ok=True)
        self.temp=TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.db=self.folder/'test.sqlite'
        self.env=patch.dict(os.environ,{'DNEWS_ANALYSIS_CONNECTION':str(self.folder/'connection.json'),
            'DNEWS_CONFIG':str(self.folder/'config.json'),'DEEPSEEK_API_KEY':''})
        self.env.start();self.addCleanup(self.env.stop)
        self.folder.joinpath('config.json').write_text('{"llm":{"model":"deepseek-flash"}}',encoding='utf-8')
        self.today=datetime.now(discovery.LOCAL_TZ).date()
        self.recent=(self.today-timedelta(days=2)).isoformat()
        self.old=(self.today-timedelta(days=150)).isoformat()
        collected=self.today.isoformat()+'T09:00:00+08:00'
        self.paper={'title':'Reinforcement learning for physical design placement optimization','content_type':'paper',
            'source':'Test Journal','url':'https://example.org/paper','doi':'10.1234/design','ingestion_scope':'archive',
            'published_at':self.recent,'collected_at':collected,'abstract_text':'We use reinforcement learning for placement optimization.',
            'summary_kind':'source','venue_type':'journal'}
        self.news={'title':'AI-driven chip placement optimization announced','content_type':'news','source':'Test News',
            'url':'https://example.org/news','published_at':self.recent,'collected_at':collected,
            'abstract_text':'AI-driven physical design placement optimization is announced.','summary_kind':'source'}
        self.hardware={**self.news,'url':'https://example.org/hardware','title':'New GPU chip for AI inference'}
        discovery.upsert_items([self.paper,self.news,self.hardware],db_path=self.db)
        self.filters=Filters(date_from=self.today-timedelta(days=29),date_to=self.today,literature_scope='all')

    def connect(self):
        return connection.save({'model':'deepseek-flash','base_url':'https://api.deepseek.com',
            'api_key':'unit-test-credential-not-a-secret'})

    def snapshot(self):
        return select(self.filters,self.db)

    def model_report(self,sources):
        source=sources[0]
        claim={'text':'A finding grounded in the selected material.', 'source_ids':[source['ref']],
               'evidence':[{'source_id':source['ref'],'quote':source['title'][:40]}]}
        return {'title':'Test research analysis','overview':claim,
            'trends':[{'title':'Research focus','observation':claim,'interpretation':claim}],
            'connections':[], 'research_question':{'question':claim,'motivation':claim,
                'approach':['Compare a controlled baseline.'],'validation':['Measure quality and time.']},
            'limitations':['Only selected metadata and abstracts were available.']}

    def test_track_filter_applies_to_papers_and_news(self):
        filters=self.filters.model_copy(update={'research_track':'ai_for_ic'})
        data=select(filters,self.db)
        self.assertEqual(data['counts'],{'paper':1,'news':1})
        self.assertFalse(any(s['title']==self.hardware['title'] for s in data['sources']))
        self.assertNotIn('library',data['sources'][0])

    def test_chinese_and_general_design_news_get_conservative_track_labels(self):
        self.assertEqual(news_analysis({**self.news,'title':'AI驱动芯片设计新进展','abstract_text':'','summary':''})['tracks'],['ai_for_ic'])
        self.assertEqual(news_analysis({**self.news,'title':'国产AI芯片用于大模型推理','abstract_text':'','summary':''})['tracks'],['ic_for_ai'])
        self.assertEqual(news_analysis({**self.news,'title':'AI assistance for chip design','abstract_text':'','summary':''})['topic_ids'],[])

    def test_ai_memory_product_strategy_is_not_ai_assisted_chip_design(self):
        for title,brief in [
            ('AI数据中心存储产品的新进展','公司介绍面向AI数据中心的RDIMM，存储竞争转向全场景布局。'),
            ('新型存储芯片用于AI推理','面向高端AI推理市场，公司拥有器件、工艺与芯片设计技术。')]:
            result=news_analysis({**self.news,'title':title,'abstract_text':brief})
            self.assertNotIn('ai_for_ic',result['tracks'])
            self.assertIn('ic_for_ai',result['tracks'])

    def test_publication_date_excludes_historical_backfill_and_month_only(self):
        discovery.upsert_items([{**self.paper,'url':'https://example.org/old','doi':'10.1234/old','published_at':self.old},
            {**self.paper,'url':'https://example.org/month','doi':'10.1234/month','published_at':None,
             'publication_month':self.today.strftime('%Y-%m')}],db_path=self.db)
        snapshot=self.snapshot()
        self.assertEqual(snapshot['total'],3)
        self.assertEqual(snapshot['excluded']['incomplete_publication_date'],1)
        collected=select(self.filters.model_copy(update={'date_basis':'collected'}),self.db)
        self.assertEqual(collected['total'],5)
        self.assertIn(self.old,[s['published_at'] for s in collected['sources']])

    def test_citations_must_exist_and_quotes_match_snapshotted_source(self):
        sources=self.snapshot()['sources']
        good=self.model_report(sources)
        self.assertEqual(validate_report(json.dumps(good),sources)['title'],good['title'])
        good['overview']['source_ids']=['S999']
        diagnostics={}
        fixed=validate_report(json.dumps(good),sources,diagnostics=diagnostics)
        self.assertEqual(fixed['overview']['source_ids'],[good['overview']['evidence'][0]['source_id']])
        self.assertTrue(diagnostics['citation_repairs'])
        bad=self.model_report(sources)
        bad['overview']['evidence'][0]['quote']='Invented performance metric: 99.999x faster'
        with self.assertRaises(ValueError):validate_report(json.dumps(bad),sources)

    def test_evidence_ids_fill_exact_original_quotes_and_correct_reference_lists(self):
        sources=self.snapshot()['sources']
        catalog=evidence_catalog(sources)
        ident,entry=next(iter(catalog.items()))
        report=self.model_report(sources)
        for _,claim in report_claims(report):
            claim['source_ids']=['S999']
            claim['evidence']=[{'evidence_id':ident}]
        diagnostics={}
        fixed=validate_report(json.dumps(report),sources,diagnostics=diagnostics)
        for _,claim in report_claims(fixed):
            self.assertEqual(claim['source_ids'],[entry['source_id']])
            self.assertEqual(claim['evidence'][0]['quote'],entry['quote'])
        self.assertTrue(diagnostics['citation_repairs'])

    def test_catalog_spans_remain_contiguous_with_long_unicode_abstracts(self):
        sources=[{'ref':'S037','title':'AI芯片设计基础','excerpt':('This is a semiconductor statement with 3.25% accuracy. '*40)+'末尾原文。'}]
        catalog=evidence_catalog(sources)
        self.assertGreater(len(catalog),2)
        for entry in catalog.values():
            self.assertLessEqual(len(entry['quote']),300)
            self.assertTrue(any(entry['quote'] in sources[0][field] for field in ('title','excerpt')))
        self.assertTrue(any('末尾原文' in e['quote'] for e in catalog.values()))
        prompt=prompt_for({'filters':{},'total':1},sources)
        self.assertIn('S037-E01',prompt)
        self.assertIn('禁止重新编号',prompt)

    def test_typographic_drift_restores_source_quote_but_changed_results_fail(self):
        source={'title':'A “neural” model — 3.25% improvement','excerpt':'Reliability improves by 2.5 times.'}
        self.assertEqual(original_quote('A "neural" model - 3.25% improvement',source),source['title'])
        self.assertIsNone(original_quote('Reliability improves by 25 times.',source))
        self.assertIsNone(original_quote('可靠性提高2.5倍',source))
        self.assertIsNone(original_quote('Reliability ... 2.5 times.',source))

    def test_wrong_legacy_source_number_requires_a_unique_actual_quote(self):
        sources=self.snapshot()['sources']
        report=self.model_report(sources)
        evidence=report['overview']['evidence'][0]
        evidence['source_id']='S999'
        fixed=validate_report(json.dumps(report),sources)
        self.assertEqual(fixed['overview']['evidence'][0]['source_id'],sources[0]['ref'])
        sources[1]['excerpt']=evidence['quote']
        with self.assertRaises(CitationValidationError):validate_report(json.dumps(report),sources)

    def test_unknown_evidence_id_is_not_replaced_with_a_random_title(self):
        sources=self.snapshot()['sources']
        report=self.model_report(sources)
        report['overview']['evidence'][0]['evidence_id']='S999-T'
        with self.assertRaises(CitationValidationError) as caught:
            validate_report(json.dumps(report),sources)
        self.assertEqual(caught.exception.issues[0]['path'],'overview.evidence[0]')
        self.assertEqual(caught.exception.issues[0]['evidence_id'],'S999-T')
        self.assertTrue(caught.exception.draft['overview']['text'])

    def test_failed_citations_keep_draft_and_precise_issues_without_extra_model_call(self):
        self.connect()
        snapshot=self.snapshot()
        report=self.model_report(snapshot['sources'])
        report['overview']['evidence'][0]['quote']='An invented performance of 999x'
        service=AnalysisService(self.db)
        complete=AsyncMock(return_value=json.dumps(report))
        async def exercise():
            with patch('src.analysis_connection.complete',new=complete):
                run=await service.start(self.filters,snapshot['fingerprint'],[s['id'] for s in snapshot['sources']])
                await service.task
                return service.get(run['id'])
        saved=asyncio.run(exercise())
        self.assertEqual(complete.await_count,1)
        self.assertEqual(saved['status'],'failed')
        self.assertIsNone(saved['report'])
        self.assertEqual(saved['error_code'],'citation_validation')
        self.assertEqual(saved['draft_report']['title'],report['title'])
        self.assertEqual(saved['citation_issues'][0]['path'],'overview.evidence[0]')
        self.assertEqual(saved['citation_issues'][0]['quote'],'An invented performance of 999x')
        self.assertNotIn('draft_report',service.history()[0])
        self.assertNotIn('citation_issues',service.history()[0])

    def test_credentials_are_redacted_and_not_reused_across_hosts(self):
        state=self.connect()
        self.assertTrue(state['key_configured'])
        self.assertNotIn('api_key',state)
        self.assertNotIn('unit-test',json.dumps(state))
        with self.assertRaises(ValueError):connection.save({'model':'another','base_url':'https://other.example/v1','api_key':''})
        connection.save({'model':'deepseek-flash','base_url':'https://api.deepseek.com','api_key':''})
        self.assertTrue(connection.status()['key_configured'])
        self.assertEqual(json.loads(self.folder.joinpath('config.json').read_text())['llm']['model'],'deepseek-flash')

    def test_cannot_silently_use_openai_key_for_deepseek(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'unit-test-openai-not-a-secret'}):
            self.assertFalse(connection.status()['key_configured'])

    def test_snapshot_changes_are_rejected_and_duplicate_selection_is_rejected(self):
        self.connect()
        snapshot=self.snapshot()
        service=AnalysisService(self.db)
        ids=[s['id'] for s in snapshot['sources']]
        with self.assertRaises(ValueError):asyncio.run(service.start(self.filters,snapshot['fingerprint'],[ids[0],ids[0]]))
        discovery.upsert_items([{**self.news,'url':'https://example.org/new'}],db_path=self.db)
        with self.assertRaises(ValueError):asyncio.run(service.start(self.filters,snapshot['fingerprint'],ids))

    def test_report_saved_with_original_material_and_exported_citations(self):
        self.connect()
        snapshot=self.snapshot()
        service=AnalysisService(self.db)
        async def exercise():
            with patch('src.analysis_connection.complete',new=AsyncMock(return_value=json.dumps(self.model_report(snapshot['sources'])))):
                run=await service.start(self.filters,snapshot['fingerprint'],[s['id'] for s in snapshot['sources']])
                await service.task
                return run['id']
        ident=asyncio.run(exercise())
        saved=AnalysisService(self.db).get(ident)
        self.assertEqual(saved['status'],'success')
        self.assertEqual(saved['sources'],snapshot['sources'])
        self.assertNotIn('unit-test-credential',json.dumps(saved))
        exported=export_markdown(saved)
        self.assertIn('https://example.org/',exported)
        self.assertIn('](#s00',exported)
        self.assertEqual(len(service.history()),1)

    def test_immediate_shutdown_leaves_failed_run_instead_of_stuck_running(self):
        self.connect()
        snapshot=self.snapshot()
        service=AnalysisService(self.db)
        async def exercise():
            run=await service.start(self.filters,snapshot['fingerprint'],[s['id'] for s in snapshot['sources']])
            await service.stop()
            return service.get(run['id'])
        saved=asyncio.run(exercise())
        self.assertEqual(saved['status'],'failed')
        self.assertTrue(saved['finished_at'])

    def test_invalid_model_evidence_fails_without_displaying_a_report(self):
        self.connect()
        snapshot=self.snapshot()
        report=self.model_report(snapshot['sources'])
        report['overview']['evidence'][0]['quote']='Not in the sources at all'
        service=AnalysisService(self.db)
        async def exercise():
            with patch('src.analysis_connection.complete',new=AsyncMock(return_value=json.dumps(report))):
                run=await service.start(self.filters,snapshot['fingerprint'],[s['id'] for s in snapshot['sources']])
                await service.task
                return service.get(run['id'])
        saved=asyncio.run(exercise())
        self.assertEqual(saved['status'],'failed')
        self.assertIsNone(saved['report'])

    def test_api_rejects_invalid_connection_without_echoing_key(self):
        from src.web.app import create_app
        async def request(method,path,body=None):
            app=create_app()
            app.state.research_analysis=AnalysisService(self.db)
            messages=[]
            async def receive():
                return {'type':'http.request','body':json.dumps(body or {}).encode(),'more_body':False}
            async def send(message):messages.append(message)
            with patch.dict(os.environ,{'DNEWS_DISCOVERY_DB':str(self.db)}):
                await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,
                    'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'','root_path':'',
                    'headers':[(b'content-type',b'application/json')],'client':('127.0.0.1',1),'server':('test',80)},receive,send)
            status=next(m['status'] for m in messages if m['type']=='http.response.start')
            content=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body').decode()
            return status,json.loads(content)
        status,result=asyncio.run(request('PUT','/api/analysis/connection',{
            'model':'deepseek-flash','base_url':'http://unsafe.example','api_key':'do-not-echo-this-secret'}))
        self.assertEqual(status,422)
        self.assertNotIn('do-not-echo',json.dumps(result))
        status,result=asyncio.run(request('POST','/api/analysis/preview',self.filters.model_dump(mode='json')))
        self.assertEqual(status,200)
        self.assertEqual(result['total'],3)
        status,result=asyncio.run(request('GET','/api/analysis/connection'))
        self.assertEqual(status,200)
        self.assertNotIn('api_key',result)

    def test_model_transport_handles_chunked_json_and_hides_error_body(self):
        class Content:
            async def iter_chunked(self,size):
                raw=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'OK'}}]}).encode()
                for i in range(0,len(raw),5):yield raw[i:i+5]
        class Response:
            status=200
            content=Content()
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        response=Response()
        captured={}
        class Session:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            def post(self,url,**kwargs):
                captured.update(url=url,**kwargs)
                return response
        self.connect()
        with patch('src.analysis_connection.aiohttp.ClientSession',return_value=Session()):
            self.assertEqual(asyncio.run(connection.complete('test',check=True)),'OK')
            self.assertEqual(captured['url'],'https://api.deepseek.com/chat/completions')
            self.assertFalse(captured['allow_redirects'])
            self.assertEqual(captured['json']['thinking'],{'type':'disabled'})
            self.assertEqual(captured['json']['max_tokens'],128)
            self.assertEqual(asyncio.run(connection.complete('test')),'OK')
            self.assertEqual(captured['json']['thinking'],{'type':'enabled'})
            self.assertEqual(captured['json']['reasoning_effort'],'low')
            self.assertEqual(captured['json']['max_tokens'],32768)
            response.status=401
            with self.assertRaisesRegex(ValueError,'密钥未通过验证'):
                asyncio.run(connection.complete('test',check=True))

    def test_vendor_specific_controls_do_not_leak_to_other_model_services(self):
        policy=connection.generation_policy({'base_url':'https://other.example/v1','model':'custom'})
        self.assertNotIn('thinking',policy)
        self.assertNotIn('reasoning_effort',policy)

    def test_truncation_retains_usage_and_retry_uses_exact_original_sources(self):
        self.connect()
        snapshot=self.snapshot()
        service=AnalysisService(self.db)
        stats={'prompt_tokens':1000,'completion_tokens':10000,'total_tokens':11000,'reasoning_tokens':9900}
        exception=connection.OutputTruncatedError(usage=stats,elapsed_seconds=50,policy={})
        async def exercise():
            with patch('src.analysis_connection.complete',new=AsyncMock(side_effect=exception)):
                old=await service.start(self.filters,snapshot['fingerprint'],[s['id'] for s in snapshot['sources']])
                await service.task
            failed=service.get(old['id'])
            self.assertEqual(failed['error_code'],'output_truncated')
            self.assertEqual(failed['usage'],stats)
            discovery.upsert_items([{**self.news,'url':'https://example.org/new-since-failure'}],db_path=self.db)
            text=connection.CompletionText(json.dumps(self.model_report(snapshot['sources'])),
                usage={'prompt_tokens':1000,'completion_tokens':2000,'total_tokens':3000},
                elapsed_seconds=12,policy={})
            with patch('src.analysis_connection.complete',new=AsyncMock(return_value=text)):
                retried=await service.retry(old['id'])
                await service.task
            return failed,service.get(retried['id'])
        failed,retried=asyncio.run(exercise())
        self.assertEqual(retried['status'],'success')
        self.assertEqual(retried['sources'],failed['sources'])
        self.assertEqual(retried['source_count'],3)
        self.assertEqual(retried['retry_of'],failed['id'])
        self.assertEqual(retried['usage']['total_tokens'],3000)
        self.assertEqual(retried['elapsed_seconds'],12)
        self.assertEqual(service.get(failed['id'])['status'],'failed')


if __name__=='__main__':unittest.main()
