"""RAGEngine — 门面类，继承所有 Mixin，保持导入路径不变

Usage:
    from core.rag_engine import RAGEngine
"""
from __future__ import annotations
import logging
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from core.config import settings
from core.llm_provider import get_llm
from core.retrieval import Reranker
from .embedding import BaseEmbedding, create_embedding
from .loader import LoaderMixin
from .chunker import ChunkerMixin
from .indexer import IndexerMixin
from .retriever import RetrieverMixin
from .core import CoreMixin

logger = logging.getLogger(__name__)


class RAGEngine(LoaderMixin, ChunkerMixin, IndexerMixin, RetrieverMixin, CoreMixin):
    _instance: Optional["RAGEngine"] = None

    @classmethod
    def get_instance(cls) -> "RAGEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.llm = get_llm()
        self.embeddings = create_embedding()
        self.chroma_client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name=settings.chroma_collection_name,
        )
        self.parent_collection = self.chroma_client.get_or_create_collection(
            name=settings.chroma_parent_collection_name,
        )
        self._loader_map = {
            ".pdf": self._load_pdf,
            ".txt": self._load_text,
            ".md": self._load_markdown,
            ".docx": self._load_docx,
            ".xlsx": self._load_xlsx,
            ".xls": self._load_xls,
            ".csv": self._load_text,
        }
        self._bm25 = None
        self._bm25_id_map = {}
        if settings.reranker_enabled:
            self.reranker = Reranker(model_name_or_path=settings.reranker_model_path)
        else:
            self.reranker = None
            logger.info("Reranker 已禁用（reranker_enabled=False），节省 ~1.2GB 内存")