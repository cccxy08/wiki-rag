import os
import pytest

os.environ["LLM_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
os.environ["OPENAI_MODEL"] = "gpt-4o"
os.environ["EMBEDDING_PROVIDER"] = "zhipu"
os.environ["ZHIPU_API_KEY"] = "test-key"
os.environ["DINGTALK_ENABLED"] = "false"
os.environ["RERANKER_ENABLED"] = "false"


@pytest.fixture
def app():
    from main import app as _app
    return _app


@pytest.fixture
def client(app):
    from httpx import AsyncClient, ASGITransport
    import asyncio

    transport = ASGITransport(app=app)
    async_client = AsyncClient(transport=transport, base_url="http://test")
    return async_client


@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
