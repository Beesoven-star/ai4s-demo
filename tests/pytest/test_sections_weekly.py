"""测试周报板块:weekly_window / load_top_entries_range / window_stats / build_weekly_top_section"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.sections.common import (
    load_top_entries_range,
    weekly_window,
    window_stats,
)
from src.sections.weekly.section import build_weekly_top_section


def patch_load(entries):
    return patch(
        "src.sections.weekly.section.load_top_entries_range", return_value=entries
    )


TZ = timezone(timedelta(hours=8))


def _write_fetch(data_dir: Path, d, entries):
    path = data_dir / f"fetch-{d.isoformat()}.json"
    path.write_text(
        json.dumps({"meta": {}, "entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


def _entry(title, score, link="", source="src", summary="s"):
    return {
        "title": title,
        "link": link,
        "source": source,
        "score": score,
        "tags": [],
        "summary": summary,
    }


class TestWeeklyWindow:
    def test_monday_window_is_single_day(self):
        now = datetime(2026, 8, 17, 17, 0, tzinfo=TZ)  # 周一
        start, end = weekly_window(now)
        assert start == end == now.date()

    def test_thursday_window_covers_mon_to_thu(self):
        now = datetime(2026, 8, 20, 17, 0, tzinfo=TZ)  # 周四
        start, end = weekly_window(now)
        assert start.isoformat() == "2026-08-17"  # 周一
        assert end.isoformat() == "2026-08-20"

    def test_friday_window_covers_friday_only(self):
        now = datetime(2026, 8, 21, 17, 0, tzinfo=TZ)  # 周五
        start, end = weekly_window(now)
        assert start == end == now.date()

    def test_sunday_window_covers_fri_to_sun(self):
        now = datetime(2026, 8, 23, 17, 0, tzinfo=TZ)  # 周日
        start, end = weekly_window(now)
        assert start.isoformat() == "2026-08-21"  # 周五
        assert end.isoformat() == "2026-08-23"


class TestLoadTopEntriesRange:
    def _cfg(self):
        return {"filter": {"min_score": 60}}

    def test_multi_day_read_and_score_order(self, tmp_path):
        _write_fetch(tmp_path, datetime(2026, 8, 17).date(), [_entry("a", 70, "l1")])
        _write_fetch(tmp_path, datetime(2026, 8, 18).date(), [_entry("b", 90, "l2")])
        out = load_top_entries_range(
            self._cfg(), datetime(2026, 8, 17).date(), datetime(2026, 8, 18).date(),
            10, data_dir=str(tmp_path),
        )
        assert [e["title"] for e in out] == ["b", "a"]

    def test_missing_day_tolerated(self, tmp_path):
        _write_fetch(tmp_path, datetime(2026, 8, 17).date(), [_entry("a", 70, "l1")])
        out = load_top_entries_range(
            self._cfg(), datetime(2026, 8, 17).date(), datetime(2026, 8, 20).date(),
            10, data_dir=str(tmp_path),
        )
        assert len(out) == 1

    def test_min_score_filter(self, tmp_path):
        _write_fetch(
            tmp_path, datetime(2026, 8, 17).date(),
            [_entry("low", 59, "l1"), _entry("high", 60, "l2")],
        )
        out = load_top_entries_range(
            self._cfg(), datetime(2026, 8, 17).date(), datetime(2026, 8, 17).date(),
            10, data_dir=str(tmp_path),
        )
        assert [e["title"] for e in out] == ["high"]

    def test_link_dedupe_keeps_highest_score(self, tmp_path):
        _write_fetch(tmp_path, datetime(2026, 8, 17).date(), [_entry("old", 65, "same")])
        _write_fetch(tmp_path, datetime(2026, 8, 18).date(), [_entry("new", 85, "same")])
        out = load_top_entries_range(
            self._cfg(), datetime(2026, 8, 17).date(), datetime(2026, 8, 18).date(),
            10, data_dir=str(tmp_path),
        )
        assert len(out) == 1
        assert out[0]["title"] == "new"

    def test_top_n_truncation(self, tmp_path):
        _write_fetch(
            tmp_path, datetime(2026, 8, 17).date(),
            [_entry(f"e{i}", 60 + i, f"l{i}") for i in range(5)],
        )
        out = load_top_entries_range(
            self._cfg(), datetime(2026, 8, 17).date(), datetime(2026, 8, 17).date(),
            2, data_dir=str(tmp_path),
        )
        assert len(out) == 2
        assert out[0]["score"] == 64

    def test_summary_truncated_and_link_optional(self, tmp_path):
        _write_fetch(
            tmp_path, datetime(2026, 8, 17).date(),
            [_entry("a", 90, "l1", summary="x" * 200)],
        )
        out = load_top_entries_range(
            self._cfg(), datetime(2026, 8, 17).date(), datetime(2026, 8, 17).date(),
            10, data_dir=str(tmp_path),
        )
        assert len(out[0]["summary"]) == 120
        assert "link" not in out[0]

        out_with_link = load_top_entries_range(
            self._cfg(), datetime(2026, 8, 17).date(), datetime(2026, 8, 17).date(),
            10, include_link=True, data_dir=str(tmp_path),
        )
        assert out_with_link[0]["link"] == "l1"

    def test_window_stats(self, tmp_path):
        _write_fetch(
            tmp_path, datetime(2026, 8, 17).date(),
            [_entry("a", 70, "l1", source="s1"), _entry("b", 80, "l2", source="s2")],
        )
        _write_fetch(
            tmp_path, datetime(2026, 8, 18).date(),
            [_entry("c", 90, "l3", source="s1"), _entry("low", 10, "l4", source="s9")],
        )
        stats = window_stats(
            self._cfg(), datetime(2026, 8, 17).date(), datetime(2026, 8, 18).date(),
            data_dir=str(tmp_path),
        )
        assert stats["totalEntries"] == 3
        assert stats["sourceCount"] == 2


class TestBuildWeeklyTopSection:
    def _cfg(self, enabled=True):
        return {
            "filter": {"min_score": 60},
            "sections": {"weekly": {"enabled": enabled, "top_hot_n": 3}},
        }

    def test_renders_ranked_list(self):
        entries = [
            {"title": "t1", "score": 95, "link": "http://a", "source": "s1", "summary": "sum1", "tags": []},
            {"title": "t2", "score": 80, "link": "", "source": "s2", "summary": "", "tags": []},
        ]
        with patch_load(entries):
            md = build_weekly_top_section(self._cfg(), datetime(2026, 8, 20, 17, 0, tzinfo=TZ))
        assert md.startswith("## 🏆 本周Top热点")
        assert "[95]" in md and "[t1](http://a)" in md and "— s1" in md
        assert "sum1" in md
        # 无 link 的条目退化为纯文本标题
        assert "[80]** t2" in md

    def test_disabled_returns_empty(self):
        assert build_weekly_top_section(self._cfg(enabled=False)) == ""

    def test_no_entries_returns_empty(self):
        with patch_load([]):
            md = build_weekly_top_section(
                self._cfg(), datetime(2026, 8, 20, 17, 0, tzinfo=TZ)
            )
        assert md == ""
