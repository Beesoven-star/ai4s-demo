"""Generate Chinese paper notes from author abstracts through the configured model."""

from pydantic import BaseModel, Field

from src.ic_evidence import evidence_excerpts, reading_points
from src.ic_paper_notes import NOTE_FIELDS
from src.ic_reading_jobs import ReadingQueue
from src.ic_reading_prompts import format_prompt


CHAR_LIMIT = 6500
EVIDENCE_WIDTH = 450
QUEUE = ReadingQueue('paper', required_field='abstract_text', watched_fields=('abstract_text',))
initialize = QUEUE.initialize
enqueue = QUEUE.enqueue
read_notes = QUEUE.read_notes


class Notes(BaseModel):
    result: str = Field(min_length=1, max_length=450)
    question: str = Field(min_length=1, max_length=300)
    method: str = Field(min_length=1, max_length=420)
    boundary: str = Field(min_length=1, max_length=350)
    evidence: str = Field(min_length=8, max_length=EVIDENCE_WIDTH)


def _abstract(item):
    return ' '.join((item.get('abstract_text') or '').split())


def _prompt(items, instructions):
    inputs = []
    for item in items:
        abstract = _abstract(item)
        text = abstract[:CHAR_LIMIT]
        excerpts = evidence_excerpts(text, width=EVIDENCE_WIDTH, limit=40)
        inputs.append({'id': item['id'], 'title': item['title'], 'abstract': text,
                       'abstract_is_excerpt': len(abstract) > CHAR_LIMIT,
                       'evidence_options': dict(enumerate(excerpts, 1))})
    return format_prompt('paper', instructions, inputs)


def _validate(raw, item):
    abstract = _abstract(item)
    text = abstract[:CHAR_LIMIT]
    if 'evidence_id' in raw:
        index = raw['evidence_id']
        excerpts = evidence_excerpts(text, width=EVIDENCE_WIDTH, limit=40)
        if type(index) is not int or not 1 <= index <= len(excerpts):
            raise ValueError('原文编号不在该论文的作者摘要中')
        raw = {**raw, 'evidence': excerpts[index - 1]}
    fields = Notes.model_validate(raw)
    points = reading_points(fields, NOTE_FIELDS, text, '作者摘要')
    return {'basis': 'abstract' if len(abstract) <= CHAR_LIMIT else 'abstract_notes_excerpt', 'points': points}


async def process_next(db_path):
    return await QUEUE.process_next(db_path, prompt=_prompt, validate=_validate, response_key='papers')
