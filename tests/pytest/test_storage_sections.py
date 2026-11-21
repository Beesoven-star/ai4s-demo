"""测试新增的 sentinel 切片与 section-aware 读取"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from storage import extract_section


class TestExtractSection:
    def test_extract_section_with_sentinel(self):
        md = (
            "intro\n"
            "<!-- SECTION:rss BEGIN -->\n"
            "RSS body\n"
            "<!-- SECTION:rss END -->\n"
            "\n"
            "<!-- SECTION:hackernews BEGIN -->\n"
            "HN body\n"
            "<!-- SECTION:hackernews END -->\n"
        )
        assert extract_section(md, "rss").strip() == "RSS body"
        assert extract_section(md, "hackernews").strip() == "HN body"
        assert extract_section(md, "insights") == ""

    def test_extract_section_legacy_file_rss(self):
        legacy = "# AI Daily\n### 1️⃣ foo\n### 2️⃣ bar\n"
        assert extract_section(legacy, "rss") == legacy

    def test_extract_section_legacy_file_non_rss(self):
        legacy = "# AI Daily\n### 1️⃣ foo\n"
        assert extract_section(legacy, "hackernews") == ""
        assert extract_section(legacy, "insights") == ""

    def test_extract_section_missing_end_marker(self):
        broken = "<!-- SECTION:rss BEGIN -->\ncontent only\n"
        assert extract_section(broken, "rss") == ""


from storage import save_push_file


class TestSavePushFileProfile:
    def test_default_profile_when_not_specified(self, tmp_path):
        f = tmp_path / "push-x.md"
        save_push_file(str(f), "body content", source_count=1, total_entries=1)
        text = f.read_text(encoding="utf-8")
        assert 'profile: "default"' in text
        assert "body content" in text

    def test_morning_profile(self, tmp_path):
        f = tmp_path / "push-x.md"
        save_push_file(
            str(f), "body", source_count=2, total_entries=3, profile="morning"
        )
        text = f.read_text(encoding="utf-8")
        assert 'profile: "morning"' in text


from storage import assemble_with_sentinels


class TestAssembleWithSentinels:
    def test_assembles_all_sections_in_order(self):
        out = assemble_with_sentinels(
            {"rss": "R", "hackernews": "H", "insights": "I", "gaps": "G"}
        )
        assert out.index("SECTION:insights") < out.index("SECTION:gaps")
        assert out.index("SECTION:gaps") < out.index("SECTION:rss")
        assert out.index("SECTION:rss") < out.index("SECTION:hackernews")
        assert "<!-- SECTION:rss BEGIN -->\nR\n<!-- SECTION:rss END -->" in out

    def test_omits_empty_sections(self):
        out = assemble_with_sentinels({"rss": "R", "hackernews": "H", "insights": "", "gaps": ""})
        assert "SECTION:insights" not in out
        assert "SECTION:gaps" not in out
        assert "SECTION:rss" in out
        assert "SECTION:hackernews" in out

    def test_returns_empty_when_all_empty(self):
        assert assemble_with_sentinels({"rss": "", "hackernews": "", "insights": "", "gaps": ""}) == ""
