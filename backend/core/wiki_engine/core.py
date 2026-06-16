"""WikiEngine 查询 Mixin — LLM 驱动的页面选择与答案合成"""
from __future__ import annotations
from typing import Optional

from core.prompts import load


class WikiQueryMixin:
    def query(self, question: str, top_k: int = 5) -> dict:
        all_pages = self._list_pages()
        if not all_pages:
            return {"hit": False, "answer": "", "sources": []}

        selected = self._find_related_pages(question, top_k)
        if not selected:
            return {"hit": False, "answer": "", "sources": []}

        pages_content = {}
        sources = []
        for title in selected:
            content = self.read_page(title)
            if content:
                pages_content[title] = content
                sources.append(title)

        if not pages_content:
            return {"hit": False, "answer": "", "sources": sources}

        answer = self._answer_from_wiki(question, pages_content)
        return {"hit": True, "answer": answer, "sources": sources}

    def _find_related_pages(self, question: str, top_k: int = 5) -> list[str]:
        page_list_lines = []
        for fp in sorted(self._list_pages(), key=lambda f: f.stem):
            try:
                first_line = fp.read_text(encoding="utf-8").split("\n", 1)[0].lstrip("# ")[:100]
            except Exception:
                first_line = ""
            page_list_lines.append(f"- {fp.stem}: {first_line}")
        page_list = "\n".join(page_list_lines)

        prompt = load("wiki_find_pages.txt", top_k=top_k, page_list=page_list, question=question)

        try:
            raw = self.llm.chat([
                {"role": "system", "content": "你只返回相关页面名称，每行一个，不要其他内容。"},
                {"role": "user", "content": prompt}
            ], label="find_pages")
            titles = []
            for line in raw.strip().split("\n"):
                t = line.strip().lstrip("- *0123456789. #（）()")
                if t:
                    titles.append(t)
            return titles[:top_k]
        except Exception:
            return [fp.stem for fp in self._list_pages()[:top_k]]

    def _answer_from_wiki(self, question: str, pages: dict[str, str]) -> str:
        context_parts = []
        for title, content in pages.items():
            if len(content) > 3000:
                content = content[:3000] + "\n...(内容过长已截断)"
            context_parts.append(f"## {title}\n{content}")

        prompt = load("wiki_answer.txt", context="\n\n---\n\n".join(context_parts), question=question)

        try:
            return self.llm.chat([
                {"role": "system", "content": (
                    "你是企业知识库助手，只依据提供的 Wiki 内容回答。不确定就说不知道。\n\n"
                    "语义理解规则：用户可能用不同的词描述同一件事（如「负责人」=「主管」、"
                    "「做支付」=「参与支付系统」）。请结合上下文理解用户意图，不要因为用词"
                    "不完全一致就认为不匹配。"
                )},
                {"role": "user", "content": prompt}
            ], label="answer")
        except Exception:
            return "系统繁忙，请稍后重试。"