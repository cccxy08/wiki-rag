"""LLM Provider 单元测试 — 重试、降级、并发控制"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).parent.parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestDetectModelTier:
    def test_gpt4_is_large(self):
        from core.llm_provider import detect_model_tier
        assert detect_model_tier("gpt-4o") == "large"
        assert detect_model_tier("gpt-4") == "large"

    def test_qwen_7b_is_small(self):
        from core.llm_provider import detect_model_tier
        assert detect_model_tier("qwen2.5:7b") == "small"

    def test_deepseek_chat_is_large(self):
        from core.llm_provider import detect_model_tier
        assert detect_model_tier("deepseek-chat") == "large"

    def test_unknown_defaults_medium(self):
        from core.llm_provider import detect_model_tier
        assert detect_model_tier("some-unknown-model") == "medium"

    def test_glm4_is_large(self):
        from core.llm_provider import detect_model_tier
        assert detect_model_tier("glm-4") == "large"


class TestLLMProviderRetry:
    def test_retryable_error_retries(self):
        from core.llm_provider import LLMProvider, LLMError

        class TestProvider(LLMProvider):
            @property
            def model_name(self):
                return "test"

            def _raw_chat(self, messages, stream=False, label=""):
                raise Exception("connection error")

            def _raw_chat_stream(self, messages):
                yield "test"

        with patch("core.llm_provider.settings") as mock_s:
            mock_s.llm_max_retries = 2
            mock_s.llm_retry_delay_base = 0.01
            provider = TestProvider()
            result = provider.chat([{"role": "user", "content": "test"}])
            assert result == "系统繁忙，请稍后重试。"

    def test_fallback_on_all_retries_exhausted(self):
        from core.llm_provider import LLMProvider, FALLBACK_MESSAGE

        class FailProvider(LLMProvider):
            @property
            def model_name(self):
                return "test"

            def _raw_chat(self, messages, stream=False, label=""):
                raise RuntimeError("always fails")

            def _raw_chat_stream(self, messages):
                yield "test"

        with patch("core.llm_provider.settings") as mock_s:
            mock_s.llm_max_retries = 1
            mock_s.llm_retry_delay_base = 0.01
            provider = FailProvider()
            result = provider.chat([{"role": "user", "content": "test"}])
            assert result == FALLBACK_MESSAGE