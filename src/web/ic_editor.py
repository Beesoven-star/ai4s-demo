"""API for the local IC observation editor."""

import os
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src import analysis_connection, discovery, ic_automatic, ic_editor as editor, ic_reading_prompts, ic_topic_evaluation, ic_topics
from src.ic_briefing import briefing


def require_ic():
    if os.environ.get('DNEWS_RESEARCH_DOMAIN') != 'ic':
        raise HTTPException(404, '当前不是集成电路工作台')


router = APIRouter(prefix='/api/ic-editor', dependencies=[Depends(require_ic)])


class Entry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(max_length=500)
    summary: str = Field(max_length=4000)
    boundary: str = Field(default='', max_length=320)
    source_ids: list[str] = Field(min_length=1, max_length=50)
    topic_ids: list[str] = Field(max_length=30)


class Edits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: Annotated[int, Field(ge=1, strict=True)]
    title: str = Field(max_length=500)
    intro: str = Field(max_length=4000)
    entries: list[Entry] = Field(max_length=80)
    source_reviews: dict[str, str] = Field(max_length=4000)


class Publish(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: Annotated[int, Field(ge=1, strict=True)]
    confirm: Literal[True]


class PromptSettings(BaseModel):
    prompt: str = Field(min_length=1, max_length=3500)


class ReadingPromptSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str | None = Field(max_length=ic_reading_prompts.MAX_PROMPT_LENGTH)


class EvaluationSettings(BaseModel):
    focus: str = Field(max_length=ic_topic_evaluation.FOCUS_LIMIT)


class Replay(BaseModel):
    day: date
    topic_id: str | None = Field(default=None, min_length=1, max_length=100)
    topics_only: bool = False


@router.get('/drafts')
def drafts():
    return {'drafts': editor.list_drafts(), 'catalog': ic_topics.display_catalog(), 'source_kinds': editor.SOURCE_KINDS}


def _request(action, *args):
    try:
        return action(*args)
    except KeyError as error:
        raise HTTPException(404, str(error.args[0])) from error
    except editor.EditionConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get('/drafts/{identity}')
def draft(identity: str):
    return _request(editor.get_draft, identity)


@router.put('/drafts/{identity}')
def save(identity: str, body: Edits):
    return _request(editor.save_draft, identity, body.revision, body.model_dump(exclude={'revision'}))


@router.post('/drafts/{identity}/publish')
def publish(identity: str, body: Publish):
    return _request(editor.publish_draft, identity, body.revision)


@router.get('/automation')
def automation():
    db = discovery._path()
    return {**ic_automatic.prompt_settings(db), 'runs': ic_automatic.recent_runs(db)}


@router.put('/automation/prompt')
def update_prompt(body: PromptSettings):
    return _request(ic_automatic.save_prompt, discovery._path(), body.prompt)


@router.get('/reading-prompts')
def reading_prompts():
    return {
        'prompts': ic_reading_prompts.settings(discovery._path()),
        'system_prompt': analysis_connection.SYSTEM_PROMPT,
        'max_length': ic_reading_prompts.MAX_PROMPT_LENGTH,
    }


@router.put('/reading-prompts/{kind}')
def update_reading_prompt(kind: Literal['paper', 'news'], body: ReadingPromptSettings):
    return _request(ic_reading_prompts.save, discovery._path(), kind, body.prompt)


@router.post('/automation/replay', status_code=202)
def replay(body: Replay):
    return {'id': _request(ic_automatic.replay, discovery._path(), body.day, body.topic_id, body.topics_only)}


@router.get('/evaluation-settings')
def evaluation_settings():
    return ic_topic_evaluation.settings(discovery._path())


@router.put('/evaluation-settings')
def update_evaluation_settings(body: EvaluationSettings):
    return ic_topic_evaluation.save_focus(discovery._path(), body.focus)


@router.get('/topics')
def topics():
    db = discovery._path()
    return {'topics': ic_topic_evaluation.topic_directory(db), 'runs': ic_topics.recent_runs(db),
            'cool_days': ic_topics.COOL_DAYS, 'as_of': ic_topics._now().date().isoformat()}


@router.get('/topics/{identity}')
def topic(identity: str):
    record = ic_topics.topic_detail(identity)
    if record is None:
        raise HTTPException(404, '专题不存在')
    if card := ic_topic_evaluation.published_cards().get(identity):
        record['evaluation'] = card
    return record


@router.get('/weekly')
def weekly(version: Annotated[str | None, Query(max_length=100)] = None, day: date | None = None):
    archived = briefing(7)
    window = archived['window']
    story = archived.get('weekly_story') or {}
    original = {'id': 'original', 'date': window['date_to'], 'date_from': window['date_from'],
                'title': story.get('question') or '本周技术观察'}
    return editor.calendar_week_archive(editor.publications('weekly'), original, day=day.isoformat() if day else None,
                                        version=version)
