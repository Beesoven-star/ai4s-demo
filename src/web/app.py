"""FastAPI 装配:报告归档 API + 前端静态托管 + SPA fallback"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.web import settings as settings_mod
from src.web import workdocs as workdocs_mod
from src.web.discovery import router as discovery_router
from src.web.analysis import router as analysis_router
from src.web.ic_editor import router as ic_editor_router
from src.web.reports import STREAM_SECTION_KEYS, load_report, scan_reports, scan_section
from src.web.schemas import (
    ReportDetail,
    ReportSummary,
    SectionEntry,
    Settings,
    WorkDocContent,
    WorkDocMeta,
)

_DEFAULT_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def _dist_dir() -> Path:
    return Path(os.environ.get("DNEWS_WEB_DIST") or _DEFAULT_DIST)


def _data_dir() -> str:
    return os.environ.get("DNEWS_DATA_DIR", "news-data")


def _work_dir() -> str:
    """工作文档目录:env 覆盖 > config sections.relevance.work_dir > ongoing_work"""
    if os.environ.get("DNEWS_WORK_DIR"):
        return os.environ["DNEWS_WORK_DIR"]
    try:
        from src.config import load_config

        return (
            load_config()
            .get("sections", {})
            .get("relevance", {})
            .get("work_dir", "ongoing_work")
        )
    except Exception:
        return "ongoing_work"


class _ImmutableStaticFiles(StaticFiles):
    """vite 产物带内容 hash,可长缓存"""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


def create_app() -> FastAPI:
    from src.discovery_collection import CollectionService

    @asynccontextmanager
    async def lifespan(app):
        from src.research_analysis import AnalysisService
        from src.ic_editor import initialize
        from src import ic_automatic, ic_news_analysis, ic_paper_analysis, ic_topic_evaluation
        from src.ic_reading_jobs import ReadingWorker
        is_ic = os.environ.get('DNEWS_RESEARCH_DOMAIN') == 'ic'
        service = CollectionService(default_enabled=os.environ.get("DNEWS_DISCOVERY_AUTO") == "1",
                                    news_interval_hours=3 if is_ic else 0)
        workers = []
        if is_ic:
            initialize(service.db_path)
            ic_automatic.initialize(service.db_path)
            ic_paper_analysis.initialize(service.db_path)
            ic_news_analysis.initialize(service.db_path)
            ic_topic_evaluation.initialize(service.db_path)
            observation_worker = ic_automatic.ObservationWorker(service.db_path, service.config_path)
            service.on_finished = observation_worker.after_collection
            workers = [
                observation_worker,
                ReadingWorker(service.db_path, ic_paper_analysis.process_next),
                ReadingWorker(service.db_path, ic_news_analysis.process_next, service.config_path),
                ReadingWorker(service.db_path, ic_topic_evaluation.process_next, interval=45),
            ]
            for worker in workers:
                worker.start()
        app.state.discovery_collection = service
        app.state.research_analysis = AnalysisService()
        await service.start()
        try:
            yield
        finally:
            await app.state.research_analysis.stop()
            await service.stop()
            for worker in workers:
                await worker.stop()

    app = FastAPI(title="AI4S Daily Archive", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.include_router(discovery_router)
    app.include_router(analysis_router)
    app.include_router(ic_editor_router)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/workspace")
    async def workspace_options():
        # The IC workbench has no report generation workflow yet. Keep legacy
        # report navigation separate even if someone follows an old bookmark.
        domain = os.environ.get("DNEWS_RESEARCH_DOMAIN", "")
        return JSONResponse({"domain": domain, "reports_enabled": domain != "ic"},
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/reports", response_model=List[ReportSummary])
    async def list_reports(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        profile: Optional[str] = Query(None),
    ):
        reports = scan_reports(_data_dir())
        if date:
            reports = [r for r in reports if r["date"] == date]
        if profile:
            reports = [r for r in reports if r["profile"] == profile]
        return reports[offset : offset + limit]

    @app.get("/api/reports/{report_id}", response_model=ReportDetail)
    async def get_report(report_id: str):
        report = load_report(report_id, _data_dir())
        if report is None:
            raise HTTPException(status_code=404, detail="报告不存在")
        return report

    @app.get("/api/sections/{key}", response_model=List[SectionEntry])
    async def get_section_stream(
        key: str,
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        """栏目流:跨报告聚合某板块(overview/plateau/peak/relevance/gaps/rss/hackernews)"""
        if key not in STREAM_SECTION_KEYS:
            raise HTTPException(status_code=404, detail="未知板块")
        entries = scan_section(key, _data_dir())
        return entries[offset : offset + limit]

    # ─── 当前工作维护 ────────────────────────────────────────

    @app.get("/api/workdocs", response_model=List[WorkDocMeta])
    async def list_work_docs():
        return workdocs_mod.list_work_docs(_work_dir())

    @app.get("/api/workdocs/{name}", response_model=WorkDocContent)
    async def get_work_doc(name: str):
        try:
            doc = workdocs_mod.read_work_doc(name, _work_dir())
        except workdocs_mod.WorkDocError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e))
        if doc is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        return doc

    @app.post("/api/workdocs/{name}", status_code=201)
    async def upload_work_doc(name: str, request: Request):
        """上传新文档(raw body);重名 409,超 10MB 413"""
        content = await request.body()
        try:
            return workdocs_mod.create_work_doc(name, content, _work_dir())
        except workdocs_mod.WorkDocError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e))

    @app.delete("/api/workdocs/{name}", status_code=204)
    async def delete_work_doc(name: str):
        try:
            ok = workdocs_mod.delete_work_doc(name, _work_dir())
        except workdocs_mod.WorkDocError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e))
        if not ok:
            raise HTTPException(status_code=404, detail="文档不存在")

    # ─── 设置 ────────────────────────────────────────────────

    @app.get("/api/settings", response_model=Settings)
    async def get_settings():
        return settings_mod.read_settings()

    @app.put("/api/settings", response_model=Settings)
    async def put_settings(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="请求体必须是 JSON")
        try:
            return settings_mod.update_settings(str(body.get("model", "")))
        except settings_mod.SettingsError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e))

    dist = _dist_dir()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", _ImmutableStaticFiles(directory=assets), name="assets")

    @app.get("/ic-exploration-20261110.json", include_in_schema=False)
    async def ic_exploration_snapshot():
        snapshot = dist / "ic-exploration-20261110.json"
        if not snapshot.is_file():
            raise HTTPException(status_code=404, detail="集成电路探索样本尚未构建")
        return FileResponse(snapshot, media_type="application/json", headers={"Cache-Control": "no-cache"})

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        index = dist / "index.html"
        if not index.is_file():
            return JSONResponse(
                status_code=503,
                content={"detail": "前端未构建,请先执行: cd web && npm ci && npm run build"},
            )
        return FileResponse(index)

    return app
