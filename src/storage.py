"""数据存储模块 - JSON文件读写"""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.config import get_timezone
from src.markdown_utils import dump_frontmatter, parse_frontmatter


def get_fetch_file(d: date = None, data_dir: str = "news-data") -> str:
    """获取fetch文件路径 (使用配置时区)"""
    if d is None:
        d = datetime.now(get_timezone()).date()
    return f"{data_dir}/fetch-{d.isoformat()}.json"


def get_push_file(push_time: datetime = None, data_dir: str = "news-data", suffix: str = "") -> str:
    """生成push文件路径;周报传 suffix="-week" 以便与日报区分"""
    if push_time is None:
        push_time = datetime.now(get_timezone())
    time_str = push_time.strftime("%Y-%m-%d-%H-%M-%S")
    return f"{data_dir}/push-{time_str}{suffix}.md"


def get_notify_file(d: date = None, data_dir: str = "news-data") -> str:
    """获取notify文件路径 (使用配置时区)"""
    if d is None:
        d = datetime.now(get_timezone()).date()
    return f"{data_dir}/notify-{d.isoformat()}.md"


def get_relevance_file(d: date = None, data_dir: str = "news-data") -> str:
    """获取相关性分析文件路径 (使用配置时区);单独落盘,不进早报"""
    if d is None:
        d = datetime.now(get_timezone()).date()
    return f"{data_dir}/relevance-{d.isoformat()}.md"


def save_notify_file(
    filepath: str,
    content: str,
    metadata: Dict = None,
):
    """保存即时推送文件（Markdown格式），同一天的内容追加到同一文件"""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    notify_time = datetime.now(get_timezone()).isoformat()

    if metadata:
        frontmatter_dict = metadata.copy()
    else:
        frontmatter_dict = {"pushTime": notify_time}

    frontmatter = dump_frontmatter(frontmatter_dict)

    new_content = f"---\n{frontmatter}---\n\n{content}\n\n------\n"

    with open(path, "a", encoding="utf-8") as f:
        f.write(new_content)


_SECTION_RE_CACHE: Dict[str, re.Pattern] = {}


def _section_re(section: str) -> re.Pattern:
    """获取/缓存 sentinel 正则。section 名做转义,允许字母数字下划线"""
    if section not in _SECTION_RE_CACHE:
        s = re.escape(section)
        pattern = (
            rf"<!--\s*SECTION:{s}\s*BEGIN\s*-->(.*?)<!--\s*SECTION:{s}\s*END\s*-->"
        )
        _SECTION_RE_CACHE[section] = re.compile(pattern, flags=re.DOTALL)
    return _SECTION_RE_CACHE[section]


def extract_section(push_md: str, section: str) -> str:
    """从 push 文件内容中切出 <!-- SECTION:{section} BEGIN/END --> 之间的 markdown。

    向后兼容:
    - 新文件(带 sentinel): 返回 sentinel 边界内的原文(不去边界空行)
    - 老文件(无 sentinel) 且 section == 'rss': 返回整个 push_md
    - 老文件(无 sentinel) 且 section != 'rss': 返回空字符串
    - sentinel 残缺(只有 BEGIN 没有 END): 返回空字符串
    """
    match = _section_re(section).search(push_md)
    if match:
        return match.group(1)

    # 老文件兜底:rss 段视为整个 body
    has_any_sentinel = "<!-- SECTION:" in push_md
    if section == "rss" and not has_any_sentinel:
        return push_md
    return ""


