"""API Key 鉴权中间件 — 支持 admin/user 二元角色，Fail-Closed 策略"""
import json
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.config import settings
from observability.audit import AuditLogger

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/api/health", "/metrics", "/", "/docs", "/redoc", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._key_map: dict[str, str] = {}
        self._load_keys()

    def _load_keys(self):
        try:
            entries = json.loads(settings.api_keys)
            for entry in entries:
                key = entry.get("key", "")
                role = entry.get("role", "user")
                if key:
                    self._key_map[key] = role
            logger.info(f"AuthMiddleware: loaded {len(self._key_map)} API keys")
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"AuthMiddleware: failed to parse API_KEYS: {e}")

    async def dispatch(self, request: Request, call_next):
        if not settings.auth_enabled:
            request.state.user_role = "admin"
            return await call_next(request)

        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith("/static") or not path.startswith("/api"):
            return await call_next(request)

        try:
            api_key = request.headers.get("X-API-Key", "")

            if not api_key:
                AuditLogger.log_auth_event("missing_key", client_ip=request.client.host if request.client else "",
                                           success=False)
                return JSONResponse(
                    status_code=401,
                    content={"error": "unauthorized", "message": "Missing API Key"},
                )

            role = self._key_map.get(api_key)
            if not role:
                AuditLogger.log_auth_event("invalid_key", client_ip=request.client.host if request.client else "",
                                           success=False)
                return JSONResponse(
                    status_code=403,
                    content={"error": "forbidden", "message": "Invalid API Key"},
                )

            if path.startswith("/api/admin") and role != "admin":
                AuditLogger.log_auth_event("insufficient_permissions", client_ip=request.client.host if request.client else "",
                                           success=False, role=role)
                return JSONResponse(
                    status_code=403,
                    content={"error": "forbidden", "message": "Insufficient permissions"},
                )

            request.state.user_role = role
            AuditLogger.log_auth_event("success", client_ip=request.client.host if request.client else "",
                                       success=True, role=role)
            return await call_next(request)

        except Exception as e:
            logger.error(f"AuthMiddleware unexpected error: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Internal authentication error"},
            )