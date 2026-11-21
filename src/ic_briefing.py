"""Versioned, public-only IC editorial snapshots; no model or database writes."""
from copy import deepcopy
from datetime import date, timedelta
from functools import lru_cache
import json
import logging
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / 'resources/ic_briefing_20261120.json'
MONTHLY_HOTSPOT_LIMIT = 50
logger = logging.getLogger(__name__)


def load_snapshot():
    return json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))


def validate_snapshot(snapshot):
    """Fail closed on dangling evidence, invalid scores, or invalid dates."""
    sources = snapshot['sources']
    tech_ids = {tech['id'] for tech in snapshot['technologies']}
    if len(tech_ids) != len(snapshot['technologies']):
        raise ValueError('Duplicate technology ID')
    event_ids = set()
    for source in sources.values():
        if source.get('published_at'):
            date.fromisoformat(source['published_at'])
        if not source['url'].startswith(('https://', 'http://')):
            raise ValueError('Invalid source URL')
    for event in snapshot['events']:
        if event['id'] in event_ids or not isinstance(event['technology_ids'], list) or not set(event['technology_ids']) <= tech_ids:
            raise ValueError('Invalid event identity or technology')
        event_ids.add(event['id'])
        if not event['source_ids'] or not set(event['source_ids']) <= sources.keys():
            raise ValueError('Event source is missing')
        if any(sources[sid]['content_type'] != 'news' for sid in event['source_ids']):
            raise ValueError('Papers must not count as attention')
    story = snapshot.get('weekly_story')
    highlight_fields = ('what_happened', 'why_it_matters', 'evidence_stage', 'watch_next')
    if story is not None:
        if not isinstance(story, dict) or any(not isinstance(story.get(field), str) or not story[field].strip()
                                              for field in ('question', 'overview', 'research_question')):
            raise ValueError('Weekly story is incomplete')
        highlight_fields += ('reading_question',)
    highlight_ids = set()
    for highlight in (*snapshot.get('weekly_highlights', []), *snapshot.get('article_briefs', [])):
        event_id = highlight['event_id']
        if event_id not in event_ids or event_id in highlight_ids:
            raise ValueError('Invalid weekly highlight event')
        highlight_ids.add(event_id)
        for field in highlight_fields:
            value = highlight.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Weekly highlight explanation is missing')
    for tech in snapshot['technologies']:
        for claim in [tech['overview'], tech['assessment'], tech['limitations'], tech['watch_next'], *tech['scores']]:
            if not claim['source_ids'] or not set(claim['source_ids']) <= sources.keys():
                raise ValueError('Evaluation evidence is missing')
        if not set(tech['paper_ids']) <= sources.keys():
            raise ValueError('Representative paper is missing')
        if any(sources[sid]['content_type'] != 'paper' for sid in tech['paper_ids']):
            raise ValueError('Representative paper must be a paper')
        if len(tech['scores']) != 3 or any(type(s['value']) is not int or not 1 <= s['value'] <= 5 for s in tech['scores']):
            raise ValueError('Invalid importance score')
        if tech['review_status'] not in ('provisional', 'reviewed'):
            raise ValueError('Invalid review status')
        if tech['review_status'] == 'reviewed' and not tech.get('reviewed_by'):
            raise ValueError('A reviewed score requires a human reviewer')


def event_briefs_by_source(snapshot):
    """Reuse each published event brief for its related articles."""
    events = {event['id']: event for event in snapshot['events']}
    sources = snapshot['sources']
    by_source = {}
    for entry in (*snapshot.get('weekly_highlights', []), *snapshot.get('article_briefs', [])):
        event = events[entry['event_id']]
        related_sources = [
            {'id': source_id, 'name': sources[source_id]['source']}
            for source_id in dict.fromkeys(event['source_ids'])
        ]
        event_brief = {**entry, 'title': event['title'], 'sources': related_sources}
        for source in related_sources:
            by_source.setdefault(source['id'], []).append(event_brief)
    return by_source


@lru_cache(maxsize=1)
def _cached_event_briefs(_snapshot_modified_at):
    snapshot = load_snapshot()
    validate_snapshot(snapshot)
    return event_briefs_by_source(snapshot)


