"""Weekly 板块:窗口期高分条目 → LLM 产出 总览/本周洞察/趋势分析 + 确定性 Top 热点榜单"""

import json
from datetime import datetime
from typing import Dict, Optional, Tuple

from src.sections.common import (
    EMPTY_MARKER,
    load_top_entries_range,
    weekly_window,
)
from src.storage import load_recent_push_content

_WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _format_window(start, end) -> str:
    """窗口期的人类可读描述,如 '8.17–8.20（周一至周四）'"""
    return (
        f"{start.month}.{start.day}–{end.month}.{end.day}"
        f"（{_WEEKDAY_NAMES[start.weekday()]}至{_WEEKDAY_NAMES[end.weekday()]}）"
    )


async def run_weekly_section(
    config: Dict,
    now: Optional[datetime] = None,
) -> Tuple[str, Optional[Dict], Optional[str]]:
    """周报主板块合同与 run_insights_section 一致:返回 (md, metadata, err)。

    无窗口期素材时返回 ("", None, None),与 gaps 板块的无素材省略策略一致。
    """
    cfg = config.get("sections", {}).get("weekly", {})
    if not cfg.get("enabled", False):
        return "", None, None

    from src.llm import generate_weekly_report, parse_weekly_with_metadata

    if now is None:
        now = datetime.now()
    start, end = weekly_window(now)

    top_n = cfg.get("top_n", 40)
    top_entries = load_top_entries_range(config, start, end, top_n)
    print(f"📋 weekly: 窗口 {_format_window(start, end)} 选取 top-{len(top_entries)} 高分条目作为分析素材")
    if not top_entries:
        return "", None, None

    context_days = config.get("filter", {}).get("push_context_days", 5)
    recent = load_recent_push_content(context_days, section="insights")

    sections = {
        "top_entries": json.dumps(top_entries, ensure_ascii=False, indent=2),
        "window": _format_window(start, end),
        "recent_context": recent or EMPTY_MARKER,
    }

    md, err = await generate_weekly_report(sections, config["llm"])
    if err:
        return "", None, f"generate_weekly_report: {err}"

    date_str = now.strftime("%Y-%m-%d")
    weekly_md, metadata = parse_weekly_with_metadata(md or "", date_str)

    return weekly_md, metadata, None


def build_weekly_top_section(
    config: Dict, now: Optional[datetime] = None
) -> str:
    """确定性「本周Top热点」榜单:窗口期按 score 降序取 top_hot_n,无 LLM 调用。

    分数在 fetch 期已由 LLM 评定,榜单排序可复现。无素材返回 ""。
    """
    cfg = config.get("sections", {}).get("weekly", {})
    if not cfg.get("enabled", False):
        return ""

    if now is None:
        now = datetime.now()
    start, end = weekly_window(now)

    top_hot_n = cfg.get("top_hot_n", 10)
    entries = load_top_entries_range(config, start, end, top_hot_n, include_link=True)
    if not entries:
        return ""

    lines = ["## 🏆 本周Top热点", ""]
    for e in entries:
        title = e.get("title", "")
        link = e.get("link", "")
        head = f"- **[{e.get('score', 0)}]** [{title}]({link})" if link else f"- **[{e.get('score', 0)}]** {title}"
        source = e.get("source", "")
        if source:
            head += f" — {source}"
        lines.append(head)
        summary = (e.get("summary") or "").strip()
        if summary:
            lines.append(f"  {summary}")
    return "\n".join(lines)
