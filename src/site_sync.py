"""报告推送后自动同步到公开静态站仓库(AI4S-Daily-HTML)并推送 GitHub。

仅在报告实际推送后调用(report 子命令的待审查稿不同步,避免未审查内容公开)。
同步为全量镜像:news-data/push-*.md → <repo>/public/reports/,目标侧多余文件删除,
可自愈此前漏同步的报告。index.json 由 GitHub Actions 构建期 prebuild 生成,无需提交。

任何失败只打印警告,绝不打断推送主流程。
"""

import filecmp
import os
import shutil
import subprocess
from typing import Dict, List

# 单次 git 命令超时;push 受网络影响单独放宽
_GIT_TIMEOUT = 60
_GIT_PUSH_TIMEOUT = 180


def sync_reports_to_site(config: Dict) -> None:
    """把 news-data/push-*.md 镜像到静态站仓库并 commit+push;失败仅告警"""
    try:
        _sync(config)
    except Exception as e:
        print(f"⚠️ 网页端同步失败(不影响推送结果): {e}")


def _sync(config: Dict) -> None:
    sync_cfg = config.get("site_sync", {})
    if not sync_cfg.get("enabled", False):
        return

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo = sync_cfg.get("repo_path", "AI4S-Daily-HTML")
    if not os.path.isabs(repo):
        repo = os.path.join(root, repo)
    branch = sync_cfg.get("branch", "main")

    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"⚠️ 静态站仓库不存在,跳过网页同步: {repo}")
        return

    src = os.path.join(root, "news-data")
    dest = os.path.join(repo, "public", "reports")
    added, removed = _mirror_reports(src, dest)
    if not added and not removed:
        print("🌐 网页端报告已是最新,无需同步")
        return

    _git(repo, "add", "--", "public/reports")
    if _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("🌐 网页端报告无内容变化,无需提交")
        return

    parts = []
    if added:
        shown = added if len(added) <= 3 else added[:3] + [f"等 {len(added)} 篇"]
        parts.append(f"更新 {', '.join(shown)}")
    if removed:
        shown = removed if len(removed) <= 3 else removed[:3] + [f"等 {len(removed)} 篇"]
        parts.append(f"移除 {', '.join(shown)}")
    _git(repo, "commit", "-m", f"同步报告:{';'.join(parts)}")
    # 远端可能先进了别的提交,rebase 后再推;本地未提交改动由 autostash 保护
    _git(repo, "pull", "--rebase", "--autostash", "origin", branch)
    _git(repo, "push", "origin", branch, timeout=_GIT_PUSH_TIMEOUT)
    print(f"🌐 已同步到网页端仓库并推送 GitHub: {';'.join(parts)}")


def _mirror_reports(src: str, dest: str):
    """全量镜像 push-*.md:新增/更新复制,目标侧多余文件删除。返回 (added, removed) 文件名列表"""
    os.makedirs(dest, exist_ok=True)
    src_files = {f for f in os.listdir(src) if f.startswith("push-") and f.endswith(".md")}
    dst_files = {f for f in os.listdir(dest) if f.startswith("push-") and f.endswith(".md")}

    added: List[str] = []
    for name in sorted(src_files):
        s, d = os.path.join(src, name), os.path.join(dest, name)
        if name not in dst_files or not filecmp.cmp(s, d, shallow=False):
            shutil.copy2(s, d)
            added.append(name)

    removed: List[str] = []
    for name in sorted(dst_files - src_files):
        os.remove(os.path.join(dest, name))
        removed.append(name)

    return added, removed


def _git(repo: str, *args: str, check: bool = True, timeout: int = _GIT_TIMEOUT):
    return subprocess.run(
        ["git", "-C", repo, *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
