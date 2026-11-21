"""与当前01专项工作的相关性板块:归纳今日消息与 ongoing_work 工作文档的相关性

产出拼进早报正文(insights 后、gaps 前,由 main.py 补 H2 板块头),
同时单独落盘 news-data/relevance-*.md 供人工核验。
"""

import json
from datetime import datetime
from typing import Dict, Optional, Tuple

from src.sections.common import load_top_entries
from src.sections.relevance.workdocs import load_work_docs


async def run_relevance_section(
    config: Dict,
    now: Optional[datetime] = None,
) -> Tuple[str, Optional[str]]:
    """返回 (markdown, error)。不带 metadata;由早报编排负责拼装与落盘。"""
    cfg = config.get("sections", {}).get("relevance", {})
    if not cfg.get("enabled", False):
        return "", None

    work_docs = load_work_docs(
        cfg.get("work_dir", "ongoing_work"),
        max_chars_per_doc=cfg.get("work_doc_max_chars", 20000),
    )
    # include_docs 非空时只保留指定文档(2026-08-27 起默认只用《以往研究内容》)
    include = cfg.get("include_docs") or []
    if include:
        kept = [d for d in work_docs if d["name"] in include]
        missing = set(include) - {d["name"] for d in kept}
        if missing:
            print(f"⚠️ relevance: include_docs 指定的文档不存在/不可用: {sorted(missing)}")
        work_docs = kept
    if not work_docs:
        print("ℹ️ relevance: 无工作文档,省略相关性分析")
        return "", None

    from src.llm import generate_work_relevance

    top_n = cfg.get("top_n", 30)
    top_entries = load_top_entries(config, top_n, include_link=True)
    print(f"📋 relevance: {len(work_docs)} 份工作文档 × top-{len(top_entries)} 高分条目")

    # 素材为空时不调 LLM,直接省略(避免零素材下硬拉关系)
    if not top_entries:
        print("ℹ️ relevance: 今日无高分素材,省略相关性分析")
        return "", None

    work_docs_text = "\n\n".join(f"### {d['name']}\n\n{d['text']}" for d in work_docs)
    sections = {
        "work_docs": work_docs_text,
        "top_entries": json.dumps(top_entries, ensure_ascii=False, indent=2),
    }

    md, err = await generate_work_relevance(sections, config["llm"])
    if err:
        return "", f"generate_work_relevance: {err}"
    return (md or "").strip(), None
