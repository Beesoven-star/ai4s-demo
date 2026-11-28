"""Bounded original-source lookup for selected technology observations."""

import asyncio
from collections import Counter
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import aiohttp

from scripts.collect_discovery import parse_crossref, parse_date, parse_feed, plain_text
from src import discovery
from src.ic_observations import SHANGHAI
from src.news_sources import NewsPage, walk_json

WEAK = {'excerpt', 'metadata', 'stored_summary', 'listing'}
PRIMARY_NEWS_GENRES = {'企业官方公告', '研究机构公告', '企业技术博客'}
ARTICLE_LIMIT = 640_000
INDEX_LIMIT = 1_500_000
MAX_PAGES = 4
DOI = re.compile(r'\b10\.\d{4,9}/[-._;()/:a-z0-9]{2,180}', re.I)
ARXIV = re.compile(r'(?:arxiv\.org/(?:abs|pdf)/|arxiv\s*:\s*)(\d{4}\.\d{4,5})(?:v\d+)?', re.I)
STOP = set('the of with and for from how its are this that have news release using leading advanced software technology html'.split())


def _url(value):
    try:
        parts = urlsplit(value)
        path = unquote(parts.path)
        if (parts.scheme == 'https' and parts.hostname and not (parts.username or parts.password) and parts.port in (None, 443)
                and not any(char in value or char in path for char in ('\\', '\r', '\n', '\t'))
                and not {'..', '.'}.intersection(path.split('/'))):
            return parts
    except ValueError:
        pass
    return None


async def _read(session, url, limit, types):
    if _url(url) is None:
        return ''
    try:
        async with session.get(url, allow_redirects=False) as response:
            if response.status != 200 or response.content_type not in types:
                return ''
            data = bytearray()
            async for chunk in response.content.iter_chunked(32768):
                if len(data) + len(chunk) > limit:
                    return ''
                data.extend(chunk)
            return data.decode('utf-8', errors='replace')
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return ''


def _tokens(text):
    return {word.removesuffix('s') for word in re.findall(r'[a-z][a-z0-9]{2,}', text.casefold()) if word not in STOP}


def _identifier_values(parts):
    text = unquote(' '.join(parts))
    dois = list(dict.fromkeys(match.group().rstrip('.,;)').casefold() for match in DOI.finditer(text)))
    papers = list(dict.fromkeys(ARXIV.findall(text)))
    return dois[:3], papers[:3]


def _same_path(parts, prefix):
    scope = _url(prefix)
    return scope and parts.hostname == scope.hostname and (
        parts.path == scope.path or parts.path.startswith(scope.path.rstrip('/') + '/'))


def _official_link(parts, source):
    settings = source.get('primary_evidence', {})
    scopes = settings.get('article_prefixes') or [source.get('homepage', source['url'])]
    if not any(_same_path(parts, prefix) for prefix in scopes) or not parts.path.strip('/'):
        return False
    return not parts.path.lower().endswith(('.pdf', '.xml', '.zip', '.jpg', '.png'))


def _candidate_url(parts):
    # Keep query selectors required by configured publishers.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))


def _official_material(html):
    page = NewsPage()
    page.feed(html)
    records = list(entry for root in page.jsonld for entry in walk_json(root))
    title = plain_text(page.meta.get('og:title') or ' '.join(page.headings or page.title))
    body = next((entry['articleBody'] for entry in records if isinstance(entry.get('articleBody'), str)), '')
    if not body:
        article = re.search(r'<(?:article|main)\b[^>]*>(.*?)</(?:article|main)>', html, re.I | re.S)
        content = article[1] if article else html
        paragraphs = re.findall(r'<p\b[^>]*>(.*?)</p>', content, re.I | re.S)
        body = '\n'.join(text for paragraph in paragraphs if len(text := plain_text(paragraph)) >= 65)
    else:
        body = plain_text(body)
    published = next((entry.get('datePublished') for entry in records if entry.get('datePublished')), None)
    return title, body[:7000], parse_date(published or page.meta.get('article:published_time'), target_timezone=SHANGHAI)


async def _index_links(session, source, cache):
    settings = source.get('primary_evidence', {})
    sitemap = settings.get('sitemap')
    if not sitemap:
        return []
    if sitemap not in cache:
        xml = await _read(session, sitemap, INDEX_LIMIT, {'application/xml', 'text/xml'})
        if not xml:
            xml = await _read(session, sitemap, INDEX_LIMIT, {'application/xml', 'text/xml'})
        try:
            cache[sitemap] = [parts for node in ElementTree.fromstring(xml).iter() if node.tag.rsplit('}', 1)[-1] == 'loc'
                              and node.text and (parts := _url(node.text.strip())) and _official_link(parts, source)]
        except ElementTree.ParseError:
            cache[sitemap] = []
    return cache[sitemap]


def _match_index(links, query):
    terms = _tokens(query)
    candidates = [(parts, terms & _tokens(parts.path)) for parts in links]
    frequency = Counter(term for _, words in candidates for term in words)
    ordered = sorted(((sum(1 / frequency[term] for term in words), len(words), parts.path, parts)
                      for parts, words in candidates if words), key=lambda row: row[:3], reverse=True)
    return [parts for _, _, _, parts in ordered[:MAX_PAGES]]


