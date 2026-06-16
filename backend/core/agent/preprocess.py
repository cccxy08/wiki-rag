import re
import json
from typing import Optional

from core.prompts import load


class PreprocessMixin:
    def _preprocess_query(self, question: str) -> tuple[str, str, dict | None, list[str]]:
        """Preprocess query: one LLM call outputs refined query, intent JSON, and sub-questions.
        Returns (refined_query, parsed_question_display, intent_data, sub_queries).
        sub_queries = list of decomposed sub-questions (empty for simple queries).
        """
        clean = question.strip()

        prompt = load("agent_preprocess.txt", question=clean)
        try:
            result = self.llm.chat([
                {"role": "system", "content": "你只按格式返回三部分内容，用 ===INTENT=== 和 ===SUBS=== 分隔，不返回其他内容。\ntarget 字段必须用最简洁的词概括用户想找的信息类型（如\"姓名\"\"日期\"\"金额\"\"人数\"\"职位\"），不要从问题中直接复制词语，也不要推测问题中没有的信息。"},
                {"role": "user", "content": prompt}
            ], label="preprocess")
        except Exception:
            return clean, clean, None, []

        subs_parts = result.split("===SUBS===", 1)
        intent_and_query = subs_parts[0]
        subs_str = subs_parts[1].strip() if len(subs_parts) > 1 else "[]"

        parts = intent_and_query.split("===INTENT===", 1)

        short_part = parts[0].strip() if parts else ""
        short_query = short_part
        for prefix in ["精简查询：", "精简查询:", "核心查询：", "核心查询:"]:
            if short_query.startswith(prefix):
                short_query = short_query[len(prefix):].strip()
                break
        if not short_query:
            short_query = clean

        intent_data = None
        if len(parts) > 1:
            json_part = parts[1].strip()
            if json_part.startswith("```"):
                json_part = re.sub(r"^```(?:json)?\s*", "", json_part)
                json_part = re.sub(r"\s*```$", "", json_part)
            try:
                parsed = json.loads(json_part)
                intent_data = parsed
            except (json.JSONDecodeError, Exception):
                parsed = {"intent": "fact_query", "entities": [], "target": ""}
        else:
            parsed = {"intent": "fact_query", "entities": [], "target": ""}

        sub_queries = []
        try:
            subs_clean = subs_str.strip()
            if subs_clean.startswith("```"):
                subs_clean = re.sub(r"^```(?:json)?\s*", "", subs_clean)
                subs_clean = re.sub(r"\s*```$", "", subs_clean)
            subs_parsed = json.loads(subs_clean)
            if isinstance(subs_parsed, list):
                sub_queries = [s.strip() for s in subs_parsed if isinstance(s, str) and s.strip()]
        except (json.JSONDecodeError, Exception):
            pass

        refined_query = short_query
        parsed_question = self._format_intent(parsed, refined_query)

        return refined_query, parsed_question, intent_data, sub_queries

    def _format_intent(self, parsed: dict, refined_query: str) -> str:
        """Format intent analysis JSON as a readable display string."""
        intent_map = {
            "comparison": "比较",
            "fact_query": "事实查询",
            "fuzzy_search": "模糊搜索",
            "statistics": "统计",
        }
        intent_label = intent_map.get(parsed.get("intent", ""), parsed.get("intent", "事实查询"))
        entities = parsed.get("entities", [])
        target = parsed.get("target", "")

        entities_str = ", ".join(entities) if entities else "无"

        if entities and target:
            if parsed.get("intent") == "comparison" and len(entities) >= 2:
                summary = f"比较{entities[0]}与{entities[1]}的{target}"
            else:
                summary = f"{entities_str}的{target}"
        else:
            summary = refined_query

        return f"意图: {intent_label} | 实体: {entities_str} → {summary}"