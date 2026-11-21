"""Acquisition lifecycle, retries and local scheduling; no network calls."""

import asyncio
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.discovery_collection import CollectionBusyError, CollectionService, validate_settings
from src.discovery import LOCAL_TZ
from src.discovery_lock import FileLock, execution_lock_path


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 6, 9, 0, tzinfo=LOCAL_TZ)


class EmptyStderr:
    async def read(self):
        return b""


class FakeProcess:
    def __init__(self, runs, *, block=False):
        self.returncode = None
        self.stderr = EmptyStderr()
        self.release = asyncio.Event()
        if not block:
            self.release.set()
        self.runs = runs
        self.stdout = self.lines()

    async def lines(self):
        await self.release.wait()
        for run in self.runs:
            yield json.dumps(run).encode() + b"\n"

    async def wait(self):
        await self.release.wait()
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self.release.set()


class CollectionJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp_root = ROOT / ".runtime" / "test-tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.config = Path(self.temp.name) / "sources.json"
        self.config.write_text(json.dumps({
            "sources": [{"id": sid, "name": sid.upper(), "kind": "feed", "content_type": kind}
                        for sid, kind in (("paper", "paper"), ("news", "news"))],
            "relevance": {"domain_terms": ["molecular"], "method_terms": ["representation"]},
        }), encoding="utf-8")
        self.service = CollectionService(Path(self.temp.name) / "test.sqlite", self.config)
        await self.service.start()
        self.clock = patch("src.discovery_collection._now", return_value=NOW)
        self.clock.start()

    async def asyncTearDown(self):
        await self.service.stop()
        self.clock.stop()
        self.temp.cleanup()

    def run_record(self, sid, status="no_results", **extras):
        return {"source_id": sid, "source_name": sid.upper(), "status": status,
                "started_at": NOW.isoformat(), "finished_at": NOW.isoformat(),
                "found": 0, "inserted": 0, "updated": 0, **extras}

    async def launch(self, runs, *, block=False, **kwargs):
        process = FakeProcess(runs, block=block)

        async def spawn(job):
            return process

        self.service._spawn = spawn
        job = await self.service.trigger(date(2026, 10, 31), NOW.date(), **kwargs)
        return job, process

    async def test_two_simultaneous_triggers_only_launch_one_job(self):
        _, process = await self.launch([], block=True)
        with self.assertRaises(CollectionBusyError):
            await self.service.trigger(NOW.date(), NOW.date())
        self.assertEqual(len(self.service._jobs()), 1)
        process.release.set()
        await self.service._job_task

    async def test_empty_success_partial_failure_and_coverage_are_distinct(self):
        warning = "Reached page limit"
        await self.launch([self.run_record("paper", coverage_warning=warning),
                           self.run_record("news", "failed", error="HTTP 503")])
        await self.service._job_task
        job = self.service.status()["job"]
        self.assertEqual(job["status"], "partial")
        self.assertEqual(job["runs"][0]["status"], "no_results")
        self.assertEqual(job["runs"][0]["coverage_warning"], warning)
        self.assertEqual(job["inserted"], 0)
        self.assertEqual(job["sources_done"], 2)

    async def test_zero_insertions_do_not_mean_failure_and_daily_is_not_duplicated(self):
        await self.launch([self.run_record("paper", "success", found=3, updated=3), self.run_record("news")])
        await self.service._job_task
        self.assertEqual(self.service.status()["job"]["status"], "success")
        self.service.save_settings({"enabled": True, "time": "08:00", "lookback_days": 7})
        await self.service.tick(NOW)
        self.assertEqual(len(self.service._jobs()), 1)
        self.assertEqual(self.service.status()["next_run_at"], "2026-11-07T08:00:00+08:00")

    async def test_intraday_refresh_collects_only_news_and_keeps_the_daily_cycle(self):
        self.service.news_interval = timedelta(hours=3)
        self.service.save_settings({"enabled": True, "time": "08:00", "lookback_days": 7})
        self.service._spawn = lambda job: self._fake_spawn([self.run_record(sid) for sid in job["source_ids"]])
        await self.service.tick(NOW)
        await self.service._job_task
        await self.service.tick(NOW + timedelta(hours=2))
        self.assertEqual(len(self.service._jobs()), 1)
        with patch("src.discovery_collection._now", return_value=NOW + timedelta(hours=3)):
            await self.service.tick(NOW + timedelta(hours=3))
            await self.service._job_task
        intraday, daily = self.service._jobs()
        self.assertEqual(intraday["trigger"], "intraday")
        self.assertEqual(intraday["source_ids"], ["news"])
        self.assertIsNone(intraday["cycle_date"])
        self.assertEqual(set(daily["source_ids"]), {"news", "paper"})

    async def test_completion_hook_runs_after_the_collector_exits(self):
        seen = []

        def on_finished(job, database):
            seen.append((job['status'], job['finished_at'], database))
            return ['sample-daily', 'sample-weekly']

        self.service.on_finished = on_finished
        await self.launch([self.run_record('paper'), self.run_record('news')])
        await self.service._job_task
        self.assertEqual(seen, [('success', NOW.isoformat(), self.service.db_path)])
        self.assertEqual(self.service.status()['job']['editor_drafts'], ['sample-daily', 'sample-weekly'])

    async def test_only_failed_source_retried_and_budget_survives_restart(self):
        await self.launch([self.run_record("paper"), self.run_record("news", "failed")])
        await self.service._job_task
        self.service.save_settings({"enabled": True, "time": "08:00", "lookback_days": 7})
        await self.service.tick(NOW + timedelta(minutes=29))
        self.assertEqual(len(self.service._jobs()), 1)
        later = NOW + timedelta(minutes=31)
        with patch("src.discovery_collection._now", return_value=later):
            self.service._spawn = lambda job: self._fake_spawn([self.run_record("news", "failed")])
            await self.service.tick(later)
            await self.service._job_task
        jobs = self.service._jobs()
        self.assertEqual(jobs[0]["source_ids"], ["news"])
        replacement = CollectionService(self.service.db_path, self.config)
        # Settings/attempts are on disk, even for a newly constructed service.
        _, pending, _ = replacement._plan(NOW + timedelta(hours=2), replacement.settings(),
                                          replacement.source_config()[1], replacement._jobs())
        self.assertEqual(pending, [])

    async def _fake_spawn(self, runs):
        return FakeProcess(runs)

    async def test_first_launch_before_daily_time_catches_up_once(self):
        early = NOW.replace(hour=7)
        with patch("src.discovery_collection._now", return_value=early):
            self.service.save_settings({"enabled": True, "time": "08:00", "lookback_days": 7})
            self.service._spawn = lambda job: self._fake_spawn([self.run_record("paper"), self.run_record("news")])
            await self.service.tick(early)
            await self.service._job_task
            await self.service.tick(early + timedelta(minutes=5))
            await self.service.tick(early + timedelta(hours=1))
        self.assertEqual(len(self.service._jobs()), 1)
        self.assertEqual(self.service._jobs()[0]["cycle_date"], "2026-11-06")

    async def test_exclusive_owner_prevents_second_process_and_recovers_stale_job(self):
        job, _ = await self.launch([], block=True)
        replacement = CollectionService(self.service.db_path, self.config)
        await replacement.start()
        self.assertFalse(replacement.status()["available"])
        await replacement.stop()
        await self.service.stop()
        self.assertEqual(self.service._jobs()[0]["status"], "interrupted")
        # Simulate a crash leaving a running row (OS lock has already released).
        job["status"] = "running"
        self.service._save_job(job)
        replacement = CollectionService(self.service.db_path, self.config)
        try:
            await replacement.start()
            self.assertEqual(replacement.status()["job"]["status"], "interrupted")
            self.assertTrue(replacement.status()["available"])
        finally:
            await replacement.stop()

    async def test_shutdown_reaps_writer_before_releasing_lock(self):
        _, process = await self.launch([], block=True)
        await asyncio.sleep(0)
        await self.service.stop()
        self.assertEqual(process.returncode, -15)
        self.assertFalse(self.service.status()["available"])
        self.assertEqual(self.service.status()["job"]["status"], "interrupted")

    async def test_orphan_collector_lock_blocks_new_job_until_writer_exits(self):
        lock = FileLock(execution_lock_path(self.service.db_path))
        self.assertTrue(lock.acquire())
        try:
            with self.assertRaises(CollectionBusyError):
                await self.service.trigger(NOW.date(), NOW.date())
            self.assertFalse(self.service.status()["available"])
            self.assertIsNone(self.service.status()["job"])
        finally:
            lock.close()
        self.assertTrue(self.service._recover_jobs())
        self.assertTrue(self.service.status()["available"])

    async def test_unstarted_sources_do_not_consume_retry_budget(self):
        for _ in range(2):
            job, process = await self.launch([], block=True)
            # Both attempts were interrupted at the first source. The second
            # source was never started and must still be eligible today.
            job["attempted_source_ids"] = ["paper"]
            self.service._save_job(job)
            process.release.set()
            await self.service._job_task
        _, pending, _ = self.service._plan(NOW + timedelta(hours=1), self.service.settings(),
                                          self.service.source_config()[1], self.service._jobs())
        self.assertEqual(pending, ["news"])

    async def test_disabled_schedule_and_invalid_window_never_spawn(self):
        await self.service.tick(NOW)
        self.assertIsNone(self.service.status()["job"])
        for start, end in ((NOW.date(), NOW.date() - timedelta(days=1)),
                           (NOW.date() - timedelta(days=366), NOW.date()),
                           (NOW.date(), NOW.date() + timedelta(days=1))):
            with self.assertRaises(ValueError):
                await self.service.trigger(start, end)
        self.assertIsNone(self.service.status()["job"])

    async def test_settings_reject_non_strict_values_and_persist(self):
        for settings in ({"enabled": "false", "time": "08:00", "lookback_days": 7},
                         {"enabled": True, "time": "28:00", "lookback_days": 7},
                         {"enabled": True, "time": "08:00", "lookback_days": True}):
            with self.assertRaises(ValueError):
                validate_settings(settings)
        expected = {"enabled": True, "time": "09:15", "lookback_days": 14}
        self.service.save_settings(expected)
        replacement = CollectionService(self.service.db_path, self.config)
        self.assertEqual(replacement.settings(), expected)


if __name__ == "__main__":
    unittest.main()
