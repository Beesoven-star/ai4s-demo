"""Store and process the IC workbench's background reading notes."""

import asyncio
from contextlib import closing, suppress
import json
import logging
import sqlite3
import time
from functools import partial
from urllib.parse import urlsplit

from pydantic import ValidationError

from src import analysis_connection, discovery, ic_reading_prompts
from src.discovery_lock import FileLock


LOGGER = logging.getLogger(__name__)
BATCH_SIZE = 3
MAX_ATTEMPTS = 2


class ReadingQueue:
    def __init__(self, kind, *, required_field=None, watched_fields=()):
        self.kind = kind
        self.table = f'ic_{kind}_analysis'
        self.required_field = required_field
        self.watched_fields = watched_fields

    def _eligible(self, prefix=''):
        sql = f"{prefix}content_type='{self.kind}'"
        if self.required_field:
            sql += f" AND trim(coalesce(json_extract({prefix}payload, '$.{self.required_field}'), '')) <> ''"
        return sql

    def initialize(self, db_path):
        fields = [
            f"json_extract(NEW.payload, '$.{field}') IS NOT json_extract(OLD.payload, '$.{field}')"
            for field in self.watched_fields
        ]
        changed = ' OR '.join(['NEW.title <> OLD.title', *fields])
        table = self.table
        # Enqueue in the ingestion transaction. Unrelated payload edits leave cached notes intact.
        with closing(discovery._connect(db_path)) as db:
            ic_reading_prompts.initialize(db)
            db.executescript(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    item_id TEXT PRIMARY KEY REFERENCES discovery_items(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    available_at INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    model TEXT,
                    error TEXT,
                    updated_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS {table}_schedule ON {table}(status, available_at);
                CREATE TRIGGER IF NOT EXISTS {table}_insert AFTER INSERT ON discovery_items
                WHEN {self._eligible('NEW.')}
                BEGIN
                    INSERT OR IGNORE INTO {table}(item_id,status) VALUES (NEW.id,'queued');
                END;
                CREATE TRIGGER IF NOT EXISTS {table}_update AFTER UPDATE OF payload ON discovery_items
                WHEN NEW.content_type = '{self.kind}' AND ({changed})
                BEGIN
                    DELETE FROM {table} WHERE item_id=NEW.id;
                    INSERT INTO {table}(item_id,status) SELECT NEW.id,'queued' WHERE {self._eligible('NEW.')};
                END;
            """)

    def enqueue(self, db_path, ids):
        with closing(discovery._connect(db_path)) as db, db:
            db.executemany(f"""
                INSERT INTO {self.table}(item_id,status)
                  SELECT id,'queued' FROM discovery_items WHERE id=? AND {self._eligible()}
                ON CONFLICT(item_id) DO UPDATE SET status='queued',available_at=0,attempts=0,error=NULL
                  WHERE {self.table}.status='failed'
            """, [(key,) for key in dict.fromkeys(ids)])

    def read_notes(self, item_id, db_path=None):
        path = discovery._path(db_path).resolve()
        if not path.exists():
            return None
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (self.table,)).fetchone():
                return None
            row = db.execute(f"SELECT notes FROM {self.table} WHERE item_id=? AND status='ready'", (item_id,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def _save(self, db, item_id, notes, model, error):
        # The queue lock prevents a second claim. An evidence edit replaces the running row.
        now = int(time.time())
        if error is None:
            db.execute(f"UPDATE {self.table} SET status='ready',notes=?,model=?,error=NULL,updated_at=? "
                       "WHERE item_id=? AND status='running'",
                       (json.dumps(notes, ensure_ascii=False) if notes else None, model, now, item_id))
        else:
            db.execute(f"UPDATE {self.table} SET status=CASE WHEN attempts>=? THEN 'failed' ELSE 'queued' END,"
                       "available_at=?,model=?,error=?,updated_at=? WHERE item_id=? AND status='running'",
                       (MAX_ATTEMPTS, now + 30, model, error, now, item_id))

    async def process_next(self, db_path, *, prompt, validate, response_key, prepare=None):
        path = discovery._path(db_path).resolve()
        lock = FileLock(path.with_suffix(f'.{self.kind}-analysis.lock'))
        if not lock.acquire():
            return False
        try:
            with closing(discovery._connect(path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                rows = db.execute(f"""
                    SELECT item.payload FROM {self.table} AS task
                    JOIN discovery_items AS item ON item.id=task.item_id
                    WHERE task.status='running' OR (task.status='queued' AND task.available_at<=?)
                    ORDER BY task.available_at, item.created_at DESC, item.id LIMIT ?
                """, (int(time.time()), BATCH_SIZE)).fetchall()
                if not rows:
                    return False
                connection = analysis_connection.credentials()
                if not connection[1]:
                    return False
                instructions = ic_reading_prompts.current(db, self.kind)
                items = [json.loads(row[0]) for row in rows]
                db.executemany(f"UPDATE {self.table} SET status='running',attempts=attempts+1 WHERE item_id=?",
                               [(item['id'],) for item in items])

            ready = items if prepare is None else await prepare(items)
            notes = await self._generate(ready, connection, prompt, instructions, validate, response_key) if ready else {}
            with closing(discovery._connect(path)) as db, db:
                for item in items:
                    result, error = notes.get(item['id'], (None, None))
                    self._save(db, item['id'], result, connection[0]['model'] if result or error else None, error)
            return True
        finally:
            lock.close()

    async def _generate(self, items, connection, prompt, instructions, validate, response_key):
        policy = {'max_tokens': 3500, 'timeout_seconds': 95}
        if urlsplit(connection[0]['base_url']).hostname == 'api.deepseek.com':
            policy['thinking'] = {'type': 'disabled'}
        try:
            raw = await analysis_connection.complete(prompt(items, instructions), connection=connection, policy_overrides=policy)
            content = raw.strip()
            if content.startswith('```') and content.endswith('```'):
                content = content.partition('\n')[2][:-3].strip()
            data = json.loads(content)
            rows = data.get(response_key) if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError('模型未返回阅读要点列表')
            by_id = {row.get('id'): row for row in rows if isinstance(row, dict) and isinstance(row.get('id'), str)}
            error = '模型遗漏了该条资料'
        except (ValueError, TimeoutError) as exc:
            by_id = {}
            error = '模型回应格式无效' if isinstance(exc, json.JSONDecodeError) else str(exc)
        results = {}
        for item in items:
            key = item['id']
            if key not in by_id:
                results[key] = None, error
                continue
            try:
                results[key] = validate(by_id[key], item), None
            except ValidationError:
                results[key] = None, '模型返回的要点结构不完整'
            except ValueError as exc:
                results[key] = None, str(exc)
        return results


class ReadingWorker:
    def __init__(self, db_path, process_next, *args, interval=5):
        self.process_next = partial(process_next, db_path, *args)
        self.interval = interval
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def _loop(self):
        while True:
            try:
                if await self.process_next():
                    continue
            except Exception:
                LOGGER.exception('IC background analysis failed')
            await asyncio.sleep(self.interval)

