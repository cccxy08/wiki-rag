"""管理后台路由"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from api.deps import _get_wiki_engine, _get_query_service, require_admin
from core.config import settings

router = APIRouter(prefix="/api", tags=["admin"])

SENSITIVE_KEYS = {"openai_api_key", "zhipu_api_key", "dingtalk_client_secret", "api_keys"}
READONLY_KEYS = {"wiki_data_dir", "wiki_raw_dir", "wiki_pages_dir", "chroma_persist_dir", "chroma_collection_name", "chroma_parent_collection_name", "host", "port"}
BOOLEAN_KEYS = {"debug", "auth_enabled", "summary_enabled", "parent_child_enabled", "reranker_enabled", "precipitation_enabled", "dingtalk_enabled"}
INT_KEYS = {"chunk_size", "chunk_overlap", "retrieval_top_k", "parent_chunk_size", "child_chunk_size", "child_chunk_overlap", "parent_chunk_overlap", "rerank_top_k", "agent_max_iterations", "agent_min_self_score", "max_history_rounds", "query_cache_ttl_seconds", "score_cache_ttl_seconds", "llm_max_retries", "rate_limit_per_minute", "rate_limit_admin_per_minute", "batch_max_files", "max_file_size_mb", "batch_concurrency", "max_retry_count", "history_retention_days", "history_default_page_size", "history_max_page_size", "precipitation_score_threshold", "precipitation_confirm_timeout_seconds", "version_snapshot_max_versions", "dingtalk_message_timeout_seconds", "dingtalk_file_download_timeout_seconds", "dingtalk_stream_reconnect_max_interval_seconds", "watcher_health_check_interval_seconds", "url_fetch_timeout_seconds", "url_max_response_size_mb"}
FLOAT_KEYS = {"similarity_threshold", "bm25_weight", "llm_retry_delay_base", "watcher_stable_wait_seconds"}

SETTINGS_GROUPS = [
    {
        "key": "llm",
        "label": "LLM 模型",
        "fields": ["llm_provider", "ollama_base_url", "ollama_model", "openai_model", "openai_base_url", "zhipu_model"],
    },
    {
        "key": "embedding",
        "label": "Embedding 向量",
        "fields": ["embedding_provider", "embedding_model", "embedding_device", "zhipu_embedding_model", "openai_embedding_model"],
    },
    {
        "key": "chunk",
        "label": "切片与检索",
        "fields": ["chunk_size", "chunk_overlap", "retrieval_top_k", "parent_child_enabled", "parent_chunk_size", "child_chunk_size", "child_chunk_overlap", "parent_chunk_overlap", "rerank_top_k", "similarity_threshold", "bm25_weight", "reranker_enabled", "reranker_model_path"],
    },
    {
        "key": "agent",
        "label": "Agent 智能体",
        "fields": ["agent_max_iterations", "agent_min_self_score", "max_history_rounds", "summary_enabled", "query_cache_ttl_seconds", "llm_max_retries", "llm_retry_delay_base"],
    },
    {
        "key": "security",
        "label": "安全与限流",
        "fields": ["auth_enabled", "rate_limit_per_minute", "rate_limit_admin_per_minute", "cors_origins"],
    },
    {
        "key": "cache",
        "label": "缓存",
        "fields": ["cache_provider", "redis_url"],
    },
    {
        "key": "batch",
        "label": "批量导入",
        "fields": ["batch_max_files", "max_file_size_mb", "batch_concurrency", "max_retry_count", "supported_file_types", "history_retention_days"],
    },
    {
        "key": "precipitation",
        "label": "沉淀审核",
        "fields": ["precipitation_enabled", "precipitation_score_threshold", "precipitation_confirm_timeout_seconds", "version_snapshot_max_versions"],
    },
    {
        "key": "dingtalk",
        "label": "钉钉机器人",
        "fields": ["dingtalk_enabled", "dingtalk_client_id", "dingtalk_robot_code", "dingtalk_mode", "dingtalk_admin_ids", "dingtalk_admin_group_webhook", "dingtalk_message_timeout_seconds", "dingtalk_file_download_timeout_seconds", "dingtalk_stream_reconnect_max_interval_seconds"],
    },
    {
        "key": "watcher",
        "label": "目录监控",
        "fields": ["watcher_allowed_dirs", "watcher_stable_wait_seconds", "watcher_health_check_interval_seconds"],
    },
    {
        "key": "url",
        "label": "URL 抓取",
        "fields": ["url_fetch_timeout_seconds", "url_max_response_size_mb", "url_allowed_schemes"],
    },
    {
        "key": "service",
        "label": "服务与日志",
        "fields": ["log_level", "log_format", "debug"],
    },
]


@router.get("/admin/dashboard")
def admin_dashboard(request: Request):
    require_admin(request)

    wiki_engine = _get_wiki_engine()
    query_service = _get_query_service()

    wiki_stats = {
        "total_pages": wiki_engine.page_count(),
        "orphan_pages": 0,
        "stale_pages": 0,
        "last_ingest": None,
    }
    rag_stats = {
        "total_documents": query_service.rag.collection_count(),
        "last_indexed": None,
    }
    cache_stats = query_service.get_cache_stats()
    try:
        log_path = wiki_engine.paths["log"]
        if log_path.exists():
            log_lines = log_path.read_text(encoding="utf-8").strip().split("\n")
            recent = [l for l in log_lines[-10:] if l.startswith("## [")]
        else:
            recent = []
    except Exception:
        recent = []
    try:
        lint_issues = wiki_engine.lint()
        wiki_stats["orphan_pages"] = sum(1 for i in lint_issues if i["type"] == "orphan")
        wiki_stats["stale_pages"] = sum(1 for i in lint_issues if i["type"] in ("stale", "deprecated_stale", "expired"))
    except Exception:
        pass
    for line in reversed(recent):
        if "ingest" in line:
            wiki_stats["last_ingest"] = line.split("]")[0].lstrip("## [")
            break
    for line in reversed(recent):
        if "index" in line.lower() or "ingest" in line:
            rag_stats["last_indexed"] = line.split("]")[0].lstrip("## [")
            break
    return {
        "wiki": wiki_stats,
        "rag": rag_stats,
        "cache": cache_stats,
        "recent_operations": [l.lstrip("## ").rstrip() for l in recent[-5:]],
    }


@router.get("/admin/settings")
def get_settings(request: Request):
    require_admin(request)
    all_fields = {}
    for field_name in settings.model_fields:
        value = getattr(settings, field_name, None)
        if field_name in SENSITIVE_KEYS and value:
            value = "***"
        all_fields[field_name] = value
    return {"settings": all_fields, "groups": SETTINGS_GROUPS, "readonlyKeys": list(READONLY_KEYS), "booleanKeys": list(BOOLEAN_KEYS), "intKeys": list(INT_KEYS), "floatKeys": list(FLOAT_KEYS)}


class UpdateSettingsRequest(BaseModel):
    updates: dict


@router.put("/admin/settings")
def update_settings(req: UpdateSettingsRequest, request: Request):
    require_admin(request)
    applied = {}
    skipped = []
    changed_fields = set()

    for key, value in req.updates.items():
        if key in READONLY_KEYS:
            skipped.append({"key": key, "reason": "readonly"})
            continue
        if key in SENSITIVE_KEYS:
            if value == "***":
                skipped.append({"key": key, "reason": "sensitive_unchanged"})
                continue
        if not hasattr(settings, key):
            skipped.append({"key": key, "reason": "unknown_field"})
            continue
        try:
            old_value = getattr(settings, key)
            if key in BOOLEAN_KEYS:
                value = str(value).lower() in ("true", "1", "yes")
            elif key in INT_KEYS:
                value = int(value)
            elif key in FLOAT_KEYS:
                value = float(value)
            setattr(settings, key, value)
            applied[key] = value
            if old_value != value:
                changed_fields.add(key)
        except (ValueError, TypeError) as e:
            skipped.append({"key": key, "reason": str(e)})

    affected_components = []
    if changed_fields:
        try:
            from core.registry import ComponentRegistry
            registry = ComponentRegistry.get_instance()
            affected_components = registry.on_config_changed(changed_fields)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Registry hot-reload failed: {e}")

    return {
        "applied": applied,
        "skipped": skipped,
        "changedFields": list(changed_fields),
        "affectedComponents": affected_components,
        "restartRequired": False,
    }


@router.get("/admin/system-status")
def system_status(request: Request):
    require_admin(request)
    status = {
        "llm": {"provider": settings.llm_provider, "model": getattr(settings, f"{settings.llm_provider}_model", "unknown")},
        "dingtalk": {"enabled": settings.dingtalk_enabled, "connected": False, "mode": settings.dingtalk_mode},
        "watchers": [],
        "cache": {"provider": settings.cache_provider},
        "precipitation": {"enabled": settings.precipitation_enabled, "threshold": settings.precipitation_score_threshold},
    }

    try:
        from api.routes.watcher import _get_watcher_service
        svc = _get_watcher_service()
        status["watchers"] = svc.list_watchers()
    except Exception:
        pass

    try:
        qs = _get_query_service()
        status["cache"]["stats"] = qs.get_cache_stats()
    except Exception:
        pass

    try:
        from core.registry import ComponentRegistry
        registry = ComponentRegistry.get_instance()
        status["components"] = registry.get_status()
    except Exception:
        status["components"] = {}

    return status


class TestConnectionRequest(BaseModel):
    service: str = Field(..., description="要测试的服务: llm / dingtalk / redis / embedding")


@router.post("/admin/test-connection")
def test_connection(req: TestConnectionRequest, request: Request):
    require_admin(request)

    if req.service == "llm":
        return _test_llm_connection()
    elif req.service == "dingtalk":
        return _test_dingtalk_connection()
    elif req.service == "redis":
        return _test_redis_connection()
    elif req.service == "embedding":
        return _test_embedding_connection()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown service: {req.service}")


def _test_llm_connection() -> dict:
    provider = settings.llm_provider
    try:
        if provider == "ollama":
            import httpx
            resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=10)
            if resp.status_code == 200:
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                return {"success": True, "message": f"Ollama 连接成功，可用模型: {', '.join(models[:5])}"}
            return {"success": False, "message": f"Ollama 返回状态码 {resp.status_code}"}
        elif provider == "openai":
            if not settings.openai_api_key:
                return {"success": False, "message": "OpenAI API Key 未配置"}
            from openai import OpenAI
            client = OpenAI(base_url=settings.openai_base_url, api_key=settings.openai_api_key)
            client.models.list()
            return {"success": True, "message": f"OpenAI 连接成功，模型: {settings.openai_model}"}
        elif provider == "zhipu":
            if not settings.zhipu_api_key:
                return {"success": False, "message": "智谱 API Key 未配置"}
            from openai import OpenAI
            client = OpenAI(base_url="https://open.bigmodel.cn/api/paas/v4", api_key=settings.zhipu_api_key)
            client.models.list()
            return {"success": True, "message": f"智谱连接成功，模型: {settings.zhipu_model}"}
        return {"success": False, "message": f"未知的 LLM Provider: {provider}"}
    except Exception as e:
        return {"success": False, "message": f"{provider} 连接失败: {str(e)[:200]}"}


def _test_dingtalk_connection() -> dict:
    if not settings.dingtalk_enabled:
        return {"success": False, "message": "钉钉未启用"}
    if not settings.dingtalk_client_id or not settings.dingtalk_client_secret:
        return {"success": False, "message": "Client ID 或 Secret 未配置"}
    try:
        import httpx
        resp = httpx.post(
            "https://api.dingtalk.com/v1.0/oauth2/accessToken",
            json={"appKey": settings.dingtalk_client_id, "appSecret": settings.dingtalk_client_secret},
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("accessToken"):
            return {"success": True, "message": f"钉钉认证成功，模式: {settings.dingtalk_mode}"}
        return {"success": False, "message": f"钉钉认证失败: {resp.text[:200]}"}
    except ImportError:
        return {"success": False, "message": "dingtalk-stream 未安装"}
    except Exception as e:
        return {"success": False, "message": f"钉钉连接失败: {str(e)[:200]}"}


def _test_redis_connection() -> dict:
    if settings.cache_provider != "redis":
        return {"success": False, "message": "当前缓存提供商不是 Redis"}
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_connect_timeout=5)
        r.ping()
        info = r.info("server")
        return {"success": True, "message": f"Redis 连接成功，版本: {info.get('redis_version', 'unknown')}"}
    except ImportError:
        return {"success": False, "message": "redis 包未安装"}
    except Exception as e:
        return {"success": False, "message": f"Redis 连接失败: {str(e)[:200]}"}


def _test_embedding_connection() -> dict:
    provider = settings.embedding_provider
    try:
        if provider == "local":
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
            dim = model.get_sentence_embedding_dimension()
            return {"success": True, "message": f"本地 Embedding 加载成功，维度: {dim}"}
        elif provider == "zhipu":
            if not settings.zhipu_api_key:
                return {"success": False, "message": "智谱 API Key 未配置"}
            from openai import OpenAI
            client = OpenAI(base_url="https://open.bigmodel.cn/api/paas/v4", api_key=settings.zhipu_api_key)
            client.embeddings.create(model=settings.zhipu_embedding_model, input=["test"])
            return {"success": True, "message": f"智谱 Embedding 连接成功，模型: {settings.zhipu_embedding_model}"}
        elif provider == "openai":
            if not settings.openai_api_key:
                return {"success": False, "message": "OpenAI API Key 未配置"}
            from openai import OpenAI
            client = OpenAI(base_url=settings.openai_base_url, api_key=settings.openai_api_key)
            client.embeddings.create(model=settings.openai_embedding_model, input=["test"])
            return {"success": True, "message": f"OpenAI Embedding 连接成功，模型: {settings.openai_embedding_model}"}
        return {"success": False, "message": f"未知 Embedding Provider: {provider}"}
    except Exception as e:
        return {"success": False, "message": f"{provider} Embedding 连接失败: {str(e)[:200]}"}