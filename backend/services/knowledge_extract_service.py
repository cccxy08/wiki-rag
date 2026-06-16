"""对知识周期性提取服务 — 按钉钉用户ID分组，LLM总结，写入沉淀审核队列"""
from __future__ import annotations
import json
import logging
from typing import Optional

from core.config import settings
from core.llm_provider import get_llm
from core.prompts import load

logger = logging.getLogger(__name__)


class KnowledgeExtractService:
    def __init__(self):
        self.llm = get_llm()

    def extract_from_conversations(self, user_id: str, conversations: list[dict]) -> list[dict]:
        """从单个用户的对话中提取知识碎片

        Args:
            user_id: 钉钉用户ID
            conversations: [{question, answer, timestamp}, ...]

        Returns:
            [{summary, content, source_conversations}, ...]
        """
        if not conversations:
            return []

        conv_text = "\n\n".join([
            f"Q{i+1}: {c.get('question', '')}\nA{i+1}: {c.get('answer', '')[:500]}"
            for i, c in enumerate(conversations)
        ])

        prompt = f"""从以下对话记录中提取有价值的知识碎片。

规则：
1. 只提取事实性、可复用的知识（制度、流程、规范、经验总结等）
2. 忽略寒暄、闲聊、纯疑问无结论的对话
3. 每条知识包含：标题（简短概括）、内容（完整描述）
4. 输出JSON数组，没有可提取的知识则输出 []
5. 不要编造，只从对话中提取

对话记录（用户ID: {user_id}）：
{conv_text}

输出格式：
[{{"title": "知识标题", "content": "知识内容"}}]
"""
        try:
            response = self.llm.chat([
                {"role": "system", "content": "你只输出JSON数组，不输出其他内容。"},
                {"role": "user", "content": prompt},
            ], label="knowledge_extract")

            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]

            knowledge_list = json.loads(cleaned)
            if not isinstance(knowledge_list, list):
                return []

            result = []
            for item in knowledge_list[:10]:
                if isinstance(item, dict) and item.get("title") and item.get("content"):
                    result.append({
                        "title": item["title"],
                        "content": item["content"],
                        "source_user_id": user_id,
                        "source_conversations": [c.get("question", "")[:100] for c in conversations[:5]],
                    })

            return result
        except Exception as e:
            logger.error(f"Knowledge extract error for user {user_id}: {e}")
            return []

    def extract_all(self) -> dict:
        """从所有用户对话中提取知识（由外部cron触发）"""
        from services.query_service import QueryService
        from services.precipitation_service import PrecipitationService
        from db.precipitation_db import PrecipitationDB
        from pathlib import Path

        qs = QueryService()
        all_sessions = qs._session_history
        if not all_sessions:
            logger.info("No conversation history found for knowledge extraction")
            return {"extracted_count": 0, "errors": []}

        db_path = Path(settings.wiki_data_dir) / "precipitation.db"
        precip_db = PrecipitationDB(db_path)
        precip_service = PrecipitationService(precip_db)

        extracted_count = 0
        errors = []
        max_users = settings.knowledge_extract_max_conversations

        for user_id, history in list(all_sessions.items())[:max_users]:
            if not history:
                continue

            try:
                knowledge_items = self.extract_from_conversations(user_id, history)
                for item in knowledge_items:
                    try:
                        precip_service.create_from_query(
                            question=item["title"],
                            answer=item["content"],
                            score=7,
                            source=f"extract:user:{user_id}",
                        )
                        extracted_count += 1
                    except Exception as e:
                        errors.append({"user": user_id, "title": item.get("title", ""), "error": str(e)[:100]})
            except Exception as e:
                errors.append({"user": user_id, "error": str(e)[:100]})

        logger.info(f"Knowledge extraction complete: {extracted_count} items, {len(errors)} errors")
        return {"extracted_count": extracted_count, "errors": errors}
