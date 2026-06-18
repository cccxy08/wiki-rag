"""FastAPI 入口 - Wiki-RAG 双引擎知识问答系统"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import router
from core.config import settings
from middleware.auth import AuthMiddleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.request_id import RequestIdMiddleware
from middleware.logging import LoggingMiddleware
from observability.logger import StructuredLogger
from observability.metrics import MetricsCollector

app = FastAPI(
    title="Wiki-RAG 企业知识问答系统",
    description="基于 Karpathy LLM Wiki 范式 + RAG 双引擎的企业级知识管理方案",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
cors_origins = []
if hasattr(settings, 'cors_origins') and settings.cors_origins:
    cors_origins = [o.strip() for o in settings.cors_origins.split(',') if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 中间件链（注册顺序与执行顺序相反，实际执行: CORS → RequestId → Auth → RateLimit → Logging）
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestIdMiddleware)

app.include_router(router)


@app.on_event("startup")
async def startup_event():
    import sys; sys.stdout.reconfigure(encoding='utf-8')

    StructuredLogger.setup()
    MetricsCollector.get_instance().setup(app)

    from core.registry import setup_registry
    setup_registry()

    if settings.dingtalk_enabled and settings.dingtalk_client_id:
        from services.dingtalk_service import DingTalkBotService
        bot = DingTalkBotService()
        bot.start_stream()

    if settings.dingtalk_drive_proxy_url and settings.dingtalk_drive_folder_id:
        try:
            from services.drive_sync_scheduler import DriveSyncScheduler
            DriveSyncScheduler.get_instance().start()
            print("   Drive sync scheduler started")
        except Exception as e:
            print(f"   Drive sync scheduler failed: {e}")

    print(f"Wiki-RAG 系统启动中...")
    print(f"   LLM Provider: {settings.llm_provider}")
    print(f"   API 文档: http://{settings.host}:{settings.port}/docs")
    print(f"   前端页面: http://{settings.host}:{settings.port}/")


# 挂载静态文件（放在路由之后，确保 API 路由优先）
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
