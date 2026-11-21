"""报告归档解析层:扫描 news-data/push-*.md,归一化为结构化报告。

纯函数实现,不依赖 FastAPI,可独立单测。复用:
- src.markdown_utils.parse_frontmatter / normalize_str_list
- src.storage.extract_section / _SECTION_ORDER(sentinel 切片与老文件 rss 兜底)

三种文件形态归一:
1. 带 frontmatter(晚报 + 2026-08-14 起的早报) → 字段取 meta
2. 无 frontmatter 的存量早报(H1 + sentinel) → 标题回退 H1,profile 按 sentinel 判定
3. 无 sentinel 的晚报 → extract_section("rss") 兜底返回全文,归一化为单 rss 板块
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from src.markdown_utils import normalize_str_list, parse_frontmatter
from src.storage import _SECTION_ORDER, extract_section

REPORT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")
_REPORT_FILE_RE = re.compile(r"^push-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})(?:-week)?\.md$")
_H1_RE = re.compile(r"^#\s+(.+)$", re.M)
_H2_RE = re.compile(r"^##\s+(.+)$", re.M)

SECTION_TITLE_FALLBACK = {
    "overview": "总览",
    "insights": "今日洞察",
    "plateau": '"高原"最新洞察',
    "peak": '"高峰"最新洞察',
    "relevance": "与当前01专项工作的相关性",
    "gaps": "问题发现",
    "rss": "今日Top热点",
    "hackernews": "Hacker News 热议",
    "weekly": "周报洞察",
    "weekly_plateau": '"高原"最新洞察',
    "weekly_peak": '"高峰"最新洞察',
    "weekly_top": "本周Top热点",
}

# insights sentinel 段内的 H2 → 子板块 key(总览/洞察类 拆为独立栏目)
# 带符号变体为日报模板新标题,纯文本变体保留以兼容历史报告;
# 🌄"高原"/⛰️"高峰" 为 2026-08-27 起新板块(替换 💡 今日洞察);
# 💡 今日洞察(insights 子板块)2026-08-31 起在归档界面退役,拆分后过滤不再展示
_INSIGHTS_H2_KEYS = {
    "总览": "overview",
    "📋 总览": "overview",
    "今日洞察": "insights",
    "💡 今日洞察": "insights",
    '"高原"最新洞察': "plateau",
    '🌄 "高原"最新洞察': "plateau",
    '"高峰"最新洞察': "peak",
    '⛰️ "高峰"最新洞察': "peak",
}

# weekly sentinel 段内的 H2 → 子板块 key(总览/高原/高峰 拆为独立栏目)
# 🌄"高原"/⛰️"高峰" 为 2026-09-05 起新格式(与日报一致);
# 💡 本周洞察/📈 趋势分析 为旧格式,保留映射兼容历史报告
_WEEKLY_H2_KEYS = {
    "总览": "weekly_overview",
    "📋 总览": "weekly_overview",
    '"高原"最新洞察': "weekly_plateau",
    '🌄 "高原"最新洞察': "weekly_plateau",
    '"高峰"最新洞察': "weekly_peak",
    '⛰️ "高峰"最新洞察': "weekly_peak",
    "本周洞察": "weekly_insights",
    "💡 本周洞察": "weekly_insights",
    "趋势分析": "weekly_trends",
    "📈 趋势分析": "weekly_trends",
}

# 栏目流(/api/sections/{key})允许的板块 key
# insights(旧 💡 今日洞察)2026-08-31 起退役,不再提供栏目流
STREAM_SECTION_KEYS = (
    "overview",
    "plateau",
    "peak",
    "relevance",
    "gaps",
    "rss",
    "hackernews",
    "weekly_overview",
    "weekly_plateau",
    "weekly_peak",
    "weekly_insights",
    "weekly_trends",
    "weekly_top",
)

# path -> (mtime_ns, parsed_report);单进程小数据量,按 mtime 失效即可
_cache: Dict[str, tuple] = {}


def report_id_from_name(name: str) -> Optional[str]:
    m = _REPORT_FILE_RE.fullmatch(name)
    return m.group(1) if m else None


def _strip_leading_h1(md: str) -> str:
    """老文件 rss 兜底返回全文时,剥掉首行 H1(报告标题已在详情头展示)"""
    return re.sub(r"\A\s*#\s+[^\n]*\n*", "", md, count=1).strip()


def _strip_leading_h2(md: str) -> str:
    """栏目流条目剥掉板块首个 H2(栏目标题已在页面头部展示,避免重复)"""
    return re.sub(r"\A\s*##\s+[^\n]*\n*", "", md, count=1).strip()


def _split_h2_sections(md: str, h2_keys: Dict[str, str], fallback_key: str) -> List[Dict]:
    """sentinel 段按 H2 拆成子板块(如 insights → 总览/高原/高峰,weekly → 总览/本周洞察/趋势分析)。

    首个 H2 前的内容并入第一块;无 H2 时整段作为单板块;
    未识别的 H2 标题归入 fallback_key。
    """
    chunks = [c.strip() for c in re.split(r"(?m)(?=^## )", md) if c.strip()]
    if not chunks:
        return []
    if not any(_H2_RE.match(c.splitlines()[0]) for c in chunks):
        # 整段无 H2(或 H2 不在行首),按单板块返回
        return [
            {
                "key": fallback_key,
                "title": SECTION_TITLE_FALLBACK[fallback_key],
                "markdown": md.strip(),
            }
        ]

    sections = []
    preamble = ""
    for chunk in chunks:
        first_line = chunk.splitlines()[0]
        if not _H2_RE.match(first_line):
            preamble += chunk + "\n\n"  # H2 之前的内容,并入下一块
            continue
        body = (preamble + chunk).strip()
        preamble = ""
        title = _H2_RE.match(first_line).group(1).strip()
        sections.append(
            {
                "key": h2_keys.get(title, fallback_key),
                "title": title,
                "markdown": body,
            }
        )
    if preamble.strip():
        # 全是 preamble(无 H2)的兜底上面已处理;此处为末尾游离内容,并入最后一块
        sections[-1]["markdown"] += "\n\n" + preamble.strip()
    return sections


def _split_sections(body: str) -> List[Dict]:
    """按 _SECTION_ORDER 切片;空段省略;insights 段再按 H2 拆子板块;
    板块标题取第一个 H2,缺省查 fallback"""
    sections = []
    for key in _SECTION_ORDER:
        md = extract_section(body, key)
        if not md.strip():
            continue
        # rss 兜底路径会把整篇 body(含残留 frontmatter / 首行 H1)还回来
        if key == "rss":
            _, md = parse_frontmatter(md)
            md = _strip_leading_h1(md)
        md = md.strip()
        if not md:
            continue
        if key == "insights":
            # 旧 💡 今日洞察 子板块(key == "insights",含未识别 H2 的 fallback)退役不展示
            sections.extend(
                s
                for s in _split_h2_sections(md, _INSIGHTS_H2_KEYS, "insights")
                if s["key"] != "insights"
            )
            continue
        if key == "weekly":
            sections.extend(_split_h2_sections(md, _WEEKLY_H2_KEYS, "weekly"))
            continue
        h2 = _H2_RE.search(md)
        sections.append(
            {
                "key": key,
                "title": h2.group(1).strip() if h2 else SECTION_TITLE_FALLBACK[key],
                "markdown": md,
            }
        )
    return sections


def parse_report(path: Path) -> Optional[Dict]:
    """解析单个 push 文件为报告 dict(含完整板块数组);文件名不合规返回 None"""
    report_id = report_id_from_name(path.name)
    if not report_id:
        return None

    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    date_str = report_id[:10]
    time_str = f"{report_id[11:13]}:{report_id[14:16]}"

    if meta:
        title = str(meta.get("title") or "").strip()
        if not title:
            h1 = _H1_RE.search(body)
            title = h1.group(1).strip() if h1 else f"AI4S 报告 {date_str}"
        profile = str(meta.get("profile") or "default")
        lead = str(meta.get("lead") or "")
        highlights = normalize_str_list(meta.get("highlights"))
        source_count = meta.get("sourceCount")
        total_entries = meta.get("totalEntries")
    else:
        h1 = _H1_RE.search(body)
        title = h1.group(1).strip() if h1 else f"AI4S 报告 {date_str}"
        profile = "morning" if "<!-- SECTION:" in body else "default"
        lead, highlights = "", []
        source_count = total_entries = None

    return {
        "id": report_id,
        "date": date_str,
        "time": time_str,
        "profile": profile,
        "title": title,
        "lead": lead,
        "highlights": highlights,
        "sourceCount": source_count,
        "totalEntries": total_entries,
        "sections": _split_sections(body),
    }


def _parse_cached(path: Path) -> Optional[Dict]:
    key = str(path)
    mtime_ns = path.stat().st_mtime_ns
    cached = _cache.get(key)
    if cached and cached[0] == mtime_ns:
        return cached[1]
    parsed = parse_report(path)
    _cache[key] = (mtime_ns, parsed)
    return parsed


def scan_reports(data_dir: str = "news-data") -> List[Dict]:
    """扫描全部报告,按时间倒序返回摘要(sections 退化为 key 列表)"""
    data_path = Path(data_dir)
    if not data_path.exists():
        return []

    reports = []
    for f in data_path.glob("push-*.md"):
        if f.stat().st_size == 0 or not report_id_from_name(f.name):
            continue
        try:
            parsed = _parse_cached(f)
        except Exception as e:
            print(f"⚠️ 报告解析失败,已跳过 {f.name}: {e}")
            continue
        if parsed:
            reports.append(parsed)

    reports.sort(key=lambda r: r["id"], reverse=True)
    return [
        {**r, "sections": [s["key"] for s in r["sections"]]} for r in reports
    ]


def load_report(report_id: str, data_dir: str = "news-data") -> Optional[Dict]:
    """按 report_id 加载完整报告;id 不合规或文件不存在返回 None。

    周报文件带 -week 后缀,两种命名都尝试。
    """
    if not REPORT_ID_RE.fullmatch(report_id):
        return None
    for name in (f"push-{report_id}.md", f"push-{report_id}-week.md"):
        path = Path(data_dir) / name
        if path.is_file():
            return _parse_cached(path)
    return None


def scan_section(key: str, data_dir: str = "news-data") -> List[Dict]:
    """栏目流:跨报告聚合指定板块的条目,按时间倒序。

    返回 [{report_id, date, time, profile, title, markdown}],仅含拥有该板块的报告。
    """
    if key not in STREAM_SECTION_KEYS:
        return []

    data_path = Path(data_dir)
    if not data_path.exists():
        return []

    entries = []
    for f in data_path.glob("push-*.md"):
        if f.stat().st_size == 0 or not report_id_from_name(f.name):
            continue
        try:
            parsed = _parse_cached(f)
        except Exception as e:
            print(f"⚠️ 报告解析失败,已跳过 {f.name}: {e}")
            continue
        if not parsed:
            continue
        for sec in parsed["sections"]:
            if sec["key"] == key:
                entries.append(
                    {
                        "report_id": parsed["id"],
                        "date": parsed["date"],
                        "time": parsed["time"],
                        "profile": parsed["profile"],
                        "title": sec["title"],
                        "markdown": _strip_leading_h2(sec["markdown"]),
                    }
                )

    entries.sort(key=lambda e: e["report_id"], reverse=True)
    return entries
