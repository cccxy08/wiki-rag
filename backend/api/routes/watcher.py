"""目录监控管理路由"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
from api.deps import require_admin

router = APIRouter(prefix="/api/ingest/watcher", tags=["watcher"])


class WatcherConfigRequest(BaseModel):
    directoryPath: str = Field(..., description="监控目录路径")
    filePatterns: Optional[list[str]] = Field(None, description="文件格式过滤")


_watcher_service = None


def _get_watcher_service():
    global _watcher_service
    if _watcher_service is None:
        from services.directory_watcher_service import DirectoryWatcherService
        _watcher_service = DirectoryWatcherService()
    return _watcher_service


@router.post("")
def add_watcher(req: WatcherConfigRequest, request: Request):
    require_admin(request)
    svc = _get_watcher_service()
    result = svc.add_watcher(req.directoryPath, req.filePatterns)
    if "error" in result:
        status_code = 403 if result.get("status") == "forbidden" else 400
        if result.get("status") == "not_found":
            status_code = 404
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result


@router.get("")
def list_watchers(request: Request):
    require_admin(request)
    svc = _get_watcher_service()
    return {"watchers": svc.list_watchers()}


@router.delete("/{dirId}")
def remove_watcher(dirId: str, request: Request):
    require_admin(request)
    svc = _get_watcher_service()
    result = svc.remove_watcher(dirId)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result