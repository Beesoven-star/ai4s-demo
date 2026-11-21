"""Markdown / YAML frontmatter 公共辅助。

供 storage、llm 等模块复用,避免重复实现。本模块零业务依赖,仅依赖 yaml/json/re。
"""

import json
import re
from typing import Any, Dict, List, Tuple

import yaml

__all__ = [
    "yaml_value",
    "dump_frontmatter",
    "parse_frontmatter",
    "normalize_str_list",
    "extract_md_links",
]


def yaml_value(v: Any) -> str:
    """把单个值序列化为 YAML 合法的 token,借道 JSON 语法。

    依据:JSON 是 YAML 1.2 的真子集,任何 json.dumps 的输出都是合法 YAML 标量/序列/映射。
    始终带引号的字符串可以避免 PyYAML 的若干怪癖(折行、未引号字符串歧义、unicode 转义)。
    """
    if isinstance(v, (dict, list, str)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    return str(v)


def dump_frontmatter(meta: Dict) -> str:
    """把扁平 metadata dict 序列化为 frontmatter 文本(不含包围的 `---`)。

    保留插入顺序(title 在前,bookkeeping 字段在后)。仅支持扁平结构 —— 当前所有
    metadata 都是扁平的,无需处理嵌套。
    """
    return "".join(f"{k}: {yaml_value(v)}\n" for k, v in meta.items())


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

# 整段输出被 ```markdown / ```yaml / ``` 代码围栏包裹(LLM 模仿 prompt 示例的常见瑕疵)
_FENCE_WRAPPED_RE = re.compile(
    r"^```(?:markdown|yaml|md)?\s*\n(.*?)\n?```\s*$", re.DOTALL
)


def parse_frontmatter(text: str) -> Tuple[Dict, str]:
    """从 markdown 文本中分离 YAML frontmatter 与正文。

    返回 (metadata_dict, body)。无 frontmatter / YAML 解析失败 / 非 dict 时返回
    ({}, 原文) —— 保证降级路径不丢内容,调用方可凭 metadata_dict 是否为空判定。

    对 LLM 输出的三种常见瑕疵容错:
    - 整段被 ```markdown 代码围栏包裹:先剥围栏再解析
    - 缺少闭合 `---`:以第一个空行为界尝试解析 YAML 头
    - frontmatter 输出两遍:剥掉第一份后,若正文仍紧跟第二份,再剥一次(保留第一份 meta)
    """
    stripped = text.strip()
    fence = _FENCE_WRAPPED_RE.match(stripped)
    if fence:
        stripped = fence.group(1).strip()
    meta, body = _parse_frontmatter_once(stripped)
    if not meta:
        return {}, text
    # 双 frontmatter:body 仍以 --- 开头则再剥一次,meta 保留第一份
    if body.startswith("---"):
        meta2, body2 = _parse_frontmatter_once(body)
        if meta2:
            body = body2
    return meta, body


def _parse_frontmatter_once(text: str) -> Tuple[Dict, str]:
    """单次解析:先按标准 `---...---` 匹配,失败则按"首个空行"容错切分"""
    match = _FRONTMATTER_RE.match(text)
    if match:
        yaml_part, body = match.group(1), match.group(2).strip()
    elif text.startswith("---"):
        # 无闭合 fence 容错:--- 之后到第一个空行之间的内容当作 YAML 头
        rest = text[3:].lstrip("\n")
        head, sep, tail = rest.partition("\n\n")
        if not sep:
            return {}, text
        yaml_part, body = head, tail.strip()
    else:
        return {}, text

    try:
        meta = yaml.safe_load(yaml_part) or {}
    except yaml.YAMLError:
        print("frontmatter 数据段解析失败")
        return {}, text

    if not isinstance(meta, dict):
        return {}, text

    return meta, body


def normalize_str_list(value: Any) -> List[str]:
    """将 str/list/None 规整为非空字符串列表。

    用于兜底 LLM 输出的列表型字段(如 frontmatter 中的 highlights):单字符串包裹为单元素列表,
    null/非列表/非字符串返回空列表,列表中夹杂的空白项过滤掉。不做数量截断。
    """
    if not value:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    return [str(x).strip() for x in items if str(x).strip()]


_MD_LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")


def extract_md_links(text: str) -> set:
    """提取 markdown 链接 [text](url) 中的 url 集合(用于已推送链接永久记录)"""
    if not text:
        return set()
    return set(_MD_LINK_RE.findall(text))
