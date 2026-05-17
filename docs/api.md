# API 接口文档

Base URL: `http://localhost:8000`

## 健康检查

```http
GET /api/health
```

Response:
```json
{
  "status": "ok",
  "llm_provider": "ollama",
  "llm_model": "qwen2.5:7b",
  "wiki_pages": 42
}
```

---

## 文档摄入

```http
POST /api/ingest
Content-Type: multipart/form-data

file: document.pdf
```

Response:
```json
{
  "status": "success",
  "wiki_page": "document-summary.md",
  "pages_updated": ["entity-xxx.md", "concept-yyy.md"],
  "log_entry": "[2026-05-15] ingest | document.pdf"
}
```

---

## 知识问答

```http
POST /api/query
Content-Type: application/json

{
  "question": "公司年假政策是什么？",
  "top_k": 5
}
```

Response:
```json
{
  "answer": "根据公司规定，年假...",
  "source": "wiki",
  "source_pages": ["hr-policy.md"],
  "confidence": "high"
}
```

source 字段说明：
- `wiki`：从 Wiki 知识库直接命中
- `rag`：通过 RAG 检索原始文档回答

---

## 查看 Wiki 目录

```http
GET /api/wiki/index
```

Response:
```json
{
  "categories": [
    {
      "name": "人力资源",
      "pages": [
        {"title": "年假政策", "file": "hr-policy.md", "updated": "2026-05-15"}
      ]
    }
  ]
}
```

---

## 查看 Wiki 页面

```http
GET /api/wiki/page/{title}
```

Response:
```json
{
  "title": "年假政策",
  "content": "# 年假政策\n\n...",
  "metadata": {
    "type": "entity",
    "created": "2026-05-15",
    "sources": ["hr-handbook.pdf"],
    "cross_refs": ["请假流程", "考勤制度"]
  }
}
```

---

## Wiki 健康检查

```http
POST /api/wiki/lint
```

Response:
```json
{
  "status": "completed",
  "issues": [
    {
      "type": "orphan",
      "page": "old-policy.md",
      "description": "无任何页面引用此页面"
    },
    {
      "type": "contradiction",
      "pages": ["hr-policy.md", "onboarding.md"],
      "description": "两个页面关于年假天数的描述不一致"
    }
  ]
}
```

---

## 错误响应格式

```json
{
  "error": "error_code",
  "message": "人类可读的错误描述",
  "detail": "详细错误信息（可选）"
}
```
