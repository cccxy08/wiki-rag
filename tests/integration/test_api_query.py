"""API 集成测试 — 查询接口鉴权"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).parent.parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestQueryAuth:
    def test_query_without_key_returns_401(self, client):
        # conftest 中 auth_enabled=False，这里临时测试鉴权逻辑
        # 直接测试 AuthMiddleware
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from middleware.auth import AuthMiddleware

        app = FastAPI()

        @app.post("/api/query")
        def query():
            return {"answer": "test"}

        app.add_middleware(AuthMiddleware)

        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.api_keys = '[{"key":"test-key","role":"user"}]'
            c = TestClient(app)
            resp = c.post("/api/query")
            assert resp.status_code == 401

    def test_query_with_invalid_key_returns_403(self):
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from middleware.auth import AuthMiddleware

        app = FastAPI()

        @app.post("/api/query")
        def query():
            return {"answer": "test"}

        app.add_middleware(AuthMiddleware)

        with patch("middleware.auth.settings") as mock_s:
            mock_s.auth_enabled = True
            mock_s.api_keys = '[{"key":"test-key","role":"user"}]'
            c = TestClient(app)
            resp = c.post("/api/query", headers={"X-API-Key": "invalid"})
            assert resp.status_code == 403