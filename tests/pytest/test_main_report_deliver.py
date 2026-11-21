"""测试 report / deliver 命令:生成与推送分离"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.main import _run_morning_push, cmd_deliver


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
async def test_morning_push_deliver_false_skips_send_but_saves(sample_config):
    """deliver=False:不推送,但仍落盘 push 文件"""
    sample_config["filter"]["push_context_days"] = 5

    with patch(
        "src.main.run_rss_section", new=AsyncMock(return_value=("R", None, None))
    ), patch(
        "src.main.run_hackernews_section", new=AsyncMock(return_value=("H", None))
    ), patch(
        "src.main.run_insights_section",
        new=AsyncMock(return_value=("I", _insights_meta(), None)),
    ), patch(
        "src.main.run_gaps_section", new=AsyncMock(return_value=("G", None))
    ), patch(
        "src.main.send_to_platforms", new=AsyncMock()
    ) as mock_send, patch(
        "src.main.save_push_file"
    ) as mock_save:
        await _run_morning_push(sample_config, deliver=False)

    mock_send.assert_not_called()
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_deliver_morning_file_uses_h1_title(sample_config, tmp_path):
    """早报文件(无 frontmatter,H1 开头):标题取 H1,正文原样推送"""
    f = tmp_path / "push-morning.md"
    f.write_text("# AI4S前瞻研判报告（5.22）\n\nbody content\n", encoding="utf-8")

    with patch("src.main.send_to_platforms", new=AsyncMock()) as mock_send:
        rc = await cmd_deliver(sample_config, str(f))

    assert rc == 0
    content, push_cfg = mock_send.call_args.args[:2]
    assert "body content" in content
    assert mock_send.call_args.kwargs["title"] == "AI4S前瞻研判报告（5.22）"


@pytest.mark.asyncio
async def test_deliver_morning_file_with_frontmatter(sample_config, tmp_path):
    """新格式早报(frontmatter + 正文 H1):剥 frontmatter,标题取 H1"""
    f = tmp_path / "push-morning-fm.md"
    f.write_text(
        "---\ntitle: \"AI4S前瞻研判报告（5.22）\"\nprofile: \"morning\"\n---\n\n"
        "# AI4S前瞻研判报告（5.22）\n\nbody content\n",
        encoding="utf-8",
    )

    with patch("src.main.send_to_platforms", new=AsyncMock()) as mock_send:
        rc = await cmd_deliver(sample_config, str(f))

    assert rc == 0
    content = mock_send.call_args.args[0]
    assert "body content" in content
    assert not content.lstrip().startswith("---")
    assert mock_send.call_args.kwargs["title"] == "AI4S前瞻研判报告（5.22）"


@pytest.mark.asyncio
async def test_deliver_default_file_strips_frontmatter(sample_config, tmp_path):
    """晚报文件(带 frontmatter):正文剥掉 frontmatter,标题加晚报前缀"""
    f = tmp_path / "push-default.md"
    f.write_text(
        "---\ntitle: \"Anthropic 发布新模型\"\nprofile: \"default\"\n---\n\ndigest body\n",
        encoding="utf-8",
    )

    with patch("src.main.send_to_platforms", new=AsyncMock()) as mock_send:
        rc = await cmd_deliver(sample_config, str(f))

    assert rc == 0
    content = mock_send.call_args.args[0]
    assert "digest body" in content
    assert "---" not in content
    assert mock_send.call_args.kwargs["title"] == "📰 AI4S Daily 每日精选 | Anthropic 发布新模型"


@pytest.mark.asyncio
async def test_deliver_missing_file_returns_1(sample_config, tmp_path):
    rc = await cmd_deliver(sample_config, str(tmp_path / "nope.md"))
    assert rc == 1
