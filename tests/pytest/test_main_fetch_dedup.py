"""测试 run_fetch_job 的入库去重:窗口链接 + 已推送永久记录联合拦截"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.main import run_fetch_job


def _cfg():
    return {
        "schedule": {"fetch_interval_minutes": 60, "fetch_lookback_minutes": 120},
        "sources": {"base_opml": "resources/rss.opml", "add": [], "block": []},
        "filter": {
            "min_score": 60,
            "hot_threshold": 90,
            "context_days": 2,
            "fetch_dedup_days": 3,
        },
        "fetch": {"max_workers": 1, "timeout": 5},
        "llm": {},
        "push": {},
    }


def _entry(link, title="t"):
    return {
        "title": title,
        "link": link,
        "source": "test",
        "published": "2026-08-25T08:00:00+08:00",
        "content": "",
        "tags": [],
        "score": 0,
        "summary": "",
    }


@pytest.mark.asyncio
async def test_pushed_links_blocked_at_fetch(tmp_path):
    """已推送永久记录中的链接不再入库评分,新链接正常入库"""
    entries = [_entry("https://dup.com/1", "重复"), _entry("https://new.com/1", "全新")]
    # 真实 score_batch 只返回入参条目:重复链接被拦截后,仅新链接参与评分
    scored = [dict(_entry("https://new.com/1", "全新"), score=50)]
    fetch_file = str(tmp_path / "fetch-test.json")

    with patch("src.main.merge_sources", return_value=[{"name": "s"}]), patch(
        "src.main.fetch_all_feeds", new=AsyncMock(return_value=entries)
    ), patch(
        "src.search_fetcher.fetch_search_entries", new=AsyncMock(return_value=([], []))
    ), patch(
        "src.main.load_existing_links", return_value=set()
    ), patch(
        "src.main.load_pushed_links", return_value={"https://dup.com/1"}
    ), patch(
        "src.main.score_batch", new=AsyncMock(return_value=(scored, []))
    ) as mock_score, patch(
        "src.main.get_fetch_file", return_value=fetch_file
    ), patch("src.main.cleanup_old_files"):
        await run_fetch_job(_cfg())

    # 重复链接被拦截,只有新链接进入评分与落盘
    scored_links = [e["link"] for e in mock_score.call_args.args[0]]
    assert scored_links == ["https://new.com/1"]
    data = json.loads(Path(fetch_file).read_text(encoding="utf-8"))
    assert [e["link"] for e in data["entries"]] == ["https://new.com/1"]


@pytest.mark.asyncio
async def test_all_blocked_skips_scoring(tmp_path):
    """全部命中已推送记录时,不调评分、不落盘"""
    entries = [_entry("https://dup.com/1")]

    with patch("src.main.merge_sources", return_value=[{"name": "s"}]), patch(
        "src.main.fetch_all_feeds", new=AsyncMock(return_value=entries)
    ), patch(
        "src.search_fetcher.fetch_search_entries", new=AsyncMock(return_value=([], []))
    ), patch(
        "src.main.load_existing_links", return_value=set()
    ), patch(
        "src.main.load_pushed_links", return_value={"https://dup.com/1"}
    ), patch(
        "src.main.score_batch", new=AsyncMock()
    ) as mock_score, patch(
        "src.main.get_fetch_file", return_value=str(tmp_path / "fetch-test.json")
    ):
        await run_fetch_job(_cfg())

    mock_score.assert_not_called()
