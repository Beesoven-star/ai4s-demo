"""问题发现板块:基于 top-N 高分条目 + HN 成品识别潜在 research gap"""

import json
from datetime import datetime
from typing import Dict, Optional, Tuple

from src.sections.common import EMPTY_MARKER, load_top_entries


async def run_gaps_section(
    hn_md: str,
    config: Dict,
    now: Optional[datetime] = None,
) -> Tuple[str, Optional[str]]:
    """返回 (markdown, error)。不带 metadata——早报 metadata 由 insights 独占。"""
    cfg = config.get("sections", {}).get("gaps", {})
    if not cfg.get("enabled", False):
        return "", None

    from src.llm import generate_research_gaps

    top_n = cfg.get("top_n", 20)
    top_entries = load_top_entries(config, top_n)
    print(f"📋 gaps: 选取 top-{len(top_entries)} 高分条目作为分析素材")

    # 素材为空时不调 LLM,直接省略该段(避免零素材下诱发幻觉 gap);
    # "有素材但都是常规更新"的细粒度判断交给 LLM 输出"本期无可靠 gap"
    if not top_entries:
        print("ℹ️ gaps: 今日无高分素材,省略问题发现段")
        return "", None

    sections = {
        "top_entries": json.dumps(top_entries, ensure_ascii=False, indent=2),
        "hackernews": hn_md or EMPTY_MARKER,
    }

    md, err = await generate_research_gaps(sections, config["llm"])
    if err:
        return "", f"generate_research_gaps: {err}"
    return (md or "").strip(), None
