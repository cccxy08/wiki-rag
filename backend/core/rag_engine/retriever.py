"""混合检索 — 向量检索 + BM25 加权融合 + Reranker 重排序"""
from __future__ import annotations
import re
from collections import defaultdict
from core.config import settings


class RetrieverMixin:
    def retrieve(self, query: str, top_k: int = None) -> list[dict]:
        return self.retrieve_with_bm25(query, top_k)

    def retrieve_vector_only(self, query: str, top_k: int = None) -> list[dict]:
        if top_k is None:
            top_k = settings.retrieval_top_k

        query_embedding = self.embeddings.encode(query, show_progress_bar=False).tolist()
        fetch_k = top_k * 3
        results = self.collection.query(query_embeddings=[query_embedding], n_results=fetch_k)

        documents = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                score = results["distances"][0][i] if results.get("distances") else 0
                if score > settings.similarity_threshold:
                    continue
                documents.append({
                    "id": doc_id,
                    "content": results["documents"][0][i] if results.get("documents") else "",
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "score": score,
                })

        docs = self._dedup_by_source(documents, top_k)

        if settings.parent_child_enabled:
            docs = self._map_children_to_parents(docs)

        if self.reranker and self.reranker.available and len(docs) > 1:
            docs = self.reranker.rerank(query, docs, top_k=settings.rerank_top_k)

        return docs

    def _dedup_by_source(self, docs: list[dict], top_k: int) -> list[dict]:
        best = {}
        for d in docs:
            src = d.get("metadata", {}).get("source", "__UNKNOWN__")
            if src not in best or d["score"] < best[src]["score"]:
                best[src] = d
        return sorted(best.values(), key=lambda x: x["score"])[:top_k]

    def _tokenize(self, text: str) -> list[str]:
        import jieba
        tokens = []
        for segment in re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text):
            if re.match(r'[\u4e00-\u9fff]+', segment):
                tokens.extend(jieba.lcut(segment))
            else:
                tokens.append(segment.lower())
        return tokens

    def _rebuild_bm25_index(self):
        from rank_bm25 import BM25Okapi
        all_data = self.collection.get(include=["documents"])
        if not all_data or not all_data.get("documents"):
            self._bm25 = None
            self._bm25_id_map = {}
            return
        tokenized_corpus = []
        self._bm25_id_map = {}
        for i, doc_text in enumerate(all_data["documents"]):
            tokenized_corpus.append(self._tokenize(doc_text))
            self._bm25_id_map[all_data["ids"][i]] = i
        self._bm25 = BM25Okapi(tokenized_corpus)

    def retrieve_with_bm25(self, query: str, top_k: int = None) -> list[dict]:
        if top_k is None:
            top_k = settings.retrieval_top_k

        query_embedding = self.embeddings.encode(query, show_progress_bar=False).tolist()
        fetch_k = top_k * 5
        results = self.collection.query(query_embeddings=[query_embedding], n_results=fetch_k)

        vector_docs = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                score = results["distances"][0][i] if results.get("distances") else 0
                vector_docs.append({
                    "id": doc_id,
                    "content": results["documents"][0][i] if results.get("documents") else "",
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "vector_l2": score,
                })

        if not vector_docs:
            return []

        if self._bm25 is None:
            self._rebuild_bm25_index()

        query_tokens = self._tokenize(query)
        bm25_scores_all = self._bm25.get_scores(query_tokens) if self._bm25 else []

        for d in vector_docs:
            idx = self._bm25_id_map.get(d["id"])
            d["bm25_raw"] = bm25_scores_all[idx] if idx is not None and len(bm25_scores_all) > 0 else 0.0

        l2_vals = [d["vector_l2"] for d in vector_docs]
        bm25_vals = [d["bm25_raw"] for d in vector_docs]
        max_l2 = max(l2_vals) if l2_vals else 1.0
        max_bm25 = max(bm25_vals) if bm25_vals else 1.0

        for d in vector_docs:
            d["vector_sim"] = 1.0 / (1.0 + d["vector_l2"])
            d["bm25_norm"] = d["bm25_raw"] / max_bm25 if max_bm25 > 0 else 0.0

        bw = settings.bm25_weight
        for d in vector_docs:
            d["hybrid_score"] = (1 - bw) * d["vector_sim"] + bw * d["bm25_norm"]

        vector_docs.sort(key=lambda x: x["hybrid_score"], reverse=True)

        buckets = defaultdict(list)
        for d in vector_docs:
            src = d.get("metadata", {}).get("source", "__UNKNOWN__")
            buckets[src].append(d)
        best = []
        for src, items in buckets.items():
            items.sort(key=lambda x: x["hybrid_score"], reverse=True)
            best.extend(items[:2])

        merged = sorted(best, key=lambda x: x["hybrid_score"], reverse=True)[:top_k]

        for d in merged:
            d["score"] = d["hybrid_score"]

        if settings.parent_child_enabled:
            merged = self._map_children_to_parents(merged)

        if self.reranker and self.reranker.available and len(merged) > 1:
            merged = self.reranker.rerank(query, merged, top_k=settings.rerank_top_k)

        return merged

    def _map_children_to_parents(self, child_docs: list[dict]) -> list[dict]:
        parent_ids_seen = set()
        parent_docs = []
        for child in child_docs:
            pid = child.get("metadata", {}).get("parent_id")
            if not pid or pid in parent_ids_seen:
                continue
            parent_ids_seen.add(pid)
            try:
                parent_data = self.parent_collection.get(ids=[pid])
                if parent_data and parent_data.get("documents"):
                    parent_docs.append({
                        "id": pid,
                        "content": parent_data["documents"][0],
                        "metadata": parent_data["metadatas"][0] if parent_data.get("metadatas") else {},
                        "score": child["score"],
                    })
            except Exception:
                continue
        return parent_docs