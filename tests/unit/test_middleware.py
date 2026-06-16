"""中间件单元测试 — Auth / RateLimit / RequestId"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).parent.parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestAuthMiddleware:
    def _make_request(self, path="/api/query", api_key=""):
        from starlette.testclient import TestClient
        from fastapi import FastAPI
        from middleware.auth import AuthMiddleware

        app = FastAPI()

        @app.get(path)
        def endpoint():
            return {"ok": True}

        app.add_middleware(AuthMiddleware)
        client = TestClient(app)
        headers = {"X-API-Key": api_key} if api_key else {}
        return client, headers

    def test_missing_key_returns_401(self):
        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.api_keys = '[{"key":"test-key","role":"user"}]'
            client, _ = self._make_request()
            resp = client.get("/api/query")
            assert resp.status_code == 401

    def test_invalid_key_returns_403(self):
        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.api_keys = '[{"key":"test-key","role":"user"}]'
            client, headers = self._make_request(api_key="wrong-key")
            resp = client.get("/api/query", headers=headers)
            assert resp.status_code == 403

    def test_valid_user_key_allowed(self):
        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.api_keys = '[{"key":"user-key","role":"user"}]'
            client, headers = self._make_request(api_key="user-key")
            resp = client.get("/api/query", headers=headers)
            assert resp.status_code == 200

    def test_user_key_admin_forbidden(self):
        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.api_keys = '[{"key":"user-key","role":"user"}]'
            client, headers = self._make_request(path="/api/admin/dashboard", api_key="user-key")
            resp = client.get("/api/admin/dashboard", headers=headers)
            assert resp.status_code == 403

    def test_admin_key_allowed(self):
        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.api_keys = '[{"key":"admin-key","role":"admin"}]'
            client, headers = self._make_request(path="/api/admin/dashboard", api_key="admin-key")
            resp = client.get("/api/admin/dashboard", headers=headers)
            assert resp.status_code == 200

    def test_auth_disabled_allows_all(self):
        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = False
            mock_s.api_keys = "[]"
            client, _ = self._make_request()
            resp = client.get("/api/query")
            assert resp.status_code == 200

    def test_health_endpoint_no_auth(self):
        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.api_keys = '[{"key":"test-key","role":"user"}]'
            client, _ = self._make_request(path="/api/health")
            resp = client.get("/api/health")
            assert resp.status_code == 200


class TestRequestIdMiddleware:
    def test_generates_request_id(self):
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from middleware.request_id import RequestIdMiddleware

        app = FastAPI()

        @app.get("/test")
        def endpoint():
            return {"ok": True}

        app.add_middleware(RequestIdMiddleware)
        client = TestClient(app)
        resp = client.get("/test")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0

    def test_propagates_existing_request_id(self):
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from middleware.request_id import RequestIdMiddleware

        app = FastAPI()

        @app.get("/test")
        def endpoint():
            return {"ok": True}

        app.add_middleware(RequestIdMiddleware)
        client = TestClient(app)
        resp = client.get("/test", headers={"X-Request-ID": "my-custom-id"})
        assert resp.headers["X-Request-ID"] == "my-custom-id"


class TestTokenBucket:
    def test_allows_within_capacity(self):
        from middleware.rate_limit import TokenBucket
        bucket = TokenBucket(rate=1.0, capacity=5)
        for _ in range(5):
            assert bucket.consume() is True

    def test_rejects_over_capacity(self):
        from middleware.rate_limit import TokenBucket
        bucket = TokenBucket(rate=1.0, capacity=2)
        assert bucket.consume() is True
        assert bucket.consume() is True
        assert bucket.consume() is False