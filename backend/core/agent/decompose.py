class DecomposeMixin:
    def _run_decomposed(self, original_question: str, refined_query: str, parsed_q: str,
                         intent_data: dict, sub_queries: list[str], base: dict) -> dict:
        """Run with query decomposition: search each sub-question separately, then synthesize.
        
        For comparison/cross-doc questions, each sub-question gets its own lookup cycle
        (wiki BFS → RAG fallback). All collected context is then merged for the final answer.
        """
        collected_pages = {}
        all_source_pages = []
        collected_rag_context = []

        for sub_q in sub_queries:
            page_titles = self._find_initial_pages(sub_q, intent_data)

            if page_titles:
                answer, source_pages = self._iterative_lookup(sub_q, page_titles)
                all_source_pages.extend(source_pages)

                wiki = self._get_wiki()
                for title in source_pages:
                    if title not in collected_pages:
                        content = wiki.read_page(title)
                        if content:
                            collected_pages[title] = content
            else:
                rag = self._get_rag()
                docs = rag.retrieve(sub_q)
                if docs:
                    rag_context = "\n\n".join(
                        f"[来源: {d['metadata'].get('source', 'unknown')}]\n{d['content'][:1500]}"
                        for d in docs[:3]
                    )
                    collected_rag_context.append({"sub_question": sub_q, "context": rag_context})

        base["pages_consulted"] = list(dict.fromkeys(all_source_pages))

        all_context_parts = []
        if collected_pages:
            for title, content in collected_pages.items():
                all_context_parts.append(f"## {title}\n{content[:2500]}")
        for rag_item in collected_rag_context:
            all_context_parts.append(
                f"## (向量检索: {rag_item['sub_question']})\n{rag_item['context']}"
            )

        if all_context_parts:
            merged_pages = dict(collected_pages)
            for rag_item in collected_rag_context:
                pseudo_title = f"检索: {rag_item['sub_question']}"
                merged_pages[pseudo_title] = rag_item['context']

            answer = self._extract_answer_from_multi_pages(
                original_question, merged_pages, refined_query
            )
            if answer:
                source_pages = list(collected_pages.keys()) + [
                    f"RAG:{r['sub_question']}" for r in collected_rag_context
                ]
                return {
                    "answer": answer,
                    "source": "wiki+rag" if collected_rag_context else "wiki",
                    "source_pages": source_pages,
                    "sources": [],
                    "confidence": "high",
                    **base,
                }

        result = self._rag_fallback(refined_query, parsed_q, original_question=original_question)
        result.update(base)
        return result

    def _extract_answer_from_multi_pages(self, question: str, pages: dict[str, str],
                                          short_query: str) -> str:
        """Synthesize answer from multiple wiki pages. Handles comparison and cross-doc queries."""
        context_parts = []
        for title, content in pages.items():
            truncated = content[:2500] + ("\n...(内容过长已截断)" if len(content) > 2500 else "")
            context_parts.append(f"### {title}\n{truncated}")
        merged_context = "\n\n".join(context_parts)

        prompt = f"""基于以下多个 Wiki 页面内容回答用户问题。

规则：
1. 综合所有页面信息，不要只看单一页面
2. 比较类问题必须列出各方的具体数据，再做比较结论
3. 数值计算必须列出算式和计算过程，不要心算
4. 如果涉及多个人的信息，分别列出每个人的相关数据
5. 允许基于页面内容做合理推断
6. 如果内容中找不到相关信息，只回复 NO_ANSWER

页面内容：
{merged_context}

用户问题：{question}

请回答："""

        try:
            result = self.llm.chat([
                {"role": "system", "content": "你是企业知识库助手。综合多页面信息回答比较类和跨文档问题。必须列出数据来源和计算过程。"},
                {"role": "user", "content": prompt}
            ], label="extract")
            result = result.strip()
            if result.upper() == "NO_ANSWER" or "NO_ANSWER" in result[:20]:
                return ""
            return result
        except Exception:
            return ""