"""Discovery queries and explicit public-source collection controls."""

from datetime import date
import os
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src import discovery as store
from src import library
from src.discovery_collection import CollectionBusyError


router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.get('/ic-briefing')
async def ic_briefing(days: int = Query(30), snapshot: bool = False):
    import os
    if os.environ.get('DNEWS_RESEARCH_DOMAIN') != 'ic':
        raise HTTPException(status_code=404, detail='当前不是集成电路工作台')
    if days not in (7, 30):
        raise HTTPException(status_code=422, detail='统计窗口必须为7天或30天')
    from src.ic_briefing import briefing
    from src.ic_hotspots import rolling_briefing
    from src.ic_topics import display_catalog
    from src.ic_topic_evaluation import with_ranked_evaluations
    edition = briefing(days) if snapshot else await run_in_threadpool(rolling_briefing, days)
    return {**with_ranked_evaluations(edition), 'topic_catalog': display_catalog()}


@router.get('/ic-observations')
async def ic_observations(day: date | None = None, version: str | None = None):
    if os.environ.get('DNEWS_RESEARCH_DOMAIN') != 'ic':
        raise HTTPException(status_code=404, detail='当前不是集成电路工作台')
    from src.ic_observations import daily_observations
    from src.ic_editor import daily_with_editions, publications
    return daily_with_editions(daily_observations(day.isoformat() if day else None), publications('daily'), version)


@router.get('/ic-exploration')
async def ic_exploration():
    import os
    if os.environ.get('DNEWS_RESEARCH_DOMAIN') != 'ic':
        raise HTTPException(status_code=404, detail='当前不是集成电路工作台')
    from src.ic_research import exploration
    return exploration()


class PersonalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    is_favorite: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=20000)
    reading_status: Optional[Literal['unread', 'reading', 'read', 'follow_up']] = None
    personal_tags: Optional[list[str]] = Field(None, max_length=20)


@router.patch('/items/{item_id}/library')
async def update_personal_record(item_id: str, body: PersonalUpdate):
    try:
        return library.update_record(item_id, body.model_dump(exclude_unset=True))
    except KeyError:
        raise HTTPException(status_code=404, detail='资料条目不存在')
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.get('/library')
async def personal_library(q: str = Query('', max_length=500),
                           reading_status: Optional[Literal['unread','reading','read','follow_up']] = None,
                           topic: Optional[str] = Query(None, max_length=100),
                           personal_tag: Optional[str] = Query(None, max_length=50),
                           content_type: Optional[Literal['paper','news']] = None,
                           limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return library.list_saved(q=q, reading_status=reading_status, topic=topic,
                              personal_tag=personal_tag, content_type=content_type, limit=limit, offset=offset)


class CollectionWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_from: date
    date_to: date


class CollectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    lookback_days: int = Field(ge=1, le=30, strict=True)


@router.get("/collection")
async def collection_status(request: Request):
    return request.app.state.discovery_collection.status()


@router.post("/collection", status_code=202)
async def start_collection(body: CollectionWindow, request: Request):
    service = request.app.state.discovery_collection
    try:
        await service.trigger(body.date_from, body.date_to)
        return service.status()
    except CollectionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/collection/settings")
async def collection_settings(body: CollectionSettings, request: Request):
    service = request.app.state.discovery_collection
    try:
        service.save_settings(body.model_dump())
        return service.status()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/items")
async def discovery_items(
    q: str = Query("", max_length=500),
    content_type: Optional[Literal["paper", "news"]] = Query(None),
    topic: Optional[str] = Query(None, max_length=100),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    date_basis: Literal["published", "collected"] = Query("published"),
    origin: Optional[Literal["seed", "collected"]] = Query(None),
    venue: Optional[str] = Query(None, max_length=200),
    publication_kind: Optional[Literal['journal','conference','preprint']] = Query(None),
    research_track: Optional[Literal['any_ai','ai_for_ic','ic_for_ai','general_ic','unconfirmed']] = Query(None),
    literature_scope: Optional[Literal['main','all','archive','pending','excluded']] = Query(None),
    news_scope: Optional[Literal['main','all','archive']] = Query(None),
    publication_period: Optional[Literal['recent_published','recent_preprint','historical','month_only','unknown','future']] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        return store.list_items(
            q=q, content_type=content_type, topic=topic, date_from=date_from,
            date_to=date_to, date_basis=date_basis, origin=origin,
            limit=limit, offset=offset, venue=venue, publication_kind=publication_kind, research_track=research_track,
            literature_scope=literature_scope, publication_period=publication_period, news_scope=news_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/items/{item_id}")
async def discovery_item(item_id: str):
    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="资料条目不存在")
    if os.environ.get('DNEWS_RESEARCH_DOMAIN') == 'ic':
        from src.ic_observations import classify_for_observation
        from src.ic_topics import discovery_catalog
        from src.ic_paper_analysis import read_notes
        from src.ic_paper_notes import paper_reading_notes
        item['observation_classification'] = classify_for_observation(item, catalog=discovery_catalog())
        if item['content_type'] == 'paper':
            if reading_notes := read_notes(item_id) or paper_reading_notes(item):
                item['reading_notes'] = reading_notes
    if item['content_type'] == 'news' and os.environ.get('DNEWS_RESEARCH_DOMAIN') == 'ic':
        from src.ic_briefing import event_briefs_for_source
        from src.ic_editor import published_source_check
        from src.ic_news_analysis import read_notes
        if not (item.get('reading_notes') or {}).get('points') and (notes := read_notes(item_id)):
            item['reading_notes'] = notes
        if event_briefs := event_briefs_for_source(item_id):
            item['event_briefs'] = event_briefs
        if source_check := published_source_check(item_id):
            item['published_source_check'] = source_check
    return item


@router.get("/facets")
async def discovery_facets():
    return store.get_facets()


@router.get("/runs")
async def discovery_runs(limit: int = Query(10, ge=1, le=100)):
    return store.list_runs(limit=limit)
