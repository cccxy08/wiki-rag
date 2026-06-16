# Wiki-RAG 钉钉接入版 — 架构确认文档

> 生成时间：2026-06-15
> 更新时间：2026-06-15
> 阶段：MVP可跑验证 + 钉钉核心集成
> 方案：A（最小可跑版），后续迭代至B（完整钉钉集成）
> 部署：Render free plan（内测）→ CentOS7（正式生产）

━━━━━━━━━━━━━━━━━━
## 一、系统现状
━━━━━━━━━━━━━━━━━━

已完成：
- FastAPI后端骨架（middleware链、路由、services、schemas）
- Wiki引擎（core/index/ingest/lint/backlinks/tags/version）
- RAG引擎（chunker/embedding/indexer/retriever/loader）
- Agent（react/decompose/preprocess）
- 15+ Prompt模板
- LLM Provider可插拔（Ollama/OpenAI/智谱）
- 钉钉Stream服务骨架（空壳：send_markdown/download_media等为stub）
- Render部署配置（render.yaml/Dockerfile.render/start.render.sh）

未完成/问题：
- 后端未验证能否启动
- 钉钉Stream核心方法为空壳
- 缺少MiniMax Provider
- 钉钉云盘文件拉取未实现
- 对话知识提取未实现
- 无测试覆盖
- architecture.md末尾中文乱码（440行后）

━━━━━━━━━━━━━━━━━━
## 二、部署策略
━━━━━━━━━━━━━━━━━━

### Render free plan（内测环境）

| 约束 | 应对 |
|------|------|
| 无持久磁盘，重启丢数据 | start.render.sh已有自动重建索引，内测够用 |
| 15分钟无请求休眠 | 钉钉用webhook模式（被动回调，不怕休眠） |
| 内存512MB | Embedding必须用云端（zhipu/openai），禁local |
| 无内置cron | 定时任务提供API端点，外部cron-job.org触发 |

### CentOS7（正式生产，后续迁移）

- Stream长连接模式
- APScheduler内置定时调度
- 可选local Embedding
- 持久磁盘，数据不丢

### 迁移时的切换项

| 配置项 | Render内测 | CentOS7正式 |
|--------|-----------|-------------|
| DINGTALK_MODE | webhook | stream |
| SCHEDULER_MODE | external（API触发） | internal（APScheduler） |
| EMBEDDING_PROVIDER | zhipu/openai | 可选local |
| DINGTALK_STREAM_ENABLED | false | true |

━━━━━━━━━━━━━━━━━━
## 三、MVP目标（方案A）
━━━━━━━━━━━━━━━━━━

### 模块1：后端启动与核心Query跑通
- Fix启动问题
- 新增MiniMax Provider（文本模型MiniMax-Text-01 + 视觉模型MiniMax-VL-01）
- Wiki→RAG→Agent Query流程端到端验证
- Embedding保持可配（local/zhipu/openai），Render环境强制云端
- 核心service单元测试
- 修复architecture.md乱码

### 模块2：钉钉webhook文本问答
- dingtalk_service.py：实现webhook模式的消息接收和回复
- webhook验签（已有verify_webhook_signature）
- 消息接收→QueryService→markdown回复 闭环
- send_markdown用钉钉webhook HTTP API实现
- download_media用钉钉开放平台API实现
- 凭证从config读取（变量占位）
- Stream模式代码保留，Render内测不启用

### 模块3：钉钉云盘文档入库（API触发）
- 钉钉云盘API：列出文件夹→下载文件→IngestService→入库
- 新增 dingtalk_drive_service.py
- 新增 /api/dingtalk/sync-drive API端点（供外部cron触发）
- 文件夹路径做config变量
- APScheduler代码预留，Render内测用外部cron触发

### 模块4：对话知识周期性提取（API触发）
- 新增 /api/dingtalk/extract-knowledge API端点
- 按钉钉用户ID分组，提取近期对话中的知识碎片
- LLM总结→写入precipitation审核队列
- 沉淀确认走日志/API，交互卡片放B方案
- 提取周期由外部cron控制

━━━━━━━━━━━━━━━━━━
## 四、技术决策
━━━━━━━━━━━━━━━━━━

