"""延迟加载服务实例 + 依赖注入 — 优先走注册中心（支持热插拔）"""
import time

START_TIME = time.time()

_registry_initialized = False


def _ensure_registry():
    global _registry_initialized
    if not _registry_initialized:
        try:
            from core.registry import setup_registry
            setup_registry()
        except Exception:
            pass
        _registry_initialized = True


def _get_query_service():
    _ensure_registry()
    try:
        from core.registry import ComponentRegistry
        return ComponentRegistry.get_instance().get("query_service")
    except Exception:
        global _query_service
        if _query_service is None:
            from services.query_service import QueryService
            _query_service = QueryService()
        return _query_service


_query_service = None
_wiki_engine = None
_ingest_service = None


def _get_ingest_service():
    global _ingest_service
    if _ingest_service is None:
        from services.ingest_service import IngestService
        _ingest_service = IngestService()
    return _ingest_service


def _get_wiki_engine():
    _ensure_registry()
    try:
        from core.registry import ComponentRegistry
        return ComponentRegistry.get_instance().get("wiki_engine")
    except Exception:
        global _wiki_engine
        if _wiki_engine is None:
            from core.wiki_engine import WikiEngine
            _wiki_engine = WikiEngine.get_instance()
        return _wiki_engine


def require_admin(request):
    """FastAPI 依赖：检查 request.state.user_role 是否为 admin"""
    if getattr(request.state, "user_role", None) != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return True


_import_db = None
_progress_service = None
_batch_ingest_service = None


def _get_import_db():
    global _import_db
    if _import_db is None:
        from db.import_db import ImportDB
        from pathlib import Path
        from core.config import settings
        db_path = Path(settings.wiki_data_dir) / "import_tasks.db"
        _import_db = ImportDB(db_path)
    return _import_db


def _get_progress_service():
    global _progress_service
    if _progress_service is None:
        from services.progress_service import ProgressService
        _progress_service = ProgressService()
    return _progress_service


def _get_batch_ingest_service():
    global _batch_ingest_service
    if _batch_ingest_service is None:
        from services.batch_ingest_service import BatchIngestService
        _batch_ingest_service = BatchIngestService(_get_import_db(), _get_progress_service())
    return _batch_ingest_service


_precipitation_service = None


def _get_precipitation_service():
    global _precipitation_service
    if _precipitation_service is None:
        from services.precipitation_service import PrecipitationService
        from db.precipitation_db import PrecipitationDB
        from pathlib import Path
        from core.config import settings
        db_path = Path(settings.wiki_data_dir) / "precipitation.db"
        _precipitation_service = PrecipitationService(PrecipitationDB(db_path))
    return _precipitation_service