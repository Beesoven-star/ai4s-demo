"""测试 insights 模块"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Stub Task 17's LLM function until it lands
import src.llm as _llm
if not hasattr(_llm, "generate_trend_insights"):
    async def _stub(*a, **k):
        return "", None
    _llm.generate_trend_insights = _stub

from src.sections.insights.section import run_insights_section


def _cfg() -> dict:
    return {
        "filter": {"push_context_days": 5},
        "sections": {"insights": {"enabled": True}},
        "llm": {
            "model": "x",
            "baseUrl": "http://x",
            "apiKeyName": "OPENAI_API_KEY",
            "prompts": {"insights": "prompts/insights.md"},
        },
    }


@pytest.mark.asyncio
async def test_disabled_returns_empty():
    cfg = _cfg()
    cfg["sections"]["insights"]["enabled"] = False
    md, meta, err = await run_insights_section("rss", "hn", cfg, now=None)
    assert md == ""
    assert meta is None
    assert err is None


@pytest.mark.asyncio
async def test_marks_empty_sections_for_llm():
    cfg = _cfg()
    captured = {}

    async def fake_gen(sections, config):
        captured["sections"] = sections
        return "insights md", None

    with patch(
        "src.llm.generate_trend_insights",
        new=AsyncMock(side_effect=fake_gen),
    ):
        md, meta, err = await run_insights_section("", "hn md", cfg, now=None)

    assert md == "insights md"
    assert err is None
    # metadata 由 parse_insights_with_metadata 注入默认标题/profile
    assert meta["profile"] == "morning"
    assert "📰 AI4S Daily 每日精选" in meta["title"]
    assert captured["sections"]["rss"] == "(本次无内容)"
    assert captured["sections"]["hackernews"] == "hn md"


def _entry(score, title="t", source="s"):
    return {"title": title, "source": source, "score": score,
            "tags": ["x"], "summary": "sum", "content": "c" * 500}


@pytest.mark.asyncio
async def test_top_entries_selected_and_capped():
    """top-N: 仅取 ≥min_score,按分数降序,截断到 top_n,summary 截断"""
    cfg = _cfg()
    cfg["filter"]["min_score"] = 60
    cfg["sections"]["insights"]["top_n"] = 2
    captured = {}

    async def fake_gen(sections, config):
        captured["sections"] = sections
        return "md", None

    entries = [_entry(90, "high"), _entry(50, "low"), _entry(70, "mid"), _entry(85, "h2")]
    with patch("src.llm.generate_trend_insights", new=AsyncMock(side_effect=fake_gen)), \
         patch("src.sections.common.get_fetch_file", return_value="x.json"), \
         patch("src.sections.common.read_entries", return_value=entries):
        await run_insights_section("", "", cfg, now=None)

    import json
    top = json.loads(captured["sections"]["top_entries"])
    assert [e["title"] for e in top] == ["high", "h2"]  # 降序 + top_n=2 + 过滤 50 分
    assert len(top[0]["summary"]) <= 120
    assert "content" not in top[0]  # 紧凑结构不含正文


@pytest.mark.asyncio
async def test_top_entries_empty_marker():
    """今日无 fetch 数据时 top_entries 用占位标记"""
    cfg = _cfg()
    captured = {}

    async def fake_gen(sections, config):
        captured["sections"] = sections
        return "md", None

    with patch("src.llm.generate_trend_insights", new=AsyncMock(side_effect=fake_gen)), \
         patch("src.sections.common.get_fetch_file", return_value="x.json"), \
         patch("src.sections.common.read_entries", return_value=[]):
        await run_insights_section("", "", cfg, now=None)

    assert captured["sections"]["top_entries"] == "(本次无内容)"
