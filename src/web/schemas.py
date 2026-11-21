"""报告归档 API 的响应模型"""

from typing import List, Optional

from pydantic import BaseModel


class Section(BaseModel):
    key: str  # overview / plateau / peak / relevance / gaps / rss / hackernews(日报);weekly_* (周报)
    title: str  # 展示标题(板块内第一个 H2,缺省查 fallback)
    markdown: str


class ReportSummary(BaseModel):
    id: str  # 文件名时间戳,如 "2026-08-14-09-58-18"
    date: str  # "2026-08-14"
    time: str  # "09:58"
    profile: str  # "morning" | "default" | "weekly"
    title: str
    lead: str = ""
    highlights: List[str] = []
    sourceCount: Optional[int] = None
    totalEntries: Optional[int] = None
    sections: List[str] = []  # 板块 key 列表,列表页显示板块徽章


class ReportDetail(BaseModel):
    id: str
    date: str
    time: str
    profile: str
    title: str
    lead: str = ""
    highlights: List[str] = []
    sourceCount: Optional[int] = None
    totalEntries: Optional[int] = None
    sections: List[Section] = []


class SectionEntry(BaseModel):
    """栏目流条目:某份报告中的一个板块"""

    report_id: str
    date: str
    time: str
    profile: str
    title: str  # 板块标题
    markdown: str


class WorkDocMeta(BaseModel):
    name: str
    ext: str  # md / txt / docx
    size: int
    modified: str


class WorkDocContent(BaseModel):
    name: str
    ext: str
    text: str


class Settings(BaseModel):
    model: str
    defaultModel: str
