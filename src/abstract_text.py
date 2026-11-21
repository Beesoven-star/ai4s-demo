"""Normalize publisher abstract headings without removing words from the body."""

from html import unescape
from html.parser import HTMLParser
import re
from typing import Any


_HEADING_TAGS = {"title", "label", "h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = _HEADING_TAGS | {"abstract", "sec", "section", "p", "div", "li", "ul", "ol", "br", "hr", "table", "tr", "td"}
_VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "wbr", "source"}
_LABEL = re.compile(r"^(?:abstract|摘要)\s*[:：.]?$", re.I)


def _space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_stored_abstract(value: Any) -> str:
    """Repair already-flattened leading labels; leave normal abstract prose alone.

    Old imports lost heading boundaries. Capitalized sentence starts and explicit
    label punctuation identify the observed artifacts, unlike 'Abstract
    representations ...', 'Abstraction ...', or occurrences inside a sentence.
    """
    text = _space(str(value or ""))
    text = re.sub(r"^(?:abstract|摘要)\s*[:：]\s*", "", text, count=1, flags=re.I)
    text = re.sub(r"^ABSTRACT(?:\s+|(?=[A-Z]))", "", text, count=1)
    text = re.sub(r"^Abstract\s*(?=[A-Z]|π[-‐‑–][A-Z])", "", text, count=1)
    return text.strip()


class _Node:
    def __init__(self, tag: str, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children: list[str | _Node] = []


class _AbstractParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        local = tag.rsplit(":", 1)[-1].lower()
        node = _Node(local, attrs)
        self.stack[-1].children.append(node)
        if local not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag.rsplit(":", 1)[-1].lower(), attrs))

    def handle_endtag(self, tag):
        local = tag.rsplit(":", 1)[-1].lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == local:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _node_text(node: _Node) -> str:
    return "".join(child if isinstance(child, str) else _node_text(child) for child in node.children)


def clean_abstract(value: Any) -> str:
    raw = str(value or "")
    # RSS descriptions can contain escaped markup in addition to XML escaping.
    if re.search(r"&lt;/?(?:[\w.-]+:)?(?:abstract|title|label|h[1-6]|p|div|span)\b", raw, re.I):
        raw = unescape(raw)
    parser = _AbstractParser()
    parser.feed(raw)
    parser.close()
    parts: list[str] = []
    body_started = False
    heading_removed = False

    def render(node: _Node):
        nonlocal body_started, heading_removed
        if node.tag in {"script", "style"}:
            return
        classes = (node.attrs.get("class") or "").lower().split()
        labelled = node.tag in _HEADING_TAGS or any(
            token in {"abstract-title", "abstract__title", "abstract-heading"} for token in classes
        )
        if not body_started and labelled and _LABEL.fullmatch(_space(_node_text(node))):
            heading_removed = True
            return
        if node.tag in _BLOCK_TAGS:
            parts.append(" ")
        for child in node.children:
            if isinstance(child, str):
                parts.append(child)
                if child.strip():
                    body_started = True
            else:
                render(child)
        if node.tag in _BLOCK_TAGS:
            parts.append(" ")

    render(parser.root)
    text = _space("".join(parts))
    return text if heading_removed else clean_stored_abstract(text)
