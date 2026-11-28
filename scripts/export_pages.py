"""Export only public display fields, reading the IC database in read-only mode."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ic_research import analyze, latest_paper_dates, TOPICS, TRACKS, VERSION
from src.publication_timing import assess, statistics
from src.research_analysis import news_analysis
from src.ic_briefing import briefing, event_briefs_by_source, load_snapshot
from src.ic_observations import classify_for_observation, export_daily_editions, public_catalog
from src.ic_paper_notes import paper_reading_notes
from src.ic_editor import publications
from src import ic_hotspots, ic_topic_evaluation, ic_topics

ITEM_FIELDS = '''id content_type origin sample_role title authors source journal venue_type venue_name
conference_year track url doi arxiv_id published_at publication_year publication_month news_genre
news_scope news_scope_reason publication_status date_kind collected_at summary summary_kind
abstract_text abstract_provenance reading_notes topics methods views relevance verification_note verification_mode'''.split()
RUN_FIELDS = 'id status created_at finished_at filters matched_count source_count counts model report'.split()
SOURCE_FIELDS = '''ref id content_type title source url doi arxiv_id published_at publication_month
publication_year collected_at venue_type venue excerpt excerpt_truncated evidence_quality tracks topics classification_basis'''.split()
TOPIC_FIELDS = '''id name overview question follow_up seeded established category_id
status merged_into latest_progress reviewed_through event_count latest_event'''.split()
EVENT_FIELDS = 'id title summary boundary date stage'.split()
STAGE_CHANGE_FIELDS = 'id date from_stage to_stage summary boundary source_id evidence'.split()
TOPIC_SOURCE_FIELDS = 'id title source url published_at content_type news_genre reading_basis verified_excerpt'.split()


def pick(data, fields):
    return {key: data[key] for key in fields if key in data}


def export_topics(database, cards, today):
    index = [pick(topic, TOPIC_FIELDS + ['in_directory', 'evaluation_status'])
             for topic in ic_topic_evaluation.topic_directory(database, cards=cards, today=today)]
    details = {}
    for topic in ic_topics.get_topics(database, today):
        detail = pick(topic, TOPIC_FIELDS)
        detail['events'] = [
            pick(event, EVENT_FIELDS) | {'sources': [pick(source, TOPIC_SOURCE_FIELDS) for source in event['sources']],
                                         'stage_changes': [pick(change, STAGE_CHANGE_FIELDS)
                                                           for change in event.get('stage_changes', ())]}
            for event in topic['events'] if event['date'] <= today.isoformat()
        ]
        if card := cards.get(topic['id']):
            detail['evaluation'] = card
        details[topic['id']] = detail
    return {'topics': index, 'details': details, 'cool_days': ic_topics.COOL_DAYS}


def export_snapshot(database, output, *, published_analysis=None):
    stamp = datetime.now(timezone(timedelta(hours=8)))
    today = stamp.date()
    catalog = ic_topics.discovery_catalog(database)
    # Never initialize/migrate the DB, load credentials, or query personal_library.
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN')
        rows = connection.execute('SELECT payload,created_at FROM discovery_items ORDER BY published_date DESC,created_at DESC,id').fetchall()
        items = []
        for row in rows:
            raw = json.loads(row['payload'])
            item = pick(raw, ITEM_FIELDS)
            item['created_at'] = row['created_at']
            item['ic_ai'] = analyze(raw)
            item['observation_classification'] = classify_for_observation({**raw, 'ic_ai': item['ic_ai']}, catalog=catalog)
            if reading_notes := paper_reading_notes(raw):
                item['reading_notes'] = reading_notes
            selection = item['ic_ai'] if raw['content_type'] == 'paper' else news_analysis(raw)
            item['analysis_classification'] = pick(selection, ('tracks', 'topic_ids', 'topics', 'scope', 'reviewed_on'))
            item['publication_timing'] = assess(raw, today)
            items.append(item)
        has_reports = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_analysis_runs'").fetchone()
        reports = [] if published_analysis is None else published_analysis
        if has_reports and published_analysis is None:
            for row in connection.execute('SELECT payload FROM research_analysis_runs ORDER BY created_at DESC,id'):
                raw = json.loads(row['payload'])
                if raw.get('status') == 'success' and raw.get('report'):
                    report = pick(raw, RUN_FIELDS)
                    report['sources'] = [pick(source, SOURCE_FIELDS) for source in raw.get('sources', [])]
                    reports.append(report)
    finally:
        connection.close()
    papers = [item for item in items if item['content_type'] == 'paper']
    news = [item for item in items if item['content_type'] == 'news']
    main = [item for item in papers if item['ic_ai']['scope'] == 'main']
    scopes = Counter(item['ic_ai']['scope'] for item in papers)
    archived_news = sum(item.get('news_scope') == 'archive' for item in news)
    new_today = [item for item in items if item.get('collected_at', '')[:10] == today.isoformat()]
    facets = {
        'domain': 'ic', 'total': len(items), 'papers': len(papers), 'news': len(news) - archived_news,
        'news_candidates': len(news), 'archived_news': archived_news,
        'seed': sum(item['origin'] == 'seed' for item in items),
        'collected': sum(item['origin'] == 'collected' for item in items),
        'today': today.isoformat(), 'new_today': len(new_today),
        'papers_today': sum(item['content_type'] == 'paper' for item in new_today),
        'news_today': sum(item['content_type'] == 'news' for item in new_today),
        'topics': [topic['name'] for topic in TOPICS], 'research_tracks': TRACKS,
        'venues': sorted({item.get('venue_name') or item.get('journal') for item in items if item.get('venue_name') or item.get('journal')}),
        'literature_scopes': dict(scopes), 'main_papers': scopes['main'], 'archive_papers': scopes['archive'],
        'latest_paper_dates': latest_paper_dates(((item, item['ic_ai']['scope']) for item in papers), today.isoformat()),
        'pending_papers': scopes['pending'], 'excluded_papers': scopes['excluded'],
        'publication_audit': statistics([item for item in papers if item['ic_ai']['scope'] != 'excluded'], today),
    }
    counts = {
        'total': len(papers), 'main': scopes['main'], 'archive': scopes['archive'],
        'excluded': scopes['excluded'], 'unconfirmed': scopes['pending'],
        **{track: sum(track in item['ic_ai']['tracks'] for item in main) for track in TRACKS},
        'both': sum({'ai_for_ic', 'ic_for_ai'} <= set(item['ic_ai']['tracks']) for item in main),
        'ai_candidates': sum(bool({'ai_for_ic', 'ic_for_ai'} & set(item['ic_ai']['tracks'])) for item in main),
    }
    snapshot = {
        'schema_version': 1, 'exported_at': stamp.isoformat(timespec='seconds'), 'items': items,
        'facets': facets, 'reports': reports,
        'exploration': {
            'version': VERSION, 'screened_on': today.isoformat(), 'tracks': TRACKS, 'counts': counts,
            'topics': [{**topic, 'count': sum(topic['id'] in item['ic_ai']['topic_ids'] for item in main)} for topic in TOPICS],
            'note': '按题名与可用原始摘要保留逐项范围依据；允许跨专题，数量不代表研究热度，未逐篇核验全文。',
        },
    }
    editorial = load_snapshot()
    # Do not publish dangling in-app references from a partial database export.
    if set(editorial['sources']) <= {item['id'] for item in items}:
        catalog = public_catalog(catalog)
        cards = ic_topic_evaluation.published_cards(database)
        snapshot['ic_topics'] = export_topics(database, cards, today)
        snapshot['ic_briefing'] = {
            str(days): {**ic_topic_evaluation.with_ranked_evaluations(briefing(days, editorial), database),
                        'topic_catalog': catalog}
            for days in (7, 30)
        }
        snapshot['ic_rankings'] = {
            str(days): {**ic_topic_evaluation.with_ranked_evaluations(
                ic_hotspots.rolling_briefing(days, database, as_of=today), database), 'topic_catalog': catalog}
            for days in (7, 30)
        }
        event_briefs = event_briefs_by_source(editorial)
        for item in news:
            if related := event_briefs.get(item['id']):
                item['event_briefs'] = related
    snapshot['daily_observations'] = sorted([*publications('daily', database), *export_daily_editions()],
                                           key=lambda row: (row['date'], row.get('published_at', '')), reverse=True)
    snapshot['weekly_observations'] = publications('weekly', database)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temporary.replace(output)
    print(f'Exported {len(papers)} papers, {len(news)} news, {len(reports)} completed reports -> {output}')
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'news-data/discovery-ic.sqlite')
    parser.add_argument('--output', type=Path, default=ROOT / 'web/public-pages/data/snapshot.json')
    parser.add_argument('--keep-public-analysis', type=Path,
                        help='Reuse the analysis archive from a previously published snapshot')
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error(f'Database not found: {args.database}')
    published_analysis = (json.loads(args.keep_public_analysis.read_text(encoding='utf-8'))['reports']
                          if args.keep_public_analysis else None)
    export_snapshot(args.database, args.output, published_analysis=published_analysis)


if __name__ == '__main__':
    main()
