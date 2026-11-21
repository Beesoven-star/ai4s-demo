"""测试早报编排:两阶段 gather + sentinel 拼装 + 失败隔离"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.main import _run_morning_push


def _insights_meta() -> dict:
    return {
        "title": "📰 AI4S Daily 每日精选 | 2026-05-22",
        "lead": "lead text",
        "highlights": ["a"],
        "profile": "morning",
        "date": "2026-05-22",
        "excerpt": "",
        "seotitle": "",
        "seodescription": "",
    }


@pytest.mark.asyncio
async def test_assembles_all_sections(sample_config, tmp_path):
    sample_config["filter"]["push_context_days"] = 5

    sent = {}

    async def fake_send(content, push_cfg, title=None, metadata=None):
        sent["content"] = content
        sent["metadata"] = metadata

    saved = {}

    def fake_save(
        filepath,
        content,
        source_count,
        total_entries,
        profile="default",
        metadata=None,
        write_frontmatter=True,
    ):
        saved["profile"] = profile
        saved["content"] = content
        saved["metadata"] = metadata
        saved["write_frontmatter"] = write_frontmatter

    with patch(
        "src.main.run_rss_section", new=AsyncMock(return_value=("R", None, None))
    ), patch(
        "src.main.run_hackernews_section", new=AsyncMock(return_value=("H", None))
    ), patch(
        "src.main.run_relevance_section", new=AsyncMock(return_value=("REL", None))
    ), patch(
        "src.main.run_insights_section",
        new=AsyncMock(return_value=("I", _insights_meta(), None)),
    ), patch(
        "src.main.run_gaps_section", new=AsyncMock(return_value=("G", None))
    ), patch(
        "src.main.get_relevance_file", return_value=str(tmp_path / "relevance.md")
    ), patch(
        "src.main.send_to_platforms", new=AsyncMock(side_effect=fake_send)
    ), patch(
        "src.main.save_push_file", side_effect=fake_save
    ):
        await _run_morning_push(sample_config)

    assert "SECTION:insights" in sent["content"]
    assert "SECTION:relevance" in sent["content"]
    assert "SECTION:gaps" in sent["content"]
    assert "SECTION:rss" in sent["content"]
    assert "SECTION:hackernews" in sent["content"]
    # RSS 段在早报中带 H2 板块头
    assert "## 📰 今日Top热点" in sent["content"]
    # 相关性分析进报告(带 H2 板块头),同时单独落盘
    assert "## 🧭 与当前01专项工作的相关性" in sent["content"]
    assert "REL" in sent["content"]
    rel_text = (tmp_path / "relevance.md").read_text(encoding="utf-8")
    assert "REL" in rel_text
    assert rel_text.startswith("# 与当前01专项工作的相关性")
    # 顺序: insights < relevance < gaps < rss < hackernews
    content = sent["content"]
    assert content.index("SECTION:insights") < content.index("SECTION:relevance")
    assert content.index("SECTION:relevance") < content.index("SECTION:gaps")
    assert content.index("SECTION:gaps") < content.index("SECTION:rss")
    assert content.index("SECTION:rss") < content.index("SECTION:hackernews")
    assert sent["metadata"]["profile"] == "morning"
    assert saved["profile"] == "morning"
    assert saved["metadata"]["lead"] == "lead text"
    # 早报落盘 frontmatter(供归档 Web 展示),推送内容不受影响
    assert saved["write_frontmatter"] is True
    assert saved["metadata"]["profile"] == "morning"


@pytest.mark.asyncio
async def test_rss_failure_raises_to_caller(sample_config):
    sample_config["filter"]["push_context_days"] = 5

    with patch(
        "src.main.run_rss_section",
        new=AsyncMock(return_value=("", None, "compose_digest 失败")),
    ), patch(
        "src.main.run_hackernews_section", new=AsyncMock(return_value=("H", None))
    ), patch(
        "src.main.run_insights_section", new=AsyncMock()
    ) as mock_insights, patch(
        "src.main.run_gaps_section", new=AsyncMock()
    ) as mock_gaps, patch(
        "src.main.notify_llm_errors", new=AsyncMock()
    ):
        with pytest.raises(RuntimeError):
            await _run_morning_push(sample_config)

    # RSS 失败立即抛错,第二阶段 insights/gaps 不应执行
    mock_insights.assert_not_called()
    mock_gaps.assert_not_called()


@pytest.mark.asyncio
async def test_section_failure_degrades_to_omission(sample_config):
    sample_config["filter"]["push_context_days"] = 5

    sent = {}

    async def fake_send(content, push_cfg, title=None, metadata=None):
        sent["content"] = content

    with patch(
        "src.main.run_rss_section", new=AsyncMock(return_value=("R", None, None))
    ), patch(
        "src.main.run_hackernews_section", new=AsyncMock(return_value=("", "hn down"))
    ), patch(
        "src.main.run_insights_section",
        new=AsyncMock(return_value=("I", _insights_meta(), None)),
    ), patch(
        "src.main.run_gaps_section", new=AsyncMock(return_value=("", "gaps down"))
    ), patch(
        "src.main.notify_llm_errors", new=AsyncMock()
    ), patch(
        "src.main.send_to_platforms", new=AsyncMock(side_effect=fake_send)
    ), patch(
        "src.main.save_push_file"
    ):
        await _run_morning_push(sample_config)

    assert "SECTION:rss" in sent["content"]
    assert "SECTION:hackernews" not in sent["content"]
    assert "SECTION:gaps" not in sent["content"]
    assert "SECTION:insights" in sent["content"]
