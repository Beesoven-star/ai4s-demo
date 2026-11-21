"""测试报告归档解析层(src/web/reports.py):三种文件形态归一 + 扫描/加载"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.web.reports import (
    REPORT_ID_RE,
    load_report,
    parse_report,
    report_id_from_name,
    scan_reports,
    scan_section,
)

MORNING_WITH_FM = """---
title: "AI4S前瞻研判报告（8.14）"
lead: "今日导读"
highlights: ["要点一", "要点二"]
profile: "morning"
date: "2026-08-14"
sourceCount: 12
totalEntries: 34
---

# AI4S前瞻研判报告（8.14）

<!-- SECTION:insights BEGIN -->
## 总览

总览正文

## 今日洞察

洞察正文
<!-- SECTION:insights END -->

<!-- SECTION:relevance BEGIN -->
## 与当前01专项工作的相关性

相关性正文
<!-- SECTION:relevance END -->

<!-- SECTION:rss BEGIN -->
## 今日Top热点

热点正文
<!-- SECTION:rss END -->
"""

MORNING_LEGACY = """# AI4S前瞻研判报告（8.13）

<!-- SECTION:insights BEGIN -->
## 总览

总览正文
<!-- SECTION:insights END -->

<!-- SECTION:gaps BEGIN -->
## 问题发现

gap 正文
<!-- SECTION:gaps END -->

<!-- SECTION:hackernews BEGIN -->
## 🟧 Hacker News 热议

HN 正文
<!-- SECTION:hackernews END -->
"""

EVENING_LEGACY = """---
title: "Anthropic 发布新模型"
lead: "晚报导读"
highlights: ["晚报要点"]
profile: "default"
date: "2026-08-12"
sourceCount: 5
totalEntries: 9
---

### 1️⃣ 条目一

digest 正文
"""


def _write(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


WEEKLY_WITH_FM = """---
title: "AI4S周报（8.17–8.20）"
lead: "周报导读"
highlights: ["要点一"]
profile: "weekly"
date: "2026-08-20"
sourceCount: 8
totalEntries: 42
---

# AI4S周报（8.17–8.20）

<!-- SECTION:weekly BEGIN -->
## 总览

周报总览正文

## 本周洞察

周报洞察正文

## 趋势分析

周报趋势正文
<!-- SECTION:weekly END -->

<!-- SECTION:weekly_top BEGIN -->
## 本周Top热点

