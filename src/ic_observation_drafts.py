"""Build source-linked observation drafts without a model or publication writes."""

from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
from itertools import combinations
import re
import unicodedata

from src.discovery import normalize_url
from src.ic_evidence import stored_reading_basis
from src.ic_observations import classify_for_observation
from src.ic_paper_notes import extract_abstract_notes
from src.ic_research import analyze


HEADLINE_WORDS = re.compile(r'\b[a-z][a-z0-9]{2,}\b', re.I)
STOP_WORDS = {'and', 'the', 'for', 'with', 'from', 'into', 'says', 'chip', 'chips', 'semiconductor', 'technologies'}
STAGE_WORDS = re.compile(
    r'\b(?:tape[- ]?out|packag\w*|liquid[- ]cool\w*|prototype|fabricat\w*|foundry|'
    r'deploy\w*|production|qualification|interoperab\w*|EUV|MOR|800V)\b|'
    r'投产|竣工|流片|量产|样片|封装|量産|実装|光刻|フォトレジスト|チップレット|MOR工場', re.I,
)
LOW_PRIORITY = re.compile(r'\b(?:revenue|profitability|award|chief executive|sponsored)\b|获奖|股价|会員限定|時代を彩った|個別化医療', re.I)


def _date(item):
    return date.fromisoformat(item['published_at']) if item.get('published_at') else None


def _words(item):
    normalized = unicodedata.normalize('NFKC', item['title']).casefold()
    return set(HEADLINE_WORDS.findall(normalized)) - STOP_WORDS


def possible_event_duplicates(items, existing):
    """Surface likely same-event headlines for review, never merge them here."""
    candidates = [item for item in items if item['content_type'] == 'news']
    new_ids = {item['id'] for item in candidates}
    corpus = candidates + [item for item in existing if item['content_type'] == 'news' and item['id'] not in new_ids]
    keys = {item['id']: (_date(item), _words(item)) for item in corpus}
    results = []
    for a, b in combinations(corpus, 2):
        if a['id'] not in new_ids and b['id'] not in new_ids:
            continue
        a_date, a_words = keys[a['id']]
        b_date, b_words = keys[b['id']]
        common = a_words & b_words
        if not a_date or not b_date or abs((a_date - b_date).days) > 3 or len(common) < 3:
            continue
        if len(common) / min(len(a_words), len(b_words)) >= .55 and len(common) / len(a_words | b_words) >= .34:
            results.append({'items': [_identity(a), _identity(b)], 'shared_title_words': sorted(common)})
    return results


def _identity(item):
    return {key: item.get(key) for key in ('id', 'title', 'source', 'url', 'published_at', 'content_type')}


def _latest_source_summary(item):
    if item['content_type'] != 'news' or item.get('summary_kind') == 'human':
        return item
    source_summaries = []
    for version in item.get('source_records', ()):
        record = version.get('record', {})
        url = record.get('url') or record.get('link')
        if version.get('origin') != 'collected' or not url or not record.get('summary'):
            continue
        if record.get('source') != item['source']:
            continue
        try:
            if normalize_url(url) == item['url']:
                source_summaries.append(record['summary'])
        except ValueError:
            continue
    # A stored editorial summary may differ from the original feed entry.
    # Only follow a later publisher update when the current summary came from that feed.
    if len(source_summaries) >= 2 and item.get('summary') in source_summaries[:-1]:
        return {**item, 'summary': source_summaries[-1]}
    return item


def _entry(item, catalog, already_known):
    item = _latest_source_summary(item)
    classified = {**item, 'ic_ai': analyze(item)} if item['content_type'] == 'paper' else item
    category = classify_for_observation(classified, catalog=catalog)
    note = extract_abstract_notes(item)
    text = (item.get('abstract_text') or item.get('summary')) if item['content_type'] == 'paper' else (
        item.get('summary') or item.get('abstract_text'))
    material = ' '.join((text or '').split())
    excerpt = material[:280].rstrip() + ('…' if len(material) > 280 else '')
    if note and note['points']:
        excerpt = note['points'][0]['text']
    review = ['确认实际进展、稿件性质和是否与已有事件重复'] if item['content_type'] == 'news' else ['核对实验设置、基线和适用范围']
    if category['basis'] == 'pending':
        review.append('确认归类或先保留为待归类线索')
    elif item['content_type'] == 'news' and category['topics']:
        title_only = classify_for_observation({**item, 'abstract_text': None, 'summary': ''}, catalog=catalog)
        if {t['id'] for t in category['topics']} - {t['id'] for t in title_only['topics']}:
            review.append('有专题仅在简介中命中，核对是否属于报道重点')
    return {**_identity(item), 'summary': excerpt, 'reading_basis': note['basis'] if note else stored_reading_basis(item),
            'paper_points': note['points'] if note else [],
            'material_digest': sha256(material.encode()).hexdigest() if material else None,
            'classification': category, 'in_library': item['id'] in already_known, 'review': review}


def _pick(entries, limit, *, spread=False):
    def key(entry):
        title = entry['title']
        return (not bool(LOW_PRIORITY.search(title)), bool(STAGE_WORDS.search(title)),
                bool(entry['summary']), entry['published_at'], entry['id'])

    queue = sorted(entries, key=key, reverse=True)
    picked = []
    categories_seen = set()
    if spread:
        for entry in queue:
            categories = {label['id'] for label in entry['classification']['categories']}
            if categories - categories_seen:
                picked.append(entry)
                categories_seen.update(categories)
            if len(picked) == limit:
                return picked
    return (picked + [entry for entry in queue if entry not in picked])[:limit]


