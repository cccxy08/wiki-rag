"""Embedding 抽象层 — 本地/智谱/OpenAI 三种实现"""
from __future__ import annotations
import logging
from typing import Union

from core.config import settings

logger = logging.getLogger(__name__)


class BaseEmbedding:
    def encode(self, texts: Union[str, list[str]], show_progress_bar: bool = False, **kwargs) -> list[list[float]]:
        raise NotImplementedError

    def get_sentence_embedding_dimension(self) -> int:
        raise NotImplementedError


class LocalEmbedding(BaseEmbedding):
    def __init__(self, model_name: str, device: str = "cpu"):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name, device=device)

    def encode(self, texts, show_progress_bar=False, **kwargs):
        return self._model.encode(texts, show_progress_bar=show_progress_bar, **kwargs)

    def get_sentence_embedding_dimension(self) -> int:
        return self._model.get_sentence_embedding_dimension()


class ZhipuAPIEmbedding(BaseEmbedding):
    MODEL_DIMS = {"embedding-3": 2048, "embedding-2": 1024}

    def __init__(self, model: str = "embedding-3", api_key: str = None, batch_size: int = 16):
        from openai import OpenAI
        self._model = model
        self._dimension = self.MODEL_DIMS.get(model, 2048)
        self._batch_size = batch_size
        api_key = api_key or settings.zhipu_api_key
        if not api_key:
            raise ValueError("智谱 Embedding 需要 ZHIPU_API_KEY，请在 .env 中配置")
        self._client = OpenAI(base_url="https://open.bigmodel.cn/api/paas/v4", api_key=api_key)

    def encode(self, texts, show_progress_bar=False, **kwargs):
        import numpy as np
        was_single = isinstance(texts, str)
        if was_single:
            texts = [texts]
        all_embeddings = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            try:
                response = self._client.embeddings.create(model=self._model, input=batch)
                all_embeddings.extend([item.embedding for item in response.data])
            except Exception as e:
                logger.error(f"智谱 Embedding API 调用失败 (batch {i // self._batch_size}): {e}")
                all_embeddings.extend([[0.0] * self._dimension] * len(batch))
        result = np.array(all_embeddings)
        if was_single:
            return result[0]
        return result

    def get_sentence_embedding_dimension(self) -> int:
        return self._dimension


class OpenAIAPIEmbedding(BaseEmbedding):
    MODEL_DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}

    def __init__(self, model: str = "text-embedding-3-small", api_key: str = None,
                 base_url: str = None, batch_size: int = 16):
        from openai import OpenAI
        self._model = model
        self._dimension = self.MODEL_DIMS.get(model, 1536)
        self._batch_size = batch_size
        api_key = api_key or settings.openai_api_key
        base_url = base_url or settings.openai_base_url
        if not api_key:
            raise ValueError("OpenAI Embedding 需要 OPENAI_API_KEY，请在 .env 中配置")
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def encode(self, texts, show_progress_bar=False, **kwargs):
        import numpy as np
        was_single = isinstance(texts, str)
        if was_single:
            texts = [texts]
        all_embeddings = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            try:
                response = self._client.embeddings.create(model=self._model, input=batch)
                all_embeddings.extend([item.embedding for item in response.data])
            except Exception as e:
                logger.error(f"OpenAI Embedding API 调用失败 (batch {i // self._batch_size}): {e}")
                all_embeddings.extend([[0.0] * self._dimension] * len(batch))
        result = np.array(all_embeddings)
        if was_single:
            return result[0]
        return result

    def get_sentence_embedding_dimension(self) -> int:
        return self._dimension


def create_embedding() -> BaseEmbedding:
    provider = settings.embedding_provider
    logger.info(f"初始化 Embedding: provider={provider}")
    if provider == "zhipu":
        return ZhipuAPIEmbedding(model=settings.zhipu_embedding_model)
    elif provider == "openai":
        return OpenAIAPIEmbedding(model=settings.openai_embedding_model)
    else:
        return LocalEmbedding(model_name=settings.embedding_model, device=settings.embedding_device)