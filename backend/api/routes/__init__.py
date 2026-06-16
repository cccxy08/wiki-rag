"""Routes 汇总注册"""
from fastapi import APIRouter
from .health import router as health_router
from .query import router as query_router
from .ingest import router as ingest_router
from .wiki import router as wiki_router
from .admin import router as admin_router
from .precipitation import router as precipitation_router
from .watcher import router as watcher_router
from .url_import import router as url_import_router
from .dingtalk import router as dingtalk_router

router = APIRouter()
router.include_router(health_router)
router.include_router(query_router)
router.include_router(ingest_router)
router.include_router(wiki_router)
router.include_router(admin_router)
router.include_router(precipitation_router)
router.include_router(watcher_router)
router.include_router(url_import_router)
router.include_router(dingtalk_router)