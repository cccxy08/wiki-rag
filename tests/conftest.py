"""全局测试 fixtures — Mock LLM/ChromaDB/Wiki，隔离外部依赖"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保后端目录在 sys.path 中
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


@pytest.fixture
def mock_llm():
    """Mock LLM Provider，拦截所有 LLM 调用"""
    llm = MagicMock()
    llm.model_name = "test-model"
    llm.chat.return_value = "测试回答"
    llm.chat_stream.return_value = iter(["测", "试", "回", "答"])
    return llm


@pytest.fixture
def mock_chroma():
    """Mock ChromaDB，拦截所有向量操作"""
    collection = MagicMock()
    collection.count.return_value = 0
    collection.query.return_value = {
        "ids": [["doc_0_abc123"]],
        "documents": [["测试文档内容"]],
        "metadatas": [[{"source": "test.md", "chunk_index": 0, "parent_id": "p_test_0"}]],
        "distances": [[0.5]],
    }
    collection.get.return_value = {
        "ids": ["doc_0_abc123"],
        "documents": ["测试文档内容"],
        "metadatas": [{"source": "test.md"}],
    }
    return collection


@pytest.fixture
def tmp_wiki(tmp_path):
    """临时 Wiki 目录，隔离测试数据"""
    wiki_dir = tmp_path / "wiki-data"
    wiki_dir.mkdir()
    (wiki_dir / "raw").mkdir()
    (wiki_dir / "raw" / "assets").mkdir()
    (wiki_dir / "wiki").mkdir()
    (wiki_dir / "wiki" / "index.md").write_text("# Wiki index\n\n> Auto-maintained\n\n", encoding="utf-8")
    (wiki_dir / "wiki" / "log.md").write_text("# Operation log\n\n> Chronological\n\n", encoding="utf-8")
    (wiki_dir / "backlinks.json").write_text("{}", encoding="utf-8")
    (wiki_dir / "tags.json").write_text("[]", encoding="utf-8")
    return wiki_dir


@pytest.fixture
def mock_settings(tmp_path, tmp_wiki):
    """覆盖 settings，指向临时目录"""
    with patch("core.config.settings") as mock_s:
        mock_s.llm_provider = "ollama"
        mock_s.ollama_base_url = "http://localhost:11434"
        mock_s.ollama_model = "test-model"
        mock_s.wiki_data_dir = str(tmp_wiki)
        mock_s.wiki_raw_dir = str(tmp_wiki / "raw")
        mock_s.wiki_pages_dir = str(tmp_wiki / "wiki")
        mock_s.chroma_persist_dir = str(tmp_path / "chroma_db")
        mock_s.chroma_collection_name = "test_collection"
        mock_s.chroma_parent_collection_name = "test_collection_parents"
        mock_s.auth_enabled = False
        mock_s.rate_limit_per_minute = 60
        mock_s.rate_limit_admin_per_minute = 20
        mock_s.cors_origins = ""
        mock_s.api_keys = "[]"
        mock_s.log_level = "WARNING"
        mock_s.log_format = "text"
        mock_s.debug = False
        mock_s.host = "0.0.0.0"
        mock_s.port = 8000
        mock_s.reranker_enabled = False
        mock_s.parent_child_enabled = True
        mock_s.retrieval_top_k = 10
        mock_s.bm25_weight = 0.3
        mock_s.similarity_threshold = 2.0
        mock_s.rerank_top_k = 3
        mock_s.chunk_size = 500
        mock_s.chunk_overlap = 50
        mock_s.parent_chunk_size = 750
        mock_s.child_chunk_size = 250
        mock_s.child_chunk_overlap = 50
        mock_s.parent_chunk_overlap = 20
        mock_s.chunk_strategy = {}
        mock_s.query_cache_ttl_seconds = 3600
        mock_s.score_cache_ttl_seconds = 86400
        mock_s.max_history_rounds = 10
        mock_s.agent_max_iterations = 5
        mock_s.agent_min_self_score = 7
        mock_s.llm_max_retries = 3
        mock_s.llm_retry_delay_base = 1.0
        mock_s.embedding_provider = "local"
        mock_s.embedding_model = "BAAI/bge-small-zh"
        mock_s.embedding_device = "cpu"
        mock_s.cache_provider = "memory"
        mock_s.redis_url = "redis://localhost:6379/0"
        mock_s.log_dir = str(tmp_path / "logs")

        def get_wiki_paths():
            return {
                "data": Path(str(tmp_wiki)),
                "raw": Path(str(tmp_wiki / "raw")),
                "pages": Path(str(tmp_wiki / "wiki")),
                "index": Path(str(tmp_wiki / "wiki" / "index.md")),
                "log": Path(str(tmp_wiki / "wiki" / "log.md")),
            }

        mock_s.get_wiki_paths = get_wiki_paths
        yield mock_s


@pytest.fixture
def client(mock_settings):
    """FastAPI TestClient"""
    from fastapi.testclient import TestClient
    with patch("core.llm_provider.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.model_name = "test-model"
        mock_llm.chat.return_value = "测试回答"
        mock_get_llm.return_value = mock_llm

        with patch("core.rag_engine.create_embedding") as mock_emb:
            mock_embedding = MagicMock()
            mock_embedding.get_sentence_embedding_dimension.return_value = 128
            mock_embedding.encode.return_value.tolist.return_value = [[0.0] * 128]
            mock_emb.return_value = mock_embedding

            from main import app
            with TestClient(app) as c:
                yield c