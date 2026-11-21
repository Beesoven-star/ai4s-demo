"""Tavily 搜索抓取：主动检索 AI4S 内容，转换为标准条目汇入评分管线。

数据源: https://api.tavily.com/search (Bearer 鉴权)
搜索结果与 RSS 条目同构，经 fetch 流程统一去重、评分、推送。
API key 环境变量名通过 `search.apiKeyName` 配置(默认 TAVILY_API_KEY)。
"""

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp

from src.storage import load_search_state, save_search_state

TAVILY_API_URL = "https://api.tavily.com/search"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


async def tavily_search(
    query: str,
    api_key: str,
    *,
    topic: str = "news",
    days: int = 1,
    max_results: int = 5,
    search_depth: str = "basic",
    exclude_domains: Optional[List[str]] = None,
    timeout: int = 20,
) -> List[Dict]:
    """调用 Tavily Search API，返回 results 数组；失败抛异常由调用方聚合"""
    payload = {
        "query": query,
        "topic": topic,
        "days": days,
        "max_results": max_results,
        "search_depth": search_depth,
        "exclude_domains": exclude_domains or [],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            TAVILY_API_URL,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Tavily 返回 {resp.status}: {text[:200]}")
            data = await resp.json()
            return data.get("results", [])


def _parse_date_or_none(raw) -> Optional[datetime]:
    """解析 Tavily 的 published_date,失败/缺失返回 None(供日期闸门与兜底共用)"""
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_published(result: Dict, now: datetime) -> datetime:
    """解析 Tavily 的 published_date，失败回退为当前时间"""
    return _parse_date_or_none(result.get("published_date")) or now


def _to_entry(result: Dict, query: str, now: datetime, content_max_chars: int) -> Dict:
    """Tavily result → 标准条目结构(与 fetcher._parse_feed_entries 同构)"""
    content = (result.get("content") or "")[:content_max_chars]
    return {
        "title": (result.get("title") or "无标题")[:200],
        "link": result.get("url", ""),
        "published": _parse_published(result, now),
        "source": f"Tavily·{query}",
        "content": content,
        "tags": [],
        "score": 0,
        "summary": "",
    }


async def fetch_search_entries(config: Dict) -> Tuple[List[Dict], List[str]]:
    """按配置执行 Tavily 批量搜索，返回 (标准条目列表, 错误列表)。

    降级语义(均返回空列表 + 空错误,不阻断 RSS 主流程):
    - search.enabled = false
    - 未配置 API key
    - 距上次搜索不足 interval_hours (限频保护额度)
    """
    cfg = config.get("search", {})
    if not cfg.get("enabled", False):
        return [], []

    api_key_name = cfg.get("apiKeyName", "TAVILY_API_KEY")
    api_key = os.environ.get(api_key_name)
    if not api_key:
        print(f"⚠️ Tavily: 未配置 {api_key_name},搜索降级跳过")
        return [], []

    interval_hours = cfg.get("interval_hours", 12)
    state = load_search_state()
    last = state.get("last_search_at")
    now = datetime.now(timezone.utc)
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if now - last_dt < timedelta(hours=interval_hours):
                print(f"⏭️ Tavily: 距上次搜索不足 {interval_hours}h,跳过")
                return [], []
        except ValueError:
            pass

    queries = cfg.get("queries", [])
    if not queries:
        return [], []

    topic = cfg.get("topic", "news")
    days = cfg.get("days", 1)
    max_age_days = cfg.get("max_age_days", 3)
    max_results = cfg.get("max_results_per_query", 5)
    search_depth = cfg.get("search_depth", "basic")
    exclude_domains = cfg.get("exclude_domains", [])
    timeout = cfg.get("request_timeout", 20)
    content_max_chars = cfg.get("content_max_chars", 4000)

    import asyncio

    print(f"🔍 Tavily: 并发搜索 {len(queries)} 个关键词...")
    results = await asyncio.gather(
        *[
            tavily_search(
                q,
                api_key,
                topic=topic,
                days=days,
                max_results=max_results,
                search_depth=search_depth,
                exclude_domains=exclude_domains,
                timeout=timeout,
            )
            for q in queries
        ],
        return_exceptions=True,
    )

    entries: List[Dict] = []
    errors: List[str] = []
    seen_urls = set()
    skipped_old = 0
    for query, res in zip(queries, results):
        if isinstance(res, Exception):
            errors.append(f"查询「{query}」失败: {res}")
            continue
        for item in res:
            url = item.get("url", "")
            if not url or url in seen_urls:
                continue
            # 客户端日期闸门:服务端 days 过滤对无日期页面失效(实测官方博客常缺
            # published_date),这里对「有日期且超窗」的结果补一刀;无日期的保留
            # (高价值信源常为无日期官方博客),重复由已推送永久记录兜底
            pub = _parse_date_or_none(item.get("published_date"))
            if pub is not None and now - pub > timedelta(days=max_age_days):
                skipped_old += 1
                continue
            seen_urls.add(url)
            entries.append(_to_entry(item, query, now, content_max_chars))

    for e in errors:
        print(f"⚠️ Tavily: {e}")
    if skipped_old:
        print(f"🗓️ Tavily: 丢弃 {skipped_old} 条超过 {max_age_days} 天的结果")
    print(f"✅ Tavily: 搜索到 {len(entries)} 条 (去重后)")

    # 只有真正执行了搜索才更新时间戳(即使结果为 0,也代表额度已消耗)
    save_search_state({"last_search_at": now.isoformat()})
    return entries, errors
