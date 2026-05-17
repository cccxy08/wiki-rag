"""检索增强：BM25 混合检索 + Rerank 重排序"""
from typing import Optional


class BM25Retriever:
    """BM25 关键词检索（基于 rank-bm25 库）"""

    def __init__(self, documents: list[str]):
        """
        Args:
            documents: 要建立索引的文档文本列表
        """
        self.documents = documents
        self._tokenized = [self._tokenize(doc) for doc in documents]
        self._bm25 = None
        self._build_index()

    def _tokenize(self, text: str) -> list[str]:
        """中文分词（简单按字+双字切分，实际可用 jieba）"""
        tokens = []
        # 按空格和标点切
        import re
        words = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+|[0-9]+", text.lower())
        for w in words:
            if len(w) <= 3:
                tokens.append(w)
            else:
                # 对长词做 2-gram 切分
                for i in range(len(w) - 1):
                    tokens.append(w[i:i+2])
        return tokens or [text[:10]]  # 兜底

    def _build_index(self):
        """构建 BM25 索引"""
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi(self._tokenized)
        except ImportError:
            self._bm25 = None  # 降级，BM25 不可用

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """
        搜索
        Returns: [(文档索引, 分数), ...]
        """
        if self._bm25 is None:
            return []
        tokenized_query = self._tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


def merge_results(
    vector_results: list[dict],
    bm25_results: list[tuple[int, float]],
    bm25_documents: list[str],
    bm25_weight: float = 0.3,
    top_k: int = 5,
) -> list[dict]:
    """
    合并向量检索和 BM25 结果
    - 向量权重 = 1 - bm25_weight
    - BM25 权重 = bm25_weight
    """
    if not bm25_results:
        return vector_results[:top_k]

    vector_weight = 1 - bm25_weight

    # 建立内容到向量的映射
    content_to_vector = {}
    for doc in vector_results:
        key = doc["content"][:100]
        content_to_vector[key] = doc

    # 合并分数
    merged_scores = {}
    for doc in vector_results:
        key = doc["content"][:100]
        merged_scores[key] = doc.get("score", 0) * vector_weight

    for idx, score in bm25_results:
        content = bm25_documents[idx][:100]
        if content in merged_scores:
            merged_scores[content] += score * bm25_weight
        else:
            merged_scores[content] = score * bm25_weight

    # 排序
    sorted_keys = sorted(merged_scores, key=merged_scores.get, reverse=True)[:top_k]

    results = []
    for key in sorted_keys:
        if key in content_to_vector:
            results.append(content_to_vector[key])
        else:
            results.append({"content": key, "score": merged_scores[key], "metadata": {}})

    return results


class Reranker:
    """Rerank 重排序器"""

    def __init__(self):
        self._reranker = None
        self._init_model()

    def _init_model(self):
        """初始化 Rerank 模型"""
        try:
            from FlagEmbedding import FlagReranker
            self._reranker = FlagReranker(
                "BAAI/bge-reranker-base",
                use_fp16=True,
            )
        except ImportError:
            self._reranker = None

    @property
    def available(self) -> bool:
        return self._reranker is not None

    def rerank(self, query: str, documents: list[dict], top_k: int = 3) -> list[dict]:
        """
        对检索结果重排序
        Args:
            query: 用户查询
            documents: 粗排结果
            top_k: 返回 Top-K
        Returns: 重新排序后的文档列表
        """
        if not self.available or len(documents) <= 1:
            return documents[:top_k]

        # 构造 (query, doc) 对
        pairs = [[query, doc["content"][:500]] for doc in documents]

        try:
            scores = self._reranker.compute_score(pairs, normalize=True)
            # 单个结果时 scores 是标量
            if not isinstance(scores, list):
                scores = [scores]

            # 附上分数并排序
            for i, doc in enumerate(documents):
                doc["rerank_score"] = float(scores[i]) if i < len(scores) else 0.0

            sorted_docs = sorted(
                documents, key=lambda x: x.get("rerank_score", 0), reverse=True
            )
            return sorted_docs[:top_k]

        except Exception:
            return documents[:top_k]
