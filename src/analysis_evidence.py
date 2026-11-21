"""Source-owned evidence spans and conservative compatibility for old quotes.

No similarity scores, translations, or fabricated fallback quotes are accepted.
Matching text verifies provenance, not whether it supports a model's conclusion.
"""
import re
import unicodedata


def evidence_catalog(sources):
    catalog = {}
    for source in sources:
        ref = source['ref']
        title = str(source.get('title') or '').strip()[:300]
        if len(title) >= 4:
            catalog[f'{ref}-T'] = {'source_id': ref, 'quote': title}
        excerpt = str(source.get('excerpt') or '')
        offset, index = 0, 1
        while offset < len(excerpt):
            stop = min(offset + 280, len(excerpt))
            if stop < len(excerpt):
                boundaries = [m.end() for m in re.finditer(r'[.!?。！？](?:\s+|$)|\s+', excerpt[offset:stop])]
                if boundaries and boundaries[-1] > 140:
                    stop = offset + boundaries[-1]
            quote = excerpt[offset:stop].strip()
            if len(quote) >= 4:
                catalog[f'{ref}-E{index:02d}'] = {'source_id': ref, 'quote': quote}
                index += 1
            offset = stop
    return catalog


_TYPOGRAPHIC = str.maketrans({'“':'"', '”':'"', '‘':"'", '’':"'", '‐':'-', '‑':'-', '–':'-', '—':'-'})


def _normalized_with_offsets(text):
    result, positions = [], []
    for offset, char in enumerate(text):
        for part in unicodedata.normalize('NFKC', char).translate(_TYPOGRAPHIC).casefold():
            if part.isspace():
                if not result or result[-1] == ' ':
                    continue
                part = ' '
            result.append(part)
            positions.append(offset)
    if result and result[-1] == ' ':
        result.pop(); positions.pop()
    return ''.join(result), positions


def original_quote(quote, source):
    """Return an actual continuous source span, allowing only typography drift."""
    normalized, _ = _normalized_with_offsets(quote)
    if len(normalized) < 4:
        return None
    for key in ('title', 'excerpt'):
        text = str(source.get(key) or '')
        haystack, offsets = _normalized_with_offsets(text)
        start = haystack.find(normalized)
        if start >= 0:
            return text[offsets[start]:offsets[start + len(normalized) - 1] + 1]
    return None


class CitationValidationError(ValueError):
    def __init__(self, draft, issues, repairs):
        super().__init__(f'报告已生成，但有{len(issues)}处引用未通过核验；已保留草稿和具体位置')
        self.draft = draft
        self.issues = issues
        self.repairs = repairs


def report_claims(report):
    yield 'overview', report['overview']
    for index, trend in enumerate(report['trends']):
        for field in ('observation', 'interpretation'):
            yield f'trends[{index}].{field}', trend[field]
    for index, claim in enumerate(report['connections']):
        yield f'connections[{index}]', claim
    for field in ('question', 'motivation'):
        yield f'research_question.{field}', report['research_question'][field]


def resolve_evidence(report, sources):
    allowed = {source['ref']: source for source in sources}
    catalog = evidence_catalog(sources)
    issues, repairs = [], []
    for path, claim in report_claims(report):
        resolved = []
        invalid = False
        for index, evidence in enumerate(claim['evidence']):
            location = f'{path}.evidence[{index}]'
            ref = evidence.get('source_id', '')
            quote = evidence.get('quote', '')
            ident = evidence.get('evidence_id')
            match = None
            if ident:
                match = catalog.get(ident)
                reason = '证据编号不属于本次材料' if not match else ''
            else:
                exact = original_quote(quote, allowed[ref]) if ref in allowed else None
                if exact is not None:
                    match = {'source_id': ref, 'quote': exact}
                else:
                    # A wrong number may be fixed only when a continuous quote
                    # identifies exactly one source, never by semantic guessing.
                    candidates = [{'source_id': sid, 'quote': found} for sid, source in allowed.items()
                                  if (found := original_quote(quote, source)) is not None]
                    if len(candidates) == 1:
                        match = candidates[0]
                reason = '引文无法匹配唯一的来源原文，可能被改写、翻译或引用编号有误' if not match else ''
            if not match:
                invalid = True
                issues.append({'path': location, 'source_id': ref, 'evidence_id': ident,
                               'quote': quote, 'reason': reason,
                               'source_title': allowed.get(ref, {}).get('title', '')})
                resolved.append(evidence)
                continue
            if ref != match['source_id'] or (quote and quote != match['quote']):
                repairs.append({'path': location, 'source_id': match['source_id'],
                                'reason': '依据证据编号或唯一原文匹配，恢复原始引文与来源编号'})
            resolved.append({**evidence, **match})
        claim['evidence'] = resolved
        refs = list(dict.fromkeys(e['source_id'] for e in resolved))
        if not invalid and set(claim['source_ids']) != set(refs):
            repairs.append({'path': path + '.source_ids', 'source_id': ', '.join(refs),
                            'reason': '引用来源列表已与核实后的证据来源对齐'})
            claim['source_ids'] = refs
    if issues:
        raise CitationValidationError(report, issues, repairs)
    return report, repairs
