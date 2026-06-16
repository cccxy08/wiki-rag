# Wiki-RAG 钉钉接入版 — 开发进度记录

> 更新时间：2026-06-15
> 项目路径：D:\我的或者AI的一些IDEA们\CodeArts Agent\LLM + RAG 钉钉接入版\LLM + RAG 准备上线版\RAG+LLM

━━━━━━━━━━━━━━━━━━
## 当前状态
━━━━━━━━━━━━━━━━━━

**测试：25 passed, 1 skipped**
**后端可启动，Health API正常**
**待填入MINIMAX_API_KEY后可端到端验证**

━━━━━━━━━━━━━━━━━━
## 模块进度
━━━━━━━━━━━━━━━━━━

### 模块1：后端跑通 ✅
- [x] MiniMax Provider实现（双模型：Text-01 + VL-01自动切换）
- [x] config.py新增minimax/钉钉云盘/知识提取配置项
- [x] 修复admin.py Field未导入
- [x] 修复deps.py _wiki_engine变量未声明
- [x] .env / .env.example / render.yaml / Dockerfile.render切换到MiniMax
- [x] 15个单元测试通过

### 模块2：钉钉webhook文本问答 ✅
- [x] dingtalk_service.py重写：send_markdown/download_media/_get_access_token实现
- [x] dingtalk.py路由重写：webhook回调+markdown回复+文件处理
- [x] /api/dingtalk/sync-drive 端点
- [x] /api/dingtalk/extract-knowledge 端点
- [x] 10个测试通过（1个需LLM的跳过）

### 模块3：钉钉云盘API触发入库 ✅
- [x] dingtalk_drive_service.py：列出文件夹+下载文件+同步入库
- [x] API路径已更新为 /spaces/{spaceId}/files/{fileId}/children + download
- [x] config新增 DINGTALK_DRIVE_SPACE_ID
- [x] .env已填入 spaceId=229780993, folderId=225152843932

### 模块4：对话知识周期性提取 ✅
- [x] knowledge_extract_service.py：按用户ID分组提取+LLM总结+写入precipitation

### 其他 ✅
- [x] architecture.md中文乱码修复（440行后重建）
- [x] architecture-v2-mvp.md架构确认文档
- [x] AI应用开发全流程提示词.md保存到 D:\我的或者AI的一些IDEA们\Dev Code\Dedup项目\

━━━━━━━━━━━━━━━━━━
## 变更文件清单
━━━━━━━━━━━━━━━━━━

### 新增文件
- backend/core/llm_provider.py → MiniMaxProvider类
- backend/services/dingtalk_drive_service.py → 钉钉云盘同步
- backend/services/knowledge_extract_service.py → 知识提取
- backend/tests/__init__.py
- backend/tests/conftest.py
- backend/tests/test_module1.py
- backend/tests/test_module2.py
- docs/architecture-v2-mvp.md → 架构确认文档

### 修改文件
- backend/core/config.py → minimax/云盘space_id/知识提取配置
- backend/core/llm_provider.py → MiniMaxProvider + detect_model_tier
- backend/core/registry.py → minimax配置字段注册
- backend/api/deps.py → _wiki_engine变量声明修复
- backend/api/routes/admin.py → Field导入修复
- backend/api/routes/dingtalk.py → 重写webhook+sync-drive+extract-knowledge
- backend/services/dingtalk_service.py → 重写完整实现
- backend/.env → MiniMax + 钉钉凭证 + 云盘ID
- .env.example → 新增所有配置项
- render.yaml → MiniMax + 云盘环境变量
- Dockerfile.render → MiniMax + 钉钉环境变量
- docs/architecture.md → 乱码修复

━━━━━━━━━━━━━━━━━━
## 待办（用户操作）
━━━━━━━━━━━━━━━━━━

1. **MINIMAX_API_KEY** → 填入 .env 后端到端验证Query流程
2. **钉钉应用** → 创建企业内部应用+启用机器人 → 填入CLIENT_ID/SECRET/ROBOT_CODE
3. **钉钉权限** → 申请ChatRobot + DriveSpaceRead + DriveSpaceDownload权限
4. **Render部署** → 在Render环境变量中填入以上凭证
5. **端到端验证** → 填入凭证后测试：Health → Query → DingTalk回调 → 云盘同步

━━━━━━━━━━━━━━━━━━
## 部署配置备忘
━━━━━━━━━━━━━━━━━━

### Render free plan（内测）
- 钉钉模式：webhook（回调模式）
- 定时任务：外部cron触发 /api/dingtalk/sync-drive 和 /api/dingtalk/extract-knowledge
- Embedding：zhipu（512MB内存跑不动local）
- 数据：重启后chroma_db自动重建

### CentOS7（正式生产，后续迁移）
- 钉钉模式：stream（长连接）
- 定时任务：APScheduler内置（代码已预留）
- Embedding：可选local
- 持久磁盘
