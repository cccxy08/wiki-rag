"""文档摄入路由 — 单文件 + 批量上传 + SSE 进度 + 导入历史"""
import asyncio
import json
from fastapi import APIRouter, UploadFile, File, Query, HTTPException
from fastapi.responses import StreamingResponse
from schemas.schemas import (
    IngestResponse, BatchIngestResponse, TaskStatusResponse,
    TaskItemResponse, ImportHistoryResponse, TaskSummaryResponse,
)
from api.deps import (
    _get_ingest_service, _get_batch_ingest_service,
    _get_import_db, _get_progress_service,
)

router = APIRouter(prefix="/api", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...)):
    ingest_service = _get_ingest_service()
    try:
        content = await file.read()
        result = ingest_service.ingest_file(content, file.filename)
        return IngestResponse(
            status=result["status"],
            wiki_pages=result.get("wiki_pages", []),
            modified_pages=result.get("modified_pages", []),
            log_entry=f"[{result['status']}] 摄入 {file.filename}",
            error=result.get("wiki_error") or result.get("rag_error"),
        )
    except Exception as e:
        return IngestResponse(status="failed", error=str(e))


@router.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch(files: list[UploadFile] = File(...)):
    batch_service = _get_batch_ingest_service()
    result = await batch_service.create_batch_task(files)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return BatchIngestResponse(
        taskId=result["taskId"],
        totalFiles=result["totalFiles"],
        skippedFiles=result["skippedFiles"],
    )


@router.get("/ingest/task/{taskId}", response_model=TaskStatusResponse)
def get_task_status(taskId: str):
    batch_service = _get_batch_ingest_service()
    task = batch_service.get_task_status(taskId)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {taskId}")

    items = []
    for item in task.get("items", []):
        wp = item.get("wikiPages", "[]")
        if isinstance(wp, str):
            try:
                wp = json.loads(wp)
            except (json.JSONDecodeError, TypeError):
                wp = []
        items.append(TaskItemResponse(
            itemId=item["itemId"],
            fileName=item["fileName"],
            fileSize=item.get("fileSize", 0),
            status=item.get("status", "pending"),
            retryCount=item.get("retryCount", 0),
            durationMs=item.get("durationMs"),
            errorMessage=item.get("errorMessage"),
            wikiPages=wp,
            ragChunks=item.get("ragChunks", 0),
        ))

    return TaskStatusResponse(
        taskId=task["taskId"],
        sourceType=task.get("sourceType", "batch_upload"),
        status=task.get("status", "pending"),
        totalFiles=task.get("totalFiles", 0),
        successCount=task.get("successCount", 0),
        partialCount=task.get("partialCount", 0),
        failedCount=task.get("failedCount", 0),
        skippedCount=task.get("skippedCount", 0),
        createdAt=task.get("createdAt", ""),
        completedAt=task.get("completedAt"),
        items=items,
    )


@router.get("/ingest/task/{taskId}/progress")
async def task_progress(taskId: str):
    progress_service = _get_progress_service()

    async def event_generator():
        queue = progress_service.subscribe(taskId)
        snapshot = progress_service.get_snapshot(taskId)
        if snapshot:
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "task_completed":
                    break
            except asyncio.TimeoutError:
                yield f": heartbeat\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/ingest/history", response_model=ImportHistoryResponse)
def import_history(
    status: str = Query(None, description="按状态筛选"),
    page: int = Query(1, ge=1, description="页码"),
    pageSize: int = Query(20, ge=1, le=100, description="每页大小"),
):
    db = _get_import_db()
    total = db.count_tasks(status)
    tasks = db.list_tasks(status, page, pageSize)
    summaries = [
        TaskSummaryResponse(
            taskId=t["taskId"],
            sourceType=t.get("sourceType", "batch_upload"),
            status=t.get("status", "pending"),
            totalFiles=t.get("totalFiles", 0),
            successCount=t.get("successCount", 0),
            failedCount=t.get("failedCount", 0),
            createdAt=t.get("createdAt", ""),
            completedAt=t.get("completedAt"),
        )
        for t in tasks
    ]
    return ImportHistoryResponse(tasks=summaries, total=total, page=page, pageSize=pageSize)


@router.post("/ingest/task/{taskId}/retry")
def retry_failed(taskId: str):
    db = _get_import_db()
    task = db.get_task(taskId)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {taskId}")

    items = db.get_pending_or_failed_items(taskId)
    if not items:
        raise HTTPException(status_code=400, detail="No failed items to retry")

    from core.config import settings
    retried = 0
    permanently_failed = 0
    for item in items:
        if item.get("retryCount", 0) >= settings.max_retry_count:
            db.update_item(item["itemId"], status="permanently_failed")
            permanently_failed += 1
        else:
            db.update_item(item["itemId"], status="pending", retryCount=item.get("retryCount", 0) + 1)
            retried += 1

    return {"taskId": taskId, "retried": retried, "permanentlyFailed": permanently_failed}


@router.post("/ingest/task/{taskId}/resume")
async def resume_task(taskId: str):
    batch_service = _get_batch_ingest_service()
    db = _get_import_db()
    task = db.get_task(taskId)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {taskId}")

    result = await batch_service.resume_task(taskId)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
