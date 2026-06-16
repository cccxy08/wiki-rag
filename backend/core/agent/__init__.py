"""Agent - Karpathy LLM Wiki iterative lookup pattern. 
Knowledge compound interest via structured wiki navigation.
"""
import re
from typing import Optional

from core.config import settings
from core.llm_provider import get_llm

from core.agent.preprocess import PreprocessMixin
from core.agent.react import ReactMixin
from core.agent.decompose import DecomposeMixin
from core.agent.core import CoreMixin


def _safe_eval(expr: str) -> Optional[float]:
    """安全计算简单算术表达式，只允许数字和+-*/()."""
    if not expr or not re.match(r'^[\d+\-*/().\s%]+$', expr.strip()):
        return None
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        if isinstance(result, (int, float)):
            return float(result)
    except Exception:
        pass
    return None


class ReActAgent(PreprocessMixin, ReactMixin, DecomposeMixin, CoreMixin):
    """
    Karpathy LLM Wiki iterative lookup agent.
    
    Modes:
    - run():          wiki BFS → RAG fallback
    - run_wiki_only(): wiki BFS only, no RAG
    - run_with_tools(): ReAct-style with wiki_search/rag_search/wiki_backlinks tools
    """

    def __init__(self):
        self.llm = get_llm()
        self.max_hops = 3

        self._wiki_engine = None
        self._rag_engine = None

    def _get_wiki(self):
        if self._wiki_engine is None:
            from core.wiki_engine import WikiEngine
            self._wiki_engine = WikiEngine.get_instance()
        return self._wiki_engine

    def _get_rag(self):
        if self._rag_engine is None:
            from core.rag_engine import RAGEngine
            self._rag_engine = RAGEngine.get_instance()
        return self._rag_engine