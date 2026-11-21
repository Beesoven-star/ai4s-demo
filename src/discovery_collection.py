"""Local acquisition jobs: the same public-source CLI, with durable progress.

One OS lock owns the scheduler for a database. A child process keeps network
requests off the web event loop and can be stopped before releasing that lock.
The scheduler only runs while the local web service is running.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import sys
import uuid

from src import discovery as store
from src.discovery_lock import FileLock, execution_lock_path


ROOT = Path(__file__).resolve().parents[1]
RETRY_DELAY = timedelta(minutes=30)
MAX_ATTEMPTS = 2
FINISHED_SOURCE_STATUSES = {"success", "no_results"}


class CollectionBusyError(RuntimeError):
    pass


def _now():
    return datetime.now(store.LOCAL_TZ)


def validate_settings(value):
    enabled = value.get("enabled")
    clock = value.get("time")
    days = value.get("lookback_days")
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须为布尔值")
    if not isinstance(clock, str) or len(clock) != 5:
        raise ValueError("采集时间必须是 HH:MM")
    try:
        parsed = time.fromisoformat(clock)
    except ValueError as exc:
        raise ValueError("采集时间必须是有效的 HH:MM") from exc
    if parsed.strftime("%H:%M") != clock:
        raise ValueError("采集时间必须是 HH:MM")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 30:
        raise ValueError("自动回看范围必须为 1 至 30 天")
    return {"enabled": enabled, "time": clock, "lookback_days": days}


class CollectionService:
    def __init__(self, db_path=None, config_path=None, *, default_enabled=False, on_finished=None,
                 news_interval_hours=0):
        self.db_path = store._path(db_path).resolve()
        self.config_path = Path(config_path or os.environ.get("DNEWS_DISCOVERY_SOURCES")
                                or ROOT / "resources" / "discovery_sources.json").resolve()
        self.defaults = {"enabled": default_enabled, "time": "08:00", "lookback_days": 7}
        self._owner = None
        self._gate = asyncio.Lock()
        self._job_task = None
        self._scheduler_task = None
        self._process = None
        self._stopping = False
        self._external_collector = False
        self.on_finished = on_finished
        self.news_interval = timedelta(hours=news_interval_hours) if news_interval_hours else None
        self._init_tables()

    def _connect(self):
        return store._connect(self.db_path)

    def _init_tables(self):
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS discovery_collection_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_collection_jobs (
                    id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)
        finally:
            conn.close()

    def settings(self):
        conn = self._connect()
        try:
            row = conn.execute("SELECT payload FROM discovery_collection_settings WHERE id=1").fetchone()
            return validate_settings(json.loads(row[0]) if row else self.defaults)
        finally:
            conn.close()

    def save_settings(self, value):
        settings = validate_settings(value)
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT INTO discovery_collection_settings(id,payload) VALUES (1,?) "
                             "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                             (json.dumps(settings),))
        finally:
            conn.close()
        return settings

    def source_config(self):
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        sources = [source for source in config["sources"] if source.get("enabled", True)]
        if not sources or len({source["id"] for source in sources}) != len(sources):
            raise ValueError("采集配置需要至少一个启用来源，且来源 ID 不能重复")
        return config, sources

    def _jobs(self):
        conn = self._connect()
        try:
            # Only recent history is needed for today's retry budget.
            rows = conn.execute("SELECT payload FROM discovery_collection_jobs ORDER BY started_at DESC,rowid DESC LIMIT 100").fetchall()
            return [json.loads(row[0]) for row in rows]
        finally:
            conn.close()

    def _save_job(self, job):
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT INTO discovery_collection_jobs(id,started_at,status,payload) VALUES (?,?,?,?) "
                             "ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload",
                             (job["id"], job["started_at"], job["status"], json.dumps(job, ensure_ascii=False)))
        finally:
            conn.close()

    def _claim_owner(self):
        lock = FileLock(self.db_path.with_suffix(self.db_path.suffix + ".collector.lock"))
        if lock.acquire():
            self._owner = lock
            return True
        return False

    def _release_owner(self):
        if self._owner is None:
            return
        self._owner.close()
        self._owner = None

    def _recover_jobs(self):
        # A collector child can outlive a force-killed web process on Windows.
        # Its own execution lock must be released before recovering/retrying.
        probe = FileLock(execution_lock_path(self.db_path))
        if not probe.acquire():
            self._external_collector = True
            return False
        try:
            self._external_collector = False
            for job in self._jobs():
                if job["status"] == "running":
                    job.update(status="interrupted", finished_at=_now().isoformat(), current_source=None,
                               error="上次采集因服务退出而中断；已保存的资料保留，未完成来源将按重试规则补查。")
                    self._save_job(job)
        finally:
            probe.close()
        return True

    async def start(self):
        if not self._claim_owner():
            return
        self._recover_jobs()
        self._scheduler_task = asyncio.create_task(self._schedule_loop())

    async def stop(self):
        self._stopping = True
        try:
            if self._scheduler_task:
                self._scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._scheduler_task
            if self._job_task and not self._job_task.done():
                self._job_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._job_task
            if self._owner:
                self._recover_jobs()
        finally:
            self._release_owner()

    def _plan(self, now, settings, sources, jobs):
        clock = time.fromisoformat(settings["time"])
        today_due = datetime.combine(now.date(), clock, tzinfo=store.LOCAL_TZ)
        # First launch catches up immediately. Later launches before the daily
        # time can finish yesterday's cycle without duplicating today's job.
        has_today = any(job.get("cycle_date") == now.date().isoformat() for job in jobs)
        cycle = now.date() if now >= today_due or not jobs or has_today else now.date() - timedelta(days=1)
        cycle_jobs = [job for job in jobs if job.get("cycle_date") == cycle.isoformat()]
        tomorrow_due = today_due if now < today_due else today_due + timedelta(days=1)
        if has_today:
            tomorrow_due = today_due + timedelta(days=1)
        pending = []
        retry_times = []
        for source in sources:
            attempts = [job for job in cycle_jobs if source["id"] in job.get("attempted_source_ids", job["source_ids"])]
            if any(run["source_id"] == source["id"] and run["status"] in FINISHED_SOURCE_STATUSES
                   for job in attempts for run in job["runs"]):
                continue
            if len(attempts) >= MAX_ATTEMPTS:
                continue
            retry_at = max(datetime.fromisoformat(job.get("finished_at") or job["started_at"]) for job in attempts) + RETRY_DELAY if attempts else now
            if retry_at <= now:
                pending.append(source["id"])
            else:
                retry_times.append(retry_at)
        next_at = now if pending else min([tomorrow_due, *retry_times])
        return cycle, pending, next_at

    def status(self):
        now = _now()
        settings = self.settings()
        config, sources = self.source_config()
        jobs = self._jobs()
        _, _, next_at = self._plan(now, settings, sources, jobs)
        news_at, _ = self._news_schedule(now, settings, sources, jobs)
        if news_at is not None:
            next_at = min(next_at, news_at)
        return {
            "settings": settings,
            "sources": [{key: source[key] for key in ("id", "name", "content_type")} for source in sources],
            "relevance": config["relevance"], "today": now.date().isoformat(),
            "next_run_at": next_at.isoformat() if settings["enabled"] and not (jobs and jobs[0]["status"] == "running") else None,
            "job": jobs[0] if jobs else None,
            "available": self._owner is not None and not self._stopping and not self._external_collector,
            "news_interval_hours": int(self.news_interval.total_seconds() / 3600) if self.news_interval else None,
        }

    def _news_schedule(self, now, settings, sources, jobs):
        if self.news_interval is None:
            return None, []
        ids = {source["id"] for source in sources if source["content_type"] == "news"}
        if not ids:
            return None, []
        daily_due = datetime.combine(now.date(), time.fromisoformat(settings["time"]), tzinfo=store.LOCAL_TZ)
        last = next((job for job in jobs if job["window_end"] == now.date().isoformat()
                     and ids <= set(job["source_ids"])), None)
        if not last:
            return daily_due, sorted(ids)
        last_at = datetime.fromisoformat(last.get("finished_at") or last["started_at"])
        return max(daily_due, last_at + self.news_interval), sorted(ids)

    async def trigger(self, start, end, *, trigger="manual", source_ids=None, cycle_date=None):
        today = _now().date()
        if start > end or (end - start).days >= 366 or end > today:
            raise ValueError("请选择不超过今天、起止顺序正确且最多 366 天的采集窗口")
        async with self._gate:
            if self._owner is None or self._stopping:
                raise RuntimeError("采集服务暂不可用，请使用正在运行的本地预览服务")
            if self._job_task and not self._job_task.done():
                raise CollectionBusyError("已有采集任务正在运行，请等待完成")
            if not self._recover_jobs():
                raise CollectionBusyError("已有命令行采集或上次采集进程仍在运行，请等待完成")
            _, sources = self.source_config()
            enabled_ids = [source["id"] for source in sources]
            selected = enabled_ids if source_ids is None else source_ids
            if not selected or set(selected) - set(enabled_ids):
                raise ValueError("采集来源必须是配置中已启用的来源")
            settings = self.settings()
            # A full manual refresh also satisfies the same day's auto cycle.
            if trigger == "manual" and end == today and start <= today - timedelta(days=settings["lookback_days"] - 1):
                cycle_date = today
            job = {
                "id": uuid.uuid4().hex, "status": "running", "trigger": trigger,
                "started_at": _now().isoformat(), "finished_at": None,
                "window_start": start.isoformat(), "window_end": end.isoformat(),
                "cycle_date": cycle_date.isoformat() if cycle_date else None,
                "source_ids": selected, "attempted_source_ids": [], "sources_total": len(selected), "sources_done": 0,
                "current_source": next(source["name"] for source in sources if source["id"] == selected[0]),
                "runs": [], "inserted": 0, "updated": 0, "error": None,
            }
            self._save_job(job)
            self._job_task = asyncio.create_task(self._execute(job, sources))
            return job

    async def _spawn(self, job):
        days = (date.fromisoformat(job["window_end"]) - date.fromisoformat(job["window_start"])).days + 1
        return await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(ROOT / "scripts" / "collect_discovery.py"),
            "--config", str(self.config_path), "--db", str(self.db_path),
            "--days", str(days), "--as-of", job["window_end"], "--sources", *job["source_ids"],
            "--progress",
            cwd=str(ROOT), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,
        )

    async def _execute(self, job, sources):
        process = None
        stderr_task = None
        try:
            process = await self._spawn(job)
            self._process = process
            stderr_task = asyncio.create_task(process.stderr.read())
            ordered = [source for source in sources if source["id"] in job["source_ids"]]
            async for raw_line in process.stdout:
                run = json.loads(raw_line.decode("utf-8"))
                if run.get("event") == "source_started" and run.get("source_id") in job["source_ids"]:
                    source_id = run["source_id"]
                    if source_id not in job["attempted_source_ids"]:
                        job["attempted_source_ids"].append(source_id)
                    job["current_source"] = next(source["name"] for source in ordered if source["id"] == source_id)
                    self._save_job(job)
                    continue
                if run.get("source_id") not in job["source_ids"] or run.get("status") not in {"success", "no_results", "failed"}:
                    raise RuntimeError("采集进程返回了无法识别的来源记录")
                job["runs"].append(run)
                if run["source_id"] not in job["attempted_source_ids"]:
                    job["attempted_source_ids"].append(run["source_id"])
                job["sources_done"] = len(job["runs"])
                job["inserted"] += run["inserted"]
                job["updated"] += run["updated"]
                remaining = [source for source in ordered if source["id"] not in {r["source_id"] for r in job["runs"]}]
                job["current_source"] = remaining[0]["name"] if remaining else None
                self._save_job(job)
            code = await process.wait()
            stderr = (await stderr_task).decode("utf-8", errors="replace")
            if code not in (0, 1) or len(job["runs"]) != job["sources_total"]:
                raise RuntimeError(f"采集进程异常退出（{code}）：{stderr[-600:]}")
            successes = sum(run["status"] in FINISHED_SOURCE_STATUSES for run in job["runs"])
            job["status"] = "success" if successes == job["sources_total"] else "partial" if successes else "failed"
        except asyncio.CancelledError:
            job.update(status="interrupted", error="服务停止，采集已中断；已入库资料保留。")
            raise
        except Exception as error:
            job.update(status="partial" if any(run["status"] in FINISHED_SOURCE_STATUSES for run in job["runs"]) else "failed",
                       error=f"{type(error).__name__}: {error}"[:800])
        finally:
            # Reap the writer before releasing ownership or marking finished.
            if process and process.returncode is None:
                with suppress(ProcessLookupError):
                    process.terminate()
                await process.wait()
            if stderr_task:
                with suppress(asyncio.CancelledError):
                    await stderr_task
            self._process = None
            job.update(finished_at=_now().isoformat(), current_source=None)
            if self.on_finished and job['status'] in {'success', 'partial'} and not self._stopping:
                try:
                    job['editor_drafts'] = await asyncio.to_thread(self.on_finished, job, self.db_path)
                except Exception as error:
                    job['editor_error'] = f'{type(error).__name__}: {error}'[:500]
            self._save_job(job)

    async def tick(self, now=None):
        if self._owner is None or self._stopping or (self._job_task and not self._job_task.done()):
            return
        if not self._recover_jobs():
            return
        settings = self.settings()
        if not settings["enabled"]:
            return
        now = now or _now()
        _, sources = self.source_config()
        jobs = self._jobs()
        cycle, pending, _ = self._plan(now, settings, sources, jobs)
        if pending:
            await self.trigger(cycle - timedelta(days=settings["lookback_days"] - 1), cycle,
                               trigger="daily", source_ids=pending, cycle_date=cycle)
            return
        news_at, ids = self._news_schedule(now, settings, sources, jobs)
        if news_at is not None and now >= news_at:
            await self.trigger(now.date() - timedelta(days=1), now.date(), trigger="intraday", source_ids=ids)

    async def _schedule_loop(self):
        while True:
            try:
                await self.tick()
            except Exception:
                # The manual API still exposes config errors; avoid killing the
                # scheduler after a transient database or source-config error.
                import logging
                logging.getLogger(__name__).exception("Daily collection scheduling failed")
            await asyncio.sleep(15)
