"""Public HTML news metadata; publish dates only, no inferred event dates."""
from html.parser import HTMLParser
import json,re
from urllib.parse import urljoin,urlparse


def collect_feed_history(source, start, collected_at, request_bytes, timeout, max_bytes, run_info):
    """Read a bounded RSS history, stopping when its oldest date passes start.

    A failed history page must remain visible even if the front page succeeds.
    Publication dates always come from the feed, never the requested window.
    """
    from datetime import date
    from scripts.collect_discovery import parse_feed
    template = source.get('history_page_url')
    maximum = min(max(int(source.get('max_feed_pages', 1)), 1), 20) if template else 1
    items, pages, errors, seen = [], [], [], set()
    reached_start = False
    for page in range(1, maximum + 1):
        url = source['url'] if page == 1 else template.replace('{page}', str(page))
        try:
            batch = parse_feed(request_bytes(url, timeout, max_bytes), source, collected_at)
        except Exception as error:
            if page == 1:
                raise
            errors.append({'url': url, 'error': str(error)[:180]})
            break
        dates = [x['published_at'] for x in batch if x.get('published_at')]
        pages.append({'url': url, 'items': len(batch), 'oldest': min(dates) if dates else None})
        fresh = [x for x in batch if x['url'] not in seen]
        items.extend(fresh)
        seen.update(x['url'] for x in batch)
        if dates and date.fromisoformat(min(dates)) < start:
            reached_start = True
            break
        if not fresh:
            break
    if template:
        run_info['coverage'] = {'pages': pages, 'errors': errors, 'reached_window_start': reached_start, 'complete': False}
        run_info['coverage_warning'] = ('已回溯到查询起点之前；订阅分页仍不保证全站历史完整。' if reached_start else '订阅分页未覆盖查询起点，较早日期可能缺漏。') + (f' {len(errors)}个分页读取失败。' if errors else '')
    return items

class NewsPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta={};self.links=[];self.headings=[];self.title=[];self.jsonld=[]
        self._h1=0;self._title=False;self._ld=False;self._buffer=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='meta':self.meta[attrs.get('property') or attrs.get('name') or '']=attrs.get('content','')
        if tag=='a' and attrs.get('href'):self.links.append(attrs['href'])
        if tag=='h1':self._h1+=1
        if tag=='title':self._title=True
        if tag=='script' and attrs.get('type')=='application/ld+json':self._ld=True;self._buffer=[]
    def handle_endtag(self,tag):
        if tag=='h1':self._h1=max(0,self._h1-1)
        if tag=='title':self._title=False
        if tag=='script' and self._ld:
            try:self.jsonld.append(json.loads(''.join(self._buffer)))
            except (ValueError,TypeError):pass
            self._ld=False
    def handle_data(self,data):
        if self._h1:self.headings.append(data)
        if self._title:self.title.append(data)
        if self._ld:self._buffer.append(data)

def walk_json(value):
    if isinstance(value,dict):
        yield value
        for entry in value.values():yield from walk_json(entry)
    elif isinstance(value,list):
        for entry in value:yield from walk_json(entry)

def parse_article(payload,url,source,collected_at):
    from scripts.collect_discovery import LOCAL_TZ,parse_date,plain_text
    text=payload.decode('utf-8',errors='replace') if isinstance(payload,bytes) else payload
    parser=NewsPage();parser.feed(text)
    articles=[entry for value in parser.jsonld for entry in walk_json(value)
        if any(t in str(entry.get('@type','')) for t in ('Article','BlogPosting'))]
    dated=next((entry for entry in articles if entry.get('datePublished')),None)
    title=plain_text(' '.join(parser.headings) or (dated or {}).get('headline') or parser.meta.get('og:title') or ' '.join(parser.title))
    published=parse_date(
        (dated or {}).get('datePublished') or parser.meta.get('article:published_time')
        or parser.meta.get('publication_date') or parser.meta.get('pubdate'),
        target_timezone=LOCAL_TZ,
    )
    date_source='JSON-LD datePublished' if dated else 'article publication meta'
    if not published and urlparse(url).hostname in {'www.ijiwei.com','ijiwei.com'}:
        match=re.search(r'"published_time"\s*:\s*"(\d{14})"',text)
        if match:
            stamp=match[1];published=parse_date(f'{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}');date_source='原站published_time字段'
    if not published:
        match=re.search(r'发布时间\s*[：:]\s*(\d{4}-\d{2}-\d{2})',plain_text(text))
        if match:published=parse_date(match[1]);date_source='原文可见发布时间'
    if not title or not published:raise ValueError('文章缺少可核验题名或首次发布日期，不能用事件日期/修改日期代替')
    description=plain_text(parser.meta.get('og:description') or parser.meta.get('description') or (dated or {}).get('description') or '')
    if description and re.search(r'[\u4e00-\u9fff]',description):description=description[:220]
    else:description=' '.join(description.split()[:100])
    return {'title':title,'url':url,'source':source['name'],'content_type':'news','published_at':published,
        'date_kind':'news_published','collected_at':collected_at,'summary':description,'abstract_text':description or None,
        'summary_kind':'source','news_genre':source.get('news_genre','专业媒体报道'),'topics':[],'methods':[],'views':[],
        'relevance':'pending','verification_note':f'题名和可用简介取自原站页面。发表日期取自 {date_source}。'}

def collect_html(source,collected_at,request_bytes,timeout,max_bytes,run_info):
    listing=request_bytes(source['url'],timeout,max_bytes).decode('utf-8',errors='replace')
    parser=NewsPage();parser.feed(listing)
    base=urlparse(source['url'])
    pattern=re.compile(source['article_url_pattern'])
    links=[]
    for href in parser.links:
        url=urljoin(source['url'],href)
        if urlparse(url).hostname==base.hostname and pattern.search(url) and url not in links:links.append(url)
    if not links:raise ValueError('目录没有可识别文章链接，不能当作成功空结果')
    maximum=min(int(source.get('max_articles',16)),40)
    items=[];errors=[]
    import time
    for url in links[:maximum]:
        time.sleep(.25)
        try:items.append(parse_article(request_bytes(url,timeout,max_bytes),url,source,collected_at))
        except Exception as error:errors.append({'url':url,'error':str(error)[:180]})
    run_info.update(coverage={'links_found':len(links),'read':len(items),'errors':errors,'complete':False},
        coverage_warning=f'仅读取当前目录前{min(len(links),maximum)}篇公开文章，不保证完整30天历史；{len(errors)}篇缺少有效元数据或读取失败。')
    if not items:raise ValueError('文章未能通过题名和日期核对')
    return items
