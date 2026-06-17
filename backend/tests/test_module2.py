"""模块2测试：钉钉webhook、云盘同步、知识提取"""
import os
import json
import pytest


class TestDingTalkWebhook:
    @pytest.mark.asyncio
    async def test_callback_disabled(self, client):
        os.environ["DINGTALK_ENABLED"] = "false"
        from core.config import settings
        settings.dingtalk_enabled = False

        response = await client.post("/api/dingtalk/callback", json={"msgtype": "text", "text": {"content": "test"}})
        assert response.status_code == 404

    @pytest.mark.skip(reason="需要真实LLM连接，在集成测试中验证")
    @pytest.mark.asyncio
    async def test_callback_text_webhook_structure(self, client):
        from core.config import settings
        settings.dingtalk_enabled = True
        settings.dingtalk_mode = "webhook"
        settings.llm_provider = "minimax"
        settings.minimax_api_key = ""

        response = await client.post(
            "/api/dingtalk/callback",
            json={
                "msgtype": "text",
                "text": {"content": "hello"},
                "senderStaffId": "test_user_001",
                "conversationId": "cid_test",
            },
        )
        assert response.status_code in (200, 500, 503)
        settings.dingtalk_enabled = False
        settings.dingtalk_mode = "webhook"

    @pytest.mark.asyncio
    async def test_sync_drive_no_folder(self, client):
        from core.config import settings
        settings.dingtalk_enabled = True
        settings.dingtalk_drive_space_id = ""
        settings.dingtalk_drive_folder_id = ""

        response = await client.post("/api/dingtalk/sync-drive")
        assert response.status_code == 400
        settings.dingtalk_enabled = False

    @pytest.mark.asyncio
    async def test_sync_drive_no_space(self, client):
        from core.config import settings
        settings.dingtalk_enabled = True
        settings.dingtalk_drive_space_id = ""
        settings.dingtalk_drive_folder_id = "some_folder"

        response = await client.post("/api/dingtalk/sync-drive")
        assert response.status_code == 400
        settings.dingtalk_enabled = False

    @pytest.mark.asyncio
    async def test_extract_knowledge_disabled(self, client):
        from core.config import settings
        settings.dingtalk_enabled = False

        response = await client.post("/api/dingtalk/extract-knowledge")
        assert response.status_code == 404


class TestDingTalkService:
    def test_verify_signature(self):
        from services.dingtalk_service import DingTalkBotService
        from core.config import settings

        settings.dingtalk_client_secret = "test_secret"
        svc = DingTalkBotService()

        timestamp = "1234567890"
        string_to_sign = f"{timestamp}\ntest_secret"
        import hmac, hashlib
        expected_sign = hmac.new(
            "test_secret".encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        assert svc.verify_webhook_signature(timestamp, expected_sign) is True
        assert svc.verify_webhook_signature(timestamp, "wrong_sign") is False

        settings.dingtalk_client_secret = ""

    def test_map_user_role(self):
        from services.dingtalk_service import DingTalkBotService
        from core.config import settings

        settings.dingtalk_admin_ids = "admin1,admin2"
        svc = DingTalkBotService()

        assert svc.map_user_role("admin1") == "admin"
        assert svc.map_user_role("admin2") == "admin"
        assert svc.map_user_role("normal_user") == "user"

        settings.dingtalk_admin_ids = ""

    def test_get_access_token_no_credentials(self):
        from services.dingtalk_service import DingTalkBotService
        from core.config import settings

        settings.dingtalk_client_id = ""
        settings.dingtalk_client_secret = ""
        svc = DingTalkBotService()
        token = svc._get_access_token()
        assert token == ""


class TestDingTalkDriveService:
    def test_init(self):
        from services.dingtalk_drive_service import DingTalkDriveService
        svc = DingTalkDriveService()
        assert svc._proxy_base is None

    def test_proxy_url_empty(self):
        from services.dingtalk_drive_service import DingTalkDriveService
        from core.config import settings
        settings.dingtalk_drive_proxy_url = ""
        svc = DingTalkDriveService()
        assert svc.proxy_base == ""

    def test_list_no_proxy(self):
        from services.dingtalk_drive_service import DingTalkDriveService
        from core.config import settings
        settings.dingtalk_drive_proxy_url = ""
        settings.dingtalk_drive_user_id = ""
        svc = DingTalkDriveService()
        result = svc.list_folder_files("229780993", "0")
        assert result == []

    def test_download_no_proxy(self):
        from services.dingtalk_drive_service import DingTalkDriveService
        from core.config import settings
        settings.dingtalk_drive_proxy_url = ""
        settings.dingtalk_drive_user_id = ""
        svc = DingTalkDriveService()
        result = svc.download_file_content("229780993", "123", "test.txt")
        assert result is None


class TestKnowledgeExtractService:
    def test_extract_from_empty_conversations(self):
        from services.knowledge_extract_service import KnowledgeExtractService
        svc = KnowledgeExtractService.__new__(KnowledgeExtractService)
        result = svc.extract_from_conversations("user1", [])
        assert result == []
