"""API 集成测试 — 健康检查"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).parent.parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "llm_provider" in data
        assert "uptime_seconds" in data

    def test_health_no_auth_required(self, client):
        # 即使开启鉴权，health 也应免认证
        resp = client.get("/api/health")
        assert resp.status_code == 200