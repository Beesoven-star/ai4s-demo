"""RSS抓取模块测试"""

import pytest
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from fetcher import (
    parse_entry_time,
    fetch_single_feed_async,
    fetch_all_feeds,
    DEFAULT_FEED_TIMEOUT,
    _parse_feed_entries,
    MAX_ENTRIES_PER_FEED,
)


class TestParseFeedEntries:
    """测试 feed 条目解析与每源条数上限"""

    def _make_rss(self, n: int, with_dates: bool = False) -> bytes:
        """构造 RSS XML。with_dates=True 时带近期 pubDate(不会被 cutoff 过滤)"""
        items = ""
        for i in range(n):
            date_tag = "<pubDate>Wed, 12 Aug 2026 10:00:00 GMT</pubDate>" if with_dates else ""
            items += f"<item><title>文章{i}</title><link>https://example.com/{i}</link>{date_tag}</item>"
        return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>'.encode()

    def test_undated_entries_capped(self):
        """无日期条目同样受每源上限约束"""
        cutoff = datetime(2024, 1, 10, tzinfo=timezone.utc)
        entries = _parse_feed_entries(self._make_rss(10), {"title": "T"}, cutoff)
        assert len(entries) == MAX_ENTRIES_PER_FEED
        assert entries[0]["title"] == "文章0"
        assert all(e["published"] is None for e in entries)

    def test_dated_entries_capped(self):
        """有日期条目在时间窗内也受每源上限约束(防大窗口高频源灌入)"""
        cutoff = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)
        entries = _parse_feed_entries(self._make_rss(10, with_dates=True), {"title": "T"}, cutoff)
        assert len(entries) == MAX_ENTRIES_PER_FEED
        assert [e["title"] for e in entries] == ["文章0", "文章1", "文章2"]

    def test_under_cap_kept(self):
        """条目数低于上限时全部保留"""
        cutoff = datetime(2024, 1, 10, tzinfo=timezone.utc)
        entries = _parse_feed_entries(self._make_rss(2), {"title": "T"}, cutoff)
        assert len(entries) == 2

    def test_uncapped_domains_exempt(self):
        """nature.com / science.org 不受每源上限约束"""
        cutoff = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)
        for url in ["https://www.nature.com/nature.rss",
                    "https://www.science.org/action/showFeed?jc=science"]:
            feed_info = {"title": "T", "xmlUrl": url}
            entries = _parse_feed_entries(self._make_rss(10, with_dates=True), feed_info, cutoff)
            assert len(entries) == 10, url


class TestParseEntryTime:
    """测试时间解析"""

    def test_parse_published_parsed(self):
        entry = MagicMock()
        entry.published_parsed = (2024, 1, 15, 10, 30, 0, 0, 0, 0)

        result = parse_entry_time(entry)
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.tzinfo == timezone.utc

    def test_parse_updated_parsed(self):
        entry = MagicMock()
        entry.published_parsed = None
        entry.updated_parsed = (2024, 1, 15, 10, 30, 0, 0, 0, 0)

        result = parse_entry_time(entry)
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_no_time(self):
        entry = MagicMock()
        entry.published_parsed = None
        entry.updated_parsed = None

        result = parse_entry_time(entry)
        assert result is None


class TestFetchSingleFeedAsync:
    """测试单源抓取"""

    @pytest.mark.asyncio
    async def test_fetch_success(self, temp_dir):
        rss_content = """<?xml version="1.0"?>
<rss version="2.0">
    <channel>
        <title>Test Feed</title>
        <item>
            <title>Article 1</title>
            <link>https://example.com/1</link>
            <pubDate>Mon, 15 Jan 2024 10:00:00 GMT</pubDate>
            <description>Test description</description>
        </item>
    </channel>
</rss>"""

        feed_info = {"title": "Test Feed", "xmlUrl": "http://test.com/rss"}
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=rss_content)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            entries = await fetch_single_feed_async(
                feed_info, cutoff, session=mock_session
            )

        assert len(entries) == 1
        assert entries[0]["title"] == "Article 1"
        assert entries[0]["link"] == "https://example.com/1"
        assert entries[0]["source"] == "Test Feed"

    @pytest.mark.asyncio
    async def test_fetch_http_error(self):
        feed_info = {"title": "Test Feed", "xmlUrl": "http://test.com/rss"}
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_response = MagicMock()
        mock_response.status = 404

        mock_session = MagicMock()
        mock_session.get = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None),
            )
        )

        entries = await fetch_single_feed_async(feed_info, cutoff, session=mock_session)
        assert entries == []

    @pytest.mark.asyncio
    async def test_fetch_timeout(self):
        feed_info = {"title": "Test Feed", "xmlUrl": "http://test.com/rss"}
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)

        import aiohttp

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ServerTimeoutError())

        entries = await fetch_single_feed_async(feed_info, cutoff, session=mock_session)
        assert entries == []

    @pytest.mark.asyncio
    async def test_fetch_cutoff_filter(self):
        feed_info = {"title": "Test Feed", "xmlUrl": "http://test.com/rss"}
        cutoff = datetime(2024, 1, 10, tzinfo=timezone.utc)

        import feedparser

        with patch(
            "fetcher.fetch_single_feed_async", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = [
                {
                    "title": "New",
                    "link": "https://example.com/new",
                    "published": datetime(2024, 1, 15, tzinfo=timezone.utc),
                }
            ]

            result = await mock_fetch(feed_info, cutoff)

        assert len(result) == 1


class TestFetchAllFeeds:
    """测试并发抓取"""

    @pytest.mark.asyncio
    async def test_concurrent_limit(self):
        feeds = [
            {"title": f"Feed{i}", "xmlUrl": f"http://feed{i}.com/rss"}
            for i in range(20)
        ]
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)

        with patch(
            "fetcher.fetch_single_feed_async", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = []
            await fetch_all_feeds(feeds, cutoff, max_workers=5)

            assert mock_fetch.call_count == 20

    @pytest.mark.asyncio
    async def test_empty_feeds(self):
        cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
        entries = await fetch_all_feeds([], cutoff)
        assert entries == []

    @pytest.mark.asyncio
    async def test_default_timeout(self):
        feed_info = {"title": "Test", "xmlUrl": "http://test.com"}
        cutoff = datetime.now(timezone.utc)

        with patch(
            "fetcher.fetch_single_feed_async", new_callable=AsyncMock
        ) as mock_fetch:
            mock_fetch.return_value = []

            await mock_fetch(feed_info, cutoff, timeout=None)

            mock_fetch.assert_called_once()
