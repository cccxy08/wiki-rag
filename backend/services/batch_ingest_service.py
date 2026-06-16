"""批量导入任务管理服务"""
from __future__ import annotations
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from core.config import settings
from db.import_db import ImportDB
from services.progress_service import ProgressService

logger = logging.getLogger(__name__)


class BatchIngestService:
    def __init__(self, db: ImportDB, progress: ProgressService):
        self._db = db
        self._progress = progress
        self._concurrency = settings.batch_concurrency
        self._semaphore = asyncio.Semaphore(self._concurrency)

    async def create_batch_task(self, files: list[UploadFile], source_type: str = "batch_upload") -> dict:
        if not files:
            return {"error": "No files provided", "status": "rejected"}

        if len(files) > settings.batch_max_files:
            return {"error": f"Too many files: {len(files)} > {settings.batch_max_files}", "status": "rejected"}

        supported = set(settings.supported_file_types.split(","))
        max_size = settings.max_file_size_mb * 1024 * 1024

        valid_items = []
        skipped = 0

        for f in files:
            ext = Path(f.filename).suffix.lower() if f.filename else ""
            if ext not in supported:
                skipped += 1
                continue
            if f.size and f.size > max_size:
                skipped += 1
                continue
            valid_items.append(f)

        if not valid_items:
            return {"error": "No valid files", "status": "rejected"}

        task_id = self._db.create_task({
            "sourceType": source_type,
            "totalFiles": len(valid_items),
        })

        for f in valid_items:
            self._db.create_item({
                "taskId": task_id,
                "fileName": f.filename or "unknown",
                "fileSize": f.size or 0,
                "status": "pending",
            })

        asyncio.create_task(self._process_batch(task_id, valid_items))

        return {
            "taskId": task_id,
            "totalFiles": len(valid_items),
            "skippedFiles": skipped,
        }

    async def _process_batch(self, task_id: str, files: list[UploadFile]):
        self._db.update_task_status(task_id, "processing")

        items = self._db.get_items_by_task(task_id)
        total = len(items)
        success = partial = failed = 0

        async def process_one(item, upload_file):
            nonlocal success, partial, failed
            async with self._semaphore:
                self._db.update_item(item["itemId"], status="processing")
                self._progress.emit(task_id, item["fileName"], "processing")

                start = time.time()
                try:
                    result = await self._ingest_file(upload_file)
                    duration_ms = int((time.time() - start) * 1000)

                    status = result.get("status", "failed")
                    if status == "success":
                        success += 1
                    elif status == "partial":
                        partial += 1
                    else:
                        failed += 1

                    self._db.update_item(
                        item["itemId"],
                        status=status,
                        durationMs=duration_ms,
                        wikiPages=result.get("wiki_pages", []),
                        ragChunks=result.get("rag_chunks", 0),
                        errorMessage=result.get("error"),
                    )
                    self._progress.emit(task_id, item["fileName"], status, duration_ms=duration_ms)

                except Exception as e:
                    failed += 1
                    duration_ms = int((time.time() - start) * 1000)
                    self._db.update_item(item["itemId"], status="failed", durationMs=duration_ms, errorMessage=str(e))
                    self._progress.emit(task_id, item["fileName"], "failed", duration_ms=duration_ms, error=str(e))

                completed = success + partial + failed
                self._progress.emit_progress(task_id, total, completed, success, partial, failed)

        file_map = {f.filename: f for f in files}
        tasks = []
        for item in items:
            uf = file_map.get(item["fileName"])
            if uf:
                tasks.append(process_one(item, uf))

        await asyncio.gather(*tasks)

        final_status = "completed" if failed == 0 else "partial" if success > 0 else "failed"
        self._db.update_task_status(
            task_id, final_status,
            successCount=success,
            partialCount=partial,
            failedCount=failed,
            completedAt=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        self._progress.emit_completed(task_id, {
            "status": final_status,
            "totalFiles": total,
            "success": success,
            "partial": partial,
            "failed": failed,
        })

    async def _ingest_file(self, upload_file: UploadFile) -> dict:
        from services.ingest_service import IngestService
        content = await upload_file.read()
        service = IngestService()
        return service.ingest_file(content, upload_file.filename)

    def get_task_status(self, task_id: str) -> Optional[dict]:
        task = self._db.get_task(task_id)
        if not task:
            return None
        items = self._db.get_items_by_task(task_id)
        task["items"] = items
        return task

    async def resume_task(self, task_id: str) -> dict:
        task = self._db.get_task(task_id)
        if not task:
            return {"error": "Task not found"}

        items = self._db.get_pending_or_failed_items(task_id)
        if not items:
            return {"error": "No pending or failed items to resume"}

        raw_dir = Path(settings.wiki_raw_dir)
        resumable = []
        permanently_failed = 0

        for item in items:
            if item.get("retryCount", 0) >= settings.max_retry_count:
                self._db.update_item(item["itemId"], status="permanently_failed")
                permanently_failed += 1
                continue

            file_path = raw_dir / item["fileName"]
            if not file_path.exists():
                self._db.update_item(item["itemId"], status="permanently_failed",
                                     errorMessage="Source file not found")
                permanently_failed += 1
                continue

            self._db.update_item(item["itemId"], status="pending",
                                 retryCount=item.get("retryCount", 0) + 1)
            resumable.append(item)

        if not resumable:
            return {"taskId": task_id, "resumed": 0, "permanentlyFailed": permanently_failed}

        self._db.update_task_status(task_id, "processing")
        total = len(resumable)
        success = partial = failed = 0

        from services.ingest_service import IngestService
        ingest = IngestService()

        for item in resumable:
            self._db.update_item(item["itemId"], status="processing")
            start = time.time()
            try:
                file_path = raw_dir / item["fileName"]
                content = file_path.read_bytes()
                result = ingest.ingest_file(content, item["fileName"])
                duration_ms = int((time.time() - start) * 1000)

                status = result.get("status", "failed")
                if status == "success":
                    success += 1
                elif status == "partial":
                    partial += 1
                else:
                    failed += 1

                self._db.update_item(
                    item["itemId"],
                    status=status,
                    durationMs=duration_ms,
                    wikiPages=result.get("wiki_pages", []),
                    ragChunks=result.get("rag_chunks", 0),
                    errorMessage=result.get("error"),
                )
            except Exception as e:
                failed += 1
                duration_ms = int((time.time() - start) * 1000)
                self._db.update_item(item["itemId"], status="failed",
                                     durationMs=duration_ms, errorMessage=str(e))

        final_status = "completed" if failed == 0 else "partial" if success > 0 else "failed"
        self._db.update_task_status(
            task_id, final_status,
            successCount=success,
            partialCount=partial,
            failedCount=failed,
            completedAt=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        return {
            "taskId": task_id,
            "resumed": total,
            "success": success,
            "partial": partial,
            "failed": failed,
            "permanentlyFailed": permanently_failed,
        }