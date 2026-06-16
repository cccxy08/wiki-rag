import re

from core.prompts import load


class CoreMixin:
    def run(self, question: str) -> dict:
        """
        Execute Karpathy LLM Wiki iterative lookup.

        Returns:
        {
            "answer": str,
            "source": "wiki" | "rag",
            "source_pages": [str],
            "sources": [dict],
            "confidence": "high" | "medium" | "low",
            "parsed_question": str,
            "pages_consulted": [str],
        }
        """
        refined_query, parsed_q, intent_data, sub_queries = self._preprocess_query(question)

        base = {"parsed_question": parsed_q, "pages_consulted": []}

        if sub_queries:
            return self._run_decomposed(question, refined_query, parsed_q, intent_data, sub_queries, base)

        page_titles = self._find_initial_pages(refined_query, intent_data)

        if not page_titles:
            result = self._rag_fallback(refined_query, parsed_q, original_question=question)
            result.update(base)
            return result

        answer, source_pages = self._iterative_lookup(refined_query, page_titles)
        base["pages_consulted"] = source_pages

        if answer and not self._is_no_answer(answer):
            if not self._answer_addresses_question(answer, question):
                pass
            else:
                result = {
                    "answer": answer,
                    "source": "wiki",
                    "source_pages": source_pages,
                    "sources": [],
                    "confidence": "high",
                }
                result.update(base)
                return result

        result = self._rag_fallback(refined_query, parsed_q, original_question=question)
        result.update(base)

        if result.get("source") == "rag" and result.get("confidence") in ("high", "medium"):
            record_id = self._maybe_persist_to_wiki(question, result)
            if record_id:
                result["precipitation_record_id"] = record_id

        return result

    def run_wiki_only(self, question: str) -> dict:
        """Wiki-only BFS lookup, no RAG fallback.

        Returns:
        {
            "answer": str (empty string if not found),
            "source": "wiki",
            "source_pages": [str],
            "sources": [],
            "confidence": "high" | "low",
            "parsed_question": str,
            "pages_consulted": [str],
        }
        """
        refined_query, parsed_q, intent_data, _sub_queries = self._preprocess_query(question)
        page_titles = self._find_initial_pages(refined_query, intent_data)

        base = {"parsed_question": parsed_q, "pages_consulted": []}

        if not page_titles:
            result = {
                "answer": "",
                "source": "wiki",
                "source_pages": [],
                "sources": [],
                "confidence": "low",
            }
            result.update(base)
            return result

        answer, source_pages = self._iterative_lookup(refined_query, page_titles)
        base["pages_consulted"] = source_pages

        result = {
            "answer": answer if answer else "",
            "source": "wiki",
            "source_pages": source_pages,
            "sources": [],
            "confidence": "high" if answer else "low",
        }
        result.update(base)
        return result

    def _iterative_lookup(self, short_query: str, page_titles: list[str]) -> tuple[str, list[str]]:
        """BFS through wiki pages, expanding via [[links]]. Max 3 hops.
        Returns (answer, source_pages) or ("", []).
        """
        wiki = self._get_wiki()
        visited = set()
        queue = list(page_titles)
        hops = 0
        source_pages = []

        while queue and hops < self.max_hops:
            page = queue.pop(0)
            if page in visited:
                continue
            visited.add(page)
            hops += 1

            content = wiki.read_page(page)
            if not content:
                continue

            answer = self._extract_answer_from_page(page, content, short_query)
            if answer:
                source_pages.append(page)
                return answer, source_pages

            source_pages.append(page)

            links = self._extract_links(content)
            for link in links:
                if link not in visited and link not in queue:
                    queue.append(link)

        return "", source_pages

    def _extract_answer_from_page(self, page_title: str, content: str, short_query: str) -> str:
        """Ask LLM: does this page contain the answer to short_query? Extract if yes."""
        if len(content) > 3000:
            content = content[:3000] + "\n...(内容过长已截断)"

        prompt = load("agent_extract.txt", page_title=page_title, content=content, short_query=short_query)
        try:
            result = self.llm.chat([
                {"role": "system", "content": "你是企业知识库助手，只依据提供的 Wiki 内容回答。如果内容中找不到相关信息，只回复 NO_ANSWER。\n重要规则：如果回答涉及数值计算（比较大小、求差值、百分比等），必须列出计算过程和算式，不要心算。"},
                {"role": "user", "content": prompt}
            ], label="extract")
            result = result.strip()
            if result.upper() == "NO_ANSWER" or "NO_ANSWER" in result[:20]:
                return ""
            return result
        except Exception:
            return ""

    def _extract_links(self, content: str) -> list[str]:
        """Extract [[page name]] references from wiki page content."""
        clean = re.sub(r"```[\s\S]*?```", "", content)
        clean = re.sub(r"`[^`]+`", "", clean)
        links = re.findall(r"\[\[(.+?)\]\]", clean)
        seen = set()
        result = []
        for link in links:
            if link not in seen:
                seen.add(link)
                result.append(link)
        return result

    def _rag_fallback(self, short_query: str, parsed_question: str = None, original_question: str = None) -> dict:
        """RAG fallback when wiki doesn't have the answer.
        
        Uses original_question (if provided) for retrieval and answering,
        because short_query may lose critical info (e.g. '负责人' stripped from 'AIGC事业群负责人').
        """
        retrieve_query = original_question if original_question else short_query
        answer_question = original_question if original_question else short_query

        rag = self._get_rag()
        try:
            docs = rag.retrieve(retrieve_query, top_k=5)
        except Exception:
            docs = []

        display_q = parsed_question if parsed_question else short_query
        base = {"parsed_question": display_q, "pages_consulted": []}

        if not docs:
            result = {
                "answer": "未在 Wiki 和文档库中找到相关信息。",
                "source": "rag",
                "source_pages": [],
                "sources": [],
                "confidence": "low",
            }
            result.update(base)
            return result

        try:
            answer = rag.answer(answer_question, docs)
        except Exception:
            answer = "系统繁忙，请稍后重试。"

        sources = [
            {"file": d.get("metadata", {}).get("source", "unknown"), "score": d.get("score", 0)}
            for d in docs[:3]
        ]

        result = {
            "answer": answer,
            "source": "rag",
            "source_pages": [],
            "sources": sources,
            "confidence": "medium",
        }
        result.update(base)
        return result

    def _maybe_persist_to_wiki(self, question: str, result: dict):
        """Create precipitation record for high-quality RAG answers.
        
        No longer auto-writes to Wiki. Instead creates a pending_confirm record
        that requires user confirmation + admin review before writing.
        """
        answer = result.get("answer", "")
        if not answer or answer == "未在 Wiki 和文档库中找到相关信息。":
            return
        if self._is_no_answer(answer):
            return

        try:
            from services.precipitation_service import PrecipitationService
            from db.precipitation_db import PrecipitationDB
            from pathlib import Path
            from core.config import settings
            db_path = Path(settings.wiki_data_dir) / "precipitation.db"
            precip_db = PrecipitationDB(db_path)
            precip_service = PrecipitationService(precip_db)
            source_files = [s.get("file", "unknown") for s in result.get("sources", [])]
            sources_str = ", ".join(source_files) if source_files else "rag"
            record_id = precip_service.create_from_query(question, answer, 7, sources_str)
            return record_id
        except Exception:
            return None

    _NO_ANSWER_PATTERNS = [
        "NO_ANSWER",
        "未找到",
        "未在.*找到",
        "无法确定",
        "无法比较",
        "无法回答",
        "未明确提及",
        "内容中未",
        "没有提供",
        "没有提及",
        "无法提供",
        "无法进行",
        "信息不足",
        "无法得知",
        "无法确认",
    ]

    def _is_no_answer(self, answer: str) -> bool:
        """Check if the LLM's answer is essentially a 'not found' response."""
        if not answer or not answer.strip():
            return True
        stripped = answer.strip()
        if len(stripped) < 10:
            return True
        for pattern in self._NO_ANSWER_PATTERNS:
            if re.search(pattern, stripped):
                return True
        return False

    def _answer_addresses_question(self, answer: str, question: str) -> bool:
        """Check if the wiki answer actually addresses the original question.
        
        Catches cases like: question='AIGC事业群的负责人是谁' but answer='AIGC是人工智能生成内容...'
        Uses lightweight heuristic: if the question asks 'who/谁' and the answer
        contains no person names, it's likely off-topic.
        """
        import re as _re
        asks_who = bool(_re.search(r'谁|负责人|主管|领导|经理|担任', question))
        asks_when = bool(_re.search(r'什么时候|何时|哪年|日期|时间', question))
        asks_howmuch = bool(_re.search(r'多少|几|金额|数额|费用|预算|经费|收入|营收', question))

        if asks_who:
            clean = _re.sub(r'<[^>]+>', '', answer)
            has_name = bool(_re.search(r'[\u4e00-\u9fff]{2,4}(?=（|\(|，|是|为|的|兼|担任|负责)', clean))
            if not has_name:
                return False

        if asks_when:
            clean = _re.sub(r'<[^>]+>', '', answer)
            has_date = bool(_re.search(r'\d{4}年|\d{4}-\d{2}-\d{2}|\d{4}\.\d{1,2}\.\d{1,2}', clean))
            if not has_date:
                return False

        if asks_howmuch:
            clean = _re.sub(r'<[^>]+>', '', answer)
            has_number = bool(_re.search(r'\d+[.\d]*万|\d+[.\d]*亿|\d+[.\d]*元|\d+[.\d]*%', clean))
            if not has_number:
                return False

        return True

    def _find_initial_pages(self, short_query: str, intent_data: dict = None) -> list[str]:
        """Read wiki index and let LLM select 1-3 most relevant page titles.
        If intent_data is provided, appends intent context to selection prompt.
        """
        wiki = self._get_wiki()
        try:
            index_content = wiki.get_index()
        except Exception:
            return []

        if not index_content or index_content.strip() == "":
            return []

        all_paths = wiki._list_pages()
        if not all_paths:
            return []

        page_lines = []
        for fp in sorted(all_paths, key=lambda f: f.stem):
            name = fp.stem
            tags = wiki.get_page_tags(name)
            tag_str = f" (tags: {', '.join(tags)})" if tags else ""
            page_lines.append(f"- {name}{tag_str}")
        page_list = "\n".join(page_lines)

        if intent_data and intent_data.get('intent') == 'comparison':
            comparison_suffix = "，确保覆盖比较的双方"
            comparison_hint = "如果是比较类问题，请确保同时选到参与比较的两个实体的相关页面。"
            max_pages = "2-4"
        else:
            comparison_suffix = ""
            comparison_hint = ""
            max_pages = "1-3"

        intent_context = ""
        if intent_data:
            intent_label = intent_data.get("intent", "")
            target_info = intent_data.get("target", "")
            intent_context = f"\n意图类型：{intent_label}，目标信息：{target_info}。请优先选择包含这些信息的页面。"

        prompt = load("agent_find_pages.txt",
            max_pages=max_pages,
            comparison_suffix=comparison_suffix,
            intent_context=intent_context,
            page_list=page_list,
            short_query=short_query,
            comparison_hint=comparison_hint,
        )
        try:
            raw = self.llm.chat([
                {"role": "system", "content": "你只返回相关页面名称，每行一个，最多 3 个。不要其他内容。"},
                {"role": "user", "content": prompt}
            ], label="find_pages")
            titles = []
            all_names = {fp.stem for fp in all_paths}
            for line in raw.strip().split("\n"):
                t = line.strip().lstrip("- *0123456789. #（）()")
                if t and t in all_names:
                    titles.append(t)
            return titles[:3]
        except Exception:
            return []