| 决策项 | 选择 | 理由 |
|--------|------|------|
| LLM Provider | MiniMax（兼容OpenAI SDK） | 多模态能力，PDF/图片视觉识别，简化解析链路 |
| MiniMax接入方式 | openai库，改base_url | 现有openai provider可复用，零新依赖 |
| MiniMax模型 | Text-01(文本) + VL-01(视觉) | 文本模型处理对话，视觉模型处理文件/图片 |
| 文档解析策略 | MiniMax多模态优先，传统解析兜底 | PDF/图片→视觉识别；txt/md→传统loader |
| 钉钉模式(Render) | Webhook | free plan休眠，webhook不怕断连 |
| 钉钉模式(CentOS7) | Stream | 正式环境长连接，稳定 |
| 钉钉云盘 | 钉钉开放平台Drive API | 企业内部应用，需DriveScope权限 |
| 定时调度(Render) | 外部cron触发API | free plan无内置cron |
| 定时调度(CentOS7) | APScheduler | 内嵌调度，迁移后启用 |
| Embedding(Render) | 云端（zhipu/openai） | 512MB内存跑不动local |
| Embedding(CentOS7) | 可选local | 服务器内存充足 |
| 测试框架 | pytest + httpx（异步测试） | FastAPI生态标配 |

━━━━━━━━━━━━━━━━━━
## 五、新增配置项
━━━━━━━━━━━━━━━━━━

```env
# MiniMax
MINIMAX_API_KEY=                          # MiniMax API Key（待填）
MINIMAX_MODEL=MiniMax-Text-01             # MiniMax 文本模型
MINIMAX_MULTIMODAL_MODEL=MiniMax-VL-01    # MiniMax 多模态模型
MINIMAX_BASE_URL=https://api.minimax.chat/v1

# 钉钉（已有，确认占位）
DINGTALK_ENABLED=false
DINGTALK_CLIENT_ID=
DINGTALK_CLIENT_SECRET=
DINGTALK_ROBOT_CODE=
DINGTALK_MODE=webhook                     # webhook(Render内测) / stream(CentOS7)

# 钉钉云盘（新增）
DINGTALK_DRIVE_FOLDER_ID=                 # 钉钉云盘目标文件夹ID（待填）

# 知识提取（新增）
KNOWLEDGE_EXTRACT_MAX_CONVERSATIONS=50    # 单次最多处理对话数
```

━━━━━━━━━━━━━━━━━━
## 六、文件变更清单
━━━━━━━━━━━━━━━━━━

### 新增
- backend/core/llm_provider.py → 新增 MiniMaxProvider 类（双模型切换）
- backend/services/dingtalk_drive_service.py → 钉钉云盘文件拉取
- backend/services/knowledge_extract_service.py → 对话知识提取
- backend/api/routes/dingtalk.py → webhook回调端点 + sync-drive + extract-knowledge
- tests/ → 测试目录

### 修改
- backend/core/config.py → 新增MiniMax/云盘/知识提取配置项 + DINGTACK_MODE
- backend/services/dingtalk_service.py → 实现webhook回复 + send_markdown + download_media
- backend/requirements.txt → 新增apscheduler(预留)
- .env.example → 新增配置项模板
- render.yaml → 切换到MiniMax配置
- Dockerfile.render → 更新环境变量

### 修复
- docs/architecture.md → 修复440行后中文乱码

━━━━━━━━━━━━━━━━━━
## 七、实现顺序
━━━━━━━━━━━━━━━━━━

```
模块1（后端跑通）→ 模块2（钉钉webhook问答）→ 模块3（云盘API触发入库）→ 模块4（知识提取API触发）
```

每个模块完成标准：
1. 代码可运行
2. 单元测试通过
3. 端到端验证通过（API/集成测试）

━━━━━━━━━━━━━━━━━━
## 八、B方案预留（后续迭代 / CentOS7迁移）
━━━━━━━━━━━━━━━━━━

- 钉钉Stream长连接模式
- APScheduler内置定时调度
- 钉钉交互卡片（沉淀确认按钮）
- 文件上传触发入库（钉钉发文件→自动处理）
- 对话实时知识提取（非周期性）
- 更多钉钉管理命令（/status, /search等）
- 管理员审批流
- local Embedding

━━━━━━━━━━━━━━━━━━
## 九、风险
━━━━━━━━━━━━━━━━━━

| 风险 | 对策 |
|------|------|
| MiniMax API格式不完全兼容OpenAI | 先用openai库试，不行则用httpx直接调MiniMax REST API |
| 钉钉云盘API权限申请需管理员 | 先用占位变量，手动测试时再申请权限 |
| Render free plan内存不足 | 禁local Embedding，监控内存 |
| MiniMax多模态解析质量不如传统loader | 保留传统loader作为兜底，不删除 |
| 现有代码过度设计可能阻碍快速跑通 | 优先在现有结构内修复，不重构 |
| Render休眠导致首次请求慢 | 内测可接受，正式环境用CentOS7 |
