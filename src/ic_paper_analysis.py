"""Generate Chinese paper notes from author abstracts through the configured model."""

from pydantic import BaseModel, Field

from src.ic_evidence import reading_points
from src.ic_paper_notes import NOTE_FIELDS
from src.ic_reading_jobs import ReadingQueue
from src.ic_reading_prompts import format_prompt


CHAR_LIMIT = 6500
QUEUE = ReadingQueue('paper', required_field='abstract_text', watched_fields=('abstract_text',))
initialize = QUEUE.initialize
enqueue = QUEUE.enqueue
read_notes = QUEUE.read_notes


class Notes(BaseModel):
    result: str = Field(min_length=1, max_length=450)
    question: str = Field(min_length=1, max_length=300)
    method: str = Field(min_length=1, max_length=420)
    boundary: str = Field(min_length=1, max_length=350)
    evidence: str = Field(min_length=8, max_length=300)


def _abstract(item):
    return ' '.join((item.get('abstract_text') or '').split())


def _prompt(items, instructions):
    inputs = [{'id': item['id'], 'title': item['title'], 'abstract': _abstract(item)[:CHAR_LIMIT],
               'abstract_is_excerpt': len(_abstract(item)) > CHAR_LIMIT} for item in items]
    return format_prompt('paper', instructions, inputs)


def _validate(raw, item):
    fields = Notes.model_validate(raw)
    abstract = _abstract(item)
    points = reading_points(fields, NOTE_FIELDS, abstract[:CHAR_LIMIT], '作者摘要')
    return {'basis': 'abstract' if len(abstract) <= CHAR_LIMIT else 'abstract_notes_excerpt', 'points': points}


async def process_next(db_path):
    return await QUEUE.process_next(db_path, prompt=_prompt, validate=_validate, response_key='papers')