def load_recent_notify_content(
    context_days: int = 3, data_dir: str = "news-data"
) -> str:
    """加载最近 context_days 天 notify 文件正文（去除 frontmatter，仅供 LLM 查重）

    notify 文件由多个推送块用 `------` 分隔，每块带各自 frontmatter；这里逐块剥离
    frontmatter 后用 `------` 重新拼接，保留事件全文。
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        return ""

    tz = get_timezone()
    today = datetime.now(tz).date()

    blocks: List[str] = []
    loaded_files = []
    for i in range(context_days):
        d = today - timedelta(days=i)
        notify_file = data_path / f"notify-{d.isoformat()}.md"
        if not notify_file.exists() or notify_file.stat().st_size == 0:
            continue
        try:
            with open(notify_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        for block in content.split("------"):
            if not block.strip():
                continue
            _, body = parse_frontmatter(block)
            if body:
                blocks.append(body)
        loaded_files.append(notify_file.name)

    if loaded_files:
        print(
            f"   📂 已加载 {len(loaded_files)} 个 notify 文件: {', '.join(loaded_files)}"
        )

    return "\n\n------\n\n".join(blocks)


def load_recent_push_content(
    context_days: int = 3, data_dir: str = "news-data", section: str = "rss"
) -> str:
    """加载最近 context_days 天 push 文件中指定 section 的正文(去除 frontmatter,仅供 LLM 查重)。

    Args:
        section: sentinel 段名,默认 "rss"。老文件(无 sentinel) 且 section == "rss"
                 时会兜底返回整个 body(由 extract_section 处理),其它 section 在
                 老文件上返回空。
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        return ""

    tz = get_timezone()
    today = datetime.now(tz).date()

    bodies: List[str] = []
    loaded_files = []
    for i in range(context_days):
        d = today - timedelta(days=i)
        pattern = f"push-{d.isoformat()}-*.md"
        for push_file in sorted(data_path.glob(pattern)):
            if push_file.stat().st_size == 0:
                continue
            try:
                with open(push_file, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue
            section_md = extract_section(content, section)
            if not section_md:
                continue
            # 老文件兜底路径会把整篇文件还回来,此时仍需剥离 frontmatter;
            # 新文件 sentinel 内不含 frontmatter,parse_frontmatter 会原样返回。
            _, body = parse_frontmatter(section_md)
            body = body or section_md
            body = body.strip()
            if body:
                bodies.append(body)
                loaded_files.append(push_file.name)

    if loaded_files:
        print(
            f"   📂 已加载 {len(loaded_files)} 个 push 文件 (section={section}): "
            f"{', '.join(loaded_files)}"
        )

    return "\n\n------\n\n".join(bodies)


def get_last_push_file(data_dir: str = "news-data") -> Optional[str]:
    """从news-data目录找到最新的push文件"""
    data_path = Path(data_dir)
    if not data_path.exists():
        return None

    push_files = sorted(data_path.glob("push-*.md"))
    return str(push_files[-1]) if push_files else None


def extract_push_time(filepath: str) -> Optional[datetime]:
    """从push文件名提取时间(兼容周报 -week 后缀)"""
    try:
        basename = Path(filepath).name
        time_str = basename.replace("push-", "").replace(".md", "")
        time_str = time_str.removesuffix("-week")
        dt = datetime.strptime(time_str, "%Y-%m-%d-%H-%M-%S")
        return dt.replace(tzinfo=get_timezone())
    except (ValueError, AttributeError):
        return None


def read_entries(filepath: str) -> List[Dict]:
    """读取fetch文件，返回entries列表"""
    path = Path(filepath)
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("entries", [])


def read_fetch_data(filepath: str) -> Dict:
    """读取完整的fetch文件数据（包含meta和entries）"""
    path = Path(filepath)
    if not path.exists():
        return {"meta": {}, "entries": []}

    # 检查文件是否为空
    if path.stat().st_size == 0:
        return {"meta": {}, "entries": []}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_fetch_file(filepath: str, meta: Dict, entries: List[Dict]):
    """保存fetch文件（JSON格式）"""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {"meta": meta, "entries": entries}

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_entries(filepath: str, new_entries: List[Dict], meta: Dict = None):
    """追加条目到fetch文件"""
    path = Path(filepath)

    # 读取现有数据
    if path.exists():
        data = read_fetch_data(filepath)
    else:
        data = {"meta": meta or {}, "entries": []}

    # 更新meta（如果提供了）
    if meta:
        data["meta"].update(meta)

    # 去重：基于link字段
    existing_links = {e.get("link") for e in data["entries"]}
    for entry in new_entries:
        if entry.get("link") not in existing_links:
            data["entries"].append(entry)
            existing_links.add(entry.get("link"))

    # 保存
    save_fetch_file(filepath, data["meta"], data["entries"])
    return len(new_entries)


def format_entry(entry: Dict) -> str:
    """格式化单条条目为Markdown字符串"""
    tags = entry.get("tags", [])
    tags_str = json.dumps(tags, ensure_ascii=False) if tags else "[]"
    score = entry.get("score", "")
    summary = entry.get("summary", "")

    return f"""## {entry["title"]}

---
source: {entry["source"]}
link: {entry["link"]}
published: {entry["published"]}
fetched_at: {entry["fetched_at"]}
tags: {tags_str}
score: {score}
summary: {summary}
---

{entry["content"]}

------
"""


def json_to_md(data: Dict) -> str:
    """
    将JSON格式的fetch数据转换为Markdown格式，便于阅读

    Args:
        data: {"meta": {...}, "entries": [...]}

    Returns:
        Markdown格式的字符串
    """
    meta = data.get("meta", {})
    entries = data.get("entries", [])

    lines = []

    # 文件头部YAML frontmatter
    if meta.get("date"):
        lines.append("---")
        lines.append(f'date: "{meta["date"]}"')
        lines.append("---")
        lines.append("")

    # 条目
    for entry in entries:
        lines.append(format_entry(entry))

    return "\n".join(lines)


def convert_fetch_json_to_md(json_filepath: str, md_filepath: str = None) -> str:
    """
    将fetch JSON文件转换为Markdown文件

    Args:
        json_filepath: JSON文件路径
        md_filepath: 输出MD文件路径，默认为同名.md

    Returns:
        生成的Markdown内容
    """
    data = read_fetch_data(json_filepath)
    md_content = json_to_md(data)

    if md_filepath:
        path = Path(md_filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(md_content)

    return md_content


def save_push_file(
    filepath: str,
    content: str,
    source_count: int,
    total_entries: int,
    profile: str = "default",
    metadata: Dict = None,
    write_frontmatter: bool = True,
):
    """保存推送文件（Markdown格式）

    Args:
        profile: "morning" | "default"  ← 早报或常规;写入 frontmatter,便于按 profile 分析
        metadata: 元信息（可选），如果提供则使用 metadata，否则使用默认格式
        write_frontmatter: False 时只写正文。保留仅为兼容旧调用/测试;
            正常路径(含早报)均应落盘 frontmatter,供归档/分析使用
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not write_frontmatter:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return

    if metadata:
        # 使用提供的 metadata
        frontmatter_dict = metadata.copy()
        # 添加推送时间和统计信息
        frontmatter_dict["pushDate"] = datetime.now(get_timezone()).isoformat()
        frontmatter_dict["sourceCount"] = source_count
        frontmatter_dict["totalEntries"] = total_entries
    else:
        # 降级：使用默认格式
        push_time = datetime.now(get_timezone())
        frontmatter_dict = {
            "profile": profile,
            "pushDate": push_time.isoformat(),
            "sourceCount": source_count,
            "totalEntries": total_entries,
        }

    frontmatter = dump_frontmatter(frontmatter_dict)
    full_content = f"---\n{frontmatter}---\n\n{content}"

    with open(path, "w", encoding="utf-8") as f:
        f.write(full_content)


def load_existing_links(
    filepath: str = None, days: int = 3, data_dir: str = "news-data"
) -> set:
    """加载最近 days 天 fetch 文件中已有的链接（用于去重）

    覆盖当天及之前 days-1 天。旧逻辑只看当天（跨天边界才带昨天），
    Tavily 每天重复命中同一热门 URL 会在早 7 点后绕过窗口重新入库；
    固定多天窗口对 RSS/Tavily 统一生效（用户决策 2026-08-23：窗口 3 天）。

    Args:
        filepath: 额外的 fetch 文件路径（如非标准命名/目录），存在则一并纳入
        days: 去重窗口天数，默认 3
        data_dir: fetch 文件目录
    """
    tz = get_timezone()
    today = datetime.now(tz).date()

    all_links = set()
    for i in range(days):
        d = today - timedelta(days=i)
        day_file = get_fetch_file(d, data_dir)
        if Path(day_file).exists():
            all_links.update(
                {e.get("link") for e in read_entries(day_file) if e.get("link")}
            )

    if filepath and Path(filepath).exists():
        all_links.update(
            {e.get("link") for e in read_entries(filepath) if e.get("link")}
        )

    return all_links


def cleanup_old_files(
    days: Optional[int] = None,
    data_dir: str = "news-data",
    archive_days: Optional[int] = None,
):
    """清理旧文件,分两组保留窗口,默认全部保留(用户决策 2026-08-14:不自动删除任何文件):

    - 素材组 fetch-*.json/fetch-*.md: 仅当 days 显式给定时,超过 days 天删除
    - 归档组 push-*.md/notify-*.md/relevance-*.md: 仅当 archive_days 显式给定时清理
    """
    data_path = Path(data_dir)
    if not data_path.exists():
        return

    deleted_count = 0

    def _cleanup_group(patterns: List[str], keep_days: int) -> None:
        nonlocal deleted_count
        cutoff = datetime.now() - timedelta(days=keep_days)
        for pattern in patterns:
            for file in data_path.glob(pattern):
                try:
                    date_str = (
                        file.name.replace("fetch-", "")
                        .replace("push-", "")
                        .replace("notify-", "")
                        .replace("relevance-", "")
                        .replace(".json", "")
                        .replace(".md", "")
                    )
                    date_parts = date_str.split("-")
                    if len(date_parts) >= 3:
                        file_date = date(
                            int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
                        )
                        if file_date < cutoff.date():
                            file.unlink()
                            deleted_count += 1
                            print(f"   🗑️ 删除旧文件: {file.name}")
                except (ValueError, OSError):
                    continue

    if days is not None:
        _cleanup_group(["fetch-*.json", "fetch-*.md"], days)
    if archive_days is not None:
        _cleanup_group(["push-*.md", "notify-*.md", "relevance-*.md"], archive_days)

    if deleted_count > 0:
        print(f"   ✅ 清理完成: 删除了 {deleted_count} 个旧文件")


def load_search_state(path: str = "news-data/search-state.json") -> Dict:
    """读取搜索限频状态;不存在/损坏返回空 dict"""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"⚠️ search-state 读取失败,视为无状态: {path}")
        return {}


def save_search_state(state: Dict, path: str = "news-data/search-state.json") -> None:
    """写入搜索限频状态"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_pushed_links(path: str = "news-data/pushed-links.json") -> set:
    """读取已推送链接永久记录;不存在/损坏返回空 set

    该记录是「同一 URL 永久只推送一次」的判定依据(用户决策 2026-08-25):
    窗口式去重(链接/LLM 上下文)对超出窗口的重复原理性失效,
    推送成功后由 record_pushed_links 落链接,fetch 入库与快讯触发时查它。
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return set()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {link for link in data.get("links", []) if link}
    except (json.JSONDecodeError, OSError, AttributeError):
        print(f"⚠️ pushed-links 读取失败,视为无记录: {path}")
        return set()


def record_pushed_links(links, path: str = "news-data/pushed-links.json") -> int:
    """把本次实际推送的链接并入永久记录,返回新增条数(已存在的忽略)"""
    new_links = {link for link in links if link}
    if not new_links:
        return 0
    existing = load_pushed_links(path)
    added = new_links - existing
    if not added:
        return 0
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "updated_at": datetime.now(get_timezone()).isoformat(),
        "links": sorted(existing | new_links),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return len(added)


_SECTION_ORDER = (
    "insights", "relevance", "gaps", "rss", "hackernews",
    "weekly", "weekly_top",
)


def assemble_with_sentinels(sections: Dict[str, str]) -> str:
    """按固定顺序拼装各段 markdown,每段包 sentinel;空段整段省略。"""
    parts: List[str] = []
    for key in _SECTION_ORDER:
        body = (sections.get(key) or "").strip()
        if not body:
            continue
        parts.append(
            f"<!-- SECTION:{key} BEGIN -->\n{body}\n<!-- SECTION:{key} END -->"
        )
    return "\n\n".join(parts)