- **[95]** [t1](http://a) — s1
<!-- SECTION:weekly_top END -->
"""

WEEKLY_FILE_NAME = "push-2026-08-20-17-00-00-week.md"


def test_parse_weekly_report(tmp_path):
    f = _write(tmp_path, WEEKLY_FILE_NAME, WEEKLY_WITH_FM)
    r = parse_report(f)

    assert r["profile"] == "weekly"
    assert r["title"] == "AI4S周报（8.17–8.20）"
    assert r["sourceCount"] == 8
    # weekly 段按 H2 拆为三个子板块,weekly_top 独立成板块
    assert [s["key"] for s in r["sections"]] == [
        "weekly_overview", "weekly_insights", "weekly_trends", "weekly_top",
    ]
    assert r["sections"][1]["title"] == "本周洞察"
    assert "周报趋势正文" in r["sections"][2]["markdown"]
    assert "[95]" in r["sections"][3]["markdown"]


WEEKLY_NO_H2 = """---
title: "AI4S周报（8.17–8.20）"
profile: "weekly"
date: "2026-08-20"
---

# AI4S周报（8.17–8.20）

<!-- SECTION:weekly BEGIN -->
退化的周报正文(无 H2)
<!-- SECTION:weekly END -->

<!-- SECTION:weekly_top BEGIN -->
纯榜单内容无 H2
<!-- SECTION:weekly_top END -->
"""


def test_parse_weekly_emoji_headings(tmp_path):
    """带符号周报标题(2026-08-24 起模板新标题)映射到相同子板块 key"""
    f = _write(
        tmp_path, WEEKLY_FILE_NAME,
        WEEKLY_WITH_FM
        .replace("## 总览", "## 📋 总览")
        .replace("## 本周洞察", "## 💡 本周洞察")
        .replace("## 趋势分析", "## 📈 趋势分析"),
    )
    r = parse_report(f)

    assert [s["key"] for s in r["sections"]] == [
        "weekly_overview", "weekly_insights", "weekly_trends", "weekly_top",
    ]
    assert r["sections"][1]["title"] == "💡 本周洞察"
    assert "周报趋势正文" in r["sections"][2]["markdown"]


def test_parse_weekly_without_h2_uses_fallback(tmp_path):
    """weekly/weekly_top 段无 H2 时走 fallback 标题,不抛 KeyError"""
    f = _write(tmp_path, WEEKLY_FILE_NAME, WEEKLY_NO_H2)
    r = parse_report(f)

    assert r["profile"] == "weekly"
    keys = [s["key"] for s in r["sections"]]
    assert keys == ["weekly", "weekly_top"]
    assert r["sections"][0]["title"] == "周报洞察"
    assert r["sections"][1]["title"] == "本周Top热点"


def test_scan_section_weekly_stream(tmp_path):
    _write(tmp_path, WEEKLY_FILE_NAME, WEEKLY_WITH_FM)
    entries = scan_section("weekly_insights", str(tmp_path))
    assert len(entries) == 1
    assert entries[0]["profile"] == "weekly"
    assert "周报洞察正文" in entries[0]["markdown"]


WEEKLY_PLATEAU_PEAK = """---
title: "AI4S周报（9.1–9.4）"
profile: "weekly"
date: "2026-09-04"
---

# AI4S周报（9.1–9.4）

<!-- SECTION:weekly BEGIN -->
## 📋 总览

- **高原**：周报高原观点
  - **重要新闻事件**：
    - 高原要闻一
- **高峰**：周报高峰观点

## 🌄 "高原"最新洞察

### 科学通用底座
- **高原观点句** 高原支撑正文

## ⛰️ "高峰"最新洞察

### 高能物理与量子科技
- **高峰观点句** 高峰支撑正文
<!-- SECTION:weekly END -->

<!-- SECTION:weekly_top BEGIN -->
## 🏆 本周Top热点

- **[95]** [t1](http://a) — s1
<!-- SECTION:weekly_top END -->
"""


def test_parse_weekly_plateau_peak_headings(tmp_path):
    """2026-09-05 起周报改为高原/高峰双板块(与日报一致),拆为 weekly_overview/weekly_plateau/weekly_peak"""
    f = _write(tmp_path, "push-2026-09-04-17-00-00-week.md", WEEKLY_PLATEAU_PEAK)
    r = parse_report(f)

    assert [s["key"] for s in r["sections"]] == [
        "weekly_overview", "weekly_plateau", "weekly_peak", "weekly_top",
    ]
    assert r["sections"][1]["title"] == '🌄 "高原"最新洞察'
    assert "高原支撑正文" in r["sections"][1]["markdown"]
    assert r["sections"][2]["title"] == '⛰️ "高峰"最新洞察'

    # 高原/高峰栏目流可读
    plateau = scan_section("weekly_plateau", str(tmp_path))
    assert [e["report_id"] for e in plateau] == ["2026-09-04-17-00-00"]
    assert "高原支撑正文" in plateau[0]["markdown"]


def test_parse_morning_with_frontmatter(tmp_path):
    f = _write(tmp_path, "push-2026-08-14-11-44-55.md", MORNING_WITH_FM)
    r = parse_report(f)

    assert r["id"] == "2026-08-14-11-44-55"
    assert r["date"] == "2026-08-14"
    assert r["time"] == "11:44"
    assert r["profile"] == "morning"
    assert r["title"] == "AI4S前瞻研判报告（8.14）"
    assert r["lead"] == "今日导读"
    assert r["highlights"] == ["要点一", "要点二"]
    assert r["sourceCount"] == 12
    assert r["totalEntries"] == 34
    # 板块按 _SECTION_ORDER 排序,空段(gaps/hackernews)省略;
    # insights 段按 H2 拆分,旧「今日洞察」子板块 2026-08-31 起退役不展示
    assert [s["key"] for s in r["sections"]] == [
        "overview",
        "relevance",
        "rss",
    ]
    assert r["sections"][0]["title"] == "总览"
    assert "总览正文" in r["sections"][0]["markdown"]
    assert "## 今日洞察" not in r["sections"][0]["markdown"]
    assert all("洞察正文" not in s["markdown"] for s in r["sections"])
    assert "SECTION:" not in r["sections"][0]["markdown"]


def test_parse_morning_legacy_falls_back_to_h1(tmp_path):
    f = _write(tmp_path, "push-2026-08-13-15-58-32.md", MORNING_LEGACY)
    r = parse_report(f)

    assert r["profile"] == "morning"  # 含 sentinel → 判定早报
    assert r["title"] == "AI4S前瞻研判报告（8.13）"  # H1 回退
    assert r["lead"] == ""
    assert r["highlights"] == []
    assert r["sourceCount"] is None
    # 存量早报 insights 段只有「总览」一个 H2 → 拆为单 overview 板块
    assert [s["key"] for s in r["sections"]] == ["overview", "gaps", "hackernews"]


MORNING_EMOJI_HEADINGS = """---
title: "AI4S前瞻研判报告（8.21）"
profile: "morning"
date: "2026-08-21"
---

# AI4S前瞻研判报告（8.21）

<!-- SECTION:insights BEGIN -->
## 📋 总览

总览正文

## 💡 今日洞察

洞察正文
<!-- SECTION:insights END -->

<!-- SECTION:relevance BEGIN -->
## 🧭 与当前01专项工作的相关性

相关性正文
<!-- SECTION:relevance END -->

<!-- SECTION:rss BEGIN -->
## 📰 今日Top热点

热点正文
<!-- SECTION:rss END -->
"""


def test_parse_morning_emoji_headings(tmp_path):
    """2026-08-21 起日报模板标题带符号,insights 段正确拆分为 overview;
    💡 今日洞察 子板块 2026-08-31 起退役不展示"""
    f = _write(tmp_path, "push-2026-08-21-08-01-11.md", MORNING_EMOJI_HEADINGS)
    r = parse_report(f)

    assert [s["key"] for s in r["sections"]] == ["overview", "relevance", "rss"]
    assert r["sections"][0]["title"] == "📋 总览"
    assert "总览正文" in r["sections"][0]["markdown"]
    assert all("洞察正文" not in s["markdown"] for s in r["sections"])


MORNING_PLATEAU_PEAK = """---
title: "AI4S前瞻研判报告（8.27）"
profile: "morning"
date: "2026-08-27"
---

# AI4S前瞻研判报告（8.27）

<!-- SECTION:insights BEGIN -->
## 📋 总览

总览正文

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

<!-- SECTION:rss BEGIN -->
## 📰 今日Top热点

热点正文
<!-- SECTION:rss END -->
"""


def test_parse_morning_plateau_peak_headings(tmp_path):
    """2026-08-27 起 insights 段改为高原/高峰双板块,拆为 overview/plateau/peak"""
    f = _write(tmp_path, "push-2026-08-27-08-00-56.md", MORNING_PLATEAU_PEAK)
    r = parse_report(f)

    assert [s["key"] for s in r["sections"]] == ["overview", "plateau", "peak", "relevance", "rss"]
    assert r["sections"][1]["title"] == '🌄 "高原"最新洞察'
    assert "高原观点正文" in r["sections"][1]["markdown"]
    assert r["sections"][2]["title"] == '⛰️ "高峰"最新洞察'
    assert "### 高能物理与量子科技" in r["sections"][2]["markdown"]  # H3 学科子标题保留在板块内

    # 高原/高峰栏目流可读
    plateau = scan_section("plateau", str(tmp_path))
    assert [e["report_id"] for e in plateau] == ["2026-08-27-08-00-56"]
    assert "高原观点正文" in plateau[0]["markdown"]
    peak = scan_section("peak", str(tmp_path))
    assert [e["report_id"] for e in peak] == ["2026-08-27-08-00-56"]


def test_parse_evening_without_sentinels_single_rss_section(tmp_path):
    f = _write(tmp_path, "push-2026-08-12-21-43-57.md", EVENING_LEGACY)
    r = parse_report(f)

    assert r["profile"] == "default"
    assert r["title"] == "Anthropic 发布新模型"
    # 无 sentinel → extract_section("rss") 兜底返回全文,归一化为单 rss 板块
    assert [s["key"] for s in r["sections"]] == ["rss"]
    assert "digest 正文" in r["sections"][0]["markdown"]
    assert "---" not in r["sections"][0]["markdown"]  # 残留 frontmatter 已剥除


def test_scan_reports_sorted_desc_and_summary_sections(tmp_path):
    _write(tmp_path, "push-2026-08-14-11-44-55.md", MORNING_WITH_FM)
    _write(tmp_path, "push-2026-08-13-15-58-32.md", MORNING_LEGACY)
    _write(tmp_path, "push-2026-08-12-21-43-57.md", EVENING_LEGACY)
    _write(tmp_path, "push-非法文件名.md", MORNING_LEGACY)  # 应被跳过

    reports = scan_reports(str(tmp_path))

    assert [r["id"] for r in reports] == [
        "2026-08-14-11-44-55",
        "2026-08-13-15-58-32",
        "2026-08-12-21-43-57",
    ]
    # 摘要形态:sections 为 key 列表(旧 insights 板块已退役)
    assert reports[0]["sections"] == ["overview", "relevance", "rss"]


def test_load_report_and_id_validation(tmp_path):
    _write(tmp_path, "push-2026-08-14-11-44-55.md", MORNING_WITH_FM)

    r = load_report("2026-08-14-11-44-55", str(tmp_path))
    assert r is not None
    assert r["sections"][1]["key"] == "relevance"

    assert load_report("not-a-valid-id", str(tmp_path)) is None
    assert load_report("../../etc/passwd", str(tmp_path)) is None
    assert load_report("2099-01-01-00-00-00", str(tmp_path)) is None


def test_load_report_weekly_suffix(tmp_path):
    """周报文件(-week 后缀)可按同一时间戳 id 加载"""
    _write(tmp_path, WEEKLY_FILE_NAME, WEEKLY_WITH_FM)
    r = load_report("2026-08-20-17-00-00", str(tmp_path))
    assert r is not None
    assert r["profile"] == "weekly"


def test_report_id_from_name():
    assert report_id_from_name("push-2026-08-14-11-44-55.md") == "2026-08-14-11-44-55"
    # 周报文件名(-week 后缀)映射到同一时间戳 id
    assert report_id_from_name("push-2026-08-14-11-44-55-week.md") == "2026-08-14-11-44-55"
    assert report_id_from_name("push-2026-08-14.md") is None
    assert report_id_from_name("fetch-2026-08-14-11-44-55.md") is None
    assert REPORT_ID_RE.fullmatch("2026-08-14-11-44-55")


def test_scan_section_aggregates_across_reports(tmp_path):
    _write(tmp_path, "push-2026-08-14-11-44-55.md", MORNING_WITH_FM)
    _write(tmp_path, "push-2026-08-13-15-58-32.md", MORNING_LEGACY)
    _write(tmp_path, "push-2026-08-12-21-43-57.md", EVENING_LEGACY)  # 无 overview

    overview = scan_section("overview", str(tmp_path))
    assert [e["report_id"] for e in overview] == [
        "2026-08-14-11-44-55",
        "2026-08-13-15-58-32",
    ]
    assert overview[0]["date"] == "2026-08-14"
    assert overview[0]["profile"] == "morning"
    assert overview[0]["title"] == "总览"
    assert "总览正文" in overview[0]["markdown"]

    # 旧「今日洞察」栏目流 2026-08-31 起退役,不再提供
    assert scan_section("insights", str(tmp_path)) == []

    # relevance 时间倒序,缺失该板块的报告不占位
    relevance = scan_section("relevance", str(tmp_path))
    assert [e["report_id"] for e in relevance] == ["2026-08-14-11-44-55"]

    # rss:MORNING_LEGACY 无 rss 段,其余两份有(晚报由兜底归一)
    rss = scan_section("rss", str(tmp_path))
    assert [e["report_id"] for e in rss] == [
        "2026-08-14-11-44-55",
        "2026-08-12-21-43-57",
    ]

    # 未知 key → 空
    assert scan_section("nope", str(tmp_path)) == []


def test_parse_real_archived_reports():
    """用 news-data/ 真实归档文件做冒烟:全部可解析、标题非空、板块非空"""
    data_dir = Path(__file__).parent.parent.parent / "news-data"
    if not data_dir.is_dir():
        import pytest

        pytest.skip("news-data 不存在")

    reports = scan_reports(str(data_dir))
    assert reports, "news-data 中应至少有一份报告"
    for r in reports:
        assert r["title"]
        assert r["profile"] in ("morning", "default", "weekly")
        assert r["sections"], f"{r['id']} 应至少有一个板块"
