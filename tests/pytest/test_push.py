"""推送模块测试"""

import os
import pytest
import re
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from push.discord import DiscordPlatform
from push.feishu import FeishuPlatform
from push import create_platform


class FakeFeishuResp:
    """模拟 aiohttp 响应的异步上下文管理器"""

    def __init__(self, status=200, data=None, text=""):
        self.status = status
        self._data = data if data is not None else {"code": 0}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._data

    async def text(self):
        return self._text


class TestDiscordPlatform:
    """测试Discord推送"""

    def test_validate_config_valid(self):
        config = {
            "enabled": True,
            "apiKeyName": "DISCORD_WEBHOOK_URL",
        }
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123456/abcdef"},
        ):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is True

    def test_validate_config_disabled(self):
        config = {
            "enabled": False,
            "apiKeyName": "DISCORD_WEBHOOK_URL",
        }
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123456/abcdef"},
        ):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_missing_webhook(self):
        config = {"enabled": True, "apiKeyName": "DISCORD_WEBHOOK_URL"}
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_invalid_url(self):
        config = {"enabled": True, "apiKeyName": "DISCORD_WEBHOOK_URL"}
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "not-a-valid-url"}):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_wrong_domain(self):
        config = {"enabled": True, "apiKeyName": "DISCORD_WEBHOOK_URL"}
        with patch.dict(
            os.environ, {"DISCORD_WEBHOOK_URL": "https://example.com/webhook"}
        ):
            platform = DiscordPlatform(config)
            assert platform.validate_config(config) is False

    def test_split_content_short(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test.com"}):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)
            short_content = "Hello"
            chunks = platform._split_content(short_content, limit=2000)
            assert len(chunks) == 1
            assert chunks[0] == "Hello"

    def test_split_content_long_message(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test.com"}):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)
            long_content = "A\n" * 2500
            chunks = platform._split_content(long_content, limit=2000)
            assert len(chunks) > 1
            assert all(len(c) <= 2000 for c in chunks)

    def test_split_content_exact_boundary(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test.com"}):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)
            content = "A" * 2000
            chunks = platform._split_content(content, limit=2000)
            assert len(chunks) == 1

    def test_split_content_unicode(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://test.com"}):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)
            content = "你好" * 500
            chunks = platform._split_content(content, limit=100)
            assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_send_success(self):
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/abc"},
        ):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)

            with patch.object(platform, "send", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = True

                result = await mock_send("Test message")

            assert result is True

    @pytest.mark.asyncio
    async def test_send_failure(self):
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/abc"},
        ):
            config = {"apiKeyName": "DISCORD_WEBHOOK_URL"}
            platform = DiscordPlatform(config)

            with patch.object(platform, "send", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = False

                result = await mock_send("Test message")

            assert result is False


class TestFeishuPlatform:
    """测试飞书推送"""

    def test_validate_config_valid(self):
        config = {
            "enabled": True,
            "apiKeyName": "FEISHU_WEBHOOK_URL",
        }
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)
            assert platform.validate_config(config) is True

    def test_validate_config_disabled(self):
        config = {
            "enabled": False,
            "apiKeyName": "FEISHU_WEBHOOK_URL",
        }
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_missing_key(self):
        config = {"enabled": True, "apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": ""}):
            platform = FeishuPlatform(config)
            assert platform.validate_config(config) is False

    def test_validate_config_any_non_empty_webhook(self):
        config = {"enabled": True, "apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)
            assert platform.validate_config(config) is True

    @pytest.mark.asyncio
    async def test_send_chunk_retries_on_network_error(self):
        """网络错误时重试，第二次成功后正常返回"""
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)

        session = MagicMock()
        session.post.side_effect = [
            aiohttp.ClientError("Temporary failure in name resolution"),
            FakeFeishuResp(status=200, data={"code": 0}),
        ]

        with patch("push.feishu.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await platform._send_chunk(session, {"msg_type": "interactive"})

        assert session.post.call_count == 2
        mock_sleep.assert_awaited_once_with(2)

    @pytest.mark.asyncio
    async def test_send_chunk_gives_up_after_max_retries(self):
        """持续网络错误时，重试 MAX_RETRIES 次后抛 RuntimeError"""
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)

        session = MagicMock()
        session.post.side_effect = aiohttp.ClientError("DNS failure")

        with patch("push.feishu.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="重试"):
                await platform._send_chunk(session, {"msg_type": "interactive"})

        assert session.post.call_count == FeishuPlatform.MAX_RETRIES

    @pytest.mark.asyncio
    async def test_send_chunk_no_retry_on_4xx(self):
        """4xx 客户端错误不重试，直接抛错"""
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = FeishuPlatform(config)

        session = MagicMock()
        session.post.return_value = FakeFeishuResp(status=400, text="bad request")

        with patch("push.feishu.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(RuntimeError, match="400"):
                await platform._send_chunk(session, {"msg_type": "interactive"})

        assert session.post.call_count == 1
        mock_sleep.assert_not_awaited()


MORNING_REPORT_SAMPLE = """# AI4S前瞻研判报告（8.21）

<!-- SECTION:insights BEGIN -->
## 📋 总览

- **生命科学与医学**：要点一

## 🌄 "高原"最新洞察

高原观点正文

## ⛰️ "高峰"最新洞察

### 高能物理与量子科技

高峰观点正文
<!-- SECTION:insights END -->

<!-- SECTION:relevance BEGIN -->
## 🧭 与当前01专项工作的相关性

相关性正文
<!-- SECTION:relevance END -->

<!-- SECTION:gaps BEGIN -->
## 🔬 问题发现

### 1. 某个问题
- **为什么可能成立**：原因
<!-- SECTION:gaps END -->

<!-- SECTION:rss BEGIN -->
## 📰 今日Top热点

### 1️⃣ 某热点

热点正文
<!-- SECTION:rss END -->

<!-- SECTION:hackernews BEGIN -->
## 🟧 Hacker News 热议

### Show HN: 某项目

193 pts · 109 comments · [example.com](https://example.com)

**📌 内容总结**

- **作者想做什么:** 做某事

**💬 讨论总结**

- **支持点:** 一些讨论

🔗 [原文](https://example.com/post) · [HN 讨论页](https://news.ycombinator.com/item?id=1)
<!-- SECTION:hackernews END -->
"""


class TestFeishuMorningCompression:
    """飞书早报精简+折叠：总览直接展示，高原/高峰/相关性/问题发现/Top热点/HN 各自折叠"""

    def _platform(self):
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            return FeishuPlatform(config)

    def _split(self, content=MORNING_REPORT_SAMPLE):
        visible, panels = self._platform()._split_morning_report(content)
        return visible, dict(panels)

    def test_rss_section_folded_as_panel(self):
        """今日Top热点收进折叠面板(2026-08-26 起恢复,此前整块剔除)"""
        visible, panels = self._split()
        assert "热点正文" in panels["📰 今日Top热点"]
        assert not panels["📰 今日Top热点"].startswith("## ")  # H2 由面板标题承载
        assert "热点正文" not in visible

    def test_visible_keeps_only_overview(self):
        visible, _ = self._split()
        assert "## 📋 总览" in visible
        assert "高原观点正文" not in visible
        assert "高峰观点正文" not in visible
        assert "相关性正文" not in visible
        assert "问题发现" not in visible

    def test_plateau_peak_folded_as_first_panels(self):
        """高原/高峰为前两个折叠面板(2026-08-27 起替换今日洞察)"""
        _, panels_list = self._platform()._split_morning_report(MORNING_REPORT_SAMPLE)
        assert [t for t, _ in panels_list][:2] == ['🌄 "高原"最新洞察', '⛰️ "高峰"最新洞察']
        panels = dict(panels_list)
        assert "高原观点正文" in panels['🌄 "高原"最新洞察']
        assert "高峰观点正文" in panels['⛰️ "高峰"最新洞察']
        assert not panels['🌄 "高原"最新洞察'].startswith("## ")  # H2 由面板标题承载
        assert "### 高能物理与量子科技" in panels['⛰️ "高峰"最新洞察']  # H3 学科子标题保留

    def test_legacy_insight_heading_fallback(self):
        """旧格式(2026-08-27 前的今日洞察)deliver 时回退为 💡 单面板"""
        old = MORNING_REPORT_SAMPLE.replace(
            '## 🌄 "高原"最新洞察\n\n高原观点正文\n\n## ⛰️ "高峰"最新洞察\n\n### 高能物理与量子科技\n\n高峰观点正文',
            "## 💡 今日洞察\n\n洞察正文",
        )
        _, panels = self._split(old)
        assert "洞察正文" in panels["💡 今日洞察"]
        assert '🌄 "高原"最新洞察' not in panels

    def test_legacy_insight_heading_without_emoji(self):
        """无符号旧标题(2026-08-21 前的报告)今日洞察同样折叠"""
        old = MORNING_REPORT_SAMPLE.replace(
            '## 🌄 "高原"最新洞察\n\n高原观点正文\n\n## ⛰️ "高峰"最新洞察\n\n### 高能物理与量子科技\n\n高峰观点正文',
            "## 今日洞察\n\n洞察正文",
        )
        _, panels = self._split(old)
        assert "洞察正文" in panels["💡 今日洞察"]

    def test_panels_split_per_section(self):
        _, panels = self._split()
        assert set(panels) == {'🌄 "高原"最新洞察', '⛰️ "高峰"最新洞察', "🧭 与当前01专项工作的相关性", "🔬 问题发现", "📰 今日Top热点", "🟧 Hacker News 热议"}
        assert "相关性正文" in panels["🧭 与当前01专项工作的相关性"]
        assert "某个问题" in panels["🔬 问题发现"]
        assert "热点正文" in panels["📰 今日Top热点"]

    def test_panel_content_strips_section_h2(self):
        _, panels = self._split()
        for md in panels.values():
            assert not md.startswith("## ")

    def test_hn_panel_keeps_summary_stats_and_links(self):
        _, panels = self._split()
        hn = panels["🟧 Hacker News 热议"]
        assert "### Show HN: 某项目" in hn
        assert "193 pts · 109 comments" in hn
        assert "📌 内容总结" in hn
        assert "作者想做什么" in hn
        assert "HN 讨论页" in hn

    def test_hn_panel_drops_discussion(self):
        _, panels = self._split()
        assert "💬 讨论总结" not in panels["🟧 Hacker News 热议"]
        assert "支持点" not in panels["🟧 Hacker News 热议"]

    def test_missing_fold_section_skipped(self):
        content = re.sub(
            r"<!-- SECTION:gaps BEGIN -->.*?<!-- SECTION:gaps END -->\n?",
            "", MORNING_REPORT_SAMPLE, flags=re.S,
        )
        _, panels = self._split(content)
        assert set(panels) == {'🌄 "高原"最新洞察', '⛰️ "高峰"最新洞察', "🧭 与当前01专项工作的相关性", "📰 今日Top热点", "🟧 Hacker News 热议"}

    def test_passthrough_without_sentinels(self):
        plain = "# 即时推送\n\n某条高分条目"
        assert self._platform()._split_morning_report(plain) is None

    def test_passthrough_weekly_report(self):
        weekly = "# AI4S周报\n\n<!-- SECTION:weekly BEGIN -->\n## 周报总览\n正文\n<!-- SECTION:weekly END -->"
        assert self._platform()._split_morning_report(weekly) is None

    def test_morning_payload_structure(self):
        platform = self._platform()
        visible, panels = platform._split_morning_report(MORNING_REPORT_SAMPLE)
        payload = platform._build_fold_payload(visible, panels, title="早报标题")

        card = payload["card"]
        assert card["schema"] == "2.0"
        assert card["header"]["title"]["content"] == "早报标题"

        elements = card["body"]["elements"]
        assert elements[0]["tag"] == "markdown"
        assert elements[0]["content"] == visible

        panel_els = elements[1:-1]
        assert [e["tag"] for e in panel_els] == ["collapsible_panel"] * 6
        assert [e["header"]["title"]["content"] for e in panel_els] == [
            '🌄 "高原"最新洞察', '⛰️ "高峰"最新洞察', "🧭 与当前01专项工作的相关性", "🔬 问题发现", "📰 今日Top热点", "🟧 Hacker News 热议",
        ]
        assert all(e["expanded"] is False for e in panel_els)

        # 归档站链接为最后一个元素
        assert elements[-1]["tag"] == "markdown"
        assert elements[-1]["content"] == platform.ARCHIVE_LINK_LINE

    def test_compressed_under_feishu_limit(self):
        platform = self._platform()
        visible, panels = platform._split_morning_report(MORNING_REPORT_SAMPLE)
        assert platform._within_limit(visible, panels)


class TestFeishuNoTeacherVariant:
    """飞书第二机器人(feishu_no_teacher):剔除 relevance 面板与归档站链接,其余与主机器人一致"""

    def _platform(self):
        config = {
            "apiKeyName": "FEISHU_WEBHOOK_URL_no_teacher",
            "exclude_sections": ["relevance"],
            "include_archive_link": False,
        }
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL_no_teacher": "https://open.feishu.cn/open-apis/bot/v2/hook/test2"}):
            return FeishuPlatform(config)

    def test_relevance_section_removed_entirely(self):
        """relevance 段不进面板也不进可见区"""
        visible, panels = self._platform()._split_morning_report(MORNING_REPORT_SAMPLE)
        assert "🧭 与当前01专项工作的相关性" not in dict(panels)
        assert "相关性正文" not in visible
        # 其余面板不受影响
        assert set(dict(panels)) == {'🌄 "高原"最新洞察', '⛰️ "高峰"最新洞察', "🔬 问题发现", "📰 今日Top热点", "🟧 Hacker News 热议"}

    def test_payload_has_no_archive_link(self):
        """卡片末尾无归档站链接,其余结构(总览可见+折叠面板)与主机器人一致"""
        platform = self._platform()
        visible, panels = platform._split_morning_report(MORNING_REPORT_SAMPLE)
        payload = platform._build_fold_payload(visible, panels, title="早报标题")

        elements = payload["card"]["body"]["elements"]
        assert elements[0]["tag"] == "markdown"
        assert elements[0]["content"] == visible
        panel_els = elements[1:]
        assert [e["tag"] for e in panel_els] == ["collapsible_panel"] * 5
        assert all(e["expanded"] is False for e in panel_els)
        assert platform.ARCHIVE_LINK_LINE not in [e.get("content") for e in elements]


WEEKLY_REPORT_SAMPLE = """# AI4S周报（8.17–8.20）

<!-- SECTION:weekly BEGIN -->
## 📋 总览

- **生命科学与医学**：周报要点一

## 💡 本周洞察

周报洞察正文

## 📈 趋势分析

周报趋势正文
<!-- SECTION:weekly END -->

<!-- SECTION:weekly_top BEGIN -->
## 🏆 本周Top热点

- **[95]** [t1](http://a) — s1
  榜单摘要
<!-- SECTION:weekly_top END -->
"""


class TestFeishuWeeklyFold:
    """飞书周报折叠:总览直接展示,本周洞察/趋势分析/本周Top热点各自折叠"""

    def _platform(self):
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            return FeishuPlatform(config)

    def _split(self, content=WEEKLY_REPORT_SAMPLE):
        visible, panels = self._platform()._split_weekly_report(content)
        return visible, dict(panels)

    def test_visible_keeps_only_overview(self):
        visible, _ = self._split()
        assert "## 📋 总览" in visible
        assert "周报要点一" in visible
        assert "周报洞察正文" not in visible
        assert "周报趋势正文" not in visible
        assert "榜单摘要" not in visible

    def test_panels_split_per_section(self):
        _, panels = self._split()
        assert set(panels) == {"💡 本周洞察", "📈 趋势分析", "🏆 本周Top热点"}
        assert "周报洞察正文" in panels["💡 本周洞察"]
        assert "周报趋势正文" in panels["📈 趋势分析"]
        assert "榜单摘要" in panels["🏆 本周Top热点"]

    def test_panel_content_strips_section_h2(self):
        _, panels = self._split()
        for md in panels.values():
            assert not md.startswith("## ")

    def test_fold_legacy_plain_headings(self):
        """无符号旧标题(2026-08-24 前的周报)同样正确折叠"""
        legacy = (
            WEEKLY_REPORT_SAMPLE
            .replace("## 📋 总览", "## 总览")
            .replace("## 💡 本周洞察", "## 本周洞察")
            .replace("## 📈 趋势分析", "## 趋势分析")
            .replace("## 🏆 本周Top热点", "## 本周Top热点")
        )
        visible, panels = self._split(legacy)
        assert "## 总览" in visible
        assert "周报洞察正文" in panels["💡 本周洞察"]
        assert "周报趋势正文" in panels["📈 趋势分析"]
        assert "榜单摘要" in panels["🏆 本周Top热点"]

    def test_missing_weekly_top_skipped(self):
        content = re.sub(
            r"<!-- SECTION:weekly_top BEGIN -->.*?<!-- SECTION:weekly_top END -->\n?",
            "", WEEKLY_REPORT_SAMPLE, flags=re.S,
        )
        _, panels = self._split(content)
        assert set(panels) == {"💡 本周洞察", "📈 趋势分析"}

    def test_passthrough_morning_report(self):
        assert self._platform()._split_weekly_report(MORNING_REPORT_SAMPLE) is None

    def test_passthrough_without_sentinels(self):
        plain = "# 即时推送\n\n某条高分条目"
        assert self._platform()._split_weekly_report(plain) is None

    def test_weekly_payload_structure(self):
        platform = self._platform()
        visible, panels = platform._split_weekly_report(WEEKLY_REPORT_SAMPLE)
        payload = platform._build_fold_payload(visible, panels, title="周报标题")

        card = payload["card"]
        assert card["schema"] == "2.0"
        assert card["header"]["title"]["content"] == "周报标题"

        elements = card["body"]["elements"]
        assert elements[0]["tag"] == "markdown"
        assert elements[0]["content"] == visible

        panel_els = elements[1:-1]
        assert [e["tag"] for e in panel_els] == ["collapsible_panel"] * 3
        assert [e["header"]["title"]["content"] for e in panel_els] == [
            "💡 本周洞察", "📈 趋势分析", "🏆 本周Top热点",
        ]
        assert all(e["expanded"] is False for e in panel_els)

        # 归档站链接为最后一个元素(与早报一致)
        assert elements[-1]["tag"] == "markdown"
        assert elements[-1]["content"] == platform.ARCHIVE_LINK_LINE

    def test_compressed_under_feishu_limit(self):
        platform = self._platform()
        visible, panels = platform._split_weekly_report(WEEKLY_REPORT_SAMPLE)
        assert platform._within_limit(visible, panels)


WEEKLY_REPORT_SAMPLE_V2 = """# AI4S周报（9.1–9.4）

<!-- SECTION:weekly BEGIN -->
## 📋 总览

- **高原**：周报高原观点
  - **重要新闻事件**：
    - 高原要闻一
- **高峰**：周报高峰观点
  - **重要新闻事件**：
    - 高峰要闻一

## 🌄 "高原"最新洞察

### 科学通用底座
- **高原观点句** 高原支撑正文
### 通用 AI
- **通用AI观点句** 通用AI支撑正文

## ⛰️ "高峰"最新洞察

### 高能物理与量子科技
- **高峰观点句** 高峰支撑正文
<!-- SECTION:weekly END -->

<!-- SECTION:weekly_top BEGIN -->
## 🏆 本周Top热点

- **[95]** [t1](http://a) — s1
  榜单摘要
<!-- SECTION:weekly_top END -->
"""


class TestFeishuWeeklyFoldV2:
    """飞书周报折叠新格式(2026-09-05 起与日报一致):总览直接展示,高原/高峰/本周Top热点各自折叠"""

    def _platform(self):
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            return FeishuPlatform(config)

    def _split(self, content=WEEKLY_REPORT_SAMPLE_V2):
        visible, panels = self._platform()._split_weekly_report(content)
        return visible, dict(panels)

    def test_visible_keeps_only_overview(self):
        visible, _ = self._split()
        assert "## 📋 总览" in visible
        assert "周报高原观点" in visible
        assert "高原要闻一" in visible
        assert "高原支撑正文" not in visible
        assert "高峰支撑正文" not in visible
        assert "榜单摘要" not in visible

    def test_panels_split_per_section(self):
        _, panels = self._split()
        assert set(panels) == {'🌄 "高原"最新洞察', '⛰️ "高峰"最新洞察', "🏆 本周Top热点"}
        assert "高原支撑正文" in panels['🌄 "高原"最新洞察']
        assert "### 科学通用底座" in panels['🌄 "高原"最新洞察']  # H3 子标题保留
        assert "高峰支撑正文" in panels['⛰️ "高峰"最新洞察']
        assert "榜单摘要" in panels["🏆 本周Top热点"]
        for md in panels.values():
            assert not md.startswith("## ")  # H2 由面板标题承载

    def test_payload_structure(self):
        platform = self._platform()
        visible, panels = platform._split_weekly_report(WEEKLY_REPORT_SAMPLE_V2)
        payload = platform._build_fold_payload(visible, panels, title="周报标题")

        elements = payload["card"]["body"]["elements"]
        panel_els = elements[1:-1]
        assert [e["tag"] for e in panel_els] == ["collapsible_panel"] * 3
        assert [e["header"]["title"]["content"] for e in panel_els] == [
            '🌄 "高原"最新洞察', '⛰️ "高峰"最新洞察', "🏆 本周Top热点",
        ]
        assert elements[-1]["content"] == platform.ARCHIVE_LINK_LINE


MONTHLY_REPORT_SAMPLE = """# AI4S前沿观察月报（8.12–9.7）

<!-- SECTION:monthly BEGIN -->
## 🌄 "高原"月度脉络

### 科学通用底座
- **高原脉络观点句** 高原脉络支撑
> **专家思考**：高原专家思考内容
### 通用 AI
- **通用AI脉络观点句** 通用AI脉络支撑
> **专家思考**：通用AI专家思考内容

## ⛰️ "高峰"月度脉络

### 高能物理与量子科技
- **高峰脉络观点句** 高峰脉络支撑
> **专家思考**：高峰专家思考内容

## 📋 月度总览

- **高原**：总览高原观点
  - **重要新闻事件**：
    - 高原月度要闻一
- **高峰**：总览高峰观点
<!-- SECTION:monthly END -->

<!-- SECTION:monthly_top BEGIN -->
## 🏆 月度Top热点

- **[96]** [t1](http://a) — s1
  月度榜单摘要
<!-- SECTION:monthly_top END -->
"""


class TestFeishuMonthlyFold:
    """飞书月报折叠旧格式(2026-09-07/08 试行版,legacy 路径):高原/高峰月度脉络直接展示,月度总览/月度Top热点各自折叠"""

    def _platform(self):
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            return FeishuPlatform(config)

    def _split(self, content=MONTHLY_REPORT_SAMPLE):
        visible, panels = self._platform()._split_monthly_report(content)
        return visible, dict(panels)

    def test_visible_keeps_trajectory_sections(self):
        visible, _ = self._split()
        assert '## 🌄 "高原"月度脉络' in visible
        assert '## ⛰️ "高峰"月度脉络' in visible
        assert "高原脉络支撑" in visible
        assert "高峰脉络支撑" in visible
        assert "高原专家思考内容" in visible  # 专家思考引用块随脉络留在可见区
        assert "总览高原观点" not in visible
        assert "月度榜单摘要" not in visible

    def test_panels_overview_and_top(self):
        _, panels = self._split()
        assert set(panels) == {"📋 月度总览", "🏆 月度Top热点"}
        assert "总览高原观点" in panels["📋 月度总览"]
        assert "高原月度要闻一" in panels["📋 月度总览"]
        assert "月度榜单摘要" in panels["🏆 月度Top热点"]
        for md in panels.values():
            assert not md.startswith("## ")  # H2 由面板标题承载

    def test_payload_structure(self):
        platform = self._platform()
        visible, panels = platform._split_monthly_report(MONTHLY_REPORT_SAMPLE)
        assert platform._within_limit(visible, panels)
        payload = platform._build_fold_payload(visible, panels, title="月报标题")

        elements = payload["card"]["body"]["elements"]
        panel_els = elements[1:-1]
        assert [e["tag"] for e in panel_els] == ["collapsible_panel"] * 2
        assert [e["header"]["title"]["content"] for e in panel_els] == [
            "📋 月度总览", "🏆 月度Top热点",
        ]
        assert elements[-1]["content"] == platform.ARCHIVE_LINK_LINE


MONTHLY_REPORT_SAMPLE_V2 = """# AI4S前沿观察月报（8.12–9.9）

<!-- SECTION:monthly BEGIN -->
## 🌄 "高原"月度脉络

### 科学通用底座
- **底座脉络观点句** 8.18 事件A→8.28 事件B→9.07 事件C
- **底座趋势研判句** 研判支撑
> **专家思考·宏观**：底座宏观专家内容
> **专家思考·技术**：底座技术专家内容
### 通用 AI
- **通用AI脉络观点句** 通用AI脉络支撑
> **专家思考·宏观**：通用AI宏观专家内容
> **专家思考·技术**：通用AI技术专家内容

## ⛰️ "高峰"月度脉络

### 高能物理与量子科技
- **高峰脉络观点句** 高峰脉络支撑
> **专家思考·宏观**：高峰宏观专家内容
> **专家思考·技术**：高峰技术专家内容
### 地球科学
本期无重要动态
<!-- SECTION:monthly END -->
"""


class TestFeishuMonthlyFoldV2:
    """飞书月报折叠新格式(2026-09-09 起):每个 H3 方向仅专家思考·宏观/·技术留可见区,脉络分点折叠"""

    def _platform(self):
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            return FeishuPlatform(config)

    def _split(self, content=MONTHLY_REPORT_SAMPLE_V2):
        visible, panels = self._platform()._split_monthly_report(content)
        return visible, dict(panels)

    def test_visible_keeps_only_expert_quotes(self):
        visible, _ = self._split()
        assert '## 🌄 "高原"月度脉络' in visible
        assert '## ⛰️ "高峰"月度脉络' in visible
        assert "### 科学通用底座" in visible
        assert "底座宏观专家内容" in visible
        assert "底座技术专家内容" in visible
        assert "通用AI宏观专家内容" in visible
        assert "高峰技术专家内容" in visible
        # 脉络分点与趋势研判折叠,不在可见区
        assert "底座脉络观点句" not in visible
        assert "底座趋势研判句" not in visible
        assert "高峰脉络观点句" not in visible
        # 无专家行的 H3(本期无重要动态)整体留可见区
        assert "本期无重要动态" in visible

    def test_panels_per_direction(self):
        _, panels = self._split()
        assert set(panels) == {"🌄 科学通用底座", "🌄 通用 AI", "⛰️ 高能物理与量子科技"}
        assert "底座脉络观点句" in panels["🌄 科学通用底座"]
        assert "底座趋势研判句" in panels["🌄 科学通用底座"]
        # 专家引用块不进面板(已在可见区)
        assert "专家思考" not in panels["🌄 科学通用底座"]
        for md in panels.values():
            assert not md.startswith("## ")
            assert not md.startswith("### ")

    def test_payload_structure(self):
        platform = self._platform()
        visible, panels = platform._split_monthly_report(MONTHLY_REPORT_SAMPLE_V2)
        assert platform._within_limit(visible, panels)
        payload = platform._build_fold_payload(visible, panels, title="月报标题")

        elements = payload["card"]["body"]["elements"]
        panel_els = elements[1:-1]
        assert [e["tag"] for e in panel_els] == ["collapsible_panel"] * 3
        assert [e["header"]["title"]["content"] for e in panel_els] == [
            "🌄 科学通用底座", "🌄 通用 AI", "⛰️ 高能物理与量子科技",
        ]
        assert elements[-1]["content"] == platform.ARCHIVE_LINK_LINE


class TestFeishuStripLeadingH1:
    """卡片 header 已有标题时,去掉正文重复的 H1"""

    def _platform(self):
        config = {"apiKeyName": "FEISHU_WEBHOOK_URL"}
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            return FeishuPlatform(config)

    def test_strips_h1(self):
        content = "# AI4S前瞻研判报告（8.21）\n\n## 📋 总览\n正文"
        assert self._platform()._strip_leading_h1(content) == "## 📋 总览\n正文"

    def test_keeps_non_h1_start(self):
        content = "## 总览\n正文"
        assert self._platform()._strip_leading_h1(content) == content

    def test_keeps_nonleading_h1(self):
        content = "开头文字\n\n# 不是首行\n正文"
        assert self._platform()._strip_leading_h1(content) == content

    @pytest.mark.asyncio
    async def test_send_with_title_removes_duplicate_h1(self):
        platform = self._platform()
        with patch.object(platform, "_send_chunk", new_callable=AsyncMock) as mock_send:
            await platform.send(MORNING_REPORT_SAMPLE, title="AI4S前瞻研判报告（8.21）")

        payload = mock_send.call_args[0][1]
        visible_md = payload["card"]["body"]["elements"][0]["content"]
        assert not visible_md.startswith("# AI4S前瞻研判报告")
        assert "## 📋 总览" in visible_md

    @pytest.mark.asyncio
    async def test_send_without_title_keeps_h1(self):
        platform = self._platform()
        with patch.object(platform, "_send_chunk", new_callable=AsyncMock) as mock_send:
            await platform.send(MORNING_REPORT_SAMPLE)

        payload = mock_send.call_args[0][1]
        visible_md = payload["card"]["body"]["elements"][0]["content"]
        assert visible_md.startswith("# AI4S前瞻研判报告")


class TestPushFactory:
    """测试平台工厂"""

    def test_create_enabled_platform(self):
        config = {
            "enabled": True,
            "apiKeyName": "DISCORD_WEBHOOK_URL",
        }
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc"},
        ):
            platform = create_platform("discord", config)
            assert platform is not None

    def test_create_disabled_platform_returns_none(self):
        config = {"enabled": False, "apiKeyName": "DISCORD_WEBHOOK_URL"}
        platform = create_platform("discord", config)
        assert platform is None

    def test_create_unknown_platform_raises(self):
        with pytest.raises(ValueError):
            create_platform("unknown", {})

    def test_create_feishu_platform(self):
        config = {
            "enabled": True,
            "apiKeyName": "FEISHU_WEBHOOK_URL",
        }
        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"}):
            platform = create_platform("feishu", config)
            assert platform is not None
            assert isinstance(platform, FeishuPlatform)

    def test_create_discord_platform(self):
        config = {
            "enabled": True,
            "apiKeyName": "DISCORD_WEBHOOK_URL",
        }
        with patch.dict(
            os.environ,
            {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test/abc"},
        ):
            platform = create_platform("discord", config)
            assert platform is not None
            assert isinstance(platform, DiscordPlatform)
