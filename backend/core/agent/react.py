import re
import json
from typing import Optional

from core.prompts import load


class ReactMixin:
    def run_with_tools(self, question: str) -> dict:
        """ReAct-style agent with wiki_search, wiki_backlinks, rag_search tools.

        LLM decides which tools to use and when to output FINAL_ANSWER.
        Returns {
            "answer": str,
            "source": "wiki" | "rag" | "agent",
            "source_pages": [str],
            "sources": [dict],
            "confidence": "high" | "medium" | "low",
        }
        """
        tools_desc = (
            "- wiki_search: 搜索 Wiki 知识库。参数: keyword（关键词）。返回匹配的 Wiki 页面内容。\n"
            "- wiki_backlinks: 查看某 Wiki 页面的引用关系。参数: page_name（页面名称）。返回引用和被引列表。\n"
            "- rag_search: 在原始文档中语义搜索。参数: query（查询语句）。返回最相关的文档摘要。"
        )

        system_msg = load("agent_tools_system.txt", tools_desc=tools_desc)

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": question},
        ]

        actions_log = []
        used_rag = False
        source_pages = []

        for iteration in range(10):
            response = self.llm.chat(messages, label="agent_step")
            messages.append({"role": "assistant", "content": response})

            final = self._parse_final_answer(response)
            if final:
                source = "rag" if used_rag else "wiki"
                return {
                    "answer": final,
                    "source": source,
                    "source_pages": source_pages,
                    "sources": [],
                    "confidence": "high" if source_pages else "medium",
                }

            action_name, action_args = self._parse_action(response)
            if not action_name:
                messages.append({
                    "role": "user",
                    "content": '请使用 ACTION: <工具名>\nARGS: {"args": "参数"} 格式调用工具，或使用 FINAL_ANSWER: <答案> 输出最终答案。'
                })
                continue

            result = self._execute_tool_action(action_name, action_args)
            used_rag = used_rag or (action_name == "rag_search")
            if action_name == "wiki_search" and result and result != "未找到相关信息。":
                source_pages.append(action_args)

            actions_log.append({
                "step": iteration + 1,
                "action": action_name,
                "args": str(action_args)[:200],
            })
            messages.append({
                "role": "user",
                "content": f"工具 [{action_name}] 返回:\n{result[:3000]}"
            })

        force_prompt = "已达到最大尝试次数。请基于以上所有检索信息，给出最终答案。"
        messages.append({"role": "user", "content": force_prompt})
        final_response = self.llm.chat(messages, label="answer")
        final = self._parse_final_answer(final_response) or final_response

        source = "rag" if used_rag else ("wiki" if source_pages else "agent")
        return {
            "answer": final,
            "source": source,
            "source_pages": source_pages,
            "sources": [],
            "confidence": "low",
        }

    def _parse_final_answer(self, text: str) -> Optional[str]:
        """Parse FINAL_ANSWER from agent response."""
        match = re.search(r"FINAL_ANSWER:\s*(.+)", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _parse_action(self, text: str) -> tuple[Optional[str], str]:
        """Parse ACTION/ARGS from agent response."""
        action_match = re.search(r"ACTION:\s*(\w+)", text)
        if not action_match:
            return None, ""
        action_name = action_match.group(1)

        args_match = re.search(r"ARGS:\s*(\{[^}]+\})", text, re.DOTALL)
        if args_match:
            try:
                parsed = json.loads(args_match.group(1))
                return action_name, parsed.get("args", args_match.group(1))
            except json.JSONDecodeError:
                return action_name, args_match.group(1)

        args_match = re.search(r"ARGS:\s*(.+?)(?:\n|ACTION:|FINAL_ANSWER:)", text, re.DOTALL)
        if args_match:
            return action_name, args_match.group(1).strip()
        return action_name, ""

    def _execute_tool_action(self, action_name: str, args: str) -> str:
        """Execute a ReAct tool action."""
        try:
            if action_name == "wiki_search":
                wiki = self._get_wiki()
                result = wiki.query(args, top_k=3)
                if result.get("hit"):
                    return result["answer"]
                return "未找到相关信息。"
            elif action_name == "wiki_backlinks":
                wiki = self._get_wiki()
                bl = wiki.get_backlinks(args)
                parts = [f"## {args} 的引用关系"]
                if bl.get("incoming"):
                    parts.append("被以下页面引用：" + ", ".join(bl["incoming"]))
                if bl.get("outgoing"):
                    parts.append("引用了以下页面：" + ", ".join(bl["outgoing"]))
                if not bl.get("incoming") and not bl.get("outgoing"):
                    parts.append("无引用关系")
                return "\n".join(parts)
            elif action_name == "rag_search":
                rag = self._get_rag()
                docs = rag.retrieve(args, top_k=5)
                if not docs:
                    return "未检索到相关文档。"
                return rag.answer(args, docs)
            else:
                return f"未知工具: {action_name}"
        except Exception as e:
            return f"工具执行失败: {e}"