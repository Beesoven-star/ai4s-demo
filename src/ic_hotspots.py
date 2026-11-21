"""Rolling coverage from saved IC news and existing event/source judgments."""

from contextlib import closing
from datetime import date, datetime, timedelta
import json
import re
import sqlite3
from urllib.parse import urlsplit

from src import discovery, ic_editor, ic_topics
from src.ic_briefing import briefing, load_snapshot
from src.ic_evidence import stored_reading_basis


COPY_LOOKBACK = 7
ORIGINAL = {'original', 'original_summary'}
MEDIA_GENRE = re.compile(r'专业媒体|署名|独立报道|独立采访|技术分析')
EXCLUDED_GENRE = re.compile(r'公告|企业官方|厂商(?:供稿|白皮书|技术资料|技术文章|披露报道|问答)|企业技术博客|协会|二手|转载|转述|同稿|赞助|宣传|评选|速览|预告|快讯汇总')
DISCLOSURE = re.compile(r'联合公告|企业(?:公告|官方)|机构或厂商披露|企业说明会')
COPY_NOTICE = re.compile(
    r'转载自|转引自|原载于|本文(?:系转载|由.{0,24}供稿)|稿件由.{0,24}提供|IC风云榜候选企业'
    r'|(?:originally (?:published|appeared) (?:on|in)|reprinted (?:from|with permission)|'
    r'republished (?:from|with permission)|sponsored (?:content|by)|paid partnership|press release\s*[:—])',
    re.I,
)
# The same organization can appear on its mobile and desktop subdomains.
ORGANIZATION_ALIASES = {'laoyaoba.com': 'ijiwei.com'}
COLLABORATION = re.compile(r'\b(?:partner(?:s|ed)?|team(?:s|ed)? up|collaborat(?:e|es|ed))\s+(?:to|on|with|for)\b', re.I)
GENERIC_PARTY = {'and', 'the', 'inc', 'corp', 'technology', 'technologies', 'solutions', 'systems', 'group'}
GENERIC_ACTION = {'the', 'and', 'with', 'into', 'from', 'their', 'data', 'center', 'scale'}


def _url_key(url):
    parts = urlsplit(discovery.normalize_url(url))
    host = parts.netloc.removeprefix('www.')
    return host, parts.path.rstrip('/'), parts.query


def _organization_key(source):
    host = (urlsplit(source['url']).hostname or '').removeprefix('www.')
    host = host.removeprefix('m.').removeprefix('amp.')
    return ORGANIZATION_ALIASES.get(host, host)


def _stored_material(db_path, start, end):
    path = discovery._path(db_path).resolve()
    if not path.exists():
        return [], []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        db.execute('BEGIN')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        news = [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM discovery_items WHERE content_type='news' AND published_date BETWEEN ? AND ? "
            "ORDER BY published_date,id", (start, end))] if 'discovery_items' in tables else []
        editions = [json.loads(row[0]) for row in db.execute(
            'SELECT payload FROM ic_editor_publications WHERE date_to BETWEEN ? AND ? '
            'ORDER BY published_at DESC,id DESC', (start, end))] if 'ic_editor_publications' in tables else []
    return news, editions


def _reviews(editions):
    results = {}
    for edition in editions:
        for entry in edition['entries']:
            for source in entry.get('sources', ()):
                genre = source.get('news_genre')
                if source.get('content_type') != 'news' or genre in (None, ic_editor.SOURCE_KINDS['unconfirmed']):
                    continue
                basis = source.get('evidence_status')
                grade = 2 if basis in ORIGINAL or not edition.get('automation') else 1
                identity = source['id']
                previous = results.get(identity, (0, None, None))
                if grade > previous[0]:
                    results[identity] = grade, genre, basis
    return results


def _source(item, review):
    genre = item.get('news_genre') or ''
    summary = (item.get('summary') or item.get('abstract_text') or '').strip()
    _, reviewed_genre, reviewed_basis = review
    basis = reviewed_basis if reviewed_basis in ORIGINAL else stored_reading_basis(item)
    excluded = (item.get('news_scope') == 'archive' or not ic_topics._eligible(item)
                or bool(EXCLUDED_GENRE.search(genre) or COPY_NOTICE.search(item['title'] + '\n' + summary))
                or reviewed_genre in {ic_editor.SOURCE_KINDS[k] for k in ('official', 'reprint', 'background')})
    reporting = reviewed_genre == ic_editor.SOURCE_KINDS['reporting']
    signed = genre.startswith('署名')
    eligible = not excluded and (signed or (reporting and basis in ORIGINAL)
                                  or ('待核验' not in genre and bool(MEDIA_GENRE.search(genre))
                                      and len(ic_topics._name_key(summary)) >= 48
                                      and basis in {*ORIGINAL, 'excerpt'}))
    proof = '原文核对' if basis in ORIGINAL else '已收录来源简介' if summary else '已收录标题'
    return {k: item.get(k) for k in ('id', 'content_type', 'title', 'source', 'url', 'published_at', 'publication_month',
                                    'venue_type', 'news_genre')} | {
        'excerpt': summary, 'evidence_kind': proof, 'organization': _organization_key(item),
        'attention_eligible': eligible,
        'attention_note': proof + ('。按媒体机构计入关注度。' if eligible else '。本条未计入独立媒体覆盖。'),
    }


