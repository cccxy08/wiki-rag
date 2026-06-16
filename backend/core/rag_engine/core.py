"""RAGEngine 核心问答 — 基于检索结果生成回答"""
from __future__ import annotations
from core.config import settings


class CoreMixin:
    def answer(self, question: str, context_docs: list[dict]) -> str:
        if not context_docs:
            return "未找到相关文档，无法回答此问题。"

        context_text = "\n\n---\n\n".join([
            f"[来源: {doc['metadata'].get('source', 'unknown')}]\n{doc['content']}"
            for doc in context_docs[:settings.rerank_top_k]
        ])

        prompt = f"""你是一个企业知识库助手。请根据以下检索到的文档内容回答用户问题。

## 输出格式要求（严格遵守）

回答必须是 **纯 HTML 片段**（不含 html/body/head 标签），渲染美观，结构清晰。

### HTML 结构模板

```html
<div class="rag-answer">
  <div class="rag-section">
    <span class="rag-label">结论</span>
    <span class="rag-content"><strong>结论内容加粗</strong></span>
  </div>
  <div class="rag-section">
    <span class="rag-label">依据</span>
    <ul class="rag-list">
      <li><span class="rag-source">文档名称</span>：原文摘要</li>
    </ul>
  </div>
  <div class="rag-section">
    <span class="rag-label">补充</span>
    <span class="rag-content">额外上下文</span>
  </div>
  <div class="rag-section rag-footer">
    <span class="rag-label">来源</span>
    <span class="rag-content">文件1、文件2</span>
  </div>
</div>
```

### 规则
1. 只依据提供的文档内容回答，不要编造
2. **语义匹配**：用户用词可能不是文档中的精确用词（如"老板"可能对应文档中的"董事长/创始人/CEO"），请根据语义理解匹配，不要因为用词不同就判定"未找到"
3. 如果确实找不到相关信息，返回：<div class="rag-answer">未在文档中找到相关信息。</div>（仅在检索到的所有文档确实都不包含任何相关内容时才返回）
4. 关键数字/名称用 <strong> 加粗
5. 每个依据项标注来源文档名称
6. <span class="rag-source"> 包裹文档名，冒号后跟原文摘要
7. 不要输出 ```html 代码块包裹，直接输出 HTML 片段
8. **来源权威性**：当多个来源信息冲突时，按以下优先级取信：配置文件/制度文档 > 官方公告/通知 > 会议纪要 > 其他
9. **数值计算**：涉及数值比较或计算时，必须列出计算过程和算式，不要心算

---

检索到的文档：
{context_text}

用户问题：{question}

请按上述格式用中文回答：
"""
        return self.llm.chat([
            {"role": "system", "content": "你是企业知识库助手，只依据检索到的文档回答。注意语义匹配：用户用词可能不等于文档中的精确用词（如'老板'可能对应'董事长/CEO/创始人'），允许合理推断。回答必须是纯HTML片段，不含html/body/head标签，使用rag-answer/rag-section/rag-label/rag-content/rag-list/rag-source等class名。重要规则：来源冲突时配置文件>公告>会议纪要；数值比较必须列出计算过程。"},
            {"role": "user", "content": prompt}
        ], label="answer")

    def collection_count(self) -> int:
        return self.collection.count()

    def clear_collection(self):
        try:
            self.chroma_client.delete_collection(settings.chroma_collection_name)
        except Exception:
            pass
        try:
            self.chroma_client.delete_collection(settings.chroma_parent_collection_name)
        except Exception:
            pass
        self.collection = self.chroma_client.get_or_create_collection(name=settings.chroma_collection_name)
        self.parent_collection = self.chroma_client.get_or_create_collection(name=settings.chroma_parent_collection_name)