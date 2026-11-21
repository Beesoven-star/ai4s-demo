"""测试 Tavily 搜索抓取:降级语义、限频、去重、条目结构"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.search_fetcher import fetch_search_entries, _to_entry, _parse_published


def _cfg(**overrides) -> dict:
    cfg = {
        "search": {
            "enabled": True,
            "apiKeyName": "TAVILY_API_KEY",
            "queries": ["AI for Science", "AI drug discovery"],
            "max_results_per_query": 5,
            "topic": "news",
            "days": 1,
            "interval_hours": 12,
            "request_timeout": 20,
            "content_max_chars": 100,
        }
    }
    cfg["search"].update(overrides)
    return cfg


def _result(url, title="t", score=0.9, published=None):
    if published is None:
        published = datetime.now(timezone.utc).date().isoformat()
    return {"title": title, "url": url, "content": "body", "score": score,
            "published_date": published}


class TestDegrade:
    """降级语义:返回空且不报错"""

    @pytest.mark.asyncio
    async def test_disabled(self):
        entries, errors = await fetch_search_entries(_cfg(enabled=False))
        assert entries == [] and errors == []

    @pytest.mark.asyncio
    async def test_no_api_key(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with patch("src.search_fetcher.load_search_state", return_value={}), \
             patch("src.search_fetcher.save_search_state"):
            entries, errors = await fetch_search_entries(_cfg())
        assert entries == [] and errors == []

    @pytest.mark.asyncio
    async def test_rate_limited(self, monkeypatch, tmp_path):
        """距上次搜索不足 interval_hours 时跳过"""
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        recent = datetime.now(timezone.utc).isoformat()
        with patch("src.search_fetcher.load_search_state",
                   return_value={"last_search_at": recent}), \
             patch("src.search_fetcher.tavily_search", new_callable=AsyncMock) as mock_search, \
             patch("src.search_fetcher.save_search_state"):
            entries, errors = await fetch_search_entries(_cfg())
        assert entries == [] and errors == []
        mock_search.assert_not_called()


class TestSearch:
    @pytest.mark.asyncio
    async def test_dedup_and_entry_shape(self, monkeypatch):
        """跨查询按 url 去重,条目结构与 RSS 条目同构"""
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        shared = _result("https://a.com/1")
        extra = _result("https://b.com/2", title="t2")

        async def fake_search(query, api_key, **kw):
            return [shared, extra] if query == "AI for Science" else [shared]

        with patch("src.search_fetcher.load_search_state", return_value={}), \
             patch("src.search_fetcher.save_search_state") as mock_save, \
             patch("src.search_fetcher.tavily_search", side_effect=fake_search):
            entries, errors = await fetch_search_entries(_cfg())

        assert errors == []
        assert len(entries) == 2  # shared 去重
        urls = [e["link"] for e in entries]
        assert urls == ["https://a.com/1", "https://b.com/2"]
        e = entries[0]
        assert set(e.keys()) == {"title", "link", "published", "source",
                                 "content", "tags", "score", "summary"}
        assert e["source"] == "Tavily·AI for Science"
        assert isinstance(e["published"], datetime)
        mock_save.assert_called_once()  # 搜索执行后写入时间戳

    @pytest.mark.asyncio
    async def test_single_query_failure_tolerated(self, monkeypatch):
        """单个查询失败不影响其他查询"""
        monkeypatch.setenv("TAVILY_API_KEY", "k")

        async def fake_search(query, api_key, **kw):
            if query == "AI for Science":
                raise RuntimeError("Tavily 返回 429")
            return [_result("https://b.com/2")]

        with patch("src.search_fetcher.load_search_state", return_value={}), \
             patch("src.search_fetcher.save_search_state"), \
             patch("src.search_fetcher.tavily_search", side_effect=fake_search):
            entries, errors = await fetch_search_entries(_cfg())

        assert len(entries) == 1
        assert len(errors) == 1 and "429" in errors[0]


class TestDateGate:
    """客户端日期闸门:有日期且超 max_age_days 的结果丢弃,无日期的保留"""

    @pytest.mark.asyncio
    async def test_old_dated_dropped_nodate_kept(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        fresh = _result("https://a.com/fresh")
        old = _result("https://a.com/old", published="2020-01-01")
        nodate = {"title": "t", "url": "https://a.com/nodate",
                  "content": "body", "score": 0.9}

        async def fake_search(query, api_key, **kw):
            return [fresh, old, nodate]

        with patch("src.search_fetcher.load_search_state", return_value={}), \
             patch("src.search_fetcher.save_search_state"), \
             patch("src.search_fetcher.tavily_search", side_effect=fake_search):
            entries, errors = await fetch_search_entries(_cfg())

        assert errors == []
        urls = [e["link"] for e in entries]
        assert "https://a.com/old" not in urls  # 有日期且超窗,丢弃
        assert "https://a.com/fresh" in urls
        assert "https://a.com/nodate" in urls  # 无日期保留(高价值官方博客常无日期)

    @pytest.mark.asyncio
    async def test_max_age_days_configurable(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        five_days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
        item = _result("https://a.com/5days", published=five_days_ago)

        async def fake_search(query, api_key, **kw):
            return [item]

        with patch("src.search_fetcher.load_search_state", return_value={}), \
             patch("src.search_fetcher.save_search_state"), \
             patch("src.search_fetcher.tavily_search", side_effect=fake_search):
            dropped, _ = await fetch_search_entries(_cfg(max_age_days=3))
            kept, _ = await fetch_search_entries(_cfg(max_age_days=7))

        assert dropped == []
        assert len(kept) == 1  # 同一 url 跨查询去重后保留


class TestHelpers:
    def test_parse_published_formats(self):
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        assert _parse_published({"published_date": "2026-08-11"}, now) == \
            datetime(2026, 8, 11, tzinfo=timezone.utc)
        # 无日期/非法日期回退 now
        assert _parse_published({}, now) == now
        assert _parse_published({"published_date": "garbage"}, now) == now

    def test_content_truncated(self):
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        e = _to_entry({"title": "t", "url": "u", "content": "x" * 500}, "q", now, 100)
        assert len(e["content"]) == 100
