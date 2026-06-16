"""导入任务 SQLite 持久化层"""
from __future__ import annotations
import sqlite3
import json
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime


class ImportDB:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS import_tasks (
                taskId TEXT PRIMARY KEY,
                sourceType TEXT NOT NULL DEFAULT 'batch_upload',
                status TEXT NOT NULL DEFAULT 'pending',
                totalFiles INTEGER NOT NULL DEFAULT 0,
                successCount INTEGER NOT NULL DEFAULT 0,
                partialCount INTEGER NOT NULL DEFAULT 0,
                failedCount INTEGER NOT NULL DEFAULT 0,
                skippedCount INTEGER NOT NULL DEFAULT 0,
                createdAt TEXT NOT NULL,
                completedAt TEXT,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS task_items (
                itemId TEXT PRIMARY KEY,
                taskId TEXT NOT NULL,
                fileName TEXT NOT NULL,
                fileSize INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                retryCount INTEGER NOT NULL DEFAULT 0,
                durationMs INTEGER,
                errorMessage TEXT,
                wikiPages TEXT DEFAULT '[]',
                ragChunks INTEGER DEFAULT 0,
                createdAt TEXT NOT NULL,
                FOREIGN KEY (taskId) REFERENCES import_tasks(taskId)
            );

            CREATE INDEX IF NOT EXISTS idx_task_items_taskId ON task_items(taskId);
            CREATE INDEX IF NOT EXISTS idx_import_tasks_status ON import_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_import_tasks_createdAt ON import_tasks(createdAt);
        """)
        self._conn.commit()

    def create_task(self, task: dict) -> str:
        task_id = task.get("taskId") or str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO import_tasks (taskId, sourceType, status, totalFiles, createdAt, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, task.get("sourceType", "batch_upload"), "pending", task.get("totalFiles", 0), now, json.dumps(task.get("metadata", {}), ensure_ascii=False)),
        )
        self._conn.commit()
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM import_tasks WHERE taskId = ?", (task_id,)).fetchone()
        if not row:
            return None
        return dict(row)

    def update_task_status(self, task_id: str, status: str, **fields):
        sets = ["status = ?"]
        vals = [status]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(task_id)
        self._conn.execute(
            f"UPDATE import_tasks SET {', '.join(sets)} WHERE taskId = ?", vals
        )
        self._conn.commit()

    def create_item(self, item: dict) -> str:
        item_id = item.get("itemId") or str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO task_items (itemId, taskId, fileName, fileSize, status, createdAt) VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, item["taskId"], item["fileName"], item.get("fileSize", 0), item.get("status", "pending"), now),
        )
        self._conn.commit()
        return item_id

    def update_item(self, item_id: str, **fields):
        sets = []
        vals = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            vals.append(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False))
        vals.append(item_id)
        self._conn.execute(
            f"UPDATE task_items SET {', '.join(sets)} WHERE itemId = ?", vals
        )
        self._conn.commit()

    def get_items_by_task(self, task_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM task_items WHERE taskId = ?", (task_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_pending_or_failed_items(self, task_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM task_items WHERE taskId = ? AND status IN ('pending', 'failed')",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_tasks(self, status: str = None) -> int:
        if status:
            row = self._conn.execute("SELECT COUNT(*) FROM import_tasks WHERE status = ?", (status,)).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM import_tasks").fetchone()
        return row[0]

    def list_tasks(self, status: str = None, page: int = 1, page_size: int = 20) -> list[dict]:
        offset = (page - 1) * page_size
        if status:
            rows = self._conn.execute(
                "SELECT * FROM import_tasks WHERE status = ? ORDER BY createdAt DESC LIMIT ? OFFSET ?",
                (status, page_size, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM import_tasks ORDER BY createdAt DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def cleanup_expired(self, retention_days: int):
        cutoff = datetime.now().isoformat()
        self._conn.execute(
            "DELETE FROM import_tasks WHERE createdAt < datetime('now', ?) AND status IN ('completed', 'failed')",
            (f"-{retention_days} days",),
        )
        self._conn.commit()