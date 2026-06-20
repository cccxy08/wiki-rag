"""文档摄入服务 - 整合 Wiki + RAG 双引擎"""
import logging
import shutil
from pathlib import Path

from core.config import settings
from core.wiki_engine import WikiEngine

logger = logging.getLogger(__name__)


class IngestService:
    """文档摄入服务"""

    def __init__(self):
        self.wiki = WikiEngine.get_instance()
        self._rag = None
        self._rag_init_failed = False

    def _get_rag(self):
        if self._rag is not None:
            return self._rag
        if self._rag_init_failed:
            return None
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.available < 200 * 1024 * 1024:
                logger.warning(f"RAG skipped: low memory ({mem.available // 1024 // 1024}MB available)")
                self._rag_init_failed = True
                return None
        except ImportError:
            pass
        try:
            from core.rag_engine import RAGEngine
            self._rag = RAGEngine.get_instance()
            return self._rag
        except Exception as e:
            logger.error(f"RAG init failed: {e}")
            self._rag_init_failed = True
            return None

    def ingest_file(self, file_content: bytes, filename: str) -> dict:
        raw_dir = settings.get_wiki_paths()["raw"]
        file_path = raw_dir / filename
        file_path.write_bytes(file_content)

        rag_chunks = 0
        rag_error = None
        rag = self._get_rag()
        if rag:
            try:
                rag_chunks = rag.index_document(file_path)
            except Exception as e:
                rag_error = str(e)
        else:
            rag_error = "RAG unavailable (low memory or init failed)"

        wiki_pages = []
        modified_pages = []
        wiki_error = None
        try:
            if rag:
                texts = rag.load_file(file_path)
                full_text = "\n\n".join(texts)
            else:
                full_text = file_path.read_text(encoding="utf-8", errors="replace")
            if full_text.strip():
                result = self.wiki.ingest(full_text, filename)
                wiki_pages = result.get("wiki_pages", [])
                modified_pages = result.get("modified_pages", [])
                if result.get("error"):
                    wiki_error = result["error"]
        except Exception as e:
            wiki_error = str(e)

        status = "success"
        if wiki_error and rag_error:
            status = "failed"
        elif wiki_error or rag_error:
            status = "partial"

        return {
            "status": status,
            "wiki_pages": wiki_pages,
            "modified_pages": modified_pages,
            "rag_chunks": rag_chunks,
            "wiki_error": wiki_error,
            "rag_error": rag_error,
        }

    def ingest_text(self, text: str, source_name: str) -> dict:
        raw_dir = settings.get_wiki_paths()["raw"]
        file_path = raw_dir / source_name
        file_path.write_text(text, encoding="utf-8")

        rag_chunks = 0
        rag_error = None
        rag = self._get_rag()
        if rag:
            try:
                rag_chunks = rag.index_document(file_path)
            except Exception as e:
                rag_error = str(e)
        else:
            rag_error = "RAG unavailable (low memory or init failed)"

        wiki_pages = []
        modified_pages = []
        wiki_error = None
        try:
            if text.strip():
                result = self.wiki.ingest(text, source_name)
                wiki_pages = result.get("wiki_pages", [])
                modified_pages = result.get("modified_pages", [])
                if result.get("error"):
                    wiki_error = result["error"]
        except Exception as e:
            wiki_error = str(e)

        status = "success"
        if wiki_error and rag_error:
            status = "failed"
        elif wiki_error or rag_error:
            status = "partial"

        return {
            "status": status,
            "wiki_pages": wiki_pages,
            "modified_pages": modified_pages,
            "rag_chunks": rag_chunks,
            "wiki_error": wiki_error,
            "rag_error": rag_error,
        }
