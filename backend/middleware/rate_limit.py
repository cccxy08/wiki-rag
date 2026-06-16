"""Rate Limiting 限流中间件 — 令牌桶算法，IP 维度，异常降级"""
import time
import logging
import threading
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.config import settings

logger = logging.getLogger(__name__)


class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens >= n:
                self.tokens -= n
                return True
            return False

    @property
    def remaining(self) -> int:
        return int(self.tokens)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self._global_rate = settings.rate_limit_per_minute / 60.0
        self._admin_rate = settings.rate_limit_admin_per_minute / 60.0

    def _get_bucket(self, key: str, rate: float, capacity: int) -> TokenBucket:
        if key not in self._buckets:
            with self._lock:
                if key not in self._buckets:
                    self._buckets[key] = TokenBucket(rate=rate, capacity=capacity)
        return self._buckets[key]

    async def dispatch(self, request: Request, call_next):
        try:
            client_ip = request.client.host if request.client else "unknown"
            path = request.url.path

            if not path.startswith("/api"):
                return await call_next(request)

            is_admin = path.startswith("/api/admin")
            rate = self._admin_rate if is_admin else self._global_rate
            capacity = settings.rate_limit_admin_per_minute if is_admin else settings.rate_limit_per_minute

            bucket_key = f"{client_ip}:admin" if is_admin else f"{client_ip}:global"
            bucket = self._get_bucket(bucket_key, rate, capacity)

            if not bucket.consume():
                retry_after = int(60 / capacity * capacity)
                return JSONResponse(
                    status_code=429,
                    content={"error": "rate_limited", "message": "Too many requests"},
                    headers={
                        "X-RateLimit-Limit": str(capacity),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(time.time()) + 60),
                        "Retry-After": str(retry_after),
                    },
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(capacity)
            response.headers["X-RateLimit-Remaining"] = str(bucket.remaining)
            return response

        except Exception as e:
            logger.error(f"RateLimitMiddleware error, allowing request: {e}")
            return await call_next(request)