def _suppress_copies(sources, original_texts, curated, cutoff):
    # Only compare source wording. Editorial summaries can resemble each other even for independent reports.
    used = {}
    for identity, article in sorted(sources.items(), key=lambda pair: (
            pair[1].get('published_at') or '', not DISCLOSURE.search(pair[1].get('news_genre') or ''),
            pair[0] not in curated, pair[0])):
        day = article.get('published_at') or ''
        body = original_texts.get(identity, '')
        if not day or day < cutoff or len(body) < 90:
            continue
        signature = body[:90]
        previous = used.get(signature)
        if not previous or (date.fromisoformat(day) - date.fromisoformat(previous)).days > COPY_LOOKBACK:
            if article['attention_eligible'] or DISCLOSURE.search(article.get('news_genre') or ''):
                used[signature] = day
        elif identity not in curated:
            article.update(attention_eligible=False, attention_note='已收录简介与另一篇稿件同文，只计算原有覆盖。')


def _event_signals(article, original):
    title = article['title']
    parties = subject = frozenset()
    if match := COLLABORATION.search(title):
        parties = frozenset(re.findall(r'[a-z]{3,}', title[:match.start()].casefold())) - GENERIC_PARTY
        subject = frozenset(re.findall(r'[a-z]{3,}', title[match.end():].casefold())) - GENERIC_ACTION
    key = ic_topics._name_key(title)
    return date.fromisoformat(article['published_at']), key, frozenset(re.findall(r'\d+', key)), original, parties, subject


def _similar_reports(left, right):
    day, title, numbers, intro, parties, subject = left
    other_day, other_title, other_numbers, other_intro, other_parties, other_subject = right
    gap = abs((day - other_day).days)
    if gap > COPY_LOOKBACK:
        return False
    if len(intro) >= 90 and intro[:90] == other_intro[:90]:
        return True
    if gap <= 3 and len(parties) >= 2 and parties == other_parties and subject & other_subject:
        return True
    return numbers == other_numbers and ic_topics._same_event(title, other_title)


def rolling_briefing(days, db_path=None, *, as_of=None):
    """Read committed collection results, without collecting again or modifying editions."""
    today = as_of or datetime.now(discovery.LOCAL_TZ).date()
    end = today.isoformat()
    cutoff = (today - timedelta(days=29 + COPY_LOOKBACK)).isoformat()
    edition = load_snapshot()
    sources = edition['sources']
    curated = set(sources)
    news, editions = _stored_material(db_path, cutoff, end)
    reviews = _reviews(editions)
    aliases = {identity: identity for identity in sources}
    urls = {_url_key(row['url']): identity for identity, row in sources.items() if row['content_type'] == 'news'}
    originals = {}
    for item in news:
        identity = item['id']
        key = _url_key(item['url'])
        canonical = urls.setdefault(key, identity)
        aliases[identity] = canonical
        if item.get('summary_kind') == 'source':
            originals[canonical] = ic_topics._name_key(item.get('summary') or item.get('abstract_text') or '')
        if canonical not in sources:
            sources[canonical] = _source(item, reviews.get(identity, (0, None, None)))
    _suppress_copies(sources, originals, curated, cutoff)
    for article in sources.values():
        if article['content_type'] == 'news':
            article['organization'] = _organization_key(article)

    events = {event['id']: event for event in edition['events']}
    memberships = {key: event['id'] for event in events.values() for key in event['source_ids']}
    technologies = {row['id'] for row in edition['technologies']}
    # Close titles only provide a fallback to the event groups already saved by the workflow.
    headlines = {
        key: _event_signals(article, originals.get(key, ''))
        for key, article in sources.items() if article['content_type'] == 'news'
        and cutoff <= (article.get('published_at') or '') <= end
    }

    def attach(title, material_ids, topic_id=None):
        keys = list(dict.fromkeys(aliases[key] for key in material_ids if key in aliases and aliases[key] in headlines))
        if not keys:
            return
        anchors = {memberships[key] for key in keys if key in memberships}
        if not anchors:
            for prior, event_id in memberships.items():
                if prior not in headlines:
                    continue
                if any(_similar_reports(headlines[key], headlines[prior]) for key in keys):
                    anchors.add(event_id)
        if len(anchors) > 1:
            # Keep both established events separate when a saved group crosses them.
            return
        if anchors:
            event = events[anchors.pop()]
        else:
            primary = next((key for key in keys if sources[key]['attention_eligible']), None)
            if primary is None:
                return
            event = {'id': 'live-' + primary, 'title': title, 'technology_ids': [], 'source_ids': [],
                     'kind': 'event', 'grouping_note': '', 'occurred_at': None, 'date_basis': 'report_dates'}
            events[event['id']] = event
        for key in keys:
            if key not in memberships:
                event['source_ids'].append(key)
                memberships[key] = event['id']
        if topic_id:
            field = 'technology_ids' if topic_id in technologies else 'tracked_topic_ids'
            if topic_id not in event.setdefault(field, []):
                event[field].append(topic_id)

    for topic in ic_topics.get_topics(db_path, today):
        if topic['status'] == 'merged':
            continue
        for event in topic['events']:
            attach(event['title'], (row['id'] for row in event['sources']), topic['id'])
    for edition_row in editions:
        for entry in edition_row['entries']:
            attach(entry['title'], (row['id'] for row in entry.get('sources', ())))
    for key in headlines:
        if key not in memberships and sources[key]['attention_eligible']:
            attach(sources[key]['title'], [key])
    for key in headlines:
        if key not in memberships and key not in curated:
            attach(sources[key]['title'], [key])
    edition['events'] = list(events.values())
    edition['data_through'] = end
    return briefing(days, edition)
