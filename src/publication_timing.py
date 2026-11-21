"""Separate source publication, first preprint submission and ingestion dates."""
from datetime import date,datetime,timedelta,timezone
LABELS={'recent_published':'近期正式发表','recent_preprint':'近期预印本',
 'historical':'历史资料','month_only':'仅提供发表月份','unknown':'来源未提供发表日期','future':'来源日期晚于今天'}
def assess(item,as_of=None):
    as_of=as_of or datetime.now(timezone(timedelta(hours=8))).date()
    start=as_of-timedelta(days=29)
    stamp=item.get('published_at')
    if not stamp:kind='month_only' if item.get('publication_month') else 'unknown'
    else:
        published=date.fromisoformat(stamp[:10])
        if published>as_of:kind='future'
        elif published<start:kind='historical'
        elif item.get('venue_type')=='preprint' or item.get('date_kind')=='arxiv_first_submission':kind='recent_preprint'
        else:kind='recent_published'
    return {'kind':kind,'label':LABELS[kind],'as_of':as_of.isoformat(),'recent_start':start.isoformat(),
        'note':'按来源发表日/预印本首次提交日判断，收录日不代表发表日；仅月份不计入精确近期数量。'}

def matches(payload,kind):
    import json
    return int(assess(json.loads(payload))['kind']==kind)

def statistics(items,as_of=None):
    from collections import Counter
    stamps=[assess(item,as_of) for item in items]
    reference=stamps[0] if stamps else assess({},as_of)
    return {'as_of':reference['as_of'],'recent_start':reference['recent_start'],
        'counts':dict(Counter(stamp['kind'] for stamp in stamps)),
        'collection_days':dict(sorted(Counter(item.get('collected_at','')[:10] for item in items).items()))}