def build_drafts(items, as_of, catalog, *, reference=(), known_ids=(), source_runs=()):
    start = as_of - timedelta(days=6)
    in_window = []
    undated = []
    for item in items:
        day = _date(item)
        if day is None:
            undated.append(_identity(item))
        elif start <= day <= as_of:
            in_window.append(item)
    entries = [_entry(item, catalog, known_ids) for item in in_window]
    entries.sort(key=lambda entry: (entry['published_at'], entry['id']), reverse=True)
    day_entries = [entry for entry in entries if entry['published_at'] == as_of.isoformat()]
    latest = entries[0]['published_at'] if entries and not day_entries else None
    candidate_pairs = possible_event_duplicates(in_window, reference)
    candidate_ids = {row['id'] for pair in candidate_pairs for row in pair['items']}
    for entry in entries:
        entry['possible_duplicate'] = entry['id'] in candidate_ids
    counts = Counter('未归类' if entry['classification']['basis'] == 'pending' else
                     '命中专题' if entry['classification']['topics'] else '仅大类' for entry in entries)
    return {
        'status': 'review_required', 'as_of': as_of.isoformat(), 'catalog_version': catalog['version'],
        'collection_runs': list(source_runs), 'input_records': len(items), 'in_window': len(entries),
        'already_in_library': sum(entry['in_library'] for entry in entries), 'classifications': dict(counts),
        'undated': undated, 'outside_window': len(items) - len(entries) - len(undated),
        'possible_event_duplicates': candidate_pairs, 'entries': entries,
        'daily': {'date': as_of.isoformat(), 'entries': _pick(day_entries, 3)},
        'latest_dated_sample': {'date': latest, 'entries': _pick([
            entry for entry in entries if entry['published_at'] == latest
        ], 3)} if latest else None,
        'weekly': {'date_from': start.isoformat(), 'date_to': as_of.isoformat(), 'entries': _pick(entries, 5, spread=True)},
    }


def render_markdown(report):
    def link(row):
        title = row['title'].replace('[', '\\[').replace(']', '\\]').replace('\n', ' ')
        return f"[{title}](<{row['url']}>)"

    def section(title, entries):
        lines.extend(['', f'## {title}', ''])
        if not entries:
            lines.append('本次采集批次在这一天没有可用于起草的条目。')
        for entry in entries:
            tags = [*entry['classification']['categories'], *entry['classification']['topics']]
            names = '、'.join(tag['name'] + ('（候选）' if tag.get('status') == 'candidate' else '') for tag in tags) or '未归入具体方向'
            basis = {'abstract': '作者摘要', 'abstract_excerpt': '摘要原句', 'stored_abstract': '已收录摘要或简介',
                     'bibliography': '论文题录', 'original_summary': '原文核对简述', 'excerpt': '来源简介',
                     'headline': '标题与来源链接', 'listing': '官方检索摘要或新闻列表'}.get(entry['reading_basis'], '资料摘录')
            flags = ' · 可能与其他报道同属一个事件' if entry['possible_duplicate'] else ''
            lines.append(f"- {link(entry)} · {entry['source']} · {entry['published_at']} · {names}{flags}")
            if entry['paper_points']:
                for point in entry['paper_points']:
                    lines.append(f"  - 摘要原句 · {point['label']} · {point['text']}")
            elif entry['summary']:
                lines.append(f"  - {basis} · {entry['summary']}")

    lines = [f"# 技术观察试跑 · {report['as_of']}", '',
             '规则生成草稿，待编辑确认。以下为本批采集资料的选材，依据原站题名、发布日期和公开简介。', '',
             '## 采集与归类', '',
             f"- 采集库共 {report['input_records']} 条。七天窗口内 {report['in_window']} 条，其中 {report['already_in_library']} 条与正式库的资料标识相同。",
             f"- 专题规则版本 {report['catalog_version']}。" + '、'.join(f'{name} {count} 条' for name, count in report['classifications'].items()) + '。',
             f"- 缺准确发布日期 {len(report['undated'])} 条，窗口外 {report['outside_window']} 条。"]
    for run in report['collection_runs']:
        label = {'success': '已采集', 'no_results': '无匹配条目', 'failed': '采集失败'}.get(run['status'], run['status'])
        lines.append(f"- {run['source_name']} · {run['found']} 条 · {label}" + (f" · {run['error']}" if run.get('error') else ''))

    section(f"今日观察草稿 · {report['daily']['date']}", report['daily']['entries'])
    if sample := report['latest_dated_sample']:
        section(f"最近有资料的一天 · {sample['date']}", sample['entries'])
    weekly = report['weekly']
    section(f"本周技术观察草稿 · {weekly['date_from']} 至 {weekly['date_to']}", weekly['entries'])
    categories = dict.fromkeys(tag['name'] for entry in weekly['entries'] for tag in entry['classification']['categories'])
    if categories:
        lines.extend(['', '本期选材涉及' + '、'.join(categories) + '。据此对照各条进展的验证阶段，再确定周报主线。'])
    papers = [entry for entry in report['entries'] if entry['content_type'] == 'paper']
    if papers:
        section('本批文献的摘要摘取', papers)
    lines.extend(['', '## 人工核对', '',
                  '- 核对报道与原始披露的关系、厂商指标的测试条件和文章实际描述的进展。',
                  '- 确认日报取舍及周报希望回答的问题。待归类条目可参与选材，是否新建专题由编辑判断。',
                  f"- 标题规则提示 {len(report['possible_event_duplicates'])} 对可能重复的事件，等核对原文后定案。"])
    for pair in report['possible_event_duplicates']:
        a, b = pair['items']
        lines.append(f"  - {link(a)} · {link(b)}")
    return '\n'.join(lines) + '\n'
