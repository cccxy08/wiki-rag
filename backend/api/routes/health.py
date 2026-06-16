"""健康检查路由"""
import time
from fastapi import APIRouter
from schemas.schemas import HealthResponse
from api.deps import _get_wiki_engine, _get_query_service, START_TIME

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health():
    from core.config import settings
    return HealthResponse(
        status="ok",
        llm_provider=settings.llm_provider,
        llm_model=getattr(settings, f"{settings.llm_provider}_model", "unknown"),
        wiki_pages=-1,
        vector_count=-1,
        uptime_seconds=round(time.time() - START_TIME, 1),
    )


@router.get("/health/full", response_model=HealthResponse)
def health_full():
    from core.llm_provider import get_llm
    wiki_engine = _get_wiki_engine()
    query_service = _get_query_service()
    llm = get_llm()
    return HealthResponse(
        status="ok",
        llm_provider=llm.model_name,
        llm_model=llm.model_name,
        wiki_pages=wiki_engine.page_count(),
        vector_count=query_service.rag.collection_count(),
        uptime_seconds=round(time.time() - START_TIME, 1),
    )