def event_briefs_for_source(source_id):
    try:
        return _cached_event_briefs(SNAPSHOT_PATH.stat().st_mtime_ns).get(source_id, [])
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning('Could not load the optional IC event briefs', exc_info=True)
        return []


def _ranks(items, key, eligible, *, limit=None):
    """Number entries consecutively after sorting by metrics and stable IDs."""
    order = [item['id'] for item in sorted(
        (item for item in items if eligible(item)),
        key=lambda item: tuple(-n for n in key(item)) + (item['id'],),
    )][:limit]
    return {item_id: position for position, item_id in enumerate(order, 1)}, order


def briefing(days=30, snapshot=None):
    if type(days) is not int or days not in (7, 30):
        raise ValueError('Only 7-day and 30-day windows are supported')
    result = deepcopy(snapshot if snapshot is not None else load_snapshot())
    validate_snapshot(result)
    end = date.fromisoformat(result['data_through'])
    start = end - timedelta(days=days - 1)
    result['window'] = {'days': days, 'date_from': start.isoformat(), 'date_to': end.isoformat()}
    sources = result['sources']
    for event in result['events']:
        # A report may describe an older event. The window counts report dates,
        # never collection time or an inferred event/meeting date.
        event['window_source_ids'] = [sid for sid in event['source_ids']
            if sources[sid].get('published_at') and start <= date.fromisoformat(sources[sid]['published_at']) <= end]
        media_ids = sorted({sid for sid in event['window_source_ids'] if sources[sid]['attention_eligible']},
                           key=lambda sid: (-date.fromisoformat(sources[sid]['published_at']).toordinal(), sid))
        event['attention'] = {
            'source_ids': media_ids,
            'source_count': len({sources[sid]['organization'] for sid in media_ids}),
            'latest_reported_at': sources[media_ids[0]]['published_at'] if media_ids else None,
        }
    event_ranks, event_order = _ranks(
        result['events'],
        lambda event: (event['attention']['source_count'],
                       date.fromisoformat(event['attention']['latest_reported_at']).toordinal()),
        lambda event: event['attention']['source_count'] > 0,
        limit=MONTHLY_HOTSPOT_LIMIT if days == 30 else None,
    )
    for event in result['events']:
        event['attention_rank'] = event_ranks.get(event['id'])
    for tech in result['technologies']:
        events = [e for e in result['events'] if tech['id'] in e['technology_ids'] and e['window_source_ids']]
        active = {sid for e in events for sid in e['window_source_ids']}
        media = {sid for event in events for sid in event['attention']['source_ids']}
        institutions = sorted({sources[sid]['organization'] for sid in media})
        covered_days = sorted({sources[sid]['published_at'] for sid in media})
        counted_events = sum(bool(e['attention']['source_count']) for e in events)
        tech['attention'] = {
            'source_count': len(institutions), 'organizations': institutions,
            'event_count': counted_events, 'covered_days': len(covered_days),
            'news_count': len(active), 'other_source_count': len(active - media),
            'source_ids': sorted(media), 'event_ids': [e['id'] for e in events],
        }
        tech['importance_score'] = sum(s['value'] for s in tech['scores'])
    attention, attention_order = _ranks(result['technologies'],
        lambda t: (t['attention']['source_count'], t['attention']['event_count'], t['attention']['covered_days']),
        lambda t: t['attention']['source_count'] > 0)
    importance, importance_order = _ranks(result['technologies'], lambda t: (t['importance_score'],), lambda t: True)
    for tech in result['technologies']:
        tech['attention_rank'] = attention.get(tech['id'])
        tech['importance_rank'] = importance.get(tech['id'])
    result['attention_order'] = attention_order
    result['event_attention_order'] = event_order
    result['event_attention_method'] = (
        '按每组事件的合格媒体机构数排序，同一家媒体多篇稿件只计一家。'
        '机构数相同时，最近一篇计入报道越新，排名越靠前。名次按榜单顺序连续编号。'
        '报道以原站发布日期进入统计窗口。同一事件可关联多个技术，但在热点榜只列一条。'
    )
    result['importance_order'] = importance_order
    return result
