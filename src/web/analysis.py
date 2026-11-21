"""Evidence preview, model connection, and asynchronous analysis API."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from src import analysis_connection
from src.research_analysis import Filters, MAX_SOURCES, select, export_markdown

router=APIRouter(prefix='/api/analysis',tags=['research analysis'])


@router.get('/options')
async def options():
    from src.ic_research import TOPICS
    from src.discovery import _now
    return {'topics':TOPICS,'max_sources':MAX_SOURCES,'today':_now()[:10]}


@router.get('/connection')
async def connection():
    return analysis_connection.status()


@router.put('/connection')
async def save_connection(request:Request):
    try:
        value=await request.json()
        return analysis_connection.save(value)
    except (ValueError,TypeError):
        # Do not allow validation errors to echo credentials from the request.
        raise HTTPException(422,'连接设置无效；请检查模型名、HTTPS 服务地址和密钥。更换服务地址需要重新填写密钥。')


@router.post('/connection/test')
async def test_connection():
    try:
        await analysis_connection.complete('Reply with OK only.',check=True)
        return {'ok':True,'message':'模型连接成功'}
    except ValueError as error:
        raise HTTPException(400,str(error))


@router.post('/preview')
async def preview(filters:Filters):
    return select(filters)


class Start(BaseModel):
    model_config=ConfigDict(extra='forbid')
    filters:Filters
    fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')
    item_ids:list[str]=Field(min_length=2,max_length=MAX_SOURCES)


@router.post('/runs',status_code=202)
async def start(body:Start,request:Request):
    try:
        return await request.app.state.research_analysis.start(body.filters,body.fingerprint,body.item_ids)
    except ValueError as error:
        raise HTTPException(422,str(error))
    except RuntimeError as error:
        raise HTTPException(409,str(error))


@router.get('/runs')
async def history(request:Request):
    return request.app.state.research_analysis.history()


@router.post('/runs/{run_id}/retry',status_code=202)
async def retry_run(run_id:str,request:Request):
    try:
        return await request.app.state.research_analysis.retry(run_id)
    except KeyError:
        raise HTTPException(404,'分析记录不存在')
    except ValueError as error:
        raise HTTPException(422,str(error))
    except RuntimeError as error:
        raise HTTPException(409,str(error))


@router.get('/runs/{run_id}')
async def get_run(run_id:str,request:Request):
    result=request.app.state.research_analysis.get(run_id)
    if not result:
        raise HTTPException(404,'分析记录不存在')
    return result


@router.get('/runs/{run_id}/export')
async def export(run_id:str,request:Request):
    run=await get_run(run_id,request)
    if run['status']!='success':
        raise HTTPException(409,'分析完成后可导出')
    return Response(export_markdown(run),media_type='text/markdown; charset=utf-8',
        headers={'Content-Disposition':f'attachment; filename="research-analysis-{run_id}.md"'})
