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
HBM_WEEKLY = 'hbm_weekly'


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


def calendar_week(day):
    monday = date.fromisoformat(day) if isinstance(day, str) else day
    monday -= timedelta(days=monday.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


def stage_batch(report, batch_id, *, label, stamp=None, db_path=None, kinds=('daily', 'weekly'), natural_week=False):
    """Create observation drafts without rewriting edits on replay."""
    if not set(kinds) <= {'daily', 'weekly'}:
        raise ValueError('仅支持生成日报和自然周周报。')
    created = stamp or datetime.now(SHANGHAI).isoformat()
    ids = []
    with closing(store._connect(db_path)) as db, db:
        for kind in kinds:
            raw = report[kind]
            start, end = (raw['date'], raw['date']) if kind == 'daily' else (raw['date_from'], raw['date_to'])
            week_end = None
            if kind == 'weekly' and natural_week:
                start, week_end = calendar_week(end)
            candidates = {row['id']: row for row in report['entries'] if start <= row['published_at'] <= end}
            suggestions = []
            for pair in report['possible_event_duplicates']:
                a, b = pair['items']
                if not (start <= a['published_at'] <= end and start <= b['published_at'] <= end):
                    continue
                for row in (a, b):
                    candidates.setdefault(row['id'], {**row, 'summary': '', 'classification': {'topics': [], 'categories': []}})
                suggestions.append([a['id'], b['id']])
            entries = [row for row in raw['entries'] if row['id'] in candidates]
            identity = f'{batch_id}-{kind}'
            heading = {'daily': '今日观察', 'weekly': '本周技术观察'}[kind]
            draft = {'id': identity, 'kind': kind, 'date_from': start, 'date_to': end, 'label': label,
                     'title': f'{heading} · {end}',
                     'intro': f'本期选取 {len(entries)} 条集成电路进展。' if entries else '',
                     'catalog_version': report['catalog_version'], 'collection_runs': [
                         {key: run.get(key) for key in ('source_name', 'status', 'found', 'error')}
                         for run in report['collection_runs']],
                     'candidates': list(candidates.values()), 'suggestions': suggestions, 'source_reviews': {},
                     'entries': [{'title': row['title'], 'summary': row['summary'], 'source_ids': [row['id']],
                                  'topic_ids': [topic['id'] for topic in row['classification']['topics']]}
                                 for row in entries]}
            if week_end:
                draft['week_end'] = week_end
            db.execute('INSERT OR IGNORE INTO ic_editor_drafts VALUES (?, ?, 1, NULL, ?)',
                       (identity, created, _json(draft)))
            ids.append(identity)
    return ids


def stage_completed_collection(job, db_path, *, kinds=('daily', 'weekly')):
    end = date.fromisoformat(job['window_end'])
    start = end - timedelta(days=6)
    with closing(store._connect(db_path)) as db:
        rows = [json.loads(row[0]) for row in db.execute('SELECT payload FROM discovery_items WHERE published_date BETWEEN ? AND ?',
                                                       ((start - timedelta(days=3)).isoformat(), end.isoformat()))]
    items = [row for row in rows if row['published_at'] >= start.isoformat() and row.get('news_scope') != 'archive']
    earlier = [row for row in rows if row['published_at'] < start.isoformat() and row.get('news_scope') != 'archive']
    report = build_drafts(items, end, ic_topics.discovery_catalog(db_path), reference=earlier, source_runs=job['runs'])
    return stage_batch(report, job['id'], label=f'采集后整理 · 新增 {job["inserted"]} 条', stamp=job['finished_at'],
                       db_path=db_path, kinds=kinds, natural_week=True)


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
    if draft['kind'] == HBM_WEEKLY:
        raise EditionConflict('HBM 专题周报已停用。')
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


def calendar_publication(db, week_end):
    row = db.execute("""SELECT payload FROM ic_editor_publications WHERE kind='weekly' AND date_to=?
                    AND json_extract(payload,'$.coverage_through') IS NOT NULL LIMIT 1""", (week_end,)).fetchone()
    return json.loads(row[0]) if row else None


def _entry_sources(entry):
    return entry.get('sources') or [entry['source']]


def _normalize_calendar_report(report, start, end):
    return {**report, 'date_from': start, 'date': end, 'coverage_through': report['date'],
            'entries': [entry for entry in report.get('entries', ()) if all(
                start <= (source.get('published_at') or '') <= report['date'] for source in _entry_sources(entry))]}


def adopt_calendar_publication(draft, db_path):
    """Continue the most recent usable rolling issue when a week is first converted."""
    if not draft.get('week_end'):
        return
    start, end = draft['date_from'], draft['week_end']
    with closing(store._connect(db_path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if calendar_publication(db, end):
            return
        for (payload,) in db.execute("""SELECT payload FROM ic_editor_publications WHERE kind='weekly'
                                        AND date_to BETWEEN ? AND ? ORDER BY date_to DESC,published_at DESC,id DESC""", (start, end)):
            report = _normalize_calendar_report(json.loads(payload), start, end)
            if report['entries']:
                db.execute('UPDATE ic_editor_publications SET date_to=?,payload=? WHERE id=?', (end, _json(report), report['id']))
                return


def _merge_week_entries(previous, updates, targets):
    entries = list(previous['entries'])
    slots = [target for target in targets if target is not None]
    if len(slots) != len(set(slots)) or any(not 1 <= target <= len(entries) for target in slots):
        raise ValueError('周报更新的条目编号无效。')
    for entry, target in zip(updates, targets, strict=True):
        if target is None:
            entries.append(entry)
        else:
            entries[target - 1] = entry
    keys = [source['id'] for entry in entries for source in _entry_sources(entry)]
    if len(set(keys)) != len(keys):
        raise ValueError('周报更新重复引用了已有出处，请更新对应条目。')
    return entries


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
        return _published_report(db, draft)
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
    if week_end := draft.get('week_end'):
        previous = calendar_publication(db, week_end)
        if automatic and draft.get('weekly_base') != (previous and previous['published_at']):
            raise EditionConflict('本周周报已经更新，请基于最新版重新整理。')
        if previous and draft['date_to'] < previous['coverage_through']:
            raise EditionConflict('这次采集早于本周已发布的资料。')
        report.update(date=week_end, coverage_through=draft['date_to'])
        if previous:
            report['id'] = previous['id']
            if automatic:
                report.update(title=previous['title'], intro=previous['intro'],
                              entries=_merge_week_entries(previous, entries, [row.get('update_entry') for row in draft['entries']]))
        draft['publication_id'] = report['id']
    db.execute('''INSERT INTO ic_editor_publications VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET date_to=excluded.date_to,published_at=excluded.published_at,payload=excluded.payload''',
               (report['id'], draft['kind'], report['date'], published_at, _json(report)))
    db.execute('UPDATE ic_editor_drafts SET revision=revision+1, published_at=?, payload=? WHERE id=?',
               (published_at, _json({k: v for k, v in draft.items() if k not in ('revision', 'created_at', 'published_at')}), identity))
    return report


def _published_report(db, draft):
    identity = draft.get('publication_id', draft['id'])
    return json.loads(db.execute('SELECT payload FROM ic_editor_publications WHERE id=?', (identity,)).fetchone()[0])


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
                reports.append(_published_report(db, draft))
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


def calendar_week_archive(reports, original=None, *, day=None, version=None):
    by_id = {report['id']: report for report in reports}
    issues = {}
    for row in reports:
        _, end = calendar_week(row['date'])
        if end not in issues or (row.get('coverage_through') and not issues[end].get('coverage_through')):
            issues[end] = row
    if original:
        issues.setdefault(calendar_week(original['date'])[1], original)
    requested = original if version == 'original' else by_id.get(version)
    dates = sorted(issues, reverse=True)
    selection = day or (requested and requested['date'])
    selected_day = calendar_week(selection)[1] if selection else next(iter(dates), '')
    selected = issues.get(selected_day)
    if original and version == 'original' and selected_day == calendar_week(original['date'])[1]:
        selected = original
    report = by_id.get(selected['id']) if selected else None
    if report and not report.get('coverage_through'):
        report = _normalize_calendar_report(report, *calendar_week(report['date']))
    return {
        'selected_day': selected_day,
        'selected_version': selected['id'] if selected else None,
        'editions': [{'date': end, 'date_from': calendar_week(end)[0], 'title': issues[end]['title']} for end in dates],
        'report': report,
        'versions': [],
    }
