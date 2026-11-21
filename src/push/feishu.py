"""飞书推送平台"""

import asyncio
import os
import re
from typing import Dict

import aiohttp

from .base import PushPlatform


class _RetryablePushError(Exception):
    """可重试的推送错误（网络异常、DNS 解析失败、服务端 5xx）"""


class FeishuPlatform(PushPlatform):
    """飞书 Webhook 推送"""

    MAX_RETRIES = 3  # 单分片最多尝试次数

    # 早报飞书精简+折叠规则,依赖早报拼装时的 SECTION 哨兵注释(assemble_with_sentinels):
    # 1. 总览(insights 段的 📋 总览)直接展示
    # 2. "高原"最新洞察 / "高峰"最新洞察 / 与当前工作的相关性 / 问题发现 / 今日Top热点 / HN 热议(仅内容总结)各自一个折叠面板
    #    (insights 段 H2 2026-08-27 起由 💡 今日洞察 改为 🌄"高原"/⛰️"高峰" 双板块,旧标题保留兼容历史报告;
    #     今日Top热点 2026-08-21~26 曾整块剔除,2026-08-26 起恢复为折叠面板)
    # 3. 归档站链接作为最后一个元素
    _HN_SECTION_RE = re.compile(
        r"(<!-- SECTION:hackernews BEGIN -->)(.*?)(<!-- SECTION:hackernews END -->)",
        re.DOTALL,
    )
    _HN_DISCUSSION_RE = re.compile(r"\*\*💬 讨论总结\*\*.*?(?=🔗|$)", re.DOTALL)
    _INSIGHTS_SECTION_RE = re.compile(
        r"<!-- SECTION:insights BEGIN -->\n?(.*?)<!-- SECTION:insights END -->\n?",
        re.DOTALL,
    )
    # 高原/高峰 H2(2026-08-27 起;emoji 可缺省以兼容 LLM 输出抖动)
    _PLATEAU_H2_RE = re.compile(r'(?m)^## (?:🌄 )?"高原"最新洞察\s*\n')
    _PEAK_H2_RE = re.compile(r'(?m)^## (?:⛰️ )?"高峰"最新洞察\s*\n')
    # 今日洞察 H2(2026-08-27 前旧格式,仅兼容历史报告 deliver)
    _INSIGHT_H2_RE = re.compile(r"(?m)^## (?:💡 )?今日洞察\s*\n")

    # 折叠面板:(哨兵名, 面板标题),按展示顺序;符号与日报模板/归档 Web 栏目一致
    # 高原/高峰面板在 _split_morning_report 中插入最前
    _FOLD_SECTIONS = (
        ("relevance", "🧭 与当前01专项工作的相关性"),
        ("gaps", "🔬 问题发现"),
        ("rss", "📰 今日Top热点"),
        ("hackernews", "🟧 Hacker News 热议"),
    )
    _PLATEAU_PANEL_TITLE = '🌄 "高原"最新洞察'
    _PEAK_PANEL_TITLE = '⛰️ "高峰"最新洞察'
    _INSIGHT_PANEL_TITLE = "💡 今日洞察"

    # 周报飞书折叠规则(2026-09-05 起与日报一致),依赖 SECTION:weekly / weekly_top 哨兵:
    # 1. 📋 总览直接展示
    # 2. 🌄"高原"/⛰️"高峰"最新洞察 / 🏆 本周Top热点 各自一个折叠面板
    #    (weekly 段 H2 2026-09-05 起由 💡 本周洞察/📈 趋势分析 改为高原/高峰,旧格式回退兼容历史报告)
    # 3. 归档站链接作为最后一个元素(与早报一致);周报不剔除任何板块
    _WEEKLY_SECTION_RE = re.compile(
        r"<!-- SECTION:weekly BEGIN -->\n?(.*?)<!-- SECTION:weekly END -->\n?",
        re.DOTALL,
    )
    _WEEKLY_TOP_SECTION_RE = re.compile(
        r"<!-- SECTION:weekly_top BEGIN -->\n?(.*?)<!-- SECTION:weekly_top END -->\n?",
        re.DOTALL,
    )
    # 本周洞察/趋势分析 H2(2026-09-05 前旧格式,仅兼容历史报告 deliver)
    _WEEKLY_INSIGHT_H2_RE = re.compile(r"(?m)^## (?:💡 )?本周洞察\s*\n")
    _WEEKLY_TRENDS_H2_RE = re.compile(r"(?m)^## (?:📈 )?趋势分析\s*\n")
    _WEEKLY_TOP_PANEL_TITLE = "🏆 本周Top热点"

    # 月报飞书折叠规则,依赖 SECTION:monthly / monthly_top 哨兵:
    # 新格式(2026-09-09 起,仅脉络+双专家):每个 H3 方向仅「专家思考·宏观/·技术」两条
    # 引用块留在可见区,脉络观点分点各自折叠为该方向的折叠面板;
    # 旧格式(2026-09-07/08 试行版):脉络整体留可见区,📋 月度总览 / 🏆 月度Top热点 折叠
    _MONTHLY_SECTION_RE = re.compile(
        r"<!-- SECTION:monthly BEGIN -->\n?(.*?)<!-- SECTION:monthly END -->\n?",
        re.DOTALL,
    )
    _MONTHLY_TOP_SECTION_RE = re.compile(
        r"<!-- SECTION:monthly_top BEGIN -->\n?(.*?)<!-- SECTION:monthly_top END -->\n?",
        re.DOTALL,
    )
    _MONTHLY_OVERVIEW_H2_RE = re.compile(r"(?m)^## (?:📋 )?月度总览\s*\n")
    _MONTHLY_OVERVIEW_PANEL_TITLE = "📋 月度总览"
    _MONTHLY_TOP_PANEL_TITLE = "🏆 月度Top热点"
    # 新格式结构:H2 高原/高峰脉络 → H3 方向 → 末尾两条专家思考引用块
    _MONTHLY_H2_RE = re.compile(r"(?m)^## (.+?)[ \t]*$")
    _MONTHLY_H3_RE = re.compile(r"(?m)^### (.+?)[ \t]*$")
    _MONTHLY_EXPERT_RE = re.compile(r"(?m)^> \*\*专家思考·(?:宏观|技术)\*\*：[^\n]*$")

    # 归档站链接,早报卡片最后一个元素
    ARCHIVE_LINK_LINE = "📒 AI4S-frontier汇总： https://ai4s-frontier.github.io/AI4S-Daily-HTML/"

    def __init__(self, config: Dict):
        super().__init__(config)
        self.api_key_name = config.get("apiKeyName", "FEISHU_WEBHOOK_URL")
        self.webhook_url = os.environ.get(self.api_key_name, "")
        # 机器人变体(如 feishu_no_teacher):按哨兵名剔除指定折叠面板、可关闭归档站链接
        self.exclude_sections = set(config.get("exclude_sections", []))
        self.include_archive_link = config.get("include_archive_link", True)

    def validate_config(self, config: Dict) -> bool:
        """检查飞书配置是否有效"""
        if not config.get("enabled", False):
            return False
        api_key_name = config.get("apiKeyName", "FEISHU_WEBHOOK_URL")
        webhook = os.environ.get(api_key_name, "")
        return bool(webhook)

    async def send(self, content: str, title: str = None, metadata: Dict = None):
        """发送到飞书（忽略 metadata）。早报/周报走折叠卡片单条消息,其余按分片独立重试"""
        if title:
            # 卡片 header 已展示标题,去掉正文首行重复的 H1(早报/周报)
            content = self._strip_leading_h1(content)

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            folded = self._split_morning_report(content)
            if folded is None:
                folded = self._split_weekly_report(content)
            if folded is None:
                folded = self._split_monthly_report(content)
            if folded and self._within_limit(*folded):
                payload = self._build_fold_payload(*folded, title=title)
                await self._send_chunk(session, payload)
                return
            if folded:
                # 超长兜底:折叠面板内 markdown 同样受 8000 限制,退回纯文本分片
                visible, panels = folded
                folded_flat = "\n\n".join(
                    f"## {panel_title}\n\n{panel_md}" for panel_title, panel_md in panels
                )
                content = "\n\n".join(part for part in (visible, folded_flat) if part)
            chunks = self._split_content(content, limit=8000)
            for chunk in chunks:
                payload = self._build_payload(chunk, title)
                await self._send_chunk(session, payload)

    async def _send_chunk(self, session: aiohttp.ClientSession, payload: Dict):
        """发送单个分片，网络错误 / 5xx 指数退避重试；4xx 与业务错误不重试"""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        if resp.status >= 500:
                            raise _RetryablePushError(f"HTTP {resp.status} - {text}")
                        raise RuntimeError(f"飞书推送失败: {resp.status} - {text}")
                    data = await resp.json()
                    if data.get("code") != 0:
                        raise RuntimeError(f"飞书推送失败: {data.get('msg')}")
                    return
            except (aiohttp.ClientError, asyncio.TimeoutError, _RetryablePushError) as e:
                if attempt == self.MAX_RETRIES:
                    raise RuntimeError(f"飞书推送失败，重试 {self.MAX_RETRIES} 次后仍失败: {e}")
                wait = 2 ** attempt
                print(f"⚠️ 飞书推送失败（{e}），{wait}s 后进行第 {attempt + 1}/{self.MAX_RETRIES} 次尝试...")
                await asyncio.sleep(wait)

    @staticmethod
    def _strip_leading_h1(content: str) -> str:
        """去掉正文首行 H1(与卡片 header 标题重复);首行不是 H1 时原样返回"""
        return re.sub(r"^# [^\n]*(\n+|$)", "", content.lstrip("\n"), count=1)

    def _split_morning_report(self, content: str):
        """早报飞书精简+折叠:返回 (可见区, [(面板标题, 面板内容), ...]);非早报返回 None。

        以 SECTION:insights 哨兵判定早报(周报为 weekly/weekly_top,即时推送无哨兵,
        均返回 None 原样透传)。可见区仅 📋 总览;高原/高峰洞察(旧格式为今日洞察)/相关性/
        问题发现/今日Top热点/HN 热议各自拆成独立折叠面板,板块 H2 标题由面板标题承载故从内容中剥除。
        """
        if "<!-- SECTION:insights BEGIN -->" not in content:
            return None

        content = self._HN_SECTION_RE.sub(self._shrink_hn, content)

        # insights 段拆分:总览留可见区,高原/高峰(旧格式为今日洞察)为最前折叠面板
        m = self._INSIGHTS_SECTION_RE.search(content)
        overview, panels = self._split_insights(m.group(1))
        content = content[: m.start()] + "\n" + overview + "\n" + content[m.end():]

        for name, panel_title in self._FOLD_SECTIONS:
            m = re.search(
                rf"<!-- SECTION:{name} BEGIN -->\n?(.*?)<!-- SECTION:{name} END -->\n?",
                content, re.DOTALL,
            )
            if not m:
                continue
            # 变体机器人剔除的板块:整段从正文删除,不进面板也不进可见区
            if name in self.exclude_sections:
                content = content[: m.start()] + content[m.end():]
                continue
            # 剥掉板块自带的 H2 标题(面板标题已承载),内容收进面板
            block = re.sub(r"^## [^\n]*(\n+|$)", "", m.group(1).strip(), count=1).strip()
            block = re.sub(r"\n{3,}", "\n\n", block)
            if block:
                panels.append((panel_title, block))
            content = content[: m.start()] + content[m.end():]

        visible = re.sub(r"\n{3,}", "\n\n", content).strip()
        return visible, panels

    def _split_insights(self, block: str):
        """insights 段拆为 (总览, [(面板标题, 内容), ...])。

        新格式(2026-08-27 起):高原/高峰各成一个面板,总览为首个 H2 前内容;
        旧格式(今日洞察):回退单面板;均无 H2 时整段作为总览、无面板。
        """
        if self._PLATEAU_H2_RE.search(block) or self._PEAK_H2_RE.search(block):
            parts = self._PLATEAU_H2_RE.split(block, maxsplit=1)
            overview, rest = (parts[0].strip(), parts[1]) if len(parts) == 2 else ("", block)
            sub = self._PEAK_H2_RE.split(rest, maxsplit=1)
            mid, peak_md = (sub[0].strip(), sub[1].strip()) if len(sub) == 2 else (rest.strip(), "")
            if len(parts) == 2:
                plateau_md = mid
            else:
                # 只有高峰标题:高峰前内容归总览
                overview = mid
                plateau_md = ""
            panels = []
            if plateau_md:
                panels.append((self._PLATEAU_PANEL_TITLE, re.sub(r"\n{3,}", "\n\n", plateau_md)))
            if peak_md:
                panels.append((self._PEAK_PANEL_TITLE, re.sub(r"\n{3,}", "\n\n", peak_md)))
            return overview, panels
        # 旧格式(今日洞察,历史报告 deliver 兼容)
        parts = self._INSIGHT_H2_RE.split(block, maxsplit=1)
        if len(parts) == 1:
            return block.strip(), []
        return parts[0].strip(), [
            (self._INSIGHT_PANEL_TITLE, re.sub(r"\n{3,}", "\n\n", parts[1].strip()))
        ]

    def _split_weekly_report(self, content: str):
        """周报飞书折叠:返回 (可见区, [(面板标题, 面板内容), ...]);非周报返回 None。

        以 SECTION:weekly 哨兵判定周报(早报为 insights 哨兵,即时推送无哨兵,
        均返回 None 原样透传)。可见区仅 📋 总览;高原/高峰(2026-09-05 起,与日报一致;
        旧格式回退 本周洞察/趋势分析 双面板)/本周Top热点 各自拆成独立折叠面板,
        板块 H2 标题由面板标题承载故从内容中剥除。与早报不同:周报不剔除任何板块。
        """
        m = self._WEEKLY_SECTION_RE.search(content)
        if not m:
            return None

        # weekly 段拆分:总览留可见区,高原/高峰为折叠面板(与日报共用 _split_insights);
        # 无高原/高峰 H2 时按旧格式(本周洞察/趋势分析)回退
        overview, panels = self._split_insights(m.group(1))
        if not panels:
            overview, insight_md, trends_md = self._split_weekly_body(m.group(1))
            if insight_md:
                panels.append(("💡 本周洞察", insight_md))
            if trends_md:
                panels.append(("📈 趋势分析", trends_md))
        content = content[: m.start()] + "\n" + overview + "\n" + content[m.end():]

        # weekly_top 段 → 本周Top热点面板(H2 由面板标题承载故剥除)
        mt = self._WEEKLY_TOP_SECTION_RE.search(content)
        if mt:
            block = re.sub(r"^## [^\n]*(\n+|$)", "", mt.group(1).strip(), count=1).strip()
            block = re.sub(r"\n{3,}", "\n\n", block)
            if block:
                panels.append((self._WEEKLY_TOP_PANEL_TITLE, block))
            content = content[: mt.start()] + content[mt.end():]

        visible = re.sub(r"\n{3,}", "\n\n", content).strip()
        return visible, panels

    def _split_monthly_report(self, content: str):
        """月报飞书折叠:返回 (可见区, [(面板标题, 面板内容), ...]);非月报返回 None。

        以 SECTION:monthly 哨兵判定月报。新格式(2026-09-09 起,含专家思考·宏观/·技术
        引用块):每个 H3 方向仅两条专家思考留在可见区(H2/H3 标题保留以标识方向),
        脉络观点分点剥除专家行后折叠为该方向面板;无专家行的 H3(如「本期无重要动态」)
        整体留可见区不折叠。旧格式(无专家思考·引用块)回退 _split_monthly_legacy。
        """
        m = self._MONTHLY_SECTION_RE.search(content)
        if not m:
            return None
        block = m.group(1)
        if not self._MONTHLY_EXPERT_RE.search(block):
            return self._split_monthly_legacy(content, m)

        visible_parts, panels = [], []
        h2s = list(self._MONTHLY_H2_RE.finditer(block))
        for i, h2 in enumerate(h2s):
            h2_title = h2.group(1)
            emoji = h2_title.split(" ", 1)[0] if " " in h2_title else ""
            chunk = block[h2.end():h2s[i + 1].start() if i + 1 < len(h2s) else len(block)]
            visible_parts.append(f"## {h2_title}")

            h3s = list(self._MONTHLY_H3_RE.finditer(chunk))
            preamble = chunk[: h3s[0].start()] if h3s else chunk
            if preamble.strip():
                visible_parts.append(preamble.strip())
            for j, h3 in enumerate(h3s):
                h3_title = h3.group(1)
                body = chunk[h3.end():h3s[j + 1].start() if j + 1 < len(h3s) else len(chunk)]
                experts = self._MONTHLY_EXPERT_RE.findall(body)
                if not experts:
                    # 无专家行(本期无重要动态等):整节留可见区,不折叠
                    visible_parts.append(f"### {h3_title}\n\n{body.strip()}")
                    continue
                visible_parts.append(f"### {h3_title}\n\n" + "\n".join(experts))
                bullets = self._MONTHLY_EXPERT_RE.sub("", body)
                bullets = re.sub(r"\n{3,}", "\n\n", bullets).strip()
                if bullets:
                    panels.append((f"{emoji} {h3_title}".strip(), bullets))

        visible = "\n\n".join(visible_parts)
        content = content[: m.start()] + "\n" + visible + "\n" + content[m.end():]

        # monthly_top 段(新格式已不生成,仅兼容历史文件)→ 月度Top热点面板
        mt = self._MONTHLY_TOP_SECTION_RE.search(content)
        if mt:
            top_md = re.sub(r"^## [^\n]*(\n+|$)", "", mt.group(1).strip(), count=1).strip()
            top_md = re.sub(r"\n{3,}", "\n\n", top_md)
            if top_md:
                panels.append((self._MONTHLY_TOP_PANEL_TITLE, top_md))
            content = content[: mt.start()] + content[mt.end():]

        visible = re.sub(r"\n{3,}", "\n\n", content).strip()
        return visible, panels

    def _split_monthly_legacy(self, content: str, m: re.Match):
        """旧格式月报折叠(2026-09-07/08 试行版,仅兼容历史文件 deliver):
        高原/高峰月度脉络整体留可见区,📋 月度总览 与 🏆 月度Top热点 各拆一个折叠面板。
        """
        block = m.group(1)
        parts = self._MONTHLY_OVERVIEW_H2_RE.split(block, maxsplit=1)
        body_md = re.sub(r"\n{3,}", "\n\n", parts[0].strip())
        panels = []
        if len(parts) > 1:
            overview_md = re.sub(r"\n{3,}", "\n\n", parts[1].strip())
            if overview_md:
                panels.append((self._MONTHLY_OVERVIEW_PANEL_TITLE, overview_md))
        content = content[: m.start()] + "\n" + body_md + "\n" + content[m.end():]

        mt = self._MONTHLY_TOP_SECTION_RE.search(content)
        if mt:
            top_md = re.sub(r"^## [^\n]*(\n+|$)", "", mt.group(1).strip(), count=1).strip()
            top_md = re.sub(r"\n{3,}", "\n\n", top_md)
            if top_md:
                panels.append((self._MONTHLY_TOP_PANEL_TITLE, top_md))
            content = content[: mt.start()] + content[mt.end():]

        visible = re.sub(r"\n{3,}", "\n\n", content).strip()
        return visible, panels

    def _split_weekly_body(self, block: str):
        """weekly 段拆为 (总览, 本周洞察, 趋势分析);缺段时对应位置返回空串"""
        parts = self._WEEKLY_INSIGHT_H2_RE.split(block, maxsplit=1)
        if len(parts) == 1:
            return block.strip(), "", ""
        overview = parts[0].strip()
        sub = self._WEEKLY_TRENDS_H2_RE.split(parts[1], maxsplit=1)
        if len(sub) == 1:
            return overview, re.sub(r"\n{3,}", "\n\n", parts[1].strip()), ""
        insight_md = re.sub(r"\n{3,}", "\n\n", sub[0].strip())
        trends_md = re.sub(r"\n{3,}", "\n\n", sub[1].strip())
        return overview, insight_md, trends_md

    @staticmethod
    def _within_limit(visible: str, panels: list) -> bool:
        """可见区与各面板内容均在单 markdown 元素 8000 字符上限内"""
        return len(visible) <= 8000 and all(len(md) <= 8000 for _, md in panels)

    def _shrink_hn(self, m: re.Match) -> str:
        """HN 板块按 ### 话题切块,逐块删除 💬 讨论总结(到 🔗 链接行之前)"""
        topics = re.split(r"(?m)(?=^### )", m.group(2))
        shrunk = [self._HN_DISCUSSION_RE.sub("", t) for t in topics]
        return m.group(1) + "".join(shrunk) + m.group(3)

    def _build_fold_payload(self, visible: str, panels: list, title: str = None) -> Dict:
        """折叠卡片(早报/周报共用):可见区正文 → 各板块折叠面板(collapsible_panel) → 归档站链接"""
        header = {}
        if title:
            header = {
                "title": {"content": title, "tag": "plain_text"},
                "template": "blue",
            }

        elements = [
            {"tag": "markdown", "content": visible, "text_align": "left"},
        ]
        for panel_title, panel_md in panels:
            elements.append(
                {
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {
                        "title": {"tag": "plain_text", "content": panel_title},
                        "vertical_align": "center",
                        "icon_position": "right",
                        "icon_expanded_angle": -180,
                    },
                    "elements": [
                        {"tag": "markdown", "content": panel_md, "text_align": "left"},
                    ],
                }
            )
        if self.include_archive_link:
            elements.append(
                {"tag": "markdown", "content": self.ARCHIVE_LINK_LINE, "text_align": "left"},
            )

        return {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",
                "header": header,
                "body": {"elements": elements},
            },
        }

    def _build_payload(self, content: str, title: str = None) -> Dict:
        """
        构建飞书卡片消息 payload，支持 Markdown，
        参考  https://open.feishu.cn/document/feishu-cards/card-json-v2-structure
        """

        header = {}
        if title:
            header = {
                "title": {"content": title, "tag": "plain_text"},
                "template": "blue",
            }

        return {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",  # 【重点1】显式声明使用 V2 版本结构
                "header": header,
                "body": {  # 【重点2】V2 中，所有的内容元素都必须放在 body 里面
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": content,
                            "text_align": "left",  # 可选：left / center / right
                        },
                    ],
                },
            },
        }

    def _split_content(self, content: str, limit: int = 8000) -> list:
        """飞书卡片消息 markdown 元素限制 8000 字符"""
        if len(content) <= limit:
            return [content]

        chunks = []
        lines = content.split("\n")
        current = ""

        for line in lines:
            if len(current) + len(line) + 1 > limit:
                if current:
                    chunks.append(current)
                current = line
            else:
                current += "\n" + line if current else line

        if current:
            chunks.append(current)

        return chunks
