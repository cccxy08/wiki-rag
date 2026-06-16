"""沉淀记录 SQLite 持久化层"""
from __future__ import annotations
import sqlite3
import json
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime


class PrecipitationDB:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS precipitation_records (
                recordId TEXT PRIMARY KEY,
                questionHash TEXT NOT NULL,
                answerSummary TEXT NOT NULL DEFAULT '',
                answerContent TEXT NOT NULL DEFAULT '',
                llmScore INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending_confirm',
                confirmedBy TEXT,
                confirmedAt TEXT,
                reviewedBy TEXT,
                reviewedAt TEXT,
                reviewAction TEXT,
                reviewReason TEXT,
                wikiPageTitle TEXT,
                wikiWrittenAt TEXT,
                snapshotPath TEXT,
                revokedBy TEXT,
                revokedAt TEXT,
                revokeReason TEXT,
                createdAt TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS precipitation_log (
                logId INTEGER PRIMARY KEY AUTOINCREMENT,
                recordId TEXT NOT NULL,
                event TEXT NOT NULL,
                operator TEXT DEFAULT '',
                detail TEXT DEFAULT '{}',
                createdAt TEXT NOT NULL,
                FOREIGN KEY (recordId) REFERENCES precipitation_records(recordId)
            );

            CREATE INDEX IF NOT EXISTS idx_precip_status ON precipitation_records(status);
            CREATE INDEX IF NOT EXISTS idx_precip_createdAt ON precipitation_records(createdAt);
            CREATE INDEX IF NOT EXISTS idx_precip_log_recordId ON precipitation_log(recordId);
        """)
        self._conn.commit()

    def create_record(self, record: dict) -> str:
        record_id = record.get("recordId") or str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        self._conn.execute(
            """INSERT INTO precipitation_records
            (recordId, questionHash, answerSummary, answerContent, llmScore, source, status, createdAt, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, record.get("questionHash", ""), record.get("answerSummary", ""),
             record.get("answerContent", ""), record.get("llmScore", 0),
             record.get("source", ""), "pending_confirm", now,
             json.dumps(record.get("metadata", {}), ensure_ascii=False)),
        )
        self._add_log(record_id, "created", "", {"score": record.get("llmScore", 0)})
        return record_id

    def get_record(self, record_id: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM precipitation_records WHERE recordId = ?", (record_id,)).fetchone()
        return dict(row) if row else None

    def update_record(self, record_id: str, **fields):
        sets = []
        vals = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(record_id)
        self._conn.execute(f"UPDATE precipitation_records SET {', '.join(sets)} WHERE recordId = ?", vals)
        self._conn.commit()

    def list_records(self, status: str = None, page: int = 1, page_size: int = 20) -> list[dict]:
        offset = (page - 1) * page_size
        if status:
            rows = self._conn.execute(
                "SELECT * FROM precipitation_records WHERE status = ? ORDER BY createdAt DESC LIMIT ? OFFSET ?",
                (status, page_size, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM precipitation_records ORDER BY createdAt DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_records(self, status: str = None) -> int:
        if status:
            row = self._conn.execute("SELECT COUNT(*) FROM precipitation_records WHERE status = ?", (status,)).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM precipitation_records").fetchone()
        return row[0] if row else 0

    def _add_log(self, record_id: str, event: str, operator: str = "", detail: dict = None):
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO precipitation_log (recordId, event, operator, detail, createdAt) VALUES (?, ?, ?, ?, ?)",
            (record_id, event, operator, json.dumps(detail or {}, ensure_ascii=False), now),
        )
        self._conn.commit()

    def get_logs(self, record_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM precipitation_log WHERE recordId = ? ORDER BY createdAt", (record_id,)
        ).fetchall()
        return [dict(r) for r in rows]