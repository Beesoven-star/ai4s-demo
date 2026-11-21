"""测试「与当前01专项工作的相关性」板块与工作文档加载器"""

import sys
import zipfile
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.sections.relevance.workdocs import load_work_docs
from src.sections.relevance.section import run_relevance_section


def _make_docx(path: Path, paragraphs: list):
    """构造最小可解析的 docx(zip + word/document.xml)"""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://x">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


class TestLoadWorkDocs:
    def test_loads_docx_txt_md(self, tmp_path):
        _make_docx(tmp_path / "a.docx", ["第一段", "第二段"])
        (tmp_path / "b.txt").write_text("纯文本", encoding="utf-8")
        (tmp_path / "c.md").write_text("# 标题", encoding="utf-8")

        docs = load_work_docs(str(tmp_path))
        by_name = {d["name"]: d["text"] for d in docs}
        assert by_name["a.docx"] == "第一段\n第二段"
        assert by_name["b.txt"] == "纯文本"
        assert by_name["c.md"] == "# 标题"

    def test_skips_unsupported_extensions(self, tmp_path):
        (tmp_path / "x.pdf").write_text("fake", encoding="utf-8")
        (tmp_path / "y.txt").write_text("ok", encoding="utf-8")
        docs = load_work_docs(str(tmp_path))
        assert [d["name"] for d in docs] == ["y.txt"]

    def test_missing_dir_returns_empty(self, tmp_path):
        assert load_work_docs(str(tmp_path / "nope")) == []

    def test_truncates_long_doc(self, tmp_path):
        (tmp_path / "long.txt").write_text("x" * 100, encoding="utf-8")
        docs = load_work_docs(str(tmp_path), max_chars_per_doc=10)
        assert docs[0]["text"] == "x" * 10

    def test_empty_doc_skipped(self, tmp_path):
        (tmp_path / "empty.txt").write_text("  \n ", encoding="utf-8")
        assert load_work_docs(str(tmp_path)) == []


def _cfg(work_dir: str) -> dict:
    return {
        "filter": {"min_score": 60},
        "sections": {
            "relevance": {"enabled": True, "work_dir": work_dir, "top_n": 30}
        },
        "llm": {
            "model": "x",
            "baseUrl": "http://x",
            "apiKeyName": "OPENAI_API_KEY",
            "prompts": {"section_relevance": "prompts/section_relevance.md"},
        },
    }


def _entry(score, title="t"):
    return {"title": title, "source": "s", "score": score, "tags": [],
            "summary": "sum", "link": f"https://x/{title}", "content": "c"}


@pytest.mark.asyncio
async def test_disabled_returns_empty(tmp_path):
    cfg = _cfg(str(tmp_path))
    cfg["sections"]["relevance"]["enabled"] = False
    md, err = await run_relevance_section(cfg)
    assert (md, err) == ("", None)


@pytest.mark.asyncio
async def test_no_work_docs_skips(tmp_path):
    """无工作文档时不调 LLM"""
    cfg = _cfg(str(tmp_path))  # 空目录
    with patch("src.llm.generate_work_relevance", new=AsyncMock()) as mock_llm:
        md, err = await run_relevance_section(cfg)
    assert (md, err) == ("", None)
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_no_entries_skips_llm(tmp_path):
    (tmp_path / "w.txt").write_text("工作内容", encoding="utf-8")
    cfg = _cfg(str(tmp_path))
    with patch("src.llm.generate_work_relevance", new=AsyncMock()) as mock_llm, \
         patch("src.sections.common.get_fetch_file", return_value="x.json"), \
         patch("src.sections.common.read_entries", return_value=[]):
        md, err = await run_relevance_section(cfg)
    assert (md, err) == ("", None)
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_llm_failure_returns_error(tmp_path):
    (tmp_path / "w.txt").write_text("工作内容", encoding="utf-8")
    cfg = _cfg(str(tmp_path))
    with patch(
        "src.llm.generate_work_relevance",
        new=AsyncMock(return_value=("", "boom")),
    ), patch("src.sections.common.get_fetch_file", return_value="x.json"), \
         patch("src.sections.common.read_entries", return_value=[_entry(90)]):
        md, err = await run_relevance_section(cfg)
    assert md == ""
    assert "boom" in err


@pytest.mark.asyncio
async def test_happy_path_materials_include_work_docs_and_links(tmp_path):
    (tmp_path / "w.txt").write_text("AI4S 攻关方案", encoding="utf-8")
    cfg = _cfg(str(tmp_path))
    entries = [_entry(90, "high"), _entry(50, "low")]
    captured = {}

    async def fake_gen(sections, config):
        captured["sections"] = sections
        return "## 与当前工作的相关性\n\n...", None

    with patch(
        "src.llm.generate_work_relevance", new=AsyncMock(side_effect=fake_gen)
    ), patch("src.sections.common.get_fetch_file", return_value="x.json"), \
         patch("src.sections.common.read_entries", return_value=entries):
        md, err = await run_relevance_section(cfg)

    assert md.startswith("## 与当前工作的相关性")
    assert err is None
    assert "AI4S 攻关方案" in captured["sections"]["work_docs"]

    import json
    top = json.loads(captured["sections"]["top_entries"])
    assert [e["title"] for e in top] == ["high"]  # 过滤低分
    assert top[0]["link"] == "https://x/high"  # include_link 生效


@pytest.mark.asyncio
async def test_include_docs_filters_work_docs(tmp_path):
    """include_docs 非空时只输入指定文档(2026-08-27 起默认只用《以往研究内容》)"""
    (tmp_path / "以往研究内容.txt").write_text("以往研究正文", encoding="utf-8")
    (tmp_path / "其他文档.txt").write_text("不应出现", encoding="utf-8")

    cfg = _cfg(str(tmp_path))
    cfg["sections"]["relevance"]["include_docs"] = ["以往研究内容.txt"]
    captured = {}

    async def fake_gen(sections, config):
        captured["sections"] = sections
        return "md", None

    with patch(
        "src.llm.generate_work_relevance", new=AsyncMock(side_effect=fake_gen)
    ), patch("src.sections.common.get_fetch_file", return_value="x.json"), \
         patch("src.sections.common.read_entries", return_value=[_entry(90)]):
        md, err = await run_relevance_section(cfg)

    assert err is None
    assert "以往研究正文" in captured["sections"]["work_docs"]
    assert "不应出现" not in captured["sections"]["work_docs"]


@pytest.mark.asyncio
async def test_include_docs_all_missing_skips(tmp_path):
    """include_docs 指定的文档全部不存在时,按无工作文档省略"""
    (tmp_path / "w.txt").write_text("工作内容", encoding="utf-8")
    cfg = _cfg(str(tmp_path))
    cfg["sections"]["relevance"]["include_docs"] = ["不存在.docx"]
    with patch("src.llm.generate_work_relevance", new=AsyncMock()) as mock_llm:
        md, err = await run_relevance_section(cfg)
    assert (md, err) == ("", None)
    mock_llm.assert_not_called()
