"""板块共享逻辑:top-N 高分素材选取与空标记"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.storage import get_fetch_file, read_entries

EMPTY_MARKER = "(本次无内容)"

# 单条素材摘要截断长度,防止超长 content 撑爆 prompt
_SUMMARY_MAX_CHARS = 120


def _compact_entry(e: Dict, include_link: bool = False) -> Dict:
    """压缩条目为紧凑结构,防止超长字段撑爆 prompt"""
    item = {
        "title": e.get("title", ""),
        "source": e.get("source", ""),
        "score": e.get("score", 0),
        "tags": e.get("tags", []),
        "summary": (e.get("summary") or "")[:_SUMMARY_MAX_CHARS],
    }
    if include_link:
        item["link"] = e.get("link", "")
    return item


def load_top_entries(config: Dict, top_n: int, include_link: bool = False) -> List[Dict]:
    """读取今日 fetch 文件,按 score 降序取 top-N(仅 ≥ min_score),压缩为紧凑结构。

    include_link=True 时附带 link 字段(供人工核验类输出引用原文)。
    """
    min_score = config.get("filter", {}).get("min_score", 60)
    entries = [
        e
        for e in read_entries(get_fetch_file())
        if (e.get("score") or 0) >= min_score
    ]
    entries.sort(key=lambda e: e.get("score") or 0, reverse=True)
    return [_compact_entry(e, include_link) for e in entries[:top_n]]


def weekly_window(now: datetime) -> Tuple[date, date]:
    """周报素材窗口:周四(含)前触发 → 本周一~今天;周五(含)后触发 → 本周五~今天。

    周四 17:00 推送覆盖周一~周四,周日 17:00 推送覆盖周五~周日。
    """
    today = now.date()
    weekday = now.weekday()  # Mon=0 ... Sun=6
    if weekday <= 3:
        start = today - timedelta(days=weekday)
    else:
        start = today - timedelta(days=weekday - 4)
    return start, today


def load_top_entries_range(
    config: Dict,
    start: date,
    end: date,
    top_n: int,
    include_link: bool = False,
    data_dir: str = "news-data",
) -> List[Dict]:
    """跨天版 load_top_entries:遍历 [start..end] 的 fetch 文件,按 link 去重(保留最高分)。

    缺天的 fetch 文件直接跳过。score ≥ min_score,按 score 降序截断 top_n。
    """
    min_score = config.get("filter", {}).get("min_score", 60)
    by_link: Dict[str, Dict] = {}
    no_link: List[Dict] = []

    days = (end - start).days + 1
    for i in range(days):
        d = start + timedelta(days=i)
        for e in read_entries(get_fetch_file(d, data_dir)):
            if (e.get("score") or 0) < min_score:
                continue
            link = e.get("link") or ""
            if link:
                prev = by_link.get(link)
                if prev is None or (e.get("score") or 0) > (prev.get("score") or 0):
                    by_link[link] = e
            else:
                no_link.append(e)

    entries = sorted(
        [*by_link.values(), *no_link],
        key=lambda e: e.get("score") or 0,
        reverse=True,
    )
    return [_compact_entry(e, include_link) for e in entries[:top_n]]


def window_stats(
    config: Dict, start: date, end: date, data_dir: str = "news-data"
) -> Dict:
    """窗口期内 ≥min_score 去重后的统计,供周报 frontmatter 使用"""
    entries = load_top_entries_range(
        config, start, end, top_n=10**9, data_dir=data_dir
    )
    return {
        "totalEntries": len(entries),
        "sourceCount": len({e.get("source", "") for e in entries if e.get("source")}),
    }
