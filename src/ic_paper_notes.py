"""Reading notes for IC papers, with a source-excerpt fallback."""

from functools import lru_cache
import json
from pathlib import Path
import re


NOTES_PATH = Path(__file__).resolve().parents[1] / 'resources/ic_paper_reading_notes.json'
NOTE_FIELDS = (('result', '主要发现'), ('question', '研究问题'), ('method', '怎么做'), ('boundary', '适用范围'))
SENTENCE_END = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9(])|(?<=[。！？])\s*')
METHOD = re.compile(r'^(?:In this (?:work|paper|study),?\s+)?(?:We|This (?:paper|work|study|article))\s+(?:propose[s]?|present[s]?|introduce[s]?|develop[s]?|design[s]?)\b|^(?:本[文研究]+|我们)(?:提出|采用|开发|设计)', re.I)
RESULT = re.compile(r'^(?:The\s+)?(?:(?:experimental|industrial|simulation|evaluation|validation|benchmarking)\s+)?(?:results?|experiments?|simulations?|evaluations?|measurements?|benchmarks?|validation)\b.{0,110}\b(?:show|indicate|demonstrate|reveal|achieve|confirm)\w*\b|^(?:实验|仿真|评估|测试|测量)结果(?:表明|显示)', re.I)
DIRECT_RESULT = re.compile(
    r'\b(?:proposed|measured|fabricated|prototype|implemented|our|measurement)\b.{0,100}'
    r'\b(?:achiev\w*|demonstrat\w*|consum\w*|occup\w*|deliver\w*|report\w*|outperform\w*)\b', re.I,
)
METRIC = re.compile(r'\d\s*(?:[%×]|(?:ns|ps|GHz|MHz|kHz|mW|µW|µm|mV|mm²|dB|pJ|fJ|Gbps|TOPS|bits?)\b)', re.I)


@lru_cache(maxsize=1)
def _curated_at(_mtime):
    return json.loads(NOTES_PATH.read_text(encoding='utf-8'))


def paper_reading_notes(item):
    if item.get('content_type') != 'paper':
        return None
    original = item.get('abstract_text') or ''
    if original.strip() and NOTES_PATH.exists():
        note = _curated_at(NOTES_PATH.stat().st_mtime_ns).get(item.get('id'))
        if note:
            return {'basis': 'abstract', 'points': [{'label': label, 'text': note[key]} for key, label in NOTE_FIELDS]}

    return item.get('reading_notes') or extract_abstract_notes(item)


def extract_abstract_notes(item):
    """Use only the author abstract, independently of edited reading notes."""
    if item.get('content_type') != 'paper' or item.get('summary_kind') not in (None, 'source'):
        return None

    original = item.get('abstract_text') or ''
    sentences = [part for part in SENTENCE_END.split(' '.join(original.split())) if 40 <= len(part) <= 450]
    reported = [part for part in reversed(sentences) if RESULT.search(part)]
    result = next((part for part in reported if METRIC.search(part)), None)
    if result is None:
        result = reported[0] if reported else next((part for part in reversed(sentences)
                                                     if DIRECT_RESULT.search(part) and METRIC.search(part)), None)
    if result:
        points = [{'label': '作者报告的结果', 'text': result}]
        method = next((part for part in sentences if part != result and METHOD.search(part)), None)
        if method:
            points.append({'label': '作者描述的方法', 'text': method})
        return {'basis': 'abstract_excerpt', 'points': points}
    return None
