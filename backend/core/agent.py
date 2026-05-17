"""ReAct Agent - 自主决策调用 Wiki/RAG 引擎，实现知识复利闭环"""
import json
import hashlib
import re
import time
from typing import Callable, Optional

from core.config import settings
from core.llm_provider import get_llm


class Tool:
    """工具定义"""
    def __init__(self, name: str, description: str, func: Callable):
        self.name = name
        self.description = description
        self.func = func


class ReActAgent:
    """
    ReAct (Reasoning + Acting) Agent
    循环：Think → Act → Observe → Reflect → Answer

    内置工具：
    - wiki_search: 精确查询 Wiki 知识库
    - wiki_index: 浏览 Wiki 目录
    - rag_search: 语义检索原始文档
    - rag_retrieve: 从原始文档检索更多上下文
    - self_evaluate: 给当前答案打分
    - wiki_ingest: 将好答案沉淀到 Wiki
    """

    def __init__(self):
        self.llm = get_llm()
        self.tools: dict[str, Tool] = {}
        self.max_iterations = settings.agent_max_iterations

        # 懒加载的引擎引用（避免循环导入）
        self._wiki_engine = None
        self._rag_engine = None

    def _get_wiki(self):
        if self._wiki_engine is None:
            from core.wiki_engine import WikiEngine
            self._wiki_engine = WikiEngine()
        return self._wiki_engine

    def _get_rag(self):
        if self._rag_engine is None:
            from core.rag_engine import RAGEngine
            self._rag_engine = RAGEngine()
        return self._rag_engine

    def register_tool(self, name: str, description: str, func: Callable):
        """注册自定义工具"""
        self.tools[name] = Tool(name, description, func)

    def _ensure_builtin_tools(self):
        """确保内置 Wiki/RAG 工具已注册"""
        if "wiki_search" not in self.tools:
            self.register_tool(
                "wiki_search",
                "搜索 Wiki 知识库。参数: keyword（关键词）。返回匹配的 Wiki 页面内容。"
                "适用场景：精确查找已知的企业政策、流程、概念。",
                lambda kw: self._get_wiki().query(kw, top_k=3)["answer"]
            )
        if "wiki_index" not in self.tools:
            self.register_tool(
                "wiki_index",
                "查看 Wiki 知识库的目录索引。无参数。返回所有已沉淀条目的列表。"
                "适用场景：不确定关键词时先看目录，或在回答前确认有哪些可用知识。",
                lambda _="": self._get_wiki().get_index()
            )
        if "rag_search" not in self.tools:
            self.register_tool(
                "rag_search",
                "在原始文档中语义搜索。参数: query（查询语句）。返回最相关的文档摘要。"
                "适用场景：Wiki 中找不到时，从非结构化文档中检索信息。",
                lambda q: self._rag_answer(q)
            )
        if "self_evaluate" not in self.tools:
            self.register_tool(
                "self_evaluate",
                "评估当前草稿答案的质量（1-10分）。参数: draft（当前草稿答案）。返回分数和修改建议。"
                "适用场景：在自己提交最终答案前先自我检查。",
                lambda draft: self._self_evaluate(draft)
            )
        if "wiki_backlinks" not in self.tools:
            self.register_tool(
                "wiki_backlinks",
                "?? Wiki ??????????: page_name?????????????????????????: ?????????",
                lambda name: self._get_backlinks_info(name)
            )

    def _rag_answer(self, query: str) -> str:
        """RAG 检索 + 回答"""
        rag = self._get_rag()
        docs = rag.retrieve(query, top_k=5)
        if not docs:
            return "未检索到相关文档。"
        return rag.answer(query, docs)

    def _self_evaluate(self, draft: str) -> str:
        """LLM 自评"""
        prompt = f"""评估以下草稿答案的质量（1-10分），并给出简要的改进建议。

评估标准：
- 完整性：是否回答了问题？
- 准确性：是否有编造？
- 有用性：是否提供可操作的信息？

草稿答案：
{draft[:2000]}

请输出格式：
评分: X/10
改进建议: ...
"""
        return self.llm.chat([
            {"role": "system", "content": "你是严格的答案评估者。"},
            {"role": "user", "content": prompt}
        ])


    def _get_backlinks_info(self, page_name: str) -> str:
        """???????????? Agent ????"""
        wiki = self._get_wiki()
        bl = wiki.get_backlinks(page_name)
        if not bl:
            return f"????? {page_name} ??????"
        result = [f"## {page_name} ???\n"]
        incoming = bl.get("incoming", [])
        outgoing = bl.get("outgoing", [])
        if incoming:
            result.append("????????")
            for inc in incoming:
                result.append(f"  - {inc}")
        if outgoing:
            result.append("???????")
            for out in outgoing:
                result.append(f"  - {out}")
        if not incoming and not outgoing:
            result.append("?????")
        return "\n".join(result)
    def run(self, question: str) -> dict:
        """
        执行 ReAct 循环
        Returns: {
            "answer": str,
            "source": "wiki"|"rag"|"agent",
            "source_pages": [...],
            "sources": [...],
            "confidence": "high"|"medium"|"low",
            "iterations": int,
            "actions": [...],
            "ingested_to_wiki": bool,
        }
        """
        self._ensure_builtin_tools()
        tools_desc = self._build_tools_description()

        schema_context = ""
        try:
            from pathlib import Path
            sp = Path(settings.wiki_data_dir) / "WIKI-SCHEMA.md"
            if sp.exists():
                schema_context = sp.read_text(encoding="utf-8")[:3000]
        except Exception:
            pass



        system_msg = f"""{schema_context}你是一个企业知识库智能助手，具备 Wiki 精确检索和 RAG 语义搜索能力。

可用工具：
{tools_desc}

工作流程：
1. 先思考：这个问题更适合查 Wiki 还是 RAG？
2. 如果不知道有哪些 Wiki 条目，可以先调用 wiki_index 浏览目录
3. 先尝试 wiki_search（精确匹配快），未命中再用 rag_search 兜底
4. 获得信息后，整理答案
5. 如果答案还不完整，可以继续检索更多信息
6. 答案满意后，调用 self_evaluate 评估质量
7. 评分 ≥ {settings.agent_min_self_score} 时，建议沉淀到 Wiki
8. 最终输出 FINAL_ANSWER

输出格式：
- 要使用工具：ACTION: 工具名\nARGS: {{"args": "参数值"}}
- 要给出最终答案：FINAL_ANSWER: 完整答案内容

规则：
- 每次只执行一个 ACTION
- 最多 {self.max_iterations} 轮
- 只依据检索到的内容回答，不要编造
- 如果实在找不到信息，诚实说明
"""

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": question}
        ]

        actions_log = []

        for iteration in range(self.max_iterations):
            response = self.llm.chat(messages)
            messages.append({"role": "assistant", "content": response})

            # 检查最终答案
            final = self._parse_final_answer(response)
            if final:
                # 判断来源
                source = "wiki"
                for a in actions_log:
                    if a["action"] == "rag_search":
                        source = "rag"
                        break

                # 提取引用信息
                source_pages, doc_sources = self._extract_sources(actions_log)

                # 自评
                score = self._parse_self_score(actions_log)
                confidence = "high" if score >= 8 else "medium" if score >= 5 else "low"

                ingested = False
                if score >= settings.agent_min_self_score:
                    ingested = self._maybe_ingest(question, final, actions_log)

                return {
                    "answer": final,
                    "source": "agent" if actions_log else source,
                    "source_pages": source_pages,
                    "sources": doc_sources,
                    "confidence": confidence,
                    "iterations": iteration + 1,
                    "actions": actions_log,
                    "ingested_to_wiki": ingested,
                }

            # 解析并执行 ACTION
            action_name, action_args = self._parse_action(response)
            if action_name and action_name in self.tools:
                tool = self.tools[action_name]
                try:
                    result = self._execute_tool(tool, action_args)
                    actions_log.append({
                        "step": iteration + 1,
                        "action": action_name,
                        "args": str(action_args)[:200],
                        "result_preview": str(result)[:300],
                    })
                    messages.append({
                        "role": "user",
                        "content": f"工具 [{action_name}] 返回:\n{result[:3000]}"
                    })
                except Exception as e:
                    messages.append({
                        "role": "user",
                        "content": f"工具 [{action_name}] 执行失败: {e}"
                    })
            elif action_name:
                # ACTION 指令中写了不存在的工具名
                messages.append({
                    "role": "user",
                    "content": f"未知工具 '{action_name}'。可用工具: {', '.join(self.tools.keys())}"
                })
            else:
                # 无法解析
                messages.append({
                    "role": "user",
                    "content": (
                        "请使用 ACTION: <工具名>\nARGS: {{\"args\": \"参数\"}} 格式调用工具，"
                        "或使用 FINAL_ANSWER: <答案> 输出最终答案。"
                        f"可用工具: {', '.join(self.tools.keys())}"
                    )
                })

        # 超过最大迭代，强制总结
        force_prompt = "已达到最大尝试次数。请基于以上所有检索信息，给出最终答案。"
        messages.append({"role": "user", "content": force_prompt})
        final_response = self.llm.chat(messages)
        final = self._parse_final_answer(final_response) or final_response

        return {
            "answer": final,
            "source": "agent",
            "source_pages": [],
            "sources": [],
            "confidence": "low",
            "iterations": self.max_iterations,
            "actions": actions_log,
            "ingested_to_wiki": False,
        }

    def _maybe_ingest(self, question: str, answer: str, actions: list) -> bool:
        """决定是否将答案沉淀到 Wiki"""
        # 只沉淀 RAG 来源且质量高的答案（Wiki 已命中则不需要）
        used_rag = any(a["action"] == "rag_search" for a in actions)
        if not used_rag:
            return False

        cache_key = hashlib.md5(question.encode()).hexdigest()
        try:
            result = self._get_wiki().ingest(
                f"# 自动沉淀\n\n**问题**：{question}\n\n**答案**：{answer}",
                f"qa-{cache_key[:8]}.md"
            )
            return "error" not in result
        except Exception:
            return False

    def _extract_sources(self, actions: list) -> tuple[list, list]:
        """从 action log 中提取来源信息"""
        source_pages = []
        doc_sources = []
        for a in actions:
            if a["action"] == "wiki_search":
                source_pages.append(a.get("result_preview", "")[:100])
            elif a["action"] == "rag_search":
                doc_sources.append({"preview": a.get("result_preview", "")[:100]})
        return source_pages, doc_sources

    def _parse_self_score(self, actions: list) -> int:
        """从自评结果中提取分数"""
        for a in actions:
            if a["action"] == "self_evaluate":
                preview = a.get("result_preview", "")
                match = re.search(r"(\d+)/10", preview)
                if match:
                    return int(match.group(1))
        return 5  # 没自评就默认中等

    def _build_tools_description(self) -> str:
        """构建工具描述"""
        lines = []
        for name, tool in self.tools.items():
            lines.append(f"- {name}: {tool.description}")
        return "\n".join(lines)

    def _parse_action(self, text: str) -> tuple[Optional[str], str]:
        """解析 ACTION 指令"""
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

        # 也支持非 JSON 纯文本参数
        args_match = re.search(r"ARGS:\s*(.+?)(?:\n|ACTION:|FINAL_ANSWER:)", text, re.DOTALL)
        if args_match:
            return action_name, args_match.group(1).strip()

        return action_name, ""

    def _parse_final_answer(self, text: str) -> Optional[str]:
        """解析 FINAL_ANSWER"""
        match = re.search(r"FINAL_ANSWER:\s*(.+)", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _execute_tool(self, tool: Tool, args: str) -> str:
        """执行工具调用"""
        if isinstance(args, str) and args.strip():
            return tool.func(args)
        return tool.func()
