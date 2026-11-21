"""ongoing_work 文档加载器:提取当前工作文本(LLM 相关性分析用)

stdlib 实现,不引入新依赖。docx 为正则级解析,纯段落文本可用;
复杂排版(表格/文本框/图片)会丢内容,需要时再换 python-docx。
"""

import re
import zipfile
from pathlib import Path
from typing import Dict, List

SUPPORTED_EXTS = {".docx", ".md", ".txt"}


def _extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    # 以段落结束标签为换行边界,再剥掉所有标签
    xml = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def load_work_docs(work_dir: str, max_chars_per_doc: int = 20000) -> List[Dict]:
    """读取 work_dir 下所有支持格式的文档,返回 [{name, text}]。

    目录不存在/无可用文件返回空列表;单个文件失败不阻断其他文件。
    """
    dir_path = Path(work_dir)
    if not dir_path.is_dir():
        print(f"⚠️ 工作文档目录不存在: {work_dir}")
        return []

    docs: List[Dict] = []
    for path in sorted(dir_path.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTS:
            print(f"ℹ️ 跳过不支持的工作文档(支持 docx/md/txt): {path.name}")
            continue
        try:
            if path.suffix.lower() == ".docx":
                text = _extract_docx_text(path)
            else:
                text = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"⚠️ 工作文档读取失败 {path.name}: {e}")
            continue
        text = text.strip()
        if not text:
            print(f"ℹ️ 工作文档为空,跳过: {path.name}")
            continue
        if len(text) > max_chars_per_doc:
            text = text[:max_chars_per_doc]
            print(f"✂️ 工作文档截断到 {max_chars_per_doc} 字符: {path.name}")
        docs.append({"name": path.name, "text": text})
    return docs
