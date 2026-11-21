"""测试问题发现板块"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.sections.gaps.section import run_gaps_section


def _cfg() -> dict:
    return {
        "filter": {"min_score": 60},
        "sections": {"gaps": {"enabled": True, "top_n": 20}},
        "llm": {
            "model": "x",
            "baseUrl": "http://x",
            "apiKeyName": "OPENAI_API_KEY",
            "prompts": {"section_gaps": "prompts/section_gaps.md"},
        },
    }


def _entry(score, title="t"):
    return {"title": title, "source": "s", "score": score,
            "tags": ["x"], "summary": "sum", "content": "c" * 500}


@pytest.mark.asyncio
async def test_disabled_returns_empty():
    cfg = _cfg()
    cfg["sections"]["gaps"]["enabled"] = False
    md, err = await run_gaps_section("hn", cfg)
    assert md == ""
    assert err is None


@pytest.mark.asyncio
async def test_empty_material_skips_llm():
    """无高分素材时短路:不调 LLM,直接省略该段"""
    cfg = _cfg()
    with patch(
        "src.llm.generate_research_gaps", new=AsyncMock()
    ) as mock_llm, patch(
        "src.sections.common.get_fetch_file", return_value="x.json"
    ), patch(
        "src.sections.common.read_entries", return_value=[]
    ):
        md, err = await run_gaps_section("hn", cfg)

    assert md == ""
    assert err is None
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_llm_failure_returns_error():
    cfg = _cfg()
    entries = [_entry(90)]
    with patch(
        "src.llm.generate_research_gaps",
        new=AsyncMock(return_value=("", "boom")),
    ), patch(
        "src.sections.common.get_fetch_file", return_value="x.json"
    ), patch(
        "src.sections.common.read_entries", return_value=entries
    ):
        md, err = await run_gaps_section("hn", cfg)

    assert md == ""
    assert "boom" in err


@pytest.mark.asyncio
async def test_happy_path_passes_materials():
    """素材按分数降序+过滤低分后传入 LLM;hn_md 为空时用占位标记"""
    cfg = _cfg()
    entries = [_entry(90, "high"), _entry(50, "low"), _entry(70, "mid")]
    captured = {}

    async def fake_gen(sections, config):
        captured["sections"] = sections
        return "## 问题发现\n\n...", None

    with patch(
        "src.llm.generate_research_gaps",
        new=AsyncMock(side_effect=fake_gen),
    ), patch(
        "src.sections.common.get_fetch_file", return_value="x.json"
    ), patch(
        "src.sections.common.read_entries", return_value=entries
    ):
        md, err = await run_gaps_section("", cfg)

    assert md.startswith("## 问题发现")
    assert err is None

    import json
    top = json.loads(captured["sections"]["top_entries"])
    assert [e["title"] for e in top] == ["high", "mid"]  # 降序 + 过滤 50 分
    assert captured["sections"]["hackernews"] == "(本次无内容)"
