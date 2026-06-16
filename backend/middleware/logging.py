"""日志中间件 — 记录请求开始/结束、耗时统计"""
import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from middleware.request_id import request_id_var

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        req_id = request_id_var.get("")
        path = request.url.path
        method = request.method

        logger.info(f"request_start method={method} path={path} request_id={req_id}")

        response = await call_next(request)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            f"request_end method={method} path={path} status={response.status_code} "
            f"duration_ms={duration_ms} request_id={req_id}"
        )
        return response