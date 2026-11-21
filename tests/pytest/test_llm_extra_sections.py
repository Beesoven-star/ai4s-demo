"""测试新增 LLM 函数 (select_ai_related_hn / summarize_hackernews)"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from llm import (
    generate_research_gaps,
    generate_work_relevance,
    select_ai_related_hn,
    summarize_hackernews,
)


@pytest.mark.asyncio
async def test_select_ai_related_hn_parses_id_array(tmp_path):
    prompt_path = tmp_path / "select.md"
    prompt_path.write_text("k={k} candidates={candidates_json}", encoding="utf-8")
    config = {
        "model": "x",
        "baseUrl": "http://x",
        "apiKeyName": "OPENAI_API_KEY",
        "prompts": {"section_hackernews_select": str(prompt_path)},
    }
    with patch("llm.call_llm", new=AsyncMock(return_value='["111", "222"]')):
        ids, err = await select_ai_related_hn(
            [{"id": "111"}, {"id": "222"}, {"id": "333"}], k=2, config=config
        )
    assert ids == ["111", "222"]
    assert err is None


@pytest.mark.asyncio
async def test_select_ai_related_hn_empty_array(tmp_path):
    prompt_path = tmp_path / "select.md"
    prompt_path.write_text("{k}{candidates_json}", encoding="utf-8")
    config = {
        "model": "x",
        "baseUrl": "http://x",
        "apiKeyName": "OPENAI_API_KEY",
        "prompts": {"section_hackernews_select": str(prompt_path)},
    }
    with patch("llm.call_llm", new=AsyncMock(return_value="[]")):
        ids, err = await select_ai_related_hn([{"id": "1"}], k=1, config=config)
    assert ids == []
    assert err is None


@pytest.mark.asyncio
async def test_summarize_hackernews_happy(tmp_path):
    prompt_path = tmp_path / "hn.md"
    prompt_path.write_text("{stories_json}", encoding="utf-8")
    config = {
        "model": "x",
        "baseUrl": "http://x",
        "apiKeyName": "OPENAI_API_KEY",
        "prompts": {"section_hackernews": str(prompt_path)},
    }
    with patch("llm.call_llm", new=AsyncMock(return_value="## HN summary")):
        md, err = await summarize_hackernews(
            [{"id": "1", "title": "t", "link_content": "x", "top_comments": []}], config
        )
    assert md == "## HN summary"
    assert err is None


@pytest.mark.asyncio
async def test_generate_research_gaps_happy(tmp_path):
    prompt_path = tmp_path / "gaps.md"
    prompt_path.write_text("{top_entries}\n{hackernews}", encoding="utf-8")
    config = {
        "model": "x",
        "baseUrl": "http://x",
        "apiKeyName": "OPENAI_API_KEY",
        "prompts": {"section_gaps": str(prompt_path)},
    }
    sections = {"top_entries": "[]", "hackernews": "hn md"}
    with patch("llm.call_llm", new=AsyncMock(return_value="## 问题发现")):
        md, err = await generate_research_gaps(sections, config)
    assert md == "## 问题发现"
    assert err is None


@pytest.mark.asyncio
async def test_generate_research_gaps_llm_failure_returns_error(tmp_path):
    prompt_path = tmp_path / "gaps.md"
    prompt_path.write_text("{top_entries}{hackernews}", encoding="utf-8")
    config = {
        "model": "x",
        "baseUrl": "http://x",
        "apiKeyName": "OPENAI_API_KEY",
        "prompts": {"section_gaps": str(prompt_path)},
    }
    with patch("llm.call_llm", new=AsyncMock(side_effect=RuntimeError("boom"))):
        md, err = await generate_research_gaps({"top_entries": "[]"}, config)
    assert md == ""
    assert "boom" in err


@pytest.mark.asyncio
async def test_generate_work_relevance_happy(tmp_path):
    prompt_path = tmp_path / "rel.md"
    prompt_path.write_text("{work_docs}\n{top_entries}", encoding="utf-8")
    config = {
        "model": "x",
        "baseUrl": "http://x",
        "apiKeyName": "OPENAI_API_KEY",
        "prompts": {"section_relevance": str(prompt_path)},
    }
    sections = {"work_docs": "doc", "top_entries": "[]"}
    with patch("llm.call_llm", new=AsyncMock(return_value="## 与当前工作的相关性")):
        md, err = await generate_work_relevance(sections, config)
    assert md == "## 与当前工作的相关性"
    assert err is None


@pytest.mark.asyncio
async def test_generate_work_relevance_llm_failure_returns_error(tmp_path):
    prompt_path = tmp_path / "rel.md"
    prompt_path.write_text("{work_docs}{top_entries}", encoding="utf-8")
    config = {
        "model": "x",
        "baseUrl": "http://x",
        "apiKeyName": "OPENAI_API_KEY",
        "prompts": {"section_relevance": str(prompt_path)},
    }
    with patch("llm.call_llm", new=AsyncMock(side_effect=RuntimeError("boom"))):
        md, err = await generate_work_relevance({"work_docs": "d"}, config)
    assert md == ""
    assert "boom" in err
