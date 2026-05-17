"""查询服务 - Wiki 优先 + RAG 兜底 + 知识复利"""
import hashlib
import time
from typing import Optional

from core.config import settings
from core.wiki_engine import WikiEngine
from core.rag_engine import RAGEngine
from core.llm_provider import get_llm, FALLBACK_MESSAGE


class QueryService:
    """知识查询服务"""

    def __init__(self):
        self.wiki = WikiEngine()
        self.rag = RAGEngine()
        self.llm = get_llm()
        self._query_cache: dict[str, dict] = {}
        self._score_cache: dict[str, int] = {}
        self._session_history: dict[str, list[dict]] = {}  # session_id -> [{question, answer}, ...]
        self._max_history = settings.max_history_rounds
        self._cache_stats = {"query_hits": 0, "query_misses": 0, "score_hits": 0, "score_misses": 0}

    def query(self, question: str, top_k: int = 5, session_id: str = None) -> dict:
        """
        查询流程：
        1. 先查缓存
        2. 查 Wiki
        3. Wiki 命中 → 回答
        4. Wiki 未命中 → RAG 兜底
        5. RAG 回答好 → 自动存档 Wiki（知识复利）
        """
        # 1. 缓存检查
        cache_key = hashlib.md5(question.encode()).hexdigest()
        cached = self._check_cache(cache_key)
        if cached:
            cached["cached"] = True
            return cached

        # 2. Wiki 查询
        session_context = self._get_session_context(session_id) if session_id else ""
        try:
            wiki_result = self.wiki.query(question, top_k)
            wiki_hit = wiki_result.get("hit", False)
        except (AttributeError, NotImplementedError):
            wiki_hit = False
            wiki_result = {}

        if wiki_hit:
            answer = wiki_result["answer"]
            result = {
                "answer": answer,
                "source": "wiki",
                "source_pages": wiki_result["sources"],
                "sources": [],
                "confidence": "high",
                "cached": False,
            }
            self._update_cache(cache_key, result)
            return result

        # 3. RAG 兜底
        # 3.1 Query 改写
        rewritten_query = self._rewrite_query(question)
        # 3.2 检索
        docs = self.rag.retrieve(rewritten_query, top_k)
        # 3.3 回答
        answer = self.rag.answer(question, docs)

        # 3.4 评估答案质量
        score = self._evaluate_answer(question, answer)
        confidence = "high" if score >= 8 else "medium" if score >= 5 else "low"

        # 3.5 知识复利：好答案存档
        if score >= settings.agent_min_self_score:
            try:
                self.wiki.ingest(
                    f"问题：{question}\n\n答案：{answer}",
                    f"qa-{cache_key[:8]}.md"
                )
            except (AttributeError, NotImplementedError):
                pass  # WikiEngine 尚未完整实现，跳过知识复利

        sources = [
            {"file": doc["metadata"].get("source", "unknown"), "score": doc.get("score", 0)}
            for doc in docs[:3]
        ]

        result = {
            "answer": answer,
            "source": "rag",
            "source_pages": [],
            "sources": sources,
            "confidence": confidence,
            "cached": False,
        }

        self._update_cache(cache_key, result)
        if session_id:
            self._save_to_session(session_id, question, result["answer"])
        return result

    def _rewrite_query(self, question: str) -> str:
        """Query 改写：补充关键词"""
        prompt = f"""将以下用户问题改写为更适合检索的关键词组合。保留原意，补充相关术语和同义词，去除口语化表达。

原始问题：{question}

改写为关键词（逗号分隔）：
"""
        try:
            rewritten = self.llm.chat([
                {"role": "system", "content": "你只输出关键词，不输出其他内容。"},
                {"role": "user", "content": prompt}
            ])
            # 合并原问题 + 改写关键词
            return f"{question} {rewritten.strip()}"
        except Exception:
            return question

    def _evaluate_answer(self, question: str, answer: str) -> int:
        """答案质量评估"""
        # 先查评分缓存
        cache_key = hashlib.md5((question + answer).encode()).hexdigest()
        if cache_key in self._score_cache:
            self._cache_stats["score_hits"] += 1
            return self._score_cache[cache_key]

        prompt = f"""请对以下问答进行质量评估，给出 1-10 分。

评估标准：
- 是否完整回答了问题（0-4 分）
- 是否有充分的资料来源支撑（0-3 分）
- 是否有编造或推测的内容（有则扣 0-3 分）

问题：{question}
答案：{answer}

请只回复一个数字（1-10），不要其他内容。
"""
        try:
            response = self.llm.chat([
                {"role": "system", "content": "你只输出一个 1-10 的数字。"},
                {"role": "user", "content": prompt}
            ])
            score = int(response.strip())
            score = max(1, min(10, score))
            self._score_cache[cache_key] = score
            return score
        except Exception:
            return 5  # 默认中等分

    def _check_cache(self, key: str) -> Optional[dict]:
        """检查查询缓存"""
        if key in self._query_cache:
            entry = self._query_cache[key]
            if time.time() - entry["_ts"] < settings.query_cache_ttl_seconds:
                self._cache_stats["query_hits"] += 1
                return entry["data"]
        return None

    def _update_cache(self, key: str, data: dict):
        """更新查询缓存（失败/降级回复不入缓存）"""
        answer = data.get("answer", "")
        # 降级回复不缓存（避免后续查询命中失败缓存）
        if answer == FALLBACK_MESSAGE:
            return
        # 明确的无结果回复也不缓存
        if answer.strip() in ("未找到相关文档，无法回答此问题。",):
            return
        self._query_cache[key] = {
            "data": data,
            "_ts": time.time(),
        }

    def agent_query(self, question: str) -> dict:
        """
        通过 ReAct Agent 执行查询（自主决策式）
        Agent 会自己决定查 Wiki 还是 RAG、是否自评、是否沉淀。
        """
        from core.agent import ReActAgent
        agent = ReActAgent()
        return agent.run(question)


    def _get_session_context(self, session_id: str) -> str:
        """Get recent conversation context for a session"""
        if not session_id or session_id not in self._session_history:
            return ""
        history = self._session_history[session_id][-self._max_history:]
        if not history:
            return ""
        lines = ["Previous conversation:"]
        for h in history:
            lines.append(f"Q: {h['question'][:200]}")
            lines.append(f"A: {h['answer'][:200]}")
        return "\n".join(lines)

    def _save_to_session(self, session_id: str, question: str, answer: str):
        """Save Q&A to session history"""
        if not session_id:
            return
        if session_id not in self._session_history:
            self._session_history[session_id] = []
        self._session_history[session_id].append({"question": question, "answer": answer[:500]})
        # Trim to max
        if len(self._session_history[session_id]) > self._max_history:
            self._session_history[session_id] = self._session_history[session_id][-self._max_history:]

    def query_with_mode(self, question: str, mode: str = "auto", top_k: int = 5, session_id: str = None) -> dict:
        """
        统一查询入口，支持三种模式：
        - auto: 自动选择（问题短直接用 Wiki，问题长用 Agent）
        - pipeline: 固定流水线（Wiki→RAG）
        - agent: ReAct Agent 自主决策
        """
        if mode == "agent":
            return self.agent_query(question)
        elif mode == "pipeline":
            return self.query(question, top_k, session_id)
        else:  # auto: Wiki 优先 → RAG 兜底 → 好答案回写
            result = self.query(question, top_k, session_id)
            if result["source"] == "wiki":
                return result
            # RAG 兜底
            result = self.query(question, top_k, session_id)
            return result

    def get_cache_stats(self) -> dict:
        """获取缓存命中统计"""
        total_q = self._cache_stats["query_hits"] + self._cache_stats["query_misses"]
        total_s = self._cache_stats["score_hits"] + self._cache_stats["score_misses"]
        return {
            "query_cache": {
                "hits": self._cache_stats["query_hits"],
                "misses": self._cache_stats["query_misses"],
                "hit_rate": round(self._cache_stats["query_hits"] / max(total_q, 1), 3),
                "size": len(self._query_cache),
            },
            "score_cache": {
                "hits": self._cache_stats["score_hits"],
                "misses": self._cache_stats["score_misses"],
                "hit_rate": round(self._cache_stats["score_hits"] / max(total_s, 1), 3),
                "size": len(self._score_cache),
            },
        }
