"""组件注册中心 — 热插拔支持，配置变更后自动重建受影响组件

设计原则：
1. 每个组件注册时声明依赖的配置字段
2. 配置变更时，自动销毁旧实例并重建受影响的组件
3. 组件重建是级联的：LLM 变更 → RAGEngine 重建 → QueryService 重建
"""
from __future__ import annotations
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ComponentRegistry:
    _instance: Optional["ComponentRegistry"] = None

    @classmethod
    def get_instance(cls) -> "ComponentRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._components: dict[str, dict] = {}
        self._config_field_map: dict[str, list[str]] = {}

    def register(
        self,
        name: str,
        factory: Callable[[], Any],
        config_fields: list[str] = None,
        depends_on: list[str] = None,
        on_destroy: Callable[[Any], None] = None,
    ):
        self._components[name] = {
            "factory": factory,
            "config_fields": set(config_fields or []),
            "depends_on": set(depends_on or []),
            "on_destroy": on_destroy,
            "instance": None,
        }
        for field in (config_fields or []):
            if field not in self._config_field_map:
                self._config_field_map[field] = []
            self._config_field_map[field].append(name)
        logger.debug(f"Registered component: {name} (fields={config_fields}, deps={depends_on})")

    def get(self, name: str) -> Any:
        entry = self._components.get(name)
        if not entry:
            raise KeyError(f"Component not registered: {name}")
        if entry["instance"] is None:
            entry["instance"] = entry["factory"]()
            logger.info(f"Component created: {name}")
        return entry["instance"]

    def invalidate(self, name: str):
        entry = self._components.get(name)
        if not entry:
            return
        if entry["instance"] is not None:
            if entry["on_destroy"]:
                try:
                    entry["on_destroy"](entry["instance"])
                except Exception as e:
                    logger.warning(f"Error destroying component {name}: {e}")
            entry["instance"] = None
            logger.info(f"Component invalidated: {name}")

        for dep_name in self._components:
            dep = self._components[dep_name]
            if name in dep["depends_on"]:
                self.invalidate(dep_name)

    def on_config_changed(self, changed_fields: set[str]):
        affected = set()
        for field in changed_fields:
            affected.update(self._config_field_map.get(field, []))

        for name in affected:
            logger.info(f"Config change affects component: {name}")
            self.invalidate(name)

        return list(affected)

    def list_components(self) -> list[dict]:
        result = []
        for name, entry in self._components.items():
            result.append({
                "name": name,
                "configFields": list(entry["config_fields"]),
                "dependsOn": list(entry["depends_on"]),
                "instantiated": entry["instance"] is not None,
            })
        return result

    def get_status(self) -> dict:
        status = {}
        for name, entry in self._components.items():
            status[name] = {
                "instantiated": entry["instance"] is not None,
                "type": type(entry["instance"]).__name__ if entry["instance"] else None,
            }
        return status


def setup_registry():
    """注册所有核心组件"""
    registry = ComponentRegistry.get_instance()

    registry.register(
        "llm",
        factory=lambda: _create_llm(),
        config_fields=["llm_provider", "ollama_base_url", "ollama_model", "openai_api_key", "openai_model", "openai_base_url", "zhipu_api_key", "zhipu_model", "minimax_api_key", "minimax_model", "minimax_multimodal_model", "minimax_base_url"],
    )

    registry.register(
        "embedding",
        factory=lambda: _create_embedding(),
        config_fields=["embedding_provider", "embedding_model", "embedding_device", "zhipu_embedding_model", "openai_embedding_model", "zhipu_api_key", "openai_api_key", "openai_base_url"],
    )

    registry.register(
        "rag_engine",
        factory=lambda: _create_rag_engine(),
        config_fields=["chroma_persist_dir", "chroma_collection_name", "reranker_enabled", "reranker_model_path", "chunk_size", "chunk_overlap", "retrieval_top_k", "similarity_threshold", "bm25_weight", "parent_child_enabled"],
        depends_on=["llm", "embedding"],
    )

    registry.register(
        "wiki_engine",
        factory=lambda: _create_wiki_engine(),
        config_fields=["wiki_data_dir", "wiki_raw_dir", "wiki_pages_dir"],
    )

    registry.register(
        "query_service",
        factory=lambda: _create_query_service(),
        config_fields=["query_cache_ttl_seconds", "cache_provider", "redis_url", "precipitation_enabled", "precipitation_score_threshold"],
        depends_on=["rag_engine", "wiki_engine"],
    )

    registry.register(
        "auth",
        factory=lambda: _create_auth(),
        config_fields=["auth_enabled", "api_keys"],
    )

    registry.register(
        "dingtalk",
        factory=lambda: _create_dingtalk(),
        config_fields=["dingtalk_enabled", "dingtalk_client_id", "dingtalk_client_secret", "dingtalk_robot_code", "dingtalk_mode"],
    )


def _create_llm():
    from core.llm_provider import get_llm
    return get_llm()


def _create_embedding():
    from core.rag_engine.embedding import create_embedding
    return create_embedding()


def _create_rag_engine():
    from core.rag_engine import RAGEngine
    RAGEngine._instance = None
    return RAGEngine.get_instance()


def _create_wiki_engine():
    from core.wiki_engine import WikiEngine
    WikiEngine._instance = None
    return WikiEngine.get_instance()


def _create_query_service():
    from services.query_service import QueryService
    return QueryService()


def _create_auth():
    from middleware.auth import AuthMiddleware
    return AuthMiddleware(app=None)


def _create_dingtalk():
    from services.dingtalk_service import DingTalkBotService
    svc = DingTalkBotService()
    svc.start_stream()
    return svc