"""测试周报编排:weekly LLM 板块 + 确定性 Top 热点 + sentinel 拼装 + 失败降级"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.main import _run_weekly_push, now_local
from src.sections.common import weekly_window


def _weekly_meta() -> dict:
    return {
        "title": "AI4S 周报 | 2026-08-20",
        "lead": "lead text",
        "highlights": ["a"],
        "profile": "weekly",
        "date": "2026-08-20",
        "excerpt": "",
        "seotitle": "",
        "seodescription": "",
    }


def _patches(sample_config, sent, saved):
    async def fake_send(content, push_cfg, title=None, metadata=None):
        sent["content"] = content
        sent["title"] = title
        sent["metadata"] = metadata

    def fake_save(
        filepath,
        content,
        source_count,
        total_entries,
        profile="default",
        metadata=None,
        write_frontmatter=True,
    ):
        saved["filepath"] = filepath
        saved["profile"] = profile
        saved["content"] = content
        saved["metadata"] = metadata
        saved["write_frontmatter"] = write_frontmatter
        saved["stats"] = (source_count, total_entries)

    return (
        patch("src.main.run_weekly_section",
              new=AsyncMock(return_value=("W", _weekly_meta(), None))),
        patch("src.main.build_weekly_top_section", return_value="## 本周Top热点\n\nT"),
        patch("src.main.send_to_platforms", new=AsyncMock(side_effect=fake_send)),
        patch("src.main.save_push_file", side_effect=fake_save),
        patch("src.main.window_stats", return_value={"sourceCount": 5, "totalEntries": 42}),
        patch("src.main.notify_llm_errors", new=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_assembles_weekly_sections(sample_config):
    sent, saved = {}, {}
    p = _patches(sample_config, sent, saved)
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        await _run_weekly_push(sample_config)

    content = sent["content"]
    assert "SECTION:weekly" in content
    assert "SECTION:weekly_top" in content
    # 顺序: weekly < weekly_top
    assert content.index("SECTION:weekly") < content.index("SECTION:weekly_top")
    # 标题强制为 AI4S前沿观察周报（M.D–M.D）,覆盖 LLM 生成的 title
    now = now_local(sample_config)
    start, end = weekly_window(now)
    expected_title = f"AI4S前沿观察周报（{start.month}.{start.day}–{end.month}.{end.day}）"
    assert sent["title"] == expected_title
    assert content.startswith(f"# {expected_title}")
    assert sent["metadata"]["profile"] == "weekly"
    assert saved["profile"] == "weekly"
    assert saved["metadata"]["title"] == expected_title
    assert saved["write_frontmatter"] is True
    # 周报落盘文件名带 -week 后缀,与日报区分
    assert saved["filepath"].endswith("-week.md")
    # 统计来自 window_stats
    assert saved["stats"] == (5, 42)


@pytest.mark.asyncio
async def test_llm_failure_degrades_to_top_only(sample_config):
    """weekly LLM 失败 → notify + 只发确定性 Top 热点榜单,仍推送落盘"""
    sent, saved = {}, {}
    async def fake_send(content, push_cfg, title=None, metadata=None):
        sent["content"] = content
        sent["metadata"] = metadata

    def fake_save(filepath, content, source_count, total_entries,
                profile="default", metadata=None, write_frontmatter=True):
        saved["profile"] = profile

    with patch(
        "src.main.run_weekly_section",
        new=AsyncMock(return_value=("", None, "generate_weekly_report: boom")),
    ), patch(
        "src.main.build_weekly_top_section", return_value="## 本周Top热点\n\nT"
    ), patch(
        "src.main.send_to_platforms", new=AsyncMock(side_effect=fake_send)
    ), patch(
        "src.main.save_push_file", side_effect=fake_save
    ), patch(
        "src.main.window_stats", return_value={"sourceCount": 1, "totalEntries": 1}
    ), patch(
        "src.main.notify_llm_errors", new=AsyncMock()
    ) as mock_notify:
        await _run_weekly_push(sample_config)

    mock_notify.assert_awaited_once()
    assert "<!-- SECTION:weekly BEGIN -->" not in sent["content"]
    assert "<!-- SECTION:weekly_top BEGIN -->" in sent["content"]
    # metadata 回退路径:LLM 未给 metadata 时兜底 profile=weekly
    assert sent["metadata"]["profile"] == "weekly"
    assert saved["profile"] == "weekly"


@pytest.mark.asyncio
async def test_all_empty_skips_push(sample_config):
    """两板块均无输出 → 不推送不落盘"""
    with patch(
        "src.main.run_weekly_section", new=AsyncMock(return_value=("", None, None))
    ), patch(
        "src.main.build_weekly_top_section", return_value=""
    ), patch(
        "src.main.send_to_platforms", new=AsyncMock()
    ) as mock_send, patch(
        "src.main.save_push_file"
    ) as mock_save:
        await _run_weekly_push(sample_config)

    mock_send.assert_not_awaited()
    mock_save.assert_not_called()
