"""Insights 板块:基于 top-N 高分原始条目 + HN 板块成品做总览与观点"""

import json
from datetime import datetime
from typing import Dict, Optional, Tuple

from src.sections.common import EMPTY_MARKER, load_top_entries


async def run_insights_section(
    rss_md: str,
    hn_md: str,
    config: Dict,
    now: Optional[datetime] = None,
) -> Tuple[str, Optional[Dict], Optional[str]]:
    cfg = config.get("sections", {}).get("insights", {})
    if not cfg.get("enabled", False):
        return "", None, None

    from src.llm import generate_trend_insights, parse_insights_with_metadata

    top_n = cfg.get("top_n", 20)
    top_entries = load_top_entries(config, top_n)
    print(f"📋 insights: 选取 top-{len(top_entries)} 高分条目作为分析素材")

    sections = {
        "top_entries": json.dumps(top_entries, ensure_ascii=False, indent=2)
        if top_entries
        else EMPTY_MARKER,
        "rss": rss_md or EMPTY_MARKER,
        "hackernews": hn_md or EMPTY_MARKER,
    }

    md, err = await generate_trend_insights(sections, config["llm"])
    if err:
        return "", None, f"generate_trend_insights: {err}"

    if now is None:
        now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    insights_md, metadata = parse_insights_with_metadata(md or "", date_str)

    return insights_md, metadata, None
