"""Local IC editorial drafts and immutable published editions."""

from contextlib import closing
from datetime import date, datetime, timedelta
import json
import sqlite3

from src import discovery as store
from src import ic_topics
from src.ic_observation_drafts import build_drafts
from src.ic_observations import SHANGHAI


SOURCE_KINDS = {'reporting': '独立报道或采访', 'reprint': '转载或转述', 'official': '机构或厂商披露',
                'paper': '作者论文或摘要', 'background': '背景材料', 'unconfirmed': '来源性质待确认'}


class EditionConflict(ValueError):
    pass


def initialize(db_path=None):
    with closing(store._connect(db_path)) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS ic_editor_drafts (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, revision INTEGER NOT NULL,
                published_at TEXT, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ic_editor_publications (
                id TEXT PRIMARY KEY REFERENCES ic_editor_drafts(id),
                kind TEXT NOT NULL, date_to TEXT NOT NULL, published_at TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ic_editor_publications_dates
                ON ic_editor_publications(kind, date_to, published_at);
        ''')


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def stage_batch(report, batch_id, *, label, stamp=None, db_path=None):
    """Create daily and weekly siblings without rewriting edits on replay."""
    created = stamp or datetime.now(SHANGHAI).isoformat()
    ids = []
    with closing(store._connect(db_path)) as db, db:
        for kind in ('daily', 'weekly'):
            raw = report[kind]
            start, end = (raw['date'], raw['date']) if kind == 'daily' else (raw['date_from'], raw['date_to'])
            candidates = {row['id']: row for row in report['entries'] if start <= row['published_at'] <= end}
            suggestions = []
            for pair in report['possible_event_duplicates']:
                a, b = pair['items']
                if not (start <= a['published_at'] <= end and start <= b['published_at'] <= end):
                    continue
                for row in (a, b):
                    candidates.setdefault(row['id'], {**row, 'summary': '', 'classification': {'topics': [], 'categories': []}})
                suggestions.append([a['id'], b['id']])
            identity = f'{batch_id}-{kind}'
            heading = '今日观察' if kind == 'daily' else '本周技术观察'
            draft = {'id': identity, 'kind': kind, 'date_from': start, 'date_to': end, 'label': label,
                     'title': f'{heading} · {end}',
                     'intro': f'本期选取 {len(raw["entries"])} 条集成电路进展。' if raw['entries'] else '',
                     'catalog_version': report['catalog_version'], 'collection_runs': [
                         {key: run.get(key) for key in ('source_name', 'status', 'found', 'error')}
                         for run in report['collection_runs']],
                     'candidates': list(candidates.values()), 'suggestions': suggestions, 'source_reviews': {},
                     'entries': [{'title': row['title'], 'summary': row['summary'], 'source_ids': [row['id']],
                                  'topic_ids': [topic['id'] for topic in row['classification']['topics']]}
                                 for row in raw['entries']]}
            db.execute('INSERT OR IGNORE INTO ic_editor_drafts VALUES (?, ?, 1, NULL, ?)',
                       (identity, created, _json(draft)))
            ids.append(identity)
    return ids


def stage_completed_collection(job, db_path):
    end = date.fromisoformat(job['window_end'])
    start = end - timedelta(days=6)
    with closing(store._connect(db_path)) as db:
        rows = [json.loads(row[0]) for row in db.execute('SELECT payload FROM discovery_items WHERE published_date BETWEEN ? AND ?',
                                                       ((start - timedelta(days=3)).isoformat(), end.isoformat()))]
    items = [row for row in rows if row['published_at'] >= start.isoformat() and row.get('news_scope') != 'archive']
    earlier = [row for row in rows if row['published_at'] < start.isoformat() and row.get('news_scope') != 'archive']
    report = build_drafts(items, end, ic_topics.discovery_catalog(db_path), reference=earlier, source_runs=job['runs'])
    return stage_batch(report, job['id'], label=f'采集后整理 · 新增 {job["inserted"]} 条', stamp=job['finished_at'], db_path=db_path)


def _draft(row):
    return {**json.loads(row['payload']), 'revision': row['revision'], 'created_at': row['created_at'],
            'published_at': row['published_at']}


def list_drafts(db_path=None):
    with closing(store._connect(db_path)) as db:
        rows = db.execute('SELECT * FROM ic_editor_drafts ORDER BY created_at DESC, id DESC').fetchall()
    fields = ('id', 'kind', 'date_from', 'date_to', 'label', 'title', 'revision', 'published_at')
    drafts = [_draft(row) for row in rows]
    return [{**{key: draft[key] for key in fields}, 'entry_count': len(draft['entries']),
             'source_count': len(draft['candidates'])} for draft in drafts]


def _get(db, identity):
    row = db.execute('SELECT * FROM ic_editor_drafts WHERE id=?', (identity,)).fetchone()
    if row is None:
        raise KeyError('草稿不存在')
    return _draft(row)


def get_draft(identity, db_path=None):
    with closing(store._connect(db_path)) as db:
        return _get(db, identity)


def _check_revision(draft, revision):
    if draft['published_at']:
        raise EditionConflict('这份草稿已经发布。')
    if draft['revision'] != revision:
        raise EditionConflict('草稿已在其他操作中更新，请保留当前修改并重新打开草稿。')


def _check_content(draft, catalog):
    candidates = {row['id'] for row in draft['candidates']}
    topic_ids = {row['id'] for row in catalog['topics']}
    seen = set()
    for entry in draft['entries']:
        ids = set(entry['source_ids'])
        if not ids or len(ids) != len(entry['source_ids']) or not ids <= candidates or seen & ids:
            raise ValueError('请为每条进展关联有效出处。同一篇资料应只归入一条进展。')
        if len(set(entry['topic_ids'])) != len(entry['topic_ids']) or not set(entry['topic_ids']) <= topic_ids:
            raise ValueError('请选择目录中的专题。')
        seen.update(ids)
    if not set(draft['source_reviews']) <= candidates or not set(draft['source_reviews'].values()) <= SOURCE_KINDS.keys():
        raise ValueError('出处核验记录无效。')


def save_draft(identity, revision, changes, db_path=None):
    catalog = ic_topics.display_catalog(db_path)
    with closing(store._connect(db_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        draft = _get(db, identity)
        _check_revision(draft, revision)
        draft.update(changes)
        _check_content(draft, catalog)
        db.execute('UPDATE ic_editor_drafts SET revision=revision+1, payload=? WHERE id=?',
                   (_json(draft), identity))
        return _get(db, identity)


def _publish_draft(db, identity, revision, catalog, *, automatic=None):
    draft = _get(db, identity)
    if draft['published_at'] and draft['revision'] == revision + 1:
        return json.loads(db.execute('SELECT payload FROM ic_editor_publications WHERE id=?', (identity,)).fetchone()[0])
    _check_revision(draft, revision)
    _check_content(draft, catalog)
    if not draft['title'].strip() or not draft['intro'].strip() or not draft['entries']:
        raise ValueError('发布前请填写标题、导语，并至少选入一条进展。')
    if any(not row['title'].strip() or not row['summary'].strip() for row in draft['entries']):
        raise ValueError('发布前请写全每条进展的标题和正文。')
    topics = {topic['id']: topic for topic in catalog['topics']}
    candidates = {row['id']: row for row in draft['candidates']}
    entries = []
    for row in draft['entries']:
        sources = []
        for key in row['source_ids']:
            source = {k: candidates[key].get(k) for k in ('id', 'title', 'source', 'url', 'content_type', 'published_at')}
            source['news_genre'] = SOURCE_KINDS.get(draft['source_reviews'].get(key))
            if automatic:
                source['evidence_status'] = automatic['sources'][key]['status']
                source['evidence_note'] = automatic['sources'][key]['note']
            sources.append(source)
        tags = [topics[key] for key in row['topic_ids']]
        categories = {category['id'] for key in row['source_ids'] for category in candidates[key]['classification']['categories']}
        categories.update(category for tag in tags for category in tag['category_ids'])
        categories.update(row.get('category_ids', []))
        entries.append({'title': row['title'].strip(), 'summary': row['summary'].strip(), 'boundary': row.get('boundary', '').strip(),
                        'source': sources[0], 'sources': sources,
                        'classification': {'basis': 'rule' if automatic else 'editorial', 'catalog_version': catalog['version'],
                                           'topics': [{k: tag[k] for k in ('id', 'name', 'status')} for tag in tags],
                                           'categories': [cat for cat in catalog['categories'] if cat['id'] in categories]}})
    published_at = datetime.now(SHANGHAI).isoformat()
    report = {'id': identity, 'date': draft['date_to'], 'date_from': draft['date_from'], 'prepared_on': published_at[:10],
              'published_at': published_at, 'kind': draft['kind'], 'title': draft['title'].strip(), 'intro': draft['intro'].strip(),
              'catalog_version': catalog['version'], 'entries': entries}
    if automatic:
        report['automation'] = {key: automatic[key] for key in ('prompt_version', 'generated_at', 'collection_partial', 'topic_suggestions')}
        if digest := automatic.get('material_changes', {}).get(identity):
            report['automation']['material_change'] = digest
    db.execute('INSERT INTO ic_editor_publications VALUES (?, ?, ?, ?, ?)',
               (identity, draft['kind'], draft['date_to'], published_at, _json(report)))
    db.execute('UPDATE ic_editor_drafts SET revision=revision+1, published_at=? WHERE id=?', (published_at, identity))
    return report


def publish_draft(identity, revision, db_path=None):
    catalog = ic_topics.display_catalog(db_path)
    with closing(store._connect(db_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        return _publish_draft(db, identity, revision, catalog)


def publish_automatic(editions, automation, db_path=None):
    """Apply a validated model result and publish its editions atomically."""
    catalog = ic_topics.display_catalog(db_path)
    with closing(store._connect(db_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        reports = []
        for identity, changes in editions.items():
            draft = _get(db, identity)
            if draft['published_at']:
                reports.append(json.loads(db.execute('SELECT payload FROM ic_editor_publications WHERE id=?', (identity,)).fetchone()[0]))
                continue
            _check_revision(draft, 1)
            draft.update(changes)
            _check_content(draft, catalog)
            db.execute('UPDATE ic_editor_drafts SET payload=? WHERE id=?', (_json(draft), identity))
            reports.append(_publish_draft(db, identity, 1, catalog, automatic=automation))
        return reports


def publications(kind, db_path=None):
    path = store._path(db_path).resolve()
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ic_editor_publications'").fetchone()
        if not table:
            return []
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM ic_editor_publications WHERE kind=? '
                                                       'ORDER BY date_to DESC, published_at DESC, id DESC', (kind,))]


def published_source_check(source_id, db_path=None):
    """Find the best available reading basis already recorded in an observation."""
    path = store._path(db_path).resolve()
    if not path.exists():
        return None
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ic_editor_publications'").fetchone():
            return None
        row = db.execute('''
            SELECT json_extract(source.value, '$.evidence_status'), json_extract(source.value, '$.news_genre'),
                   CASE WHEN json_array_length(entry.value, '$.sources') = 1
                        THEN json_extract(entry.value, '$.summary') END,
                   CASE WHEN json_array_length(entry.value, '$.sources') = 1
                        THEN json_extract(entry.value, '$.boundary') END
              FROM ic_editor_publications AS report,
                   json_each(report.payload, '$.entries') AS entry,
                   json_each(entry.value, '$.sources') AS source
             WHERE json_extract(source.value, '$.id') = ?
               AND json_extract(source.value, '$.evidence_status') IN ('original', 'original_summary', 'metadata', 'listing', 'excerpt', 'headline')
             ORDER BY CASE json_extract(source.value, '$.evidence_status')
                      WHEN 'original' THEN 0 WHEN 'original_summary' THEN 1 WHEN 'metadata' THEN 2 ELSE 3 END,
                      CASE WHEN json_array_length(entry.value, '$.sources') = 1 THEN 0 ELSE 1 END,
                      report.published_at DESC, report.id DESC
             LIMIT 1
        ''', (source_id,)).fetchone()
    if row:
        status, genre, summary, boundary = row
        result = {'status': status, 'genre': genre if genre in SOURCE_KINDS.values() and genre != SOURCE_KINDS['unconfirmed'] else None}
        if summary and status == 'original':
            result['summary'] = summary
            if boundary:
                result['boundary'] = boundary
        return result
    return None


def _distinct_daily_editions(reports):
    seen = set()
    for report in reports:
        sources = frozenset(
            source['id'] for entry in report.get('entries', ())
            for source in (entry.get('sources') or [entry['source']])
        )
        key = (sources, (report.get('automation') or {}).get('material_change')) if sources else report['id']
        if key not in seen:
            yield report
            seen.add(key)


def daily_with_editions(legacy, reports, version=None):
    if not reports:
        return legacy
    day = legacy['selected_day']
    dates = {row['date']: row for row in legacy['editions']}
    for row in reversed(reports):
        dates[row['date']] = {'date': row['date'], 'title': row['title']}
    editions = [row for row in reports if row['date'] == day]
    versions = [{key: row[key] for key in ('id', 'title', 'published_at')} for row in _distinct_daily_editions(editions)]
    if legacy['report'] and editions:
        versions.append({'id': 'original', 'title': legacy['report']['title']})
    report = legacy['report'] if version == 'original' or not editions else next((row for row in editions if row['id'] == version), editions[0])
    return {**legacy, 'editions': [dates[key] for key in sorted(dates, reverse=True)], 'report': report, 'versions': versions}



def weekly_with_editions(reports, original, *, day=None, version=None):
    fields = ('id', 'title', 'date', 'date_from', 'published_at')
    grouped = {}
    for report in reports:
        grouped.setdefault(report['date'], []).append({key: report[key] for key in fields})
    grouped.setdefault(original['date'], []).append(original)

    by_id = {report['id']: report for report in reports}
    requested = original if version == 'original' else by_id.get(version)
    dates = sorted(grouped, reverse=True)
    selected_day = day or (requested['date'] if requested else dates[0])
    versions = grouped.get(selected_day, [])
    selected = next((row for row in versions if row['id'] == version), versions[0] if versions else None)
    return {
        'selected_day': selected_day,
        'selected_version': selected['id'] if selected else None,
        'editions': [{key: grouped[date][0][key] for key in ('date', 'date_from', 'title')} for date in dates],
        'report': by_id.get(selected['id']) if selected else None,
        'versions': versions,
    }
