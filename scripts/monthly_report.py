#!/usr/bin/env python3
"""月报试生成(2026-09-07 首版,2026-09-12 信号模板版):窗口 8.12–9.12,逐日时序素材 + 信号模板 prompt。

复用周报的 LLM 管线(load_prompt/call_llm/parse_weekly_with_metadata),
产物为 news-data/push-{时间戳}-month.md(profile: "monthly"),仅落盘供审查,不推送。
2026-09-09 修订:仅保留高原/高峰脉络,专家思考改为宏观/技术两条。
2026-09-12 修订:正文改为信号(Signal)模板——4-6 个信号,每个含 已发生的事实(带链接)/
目前可以下的判断/中观上怎么看/宏观上需要保留的预警/当前信心;模型改用 llm.monthly_model。
"""
import asyncio
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(".env")

from src.config import load_config
from src.llm import call_llm, load_prompt, parse_weekly_with_metadata
from src.markdown_utils import dump_frontmatter
from src.sections.common import _compact_entry, window_stats
from src.storage import get_fetch_file, get_push_file, read_entries

START, END = date(2026, 8, 12), date(2026, 9, 12)
PER_DAY_TOP = 6  # 每天取 top-N,保留时序分布与跨天重复(重复=信号增强)


def build_timeline_entries(config):
    """逐日取高分条目并标注日期,刻意不跨天去重"""
    min_score = config.get("filter", {}).get("min_score", 60)
    out = []
    d = START
    while d <= END:
        entries = [
            e for e in read_entries(get_fetch_file(d)) if (e.get("score") or 0) >= min_score
        ]
        entries.sort(key=lambda e: e.get("score") or 0, reverse=True)
        for e in entries[:PER_DAY_TOP]:
            item = {"date": d.strftime("%m-%d")}
            item.update(_compact_entry(e, include_link=True))
            out.append(item)
        d += timedelta(days=1)
    return out


async def main():
    config = load_config()
    window = f"{START.month}.{START.day}–{END.month}.{END.day}"

    timeline = build_timeline_entries(config)
    print(f"📋 monthly: 窗口 {window} 逐日时序素材 {len(timeline)} 条(每天 top-{PER_DAY_TOP},未跨天去重)")
    if not timeline:
        print("⚠️ 窗口期无素材,退出")
        return 1

    prompt = load_prompt(
        "prompts/monthly.md",
        window=f"{window}（{START.month}月{START.day}日至{END.month}月{END.day}日）",
        timeline_entries=json.dumps(timeline, ensure_ascii=False, indent=2),
    )
    print(f"🤖 调用 LLM(prompt {len(prompt)} 字符)...")
    # 月报模型与日报/周报区分:llm.monthly_model 缺省时回退 llm.model
    llm_cfg = dict(config["llm"])
    llm_cfg["model"] = config["llm"].get("monthly_model") or config["llm"]["model"]
    print(f"📐 月报模型: {llm_cfg['model']}")
    md, err = await call_llm(prompt, llm_cfg), None
    body, metadata = parse_weekly_with_metadata(md or "", END.isoformat())
    if not body.strip():
        print("❌ LLM 输出为空")
        return 1

    # 强制标题(同日报/周报做法)+ profile/stats
    now = datetime.now()
    metadata["title"] = f"AI4S前沿观察月报（{window}）"
    metadata["profile"] = "monthly"
    metadata["date"] = END.isoformat()
    metadata.update(window_stats(config, START, END))
    metadata["pushTime"] = now.isoformat()

    parts = [
        f"---\n{dump_frontmatter(metadata)}---",
        f"# {metadata['title']}",
        "<!-- SECTION:monthly BEGIN -->\n" + body.strip() + "\n<!-- SECTION:monthly END -->",
    ]
    final = "\n\n".join(parts) + "\n"

    path = get_push_file(suffix="-month")
    Path(path).write_text(final, encoding="utf-8")
    print(f"💾 已保存月报到 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
