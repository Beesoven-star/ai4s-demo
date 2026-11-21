"""Generate Chinese news notes from the public material available for each article."""

import asyncio
import json
import re
from functools import partial

import aiohttp
from pydantic import BaseModel, Field

from src.ic_automatic import _read_news, _news_source_hosts
from src.ic_evidence import reading_points, stored_reading_basis
from src.ic_reading_jobs import ReadingQueue
from src.ic_reading_prompts import format_prompt


CHAR_LIMIT = 3600
SHORT_INTRO_CHARS = 120
NOTE_FIELDS = (('what', '发生了什么'), ('why', '技术看点'), ('stage', '目前进展'))
BASIS = {
    'original': 'report_excerpt',
    'metadata': 'source_intro',
    'original_summary': 'report_summary',
    'listing': 'news_listing',
    'excerpt': 'source_intro',
}
QUEUE = ReadingQueue('news', watched_fields=('url', 'source', 'summary', 'abstract_text', 'summary_kind', 'verification_mode',
                                            'reading_notes'))
initialize = QUEUE.initialize
enqueue = QUEUE.enqueue
read_notes = QUEUE.read_notes


class Notes(BaseModel):
    what: str = Field(min_length=1, max_length=165)
    why: str = Field(max_length=165)
    stage: str = Field(max_length=165)
    evidence: str = Field(min_length=8, max_length=300)


def _material(item, page):
    kind = page['status']
    text = page['text']
    if kind in ('original', 'metadata'):
        fields = json.loads(text)
        text = fields.get('article') if kind == 'original' else fields.get('og:description')
        stored_kind = stored_reading_basis(item)
        has_stored_review = kind == 'metadata' and stored_kind == 'original_summary' and page.get('excerpt')
        if has_stored_review or not text or text.strip() == item['title'].strip():
            kind, text = stored_kind, page.get('excerpt') or ''
    text = re.sub(r'\s*The post .+? appeared first on [^\n]+\.?$', '', text or '', flags=re.I).strip()
    text = ' '.join(text.split())[:CHAR_LIMIT]
    if kind not in BASIS or len(text) < 15 or text.casefold() == item['title'].strip().casefold():
        return None
    return {'id': item['id'], 'source': item['source'], 'material_kind': kind, 'text': text,
            'short_intro': BASIS[kind] in ('source_intro', 'news_listing') and len(text) < SHORT_INTRO_CHARS}


async def _prepare(config_path, items):
    hosts = _news_source_hosts(config_path)
    inputs = [
        {**item, 'reading_basis': stored_reading_basis(item),
         'summary': (item.get('summary') or item.get('abstract_text') or '').strip(), 'evidence_limit': CHAR_LIMIT}
        for item in items if not (item.get('reading_notes') or {}).get('points')
    ]
    if not inputs:
        return []
    connector = aiohttp.TCPConnector(limit=3, limit_per_host=2)
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=8),
                                     headers={'User-Agent': 'AI4SResearchWorkbench/0.1 (public source metadata)'}) as session:
        pages = await asyncio.gather(*(_read_news(session, item, hosts) for item in inputs))
    return [material for item, page in zip(inputs, pages, strict=True) if (material := _material(item, page)) is not None]


def _prompt(items, instructions):
    return format_prompt('news', instructions, items)


def _validate(raw, item):
    fields = Notes.model_validate(raw)
    note_fields = NOTE_FIELDS[:1] if item['short_intro'] else NOTE_FIELDS
    points = reading_points(fields, note_fields, item['text'], '来源材料', optional=('why', 'stage'))
    return {'basis': BASIS[item['material_kind']], 'points': points}


async def process_next(db_path, config_path):
    return await QUEUE.process_next(db_path, prompt=_prompt, validate=_validate, response_key='news',
                                    prepare=partial(_prepare, config_path))

