"""测试静态站自动同步(src/site_sync.py)"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from site_sync import _mirror_reports, sync_reports_to_site


def _git_ok(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_site_repo(tmp_path):
    """建 bare 远端 + 克隆出静态站仓库结构,返回 (repo, remote)"""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo = tmp_path / "site"
    subprocess.run(["git", "clone", str(remote), str(repo)], check=True, capture_output=True)
    _git_ok(repo, "config", "user.name", "test")
    _git_ok(repo, "config", "user.email", "test@test")
    (repo / "public" / "reports").mkdir(parents=True)
    (repo / "README.md").write_text("site", encoding="utf-8")
    _git_ok(repo, "add", ".")
    _git_ok(repo, "commit", "-m", "init")
    _git_ok(repo, "push", "origin", "main")
    return repo, remote


def _config(tmp_path, repo, enabled=True):
    return {"site_sync": {"enabled": enabled, "repo_path": str(repo), "branch": "main"}}


class TestMirrorReports:
    def test_copies_new_and_removes_stale(self, tmp_path):
        src = tmp_path / "news-data"
        dest = tmp_path / "reports"
        src.mkdir()
        (src / "push-2026-08-20-08-00-00.md").write_text("旧报告", encoding="utf-8")
        (src / "push-2026-08-21-08-00-00.md").write_text("新报告", encoding="utf-8")
        (src / "fetch-2026-08-21.json").write_text("{}", encoding="utf-8")  # 非报告文件不同步
        dest.mkdir()
        (dest / "push-2026-08-19-08-00-00.md").write_text("过期", encoding="utf-8")

        added, removed = _mirror_reports(str(src), str(dest))

        assert added == ["push-2026-08-20-08-00-00.md", "push-2026-08-21-08-00-00.md"]
        assert removed == ["push-2026-08-19-08-00-00.md"]
        assert (dest / "push-2026-08-21-08-00-00.md").read_text(encoding="utf-8") == "新报告"
        assert not (dest / "push-2026-08-19-08-00-00.md").exists()
        assert not (dest / "fetch-2026-08-21.json").exists()

    def test_unchanged_files_not_reported(self, tmp_path):
        src = tmp_path / "news-data"
        dest = tmp_path / "reports"
        src.mkdir()
        dest.mkdir()
        content = "相同内容"
        (src / "push-2026-08-21-08-00-00.md").write_text(content, encoding="utf-8")
        (dest / "push-2026-08-21-08-00-00.md").write_text(content, encoding="utf-8")

        added, removed = _mirror_reports(str(src), str(dest))
        assert added == []
        assert removed == []


class TestSyncReportsToSite:
    def test_disabled_noop(self, tmp_path):
        repo, remote = _make_site_repo(tmp_path)
        sync_reports_to_site(_config(tmp_path, repo, enabled=False))
        log = subprocess.run(
            ["git", "-C", str(remote), "log", "--oneline"], capture_output=True, text=True
        ).stdout
        assert "同步报告" not in log

    def test_missing_repo_noop(self, tmp_path, capsys):
        cfg = {"site_sync": {"enabled": True, "repo_path": str(tmp_path / "不存在")}}
        sync_reports_to_site(cfg)  # 不抛异常
        assert "跳过网页同步" in capsys.readouterr().out

    def test_full_sync_commit_and_push(self, tmp_path, monkeypatch):
        repo, remote = _make_site_repo(tmp_path)
        # 伪造项目根的 news-data(site_sync 以自身位置推项目根,这里直接 mock _mirror 的源)
        src = tmp_path / "news-data"
        src.mkdir()
        (src / "push-2026-08-21-08-00-00.md").write_text("今日早报", encoding="utf-8")

        # _sync 里 src 固定为 <项目根>/news-data,替换 _mirror_reports 以指向测试源目录
        import site_sync

        orig = site_sync._mirror_reports
        monkeypatch.setattr(
            site_sync, "_mirror_reports",
            lambda _s, d: orig(str(src), d),
        )

        sync_reports_to_site(_config(tmp_path, repo))

        assert (repo / "public" / "reports" / "push-2026-08-21-08-00-00.md").exists()
        remote_log = subprocess.run(
            ["git", "-C", str(remote), "log", "--oneline"], capture_output=True, text=True
        ).stdout
        assert "同步报告" in remote_log
        # 远端内容可读回
        show = subprocess.run(
            ["git", "-C", str(remote), "show", "main:public/reports/push-2026-08-21-08-00-00.md"],
            capture_output=True, text=True,
        ).stdout
        assert show == "今日早报"

    def test_no_changes_skips_commit(self, tmp_path, monkeypatch, capsys):
        repo, remote = _make_site_repo(tmp_path)
        src = tmp_path / "news-data"
        src.mkdir()

        import site_sync

        monkeypatch.setattr(site_sync, "_mirror_reports", lambda _s, _d: ([], []))
        sync_reports_to_site(_config(tmp_path, repo))
        assert "已是最新" in capsys.readouterr().out

    def test_failure_does_not_raise(self, tmp_path, monkeypatch, capsys):
        """git 操作失败只告警不抛异常"""
        repo, _ = _make_site_repo(tmp_path)

        import site_sync

        monkeypatch.setattr(site_sync, "_mirror_reports", lambda _s, _d: (_ for _ in ()).throw(RuntimeError("磁盘错误")))
        sync_reports_to_site(_config(tmp_path, repo))
        assert "网页端同步失败" in capsys.readouterr().out
