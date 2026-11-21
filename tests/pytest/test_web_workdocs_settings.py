"""测试当前工作维护(src/web/workdocs.py)与设置(src/web/settings.py)"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.web import settings as settings_mod
from src.web import workdocs


class TestWorkDocs:
    def test_list_and_read(self, tmp_path):
        (tmp_path / "任务一.md").write_text("# 任务一\n\n内容", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("plain text", encoding="utf-8")
        (tmp_path / "image.png").write_bytes(b"png")  # 不支持格式,应被忽略

        docs = workdocs.list_work_docs(str(tmp_path))
        assert {d["name"] for d in docs} == {"任务一.md", "notes.txt"}
        assert docs[0]["size"] > 0
        assert docs[0]["modified"]

        doc = workdocs.read_work_doc("任务一.md", str(tmp_path))
        assert doc["ext"] == "md"
        assert "# 任务一" in doc["text"]

    def test_read_missing_returns_none(self, tmp_path):
        assert workdocs.read_work_doc("nope.md", str(tmp_path)) is None

    def test_name_validation(self, tmp_path):
        for bad in ("../evil.md", "a/b.md", "..md", "x" * 101 + ".md", "evil.exe", ""):
            with pytest.raises(workdocs.WorkDocError):
                workdocs.read_work_doc(bad, str(tmp_path))

    def test_create_and_duplicate_conflict(self, tmp_path):
        meta = workdocs.create_work_doc("新任务.md", b"# hello", str(tmp_path))
        assert meta["name"] == "新任务.md"
        assert (tmp_path / "新任务.md").read_bytes() == b"# hello"

        with pytest.raises(workdocs.WorkDocError) as exc:
            workdocs.create_work_doc("新任务.md", b"again", str(tmp_path))
        assert exc.value.status_code == 409

    def test_create_rejects_bad_name_and_empty(self, tmp_path):
        with pytest.raises(workdocs.WorkDocError):
            workdocs.create_work_doc("x.exe", b"data", str(tmp_path))
        with pytest.raises(workdocs.WorkDocError):
            workdocs.create_work_doc("x.md", b"", str(tmp_path))

    def test_delete(self, tmp_path):
        (tmp_path / "done.md").write_text("x", encoding="utf-8")
        assert workdocs.delete_work_doc("done.md", str(tmp_path)) is True
        assert not (tmp_path / "done.md").exists()
        assert workdocs.delete_work_doc("done.md", str(tmp_path)) is False

    def test_docx_read(self, tmp_path):
        """docx 走 zip 提取(构造最小 docx)"""
        import zipfile

        docx = tmp_path / "方案.docx"
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr(
                "word/document.xml",
                "<w:body><w:p><w:t>第一段</w:t></w:p><w:p><w:t>第二段</w:t></w:p></w:body>",
            )
        doc = workdocs.read_work_doc("方案.docx", str(tmp_path))
        assert doc["ext"] == "docx"
        assert "第一段" in doc["text"] and "第二段" in doc["text"]


class TestSettings:
    def _write_config(self, tmp_path, model="deepseek-v4-flash"):
        cfg = {"llm": {"model": model, "baseUrl": "http://x/v1"}, "filter": {}}
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")
        return p

    def test_read_default_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DNEWS_CONFIG", str(tmp_path / "nope.json"))
        s = settings_mod.read_settings()
        assert s["model"] == "deepseek-v4-flash"
        assert s["defaultModel"] == "deepseek-v4-flash"

    def test_update_writes_back(self, tmp_path, monkeypatch):
        p = self._write_config(tmp_path)
        monkeypatch.setenv("DNEWS_CONFIG", str(p))

        s = settings_mod.update_settings("deepseek-v4-pro")
        assert s["model"] == "deepseek-v4-pro"

        cfg = json.loads(p.read_text(encoding="utf-8"))
        assert cfg["llm"]["model"] == "deepseek-v4-pro"
        assert cfg["llm"]["baseUrl"] == "http://x/v1"  # 其他字段不受影响

    def test_update_validation(self, tmp_path, monkeypatch):
        p = self._write_config(tmp_path)
        monkeypatch.setenv("DNEWS_CONFIG", str(p))
        with pytest.raises(settings_mod.SettingsError):
            settings_mod.update_settings("   ")
        with pytest.raises(settings_mod.SettingsError):
            settings_mod.update_settings("bad\nmodel")
