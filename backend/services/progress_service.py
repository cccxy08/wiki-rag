"""SSE 进度推送服务 — asyncio.Queue + 全量快照"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class ProgressService:
    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._snapshots: dict[str, dict] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue:
        if task_id not in self._queues:
            self._queues[task_id] = asyncio.Queue(maxsize=100)
        return self._queues[task_id]

    def emit(self, task_id: str, file_name: str, status: str,
             duration_ms: Optional[int] = None, error: Optional[str] = None):
        event = {
            "type": "file_progress",
            "taskId": task_id,
            "fileName": file_name,
            "status": status,
            "timestamp": time.time(),
        }
        if duration_ms is not None:
            event["durationMs"] = duration_ms
        if error:
            event["error"] = error
        self._push(task_id, event)

    def emit_progress(self, task_id: str, total: int, completed: int,
                      success: int, partial: int, failed: int):
        event = {
            "type": "progress_update",
            "taskId": task_id,
            "total": total,
            "completed": completed,
            "success": success,
            "partial": partial,
            "failed": failed,
            "timestamp": time.time(),
        }
        self._push(task_id, event)

    def emit_completed(self, task_id: str, summary: dict):
        event = {
            "type": "task_completed",
            "taskId": task_id,
            "summary": summary,
            "timestamp": time.time(),
        }
        self._push(task_id, event)

    def _push(self, task_id: str, event: dict):
        self._snapshots[task_id] = event
        if task_id in self._queues:
            q = self._queues[task_id]
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                q.put_nowait(event)

    def get_snapshot(self, task_id: str) -> Optional[dict]:
        return self._snapshots.get(task_id)

    def cleanup(self, task_id: str):
        self._queues.pop(task_id, None)
        self._snapshots.pop(task_id, None)