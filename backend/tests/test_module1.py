"""模块1测试：配置、LLM Provider、API启动"""
import os
import pytest


class TestConfig:
    def test_settings_loads(self):
        from core.config import settings
        assert settings.llm_provider in ("ollama", "openai", "zhipu", "minimax")
        assert settings.port > 0

    def test_minimax_config_fields(self):
        from core.config import settings
        assert hasattr(settings, "minimax_api_key")
        assert hasattr(settings, "minimax_model")
        assert hasattr(settings, "minimax_multimodal_model")
        assert hasattr(settings, "minimax_base_url")
        assert settings.minimax_base_url == "https://api.minimax.chat/v1"

    def test_dingtalk_config_fields(self):
        from core.config import settings
        assert hasattr(settings, "dingtalk_mode")
        assert settings.dingtalk_mode in ("stream", "webhook")
        assert hasattr(settings, "dingtalk_drive_folder_id")
        assert hasattr(settings, "knowledge_extract_interval_hours")

    def test_wiki_paths(self):
        from core.config import settings
        paths = settings.get_wiki_paths()
        assert "data" in paths
        assert "raw" in paths
        assert "pages" in paths


class TestLLMProvider:
    def test_detect_model_tier(self):
        from core.llm_provider import detect_model_tier
        assert detect_model_tier("gpt-4o") == "large"
        assert detect_model_tier("MiniMax-Text-01") == "large"
        assert detect_model_tier("qwen2.5:7b") == "small"
        assert detect_model_tier("deepseek-chat") == "large"

    def test_minimax_provider_lazy_init_no_key(self):
        from core.llm_provider import MiniMaxProvider
        os.environ["MINIMAX_API_KEY"] = ""
        from core.config import settings
        settings.minimax_api_key = ""
        provider = MiniMaxProvider()
        assert provider._client is None
        with pytest.raises(ValueError, match="MINIMAX_API_KEY"):
            provider._ensure_client()

    def test_minimax_provider_init_with_key(self):
        from core.llm_provider import MiniMaxProvider
        from core.config import settings
        settings.minimax_api_key = "test-key"
        provider = MiniMaxProvider()
        assert provider.model_name == settings.minimax_model
        assert provider._vl_model == settings.minimax_multimodal_model
        settings.minimax_api_key = ""

    def test_minimax_model_selection_text(self):
        from core.llm_provider import MiniMaxProvider
        from core.config import settings
        settings.minimax_api_key = "test-key"
        provider = MiniMaxProvider()
        messages = [{"role": "user", "content": "hello"}]
        assert provider._choose_model(messages) == settings.minimax_model
        settings.minimax_api_key = ""

    def test_minimax_model_selection_vision(self):
        from core.llm_provider import MiniMaxProvider
        from core.config import settings
        settings.minimax_api_key = "test-key"
        provider = MiniMaxProvider()
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}}
        ]}]
        assert provider._choose_model(messages) == settings.minimax_multimodal_model
        settings.minimax_api_key = ""

    def test_provider_map_has_minimax(self):
        from core.llm_provider import get_llm
        from core.config import settings
        settings.llm_provider = "minimax"
        settings.minimax_api_key = "test-key"
        llm = get_llm()
        assert "MiniMax" in llm.model_name or "minimax" in llm.model_name.lower()
        settings.minimax_api_key = ""
        settings.llm_provider = "openai"


class TestPrompts:
    def test_load_prompt(self):
        from core.prompts import load
        text = load("rag_rewrite.txt", question="test question")
        assert "test question" in text

    def test_load_without_kwargs(self):
        from core.prompts import load
        text = load("rag_rewrite.txt")
        assert len(text) > 0


class TestAPIStartup:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "llm_provider" in data

    @pytest.mark.asyncio
    async def test_openapi_schema(self, client):
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "paths" in data
        assert "/api/health" in data["paths"]

    @pytest.mark.asyncio
    async def test_admin_settings(self, client):
        response = await client.get("/api/admin/settings")
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        assert data["settings"]["dingtalk_mode"] in ("stream", "webhook")
