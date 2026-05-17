# Wiki-RAG 双引擎企业知识问答系统

> 基于 Karpathy LLM Wiki 范式 + RAG 的企业级知识管理解决方案

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 核心理念

**不是又一个 RAG Chatbot。**

现有的 RAG 问答系统只能「检索 → 回答」，答案随对话消失，同样的
问题被反复搜索。本系统实现了 **Wiki + RAG 双引擎架构**：

- **Wiki 引擎**：将高质量答案结构化沉淀，知识越用越厚
- **RAG 引擎**：兜底检索未结构化的原始文档
- **知识复利**：RAG 产生的优质答案自动回流 Wiki，相同问题不查两遍

```
用户提问 → 先查 Wiki（精确命中） → 未命中 → RAG 兜底 → 好答案写回 Wiki
```

---

## 快速开始

### 环境要求

- Python 3.10+
- [Ollama](https://ollama.com)（本地 LLM 推理）
- 16GB+ RAM（笔记本开发）
- 8GB+ VRAM（台式机跑模型，可选）

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd CodeXFiles
```

### 2. 安装依赖

```bash
pip install -r backend/requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，配置 LLM Provider 和台式机 IP
```

### 4. 启动 Ollama（台式机）

```bash
# 在台式机上
ollama serve
ollama pull qwen2.5:7b
```

### 5. 启动后端

```bash
cd backend
python main.py
# 访问 http://localhost:8000/docs 查看 API 文档
```

---

## 技术栈

| 模块 | 技术 |
|------|------|
| 后端 | FastAPI + Python 3.10+ |
| LLM | Ollama Qwen2.5-7B（可切换 OpenAI/智谱） |
| Embedding | BGE-small-zh |
| 向量库 | Chroma |
| 文档解析 | LangChain Loaders |
| Wiki 格式 | Markdown + Git |

---

## 项目结构

详见 [docs/architecture.md](docs/architecture.md)

---

## API 文档

启动后访问 `http://localhost:8000/docs` 查看 Swagger 文档。

主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/ingest` | 上传文档 |
| POST | `/api/query` | 知识问答 |
| GET | `/api/wiki/index` | Wiki 目录 |
| POST | `/api/wiki/lint` | 健康检查 |

---

## 创新点

1. **Wiki + RAG 双引擎**：结构化精确检索 + 非结构化语义兜底
2. **知识复利机制**：每次回答都在沉淀，越用越聪明
3. **LLM 驱动的 Wiki 维护**：自动交叉引用、矛盾检测、过期标记
4. **Karpathy 范式工程化落地**：从概念到可运行的企业级系统

---

## License

MIT
