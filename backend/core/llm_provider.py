"""LLM Provider - 可插拔的 LLM 调用层（含重试、降级、并发控制）"""
import asyncio
import time
import logging
from abc import ABC, abstractmethod
from threading import Semaphore
from typing import Generator

from openai import OpenAI, APIError, APIConnectionError, APITimeoutError, RateLimitError

from core.config import settings

logger = logging.getLogger(__name__)

# 全局限流：最多 3 个 LLM 并发请求
_global_semaphore = Semaphore(3)

# 可重试的错误类型（网络瞬断、超时、限流）
RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError)

# 降级回复
FALLBACK_MESSAGE = "系统繁忙，请稍后重试。"


class LLMError(Exception):
    """LLM 调用异常"""
    def __init__(self, message: str, retryable: bool = True, original: Exception = None):
        super().__init__(message)
        self.retryable = retryable
        self.original = original


class LLMProvider(ABC):
    """LLM 抽象基类 — 内置重试、降级、并发控制"""

    def __init__(self):
        self._max_retries = getattr(settings, 'llm_max_retries', 3)
        self._retry_base_delay = getattr(settings, 'llm_retry_delay_base', 1.0)
        self._retry_backoff = 2.0

    @abstractmethod
    def _raw_chat(self, messages: list[dict], stream: bool = False):
        """子类实现实际的 API 调用"""
        ...

    @abstractmethod
    def _raw_chat_stream(self, messages: list[dict]) -> Generator[str, None, None]:
        """子类实现实际的流式 API 调用"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    def _classify_error(self, error: Exception) -> LLMError:
        """分类错误：可重试 vs 不可重试"""
        if isinstance(error, RETRYABLE_ERRORS):
            return LLMError(str(error), retryable=True, original=error)
        if isinstance(error, APIError):
            # 4xx 通常是客户端问题不可重试，5xx 可重试
            status = getattr(error, 'status_code', None) or getattr(error, 'http_status', None)
            if status and 400 <= status < 500 and status != 429:
                return LLMError(str(error), retryable=False, original=error)
            return LLMError(str(error), retryable=True, original=error)
        return LLMError(str(error), retryable=False, original=error)

    def chat(self, messages: list[dict], stream: bool = False) -> str:
        """同步对话 — 自动重试 + 降级"""
        last_error = None

        for attempt in range(self._max_retries):
            try:
                with _global_semaphore:
                    return self._raw_chat(messages, stream=stream)
            except Exception as e:
                classified = self._classify_error(e)
                last_error = classified

                if not classified.retryable:
                    logger.error(f"LLM 不可恢复错误: {classified}")
                    break

                if attempt < self._max_retries - 1:
                    delay = self._retry_base_delay * (self._retry_backoff ** attempt)
                    logger.warning(
                        f"LLM 调用失败 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"{delay:.1f}s 后重试: {str(e)[:200]}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"LLM 调用全部 {self._max_retries} 次重试失败: {str(e)[:200]}")

        # 全部重试失败 → 降级回复
        import sys
        print(f"\n[LLM-FATAL] chat() 全部重试失败", file=sys.stderr)
        if last_error:
            print(f"[LLM-FATAL] 最后错误: {type(last_error).__name__}: {last_error}", file=sys.stderr)
            if last_error.original:
                print(f"[LLM-FATAL] 原始异常: {type(last_error.original).__name__}: {str(last_error.original)[:500]}", file=sys.stderr)
        print("", file=sys.stderr)
        return FALLBACK_MESSAGE

    def chat_stream(self, messages: list[dict]) -> Generator[str, None, None]:
        """流式对话 — 自动重试 + 降级"""
        last_error = None

        for attempt in range(self._max_retries):
            try:
                with _global_semaphore:
                    for chunk in self._raw_chat_stream(messages):
                        yield chunk
                    return
            except Exception as e:
                classified = self._classify_error(e)
                last_error = classified

                if not classified.retryable:
                    logger.error(f"LLM 流式调用不可恢复错误: {classified}")
                    break

                if attempt < self._max_retries - 1:
                    delay = self._retry_base_delay * (self._retry_backoff ** attempt)
                    logger.warning(
                        f"LLM 流式调用失败 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"{delay:.1f}s 后重试: {str(e)[:200]}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"LLM 流式调用全部 {self._max_retries} 次重试失败: {str(e)[:200]}")

        # 全部失败 → 返回降级消息
        yield FALLBACK_MESSAGE


class OllamaProvider(LLMProvider):
    """Ollama 本地模型"""

    def __init__(self):
        super().__init__()
        self.client = OpenAI(
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama"
        )
        self._model = settings.ollama_model

    @property
    def model_name(self) -> str:
        return self._model

    def _raw_chat(self, messages: list[dict], stream: bool = False) -> str:
        response = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=stream,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    def _raw_chat_stream(self, messages: list[dict]) -> Generator[str, None, None]:
        response = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            temperature=0.3,
        )
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class OpenAIProvider(LLMProvider):
    """OpenAI API"""

    def __init__(self):
        super().__init__()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY 未设置")
        self.client = OpenAI(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key
        )
        self._model = settings.openai_model

    @property
    def model_name(self) -> str:
        return self._model

    def _raw_chat(self, messages: list[dict], stream: bool = False) -> str:
        import sys
        key_prefix = (settings.openai_api_key or "")[:15] + "..." if settings.openai_api_key else "NONE"
        print(f"[LLM-DEBUG] 调用: base_url={settings.openai_base_url} model={self._model} key={key_prefix}", file=sys.stderr)
        response = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=stream,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    def _raw_chat_stream(self, messages: list[dict]) -> Generator[str, None, None]:
        response = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            temperature=0.3,
        )
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class ZhipuProvider(LLMProvider):
    """智谱 GLM API"""

    def __init__(self):
        super().__init__()
        if not settings.zhipu_api_key:
            raise ValueError("ZHIPU_API_KEY 未设置")
        self.client = OpenAI(
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key=settings.zhipu_api_key
        )
        self._model = settings.zhipu_model

    @property
    def model_name(self) -> str:
        return self._model

    def _raw_chat(self, messages: list[dict], stream: bool = False) -> str:
        response = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=stream,
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    def _raw_chat_stream(self, messages: list[dict]) -> Generator[str, None, None]:
        response = self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
            temperature=0.3,
        )
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content



def detect_model_tier(model_name: str) -> str:
    """检测模型能力层级: small / medium / large"""
    small_patterns = ["7b", "8b", "3b", "1b", "qwen2.5", "qwen3", "llama3", "mistral", "phi"]
    medium_patterns = ["14b", "32b", "qwen2.5-32b", "llama3-70b"]
    large_patterns = ["gpt-4", "gpt-4o", "claude", "glm-4", "deepseek", "qwen-max"]
    ml = model_name.lower()
    for p in large_patterns:
        if p in ml:
            return "large"
    for p in medium_patterns:
        if p in ml:
            return "medium"
    for p in small_patterns:
        if p in ml:
            return "small"
    return "medium"  # 默认中等

def get_llm() -> LLMProvider:
    """工厂函数：根据配置返回对应的 LLM Provider"""
    provider_map = {
        "ollama": OllamaProvider,
        "openai": OpenAIProvider,
        "zhipu": ZhipuProvider,
    }
    provider_class = provider_map.get(settings.llm_provider)
    if provider_class is None:
        raise ValueError(f"不支持的 LLM Provider: {settings.llm_provider}")
    return provider_class()

