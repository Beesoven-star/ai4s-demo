"""测试 markdown_utils.parse_frontmatter 的标准与容错路径"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.markdown_utils import extract_md_links, parse_frontmatter


def test_extract_md_links():
    """提取 markdown 链接 url;裸链接不提取,空文本返回空集"""
    text = "见 [A](https://a.com/1) 和 [B](http://b.com/2)。裸链接 https://c.com/3 不提取"
    assert extract_md_links(text) == {"https://a.com/1", "http://b.com/2"}
    assert extract_md_links("") == set()
    assert extract_md_links(None) == set()


def test_standard_frontmatter():
    text = '---\ntitle: "标题"\nlead: "导语"\n---\n\n## 正文\n内容'
    meta, body = parse_frontmatter(text)
    assert meta["title"] == "标题"
    assert body.startswith("## 正文")


def test_missing_closing_fence():
    """LLM 漏写闭合 --- 时,按第一个空行容错切分"""
    text = '---\ntitle: "标题"\nhighlights:\n  - "a"\n  - "b"\n\n## 总览\n内容'
    meta, body = parse_frontmatter(text)
    assert meta["title"] == "标题"
    assert meta["highlights"] == ["a", "b"]
    assert body.startswith("## 总览")


def test_double_frontmatter():
    """LLM 输出两遍 frontmatter 时,保留第一份 meta,剥掉两份"""
    text = (
        '---\ntitle: "第一份"\n---\n\n'
        '---\ntitle: "第二份"\n---\n\n## 正文\n内容'
    )
    meta, body = parse_frontmatter(text)
    assert meta["title"] == "第一份"
    assert body.startswith("## 正文")


def test_no_frontmatter():
    text = "## 正文\n内容"
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_broken_yaml_returns_original():
    text = "---\ntitle: [未闭合\n\n## 正文"
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_code_fence_wrapped_output():
    """LLM 把整段输出(含 frontmatter)用 ```markdown 围栏包裹时,先剥围栏再解析"""
    text = '```markdown\n---\ntitle: "标题"\nlead: "导语"\n---\n\n## 总览\n内容\n```'
    meta, body = parse_frontmatter(text)
    assert meta["title"] == "标题"
    assert body.startswith("## 总览")
    assert "```" not in body


def test_code_fence_wrapped_without_frontmatter():
    """围栏内没有 frontmatter 时,剥围栏后按原文降级返回"""
    text = "```markdown\n## 正文\n内容\n```"
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == text

