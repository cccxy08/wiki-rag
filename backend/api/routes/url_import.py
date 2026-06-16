"""URL 导入路由 — 单 URL / 批量 URL 抓取并摄入"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from api.deps import require_admin

router = APIRouter(prefix="/api/ingest/url", tags=["url-import"])


class URLImportRequest(BaseModel):
    url: str = Field(..., description="要导入的 URL")


class URLBatchImportRequest(BaseModel):
    urls: list[str] = Field(..., description="要批量导入的 URL 列表")


_url_crawl_service = None


def _get_url_crawl_service():
    global _url_crawl_service
    if _url_crawl_service is None:
        from services.url_crawl_service import URLCrawlService
        _url_crawl_service = URLCrawlService()
    return _url_crawl_service


@router.post("")
def import_url(req: URLImportRequest, request: Request):
    require_admin(request)
    svc = _get_url_crawl_service()
    result = svc.crawl_single(req.url)
    if "error" in result and result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/batch")
def import_url_batch(req: URLBatchImportRequest, request: Request):
    require_admin(request)
    if len(req.urls) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 URLs per batch")
    svc = _get_url_crawl_service()
    task_id = svc.crawl_batch(req.urls)
    return {"taskId": task_id, "totalUrls": len(req.urls)}