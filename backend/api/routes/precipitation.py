"""沉淀审核路由 — 用户确认 + 管理员审核 + 撤回 + 版本快照"""
from fastapi import APIRouter, Query, HTTPException, Request
from schemas.schemas import (
    PrecipitationConfirmRequest,
    PrecipitationReviewRequest,
    PrecipitationRecordResponse,
)
from api.deps import require_admin, _get_precipitation_service

router = APIRouter(prefix="/api/precipitation", tags=["precipitation"])


def _get_svc():
    return _get_precipitation_service()


@router.post("/confirm")
def confirm_record(req: PrecipitationConfirmRequest):
    svc = _get_svc()
    if req.action == "confirm":
        if not req.question or not req.answer:
            raise HTTPException(status_code=400, detail="question and answer are required for confirm")
        record_id = svc.create_from_query(req.question, req.answer, req.llmScore, req.source)
        if not record_id:
            return {"status": "skipped", "reason": "score below threshold or precipitation disabled"}
        result = svc.confirm(record_id, user="anonymous")
        return result
    elif req.action == "ignore":
        return {"status": "ignored"}
    raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")


@router.post("/confirm/{recordId}")
def confirm_existing(recordId: str):
    svc = _get_svc()
    result = svc.confirm(recordId, user="anonymous")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/ignore/{recordId}")
def ignore_record(recordId: str):
    svc = _get_svc()
    result = svc.ignore(recordId, user="anonymous")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/review/{recordId}")
def review_record(recordId: str, req: PrecipitationReviewRequest, request: Request):
    require_admin(request)
    svc = _get_svc()
    reviewer = getattr(request.state, "user_role", "admin")

    if req.action == "approve":
        result = svc.review_approve(recordId, reviewer=reviewer)
    elif req.action == "reject":
        result = svc.review_reject(recordId, reviewer=reviewer, reason=req.reason or "")
    elif req.action == "modify_approve":
        if not req.modifiedContent:
            raise HTTPException(status_code=400, detail="modifiedContent is required for modify_approve")
        svc._get_precip_service = lambda: svc
        record = svc._db.get_record(recordId)
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        svc._db.update_record(recordId, answerContent=req.modifiedContent)
        result = svc.review_approve(recordId, reviewer=reviewer)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/revoke/{recordId}")
def revoke_record(recordId: str, request: Request, reason: str = ""):
    require_admin(request)
    svc = _get_svc()
    result = svc.revoke(recordId, operator="admin", reason=reason)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/pending", response_model=dict)
def list_pending_reviews(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    require_admin(request)
    svc = _get_svc()
    return svc.get_pending_reviews(page, pageSize)


@router.get("/record/{recordId}")
def get_record(recordId: str):
    svc = _get_svc()
    record = svc._db.get_record(recordId)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.get("/record/{recordId}/logs")
def get_record_logs(recordId: str):
    svc = _get_svc()
    return {"logs": svc._db.get_logs(recordId)}


@router.get("/stats")
def get_stats(request: Request):
    require_admin(request)
    svc = _get_svc()
    db = svc._db
    return {
        "pendingConfirm": db.count_records("pending_confirm"),
        "pendingReview": db.count_records("pending_review"),
        "approved": db.count_records("approved"),
        "rejected": db.count_records("rejected"),
        "ignored": db.count_records("ignored"),
        "revoked": db.count_records("revoked"),
        "total": db.count_records(),
    }


@router.get("/records")
def list_records(
    request: Request,
    status: str = Query(None, description="按状态筛选"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    require_admin(request)
    svc = _get_svc()
    effective_status = status if status else None
    records = svc._db.list_records(effective_status, page, pageSize)
    total = svc._db.count_records(effective_status)
    return {"records": records, "total": total, "page": page, "pageSize": pageSize}