async def _official_options(session, article, links, sources, cache):
    query = f"{article['title']} {article.get('summary', '')}"
    direct = []
    for link in links:
        try:
            parts = _url(urljoin(article['url'], link))
        except ValueError:
            continue
        if parts:
            direct.append(parts)
    for source in sources:
        matches = [parts for parts in direct if _official_link(parts, source)]
        hint = source.get('primary_evidence', {}).get('mentions')
        if hint and re.search(hint, query, re.I) and len(matches) < MAX_PAGES:
            matches.extend(_match_index(await _index_links(session, source, cache), query))
        urls = list(dict.fromkeys(_candidate_url(parts) for parts in matches))
        for url in urls:
            if url == article['url']:
                continue
            yield source, url


def _paper_scope(item, sources):
    return any(item.get('source') == source['name'] or (
        source.get('journal_name') and (item.get('journal') or '').casefold() == source['journal_name'].casefold())
        for source in sources)


def _stored_papers(db_path, dois, arxiv, sources):
    if not (dois or arxiv):
        return []
    with closing(discovery._connect(db_path)) as db:
        rows = db.execute(
            "SELECT payload FROM discovery_items WHERE content_type='paper' AND "
            "(lower(json_extract(payload,'$.doi')) IN (SELECT value FROM json_each(?)) OR "
            "json_extract(payload,'$.arxiv_id') IN (SELECT value FROM json_each(?)))",
            (json.dumps(dois), json.dumps(arxiv))).fetchall()
    return [item for (payload,) in rows if (item := json.loads(payload)).get('abstract_text') and _paper_scope(item, sources)]


async def _online_papers(session, dois, arxiv, sources):
    stamp = datetime.now(SHANGHAI).isoformat()
    crossref = [source for source in sources if source.get('kind') in {'crossref_journal', 'crossref_conference'}
                and (endpoint := _url(source['url'])) and endpoint.hostname == 'api.crossref.org']
    if crossref:
        for doi in dois:
            payload = await _read(session, 'https://api.crossref.org/works/' + quote(doi, safe='/'),
                                  ARTICLE_LIMIT, {'application/json'})
            if payload:
                try:
                    response = json.loads(payload)
                    record = response['message']
                    parsed = json.dumps({'status': response.get('status'), 'message': {'items': [record]}})
                    for source in crossref:
                        if source['kind'] == 'crossref_journal' and source.get('issn') not in record.get('ISSN', []):
                            continue
                        items = parse_crossref(parsed, source, stamp)
                        item = next((row for row in items if (row.get('doi') or '').casefold() == doi and row.get('abstract_text')), None)
                        if item:
                            yield item
                            break
                except (ValueError, KeyError, TypeError):
                    continue
    arxiv_source = next((source for source in sources if source.get('kind') == 'arxiv' and _url(source['url'])), None)
    if arxiv_source and arxiv:
        payload = await _read(session, arxiv_source['url'] + '?id_list=' + quote(','.join(arxiv)),
                              ARTICLE_LIMIT, {'text/xml', 'application/xml', 'application/atom+xml'})
        if payload:
            try:
                for item in parse_feed(payload.encode(), arxiv_source, stamp):
                    if item.get('arxiv_id') in arxiv and item.get('abstract_text'):
                        yield item
            except (ElementTree.ParseError, ValueError):
                pass


async def lookup(article_batch, config_path, db_path, cutoff):
    """Return primary candidates grouped by selected media ID."""
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    enabled = [source for source in config['sources'] if source.get('enabled', True)]
    officials = [source for source in enabled if source.get('news_genre') in PRIMARY_NEWS_GENRES]
    papers = [source for source in enabled if source.get('content_type') == 'paper']
    cache = {}
    output = {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8),
                                     headers={'User-Agent': 'AI4SResearchWorkbench/0.1 (public source metadata)'}) as session:
        for article, material in article_batch:
            links = material.get('links', ())
            dois, arxiv = _identifier_values([article['title'], material['text'], *links])
            candidates = {}
            for item in _stored_papers(db_path, dois, arxiv, papers):
                if item.get('published_at') and item['published_at'] <= cutoff:
                    candidates[item['url']] = (item, 'abstract', item['abstract_text'][:5000])
            if (dois or arxiv) and not candidates:
                async for item in _online_papers(session, dois, arxiv, papers):
                    if item.get('published_at') and item['published_at'] <= cutoff:
                        candidates[item['url']] = (item, 'abstract', item['abstract_text'][:5000])
            pages = []
            async for source, url in _official_options(session, article, links, officials, cache):
                pages.append((source, url))
                if len(pages) >= MAX_PAGES:
                    break
            documents = await asyncio.gather(*(_read(session, url, ARTICLE_LIMIT, {'text/html'}) for _, url in pages))
            for (source, url), html in zip(pages, documents, strict=True):
                if not html:
                    continue
                title, body, published = _official_material(html)
                if not title or len(body) < 120 or (published and published > cutoff):
                    continue
                if not published and cutoff < datetime.now(SHANGHAI).date().isoformat():
                    continue
                item = {'title': title, 'source': source['name'], 'url': url, 'published_at': published, 'content_type': 'news'}
                candidates[url] = (item, 'original', body)
            output[article['id']] = list(candidates.values())
    return output
