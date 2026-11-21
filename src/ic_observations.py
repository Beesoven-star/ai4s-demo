"""IC topic catalog and immutable daily observation editions."""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

RESOURCES = Path(__file__).resolve().parents[1] / 'resources'
CATALOG_PATH = RESOURCES / 'ic_topic_catalog.json'
DAILY_DIR = RESOURCES / 'ic_daily'
SHANGHAI = timezone(timedelta(hours=8))
TOPIC_STATES = {'candidate', 'active', 'paused', 'merged'}


def today_in_shanghai():
    return datetime.now(SHANGHAI).date().isoformat()


def validate_catalog(catalog):
    categories = {entry['id'] for entry in catalog['categories']}
    topics = {entry['id']: entry for entry in catalog['topics']}
    if len(categories) != len(catalog['categories']) or len(topics) != len(catalog['topics']):
        raise ValueError('Duplicate catalog ID')
    for entry in catalog['topics']:
        if entry['status'] not in TOPIC_STATES or not set(entry['category_ids']) <= categories:
            raise ValueError(f"Invalid topic: {entry['id']}")
        if entry['status'] == 'merged':
            target = topics.get(entry.get('merged_into'))
            if not target or target['status'] not in {'active', 'paused'}:
                raise ValueError(f"Invalid merge target: {entry['id']}")


@lru_cache(maxsize=1)
def _catalog_at(_revision):
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    validate_catalog(catalog)
    return catalog


def load_catalog():
    return _catalog_at(CATALOG_PATH.stat().st_mtime_ns)


def public_catalog(catalog=None):
    catalog = catalog if catalog is not None else load_catalog()
    return {**catalog,
            'categories': [{key: row[key] for key in ('id', 'name')} for row in catalog['categories']],
            'topics': [{key: row[key] for key in ('id', 'name', 'status', 'category_ids', 'reason', 'source_ids', 'merged_into', 'question', 'follow_up', 'briefing_event_ids') if key in row}
                       for row in catalog['topics']]}


def classify_for_observation(item, *, catalog=None, topic_ids=()):
    catalog = catalog if catalog is not None else load_catalog()
    topics = {entry['id']: entry for entry in catalog['topics']}
    title = item['title']
    text = f"{title}\n{item.get('abstract_text') or item.get('summary') or ''}"
    research_ids = set((item.get('ic_ai') or {}).get('topic_ids', [])) if item['content_type'] == 'paper' else set()
    explicit = bool(topic_ids)
    if explicit:
        matches = [topics[topic_id] for topic_id in topic_ids]
    else:
        matches = [entry for entry in topics.values() if
                   (entry.get('pattern') and re.search(entry['pattern'], text, re.I))
                   or item.get('id') in entry.get('source_ids', ())
                   or research_ids.intersection(entry.get('paper_topic_ids', []))]
    resolved = {entry['id']: entry for entry in (topics[entry['merged_into']] if entry['status'] == 'merged' else entry for entry in matches)}
    selected_categories = {category for entry in resolved.values() for category in entry['category_ids']}
    selected_categories.update(entry['id'] for entry in catalog['categories'] if re.search(entry['pattern'], title, re.I))
    categories = [{key: entry[key] for key in ('id', 'name')} for entry in catalog['categories'] if entry['id'] in selected_categories]
    tags = [{key: entry[key] for key in ('id', 'name', 'status')} for entry in resolved.values()]
    return {'catalog_version': catalog['version'], 'categories': categories, 'topics': tags,
            'basis': 'editorial' if explicit else 'rule' if categories or tags else 'pending'}


def _saved_editions(directory):
    return sorted((path for path in directory.glob('????-??-??.json') if path.is_file()), reverse=True)


def daily_observations(day=None, directory=DAILY_DIR):
    today = today_in_shanghai()
    selected_day = day or today
    editions = []
    selected = None
    for path in _saved_editions(directory):
        if path.stem > today:
            continue
        report = json.loads(path.read_text(encoding='utf-8'))
        editions.append({key: report[key] for key in ('date', 'title')})
        if report['date'] == selected_day:
            selected = report
    return {'today': today, 'selected_day': selected_day, 'editions': editions, 'report': selected}


def export_daily_editions(directory=DAILY_DIR):
    today = today_in_shanghai()
    return [json.loads(path.read_text(encoding='utf-8')) for path in _saved_editions(directory) if path.stem <= today]


def save_daily_edition(draft, items_by_id, directory=DAILY_DIR, *, catalog=None):
    """Resolve source and topic references once, then freeze the edition."""
    catalog = catalog if catalog is not None else load_catalog()
    day = date.fromisoformat(draft['date']).isoformat()
    if day > today_in_shanghai():
        raise ValueError('Daily observation date has not arrived')
    entries = []
    for entry in draft['entries']:
        item = items_by_id[entry['source_id']]
        if item.get('published_at') != day:
            raise ValueError(f"Source {item['id']} was not published on {day}")
        source = {key: item.get(key) for key in ('id', 'source', 'title', 'url', 'content_type', 'published_at', 'news_genre')}
        entries.append({'title': entry['title'], 'summary': entry['summary'], 'source': source,
                        'classification': classify_for_observation(item, catalog=catalog, topic_ids=entry.get('topic_ids', ()))})
    if not entries or len({entry['source']['id'] for entry in entries}) != len(entries):
        raise ValueError('A daily observation needs distinct source entries')
    report = {'date': day, 'title': draft['title'], 'intro': draft['intro'],
              'prepared_on': today_in_shanghai(), 'catalog_version': catalog['version'], 'entries': entries}
    directory.mkdir(parents=True, exist_ok=True)
    # An atomic no-clobber publish keeps readers from seeing partial output and
    # prevents retries from rewriting a previously published day.
    with NamedTemporaryFile(dir=directory, suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        destination = directory / f'{day}.json'
        if os.name == 'nt':
            temporary.rename(destination)
        else:
            destination.hardlink_to(temporary)
    finally:
        temporary.unlink(missing_ok=True)
    return report
