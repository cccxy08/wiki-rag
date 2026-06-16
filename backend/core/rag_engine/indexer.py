"""索引管理 — 文档索引、增量更新、旧 chunks 清理"""
from __future__ import annotations
import hashlib
from pathlib import Path
from core.config import settings


class IndexerMixin:
    def index_document(self, file_path: Path) -> int:
        self._remove_document_chunks(file_path)

        try:
            texts = self.load_file(file_path)
        except Exception as e:
            raise RuntimeError(f"文档加载失败 [{file_path.name}]: {e}")

        if not texts:
            raise ValueError(f"文档内容为空: {file_path.name}")

        child_chunks, parent_chunks, child_to_parent = self.chunk_texts_parent_child(texts)

        if not child_chunks:
            raise ValueError(f"切片后无内容: {file_path.name}")

        parent_ids = [f"p_{file_path.stem}_{i}" for i in range(len(parent_chunks))]
        parent_metadatas = [
            {"source": file_path.name, "parent_index": i, "path": str(file_path)}
            for i in range(len(parent_chunks))
        ]
        dim = self.embeddings.get_sentence_embedding_dimension()
        parent_embeddings = [[0.0] * dim for _ in parent_chunks]
        self.parent_collection.add(
            ids=parent_ids, embeddings=parent_embeddings,
            documents=parent_chunks, metadatas=parent_metadatas,
        )

        child_ids = []
        for i, chunk in enumerate(child_chunks):
            chunk_hash = hashlib.md5(chunk.encode()).hexdigest()[:12]
            child_ids.append(f"{file_path.stem}_{i}_{chunk_hash}")

        embeddings = self.embeddings.encode(child_chunks, show_progress_bar=False).tolist()
        metadatas = [
            {
                "source": file_path.name,
                "chunk_index": i,
                "path": str(file_path),
                "parent_id": f"p_{file_path.stem}_{child_to_parent[i]}",
            }
            for i in range(len(child_chunks))
        ]

        self.collection.add(
            ids=child_ids, embeddings=embeddings,
            documents=child_chunks, metadatas=metadatas,
        )

        self._bm25 = None
        return len(child_chunks)

    def _remove_document_chunks(self, file_path: Path) -> int:
        deleted = 0
        try:
            existing = self.collection.get(where={"path": str(file_path)})
            old_ids = existing.get("ids", [])
            if old_ids:
                self.collection.delete(ids=old_ids)
                deleted = len(old_ids)
        except Exception:
            pass

        try:
            existing_parents = self.parent_collection.get(where={"path": str(file_path)})
            old_parent_ids = existing_parents.get("ids", [])
            if old_parent_ids:
                self.parent_collection.delete(ids=old_parent_ids)
        except Exception:
            pass

        return deleted