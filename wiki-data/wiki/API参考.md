---
title: API参考
type: entity
created: 2026-05-17
updated: 2026-05-17
tags: [api, reference, developer]
---

# API 接口文档

## 概述

CodeXFiles 提供 RESTful API 接口，所有接口均以 `/api` 为前缀。API 文档也通过 Swagger UI 自动生成，服务启动后可访问 `/docs` 查看交互式文档。

## 基础信息

| 属性 | 值 |
|------|-----|
| 基础路径 | `http://{host}:{port}/api` |
| 认证方式 | 当前为开放访问（MVP 阶段） |
| 数据格式 | JSON |
| 字符编码 | UTF-8 |

## 接口列表

### 1. 健康检查

```
GET /api/health
```

检查系统运行状态，返回 LLM 连接、文档数量等信息。

**响应示例：**
```json
{
  "status": "ok",
  "llm_provider": "deepseek-chat",
  "llm_model": "deepseek-chat",
  "wiki_pages": 6,
  "vector_count": 15,
  "uptime_seconds": 3600
}
```

### 2. 知识问答

```
POST /api/query
```

核心接口，支持三种查询模式。

**请求参数：**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| question | string | 是 | - | 用户问题 |
| mode | string | 否 | "auto" | 查询模式：auto / pipeline / agent |
| top_k | integer | 否 | 5 | 检索返回条数（1-20） |
| session_id | string | 否 | null | 会话 ID，用于多轮对话 |
| stream | boolean | 否 | false | 是否流式输出 |

**响应字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| answer | string | 回答内容（Markdown 格式） |
| source | string | 答案来源：wiki / rag / agent |
| source_pages | string[] | 引用的 Wiki 页面列表 |
| sources | SourceInfo[] | RAG 来源详细信息 |
| confidence | string | 置信度：high / medium / low |
| cached | boolean | 是否来自缓存 |

**请求示例：**
```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"系统有哪些查询模式？","mode":"pipeline","top_k":3}'
```

### 3. 流式问答

```
POST /api/query/stream
```

与 `/api/query` 相同的参数，但响应以流式方式返回，适用于前端实时显示。

### 4. 文档摄入

```
POST /api/ingest
```

上传文档并自动触发 Wiki 和 RAG 双引擎索引。

**请求参数：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | 上传的文档文件 |

**支持的文档格式：** PDF、TXT、Markdown（.md）、Word（.docx）

### 5. Wiki 目录

```
GET /api/wiki/index
```

获取 Wiki 知识库的所有页面目录。

### 6. Wiki 页面

```
GET /api/wiki/page/{title}
```

获取指定 Wiki 页面的完整内容，包含交叉引用信息。

### 7. Wiki 健康检查

```
POST /api/wiki/lint
```

触发 Wiki 健康扫描，检测孤立页面、过期内容等。

### 8. 管理后台

```
GET /api/admin/dashboard
```

返回管理仪表盘数据，包含 Wiki 统计、RAG 统计、缓存统计和最近操作。

## 数据模型

### QueryRequest
```json
{
  "question": "string (必填)",
  "session_id": "string|null",
  "top_k": "integer (1-20, 默认5)",
  "stream": "boolean (默认false)",
  "mode": "enum (auto|pipeline|agent, 默认auto)"
}
```

### QueryResponse
```json
{
  "answer": "string",
  "source": "enum (wiki|rag|agent)",
  "source_pages": ["string"],
  "sources": [{"file": "string", "page": "int|null", "chunk_id": "string|null"}],
  "confidence": "enum (high|medium|low)",
  "cached": "boolean",
  "session_id": "string|null"
}
```

## 错误码

| HTTP 状态码 | 说明 | 处理方式 |
|-------------|------|---------|
| 200 | 成功 | 正常解析响应 |
| 400 | 请求参数错误 | 检查请求体格式 |
| 422 | 参数校验失败 | 检查必填字段和类型 |
| 500 | 服务器内部错误 | 查看服务器日志排查 |

## 相关文档

- 详见 [[系统架构]] 了解后端处理流程
- 详见 [[使用指南]] 了解如何通过界面使用
- 详见 [[RAG引擎]] 了解查询的底层原理
- 详见 [[技术栈]] 了解技术选型
