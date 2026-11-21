"""当前工作维护:ongoing_work/ 工作文档的列表/查看/上传/删除。

纯函数实现,不依赖 FastAPI。文档解析复用 relevance 板块的
workdocs 加载器(docx 正则级提取,md/txt 直读)。
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.sections.relevance.workdocs import SUPPORTED_EXTS, _extract_docx_text

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# 文件名:拒绝路径分隔/父目录/控制字符,允许中英文、数字、点、空格、常用括号连字符
_ILLEGAL_NAME_RE = re.compile(r'[/\\]|\.\.|[\x00-\x1f]')


class WorkDocError(Exception):
    """业务校验错误,message 可直接展示给用户"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_doc_name(name: str) -> str:
    """校验文件名合法性,返回原名;不合法抛 WorkDocError"""
    if not name or len(name) > 100:
        raise WorkDocError("文件名不能为空且不超过 100 字符")
    if _ILLEGAL_NAME_RE.search(name):
        raise WorkDocError("文件名包含非法字符")
    if Path(name).suffix.lower() not in SUPPORTED_EXTS:
        raise WorkDocError("仅支持 .md / .txt / .docx 格式")
    return name


def list_work_docs(work_dir: str = "ongoing_work") -> List[Dict]:
    """列出工作文档元信息,按修改时间倒序"""
    dir_path = Path(work_dir)
    if not dir_path.is_dir():
        return []

    docs = []
    for path in dir_path.iterdir():
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        stat = path.stat()
        docs.append(
            {
                "name": path.name,
                "ext": path.suffix.lower().lstrip("."),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(
                    timespec="seconds"
                ),
            }
        )
    docs.sort(key=lambda d: d["modified"], reverse=True)
    return docs


def read_work_doc(name: str, work_dir: str = "ongoing_work") -> Optional[Dict]:
    """读取单个文档内容;docx 提取纯文本,md/txt 返回原文。不存在返回 None"""
    validate_doc_name(name)
    path = Path(work_dir) / name
    if not path.is_file():
        return None

    ext = path.suffix.lower().lstrip(".")
    if path.suffix.lower() == ".docx":
        text = _extract_docx_text(path)
    else:
        text = path.read_text(encoding="utf-8")
    return {"name": name, "ext": ext, "text": text}


def create_work_doc(
    name: str, content: bytes, work_dir: str = "ongoing_work"
) -> Dict:
    """上传新文档;重名拒绝(409),超限拒绝(413)"""
    validate_doc_name(name)
    if not content:
        raise WorkDocError("文件内容为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise WorkDocError("文件超过 10 MB 上限", status_code=413)

    dir_path = Path(work_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / name
    if path.exists():
        raise WorkDocError(f"已存在同名文档: {name}", status_code=409)

    path.write_bytes(content)
    return {"name": name, "size": len(content)}


def delete_work_doc(name: str, work_dir: str = "ongoing_work") -> bool:
    """删除文档;不存在返回 False"""
    validate_doc_name(name)
    path = Path(work_dir) / name
    if not path.is_file():
        return False
    path.unlink()
    return True
