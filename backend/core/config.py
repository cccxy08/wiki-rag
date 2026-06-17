import os
from pydantic_settings import BaseSettings
from typing import Optional, Literal
from pathlib import Path

HF_DATA_DIR = os.environ.get("HF_HOME", "/data") if os.environ.get("SPACE_ID") else None
RENDER_ENV = bool(os.environ.get("RENDER", ""))

class Settings(BaseSettings):
    llm_provider: Literal["ollama", "openai", "zhipu", "minimax"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3"
    ollama_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"
    zhipu_api_key: Optional[str] = None
    zhipu_model: str = "glm-4"

    # ===== MiniMax 配置 =====
    minimax_api_key: Optional[str] = None
    minimax_model: str = "MiniMax-Text-01"
    minimax_multimodal_model: str = "MiniMax-VL-01"
    minimax_base_url: str = "https://api.minimax.chat/v1"

    # ===== Embedding 配置 =====
    # local: 本地 SentenceTransformer（需 ~500MB 内存加载 bge-small-zh）
    # zhipu: 智谱 Embedding API（推荐，零内存，¥0.5/百万token）
    # openai: OpenAI Embedding API（零内存，$0.02/百万token）
    embedding_provider: Literal["local", "zhipu", "openai"] = "local"
    embedding_model: str = "BAAI/bge-small-zh"  # local 模式下的模型名
    embedding_device: str = "cpu"                # local 模式下的设备
    zhipu_embedding_model: str = "embedding-3"   # 智谱 Embedding 模型名
    openai_embedding_model: str = "text-embedding-3-small"  # OpenAI Embedding 模型名

    # ===== 向量库配置 =====
    chroma_persist_dir: str = "./chroma_db"
    chroma_collection_name: str = "enterprise_knowledge"
    chroma_parent_collection_name: str = "enterprise_knowledge_parents"

    # ===== Wiki 数据路径 =====
    wiki_data_dir: str = "../wiki-data"
    wiki_raw_dir: str = "../wiki-data/raw"
    wiki_pages_dir: str = "../wiki-data/wiki"

    # ===== 切片配置 =====
    chunk_size: int = 500
    chunk_overlap: int = 50
    chunk_strategy: dict = {}
    retrieval_top_k: int = 10
    parent_child_enabled: bool = True
    parent_chunk_size: int = 750   # Parent 大切片（上下文完整）
    child_chunk_size: int = 250   # Child 小切片（检索精度高）
    child_chunk_overlap: int = 50
    parent_chunk_overlap: int = 20
    rerank_top_k: int = 3
    similarity_threshold: float = 2.0
    bm25_weight: float = 0.3

    # ===== Reranker 配置 =====
    reranker_enabled: bool = False  # 关闭可省 ~1.2GB 内存，BM25+向量混合检索已够用
    reranker_model_path: str = "./.models/BAAI/bge-reranker-base"

    # ===== Agent 配置 =====
    agent_max_iterations: int = 5
    agent_min_self_score: int = 7
    max_history_rounds: int = 10
    summary_enabled: bool = True
    query_cache_ttl_seconds: int = 3600
    score_cache_ttl_seconds: int = 86400
    llm_max_retries: int = 3
    llm_retry_delay_base: float = 1.0

    # ===== 服务配置 =====
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_dir: str = "./logs"
    log_level: str = "INFO"
    log_format: str = "json"

    # ===== 安全配置 =====
    auth_enabled: bool = False
    api_keys: str = "[]"
    cors_origins: str = ""
    rate_limit_per_minute: int = 60
    rate_limit_admin_per_minute: int = 20

    # ===== 缓存配置 =====
    cache_provider: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"

    # ===== 批量导入配置 =====
    batch_max_files: int = 50
    max_file_size_mb: int = 100
    batch_concurrency: int = 3
    max_retry_count: int = 3
    supported_file_types: str = ".pdf,.txt,.md,.docx,.xlsx,.xls,.csv"
    history_retention_days: int = 90
    history_default_page_size: int = 20
    history_max_page_size: int = 100

    # ===== 沉淀审核配置 =====
    precipitation_enabled: bool = True
    precipitation_score_threshold: int = 7
    precipitation_confirm_timeout_seconds: int = 300
    version_snapshot_max_versions: int = 10

    # ===== 钉钉机器人配置 =====
    dingtalk_enabled: bool = False
    dingtalk_client_id: str = ""
    dingtalk_client_secret: str = ""
    dingtalk_robot_code: str = ""
    dingtalk_mode: Literal["stream", "webhook"] = "webhook"
    dingtalk_admin_ids: str = ""
    dingtalk_admin_group_webhook: str = ""
    dingtalk_message_timeout_seconds: int = 10
    dingtalk_file_download_timeout_seconds: int = 60
    dingtalk_stream_reconnect_max_interval_seconds: int = 60

    # ===== 钉钉云盘配置 =====
    dingtalk_drive_space_id: str = ""
    dingtalk_drive_folder_id: str = ""
    dingtalk_drive_sync_interval_hours: int = 72
    dingtalk_union_id: str = ""
    dingtalk_drive_proxy_url: str = ""
    dingtalk_drive_user_id: str = ""

    # ===== 知识提取配置 =====
    knowledge_extract_interval_hours: int = 72
    knowledge_extract_max_conversations: int = 50

    # ===== 目录监控配置 =====
    watcher_allowed_dirs: str = ""
    watcher_stable_wait_seconds: float = 5.0
    watcher_health_check_interval_seconds: int = 30

    # ===== URL 抓取配置 =====
    url_fetch_timeout_seconds: int = 30
    url_max_response_size_mb: int = 50
    url_allowed_schemes: str = "http,https"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if HF_DATA_DIR:
            self._apply_hf_paths()
        elif RENDER_ENV:
            self._apply_render_paths()

    def _apply_hf_paths(self):
        self.chroma_persist_dir = f"{HF_DATA_DIR}/chroma_db"
        self.wiki_data_dir = f"{HF_DATA_DIR}/wiki-data"
        self.wiki_raw_dir = f"{HF_DATA_DIR}/wiki-data/raw"
        self.wiki_pages_dir = f"{HF_DATA_DIR}/wiki-data/wiki"
        self.log_dir = f"{HF_DATA_DIR}/logs"

    def _apply_render_paths(self):
        self.chroma_persist_dir = "/app/chroma_db"
        self.wiki_data_dir = "/app/wiki-data"
        self.wiki_raw_dir = "/app/wiki-data/raw"
        self.wiki_pages_dir = "/app/wiki-data/wiki"
        self.log_dir = "/app/logs"

    def get_wiki_paths(self):
        return {
            "data": Path(self.wiki_data_dir),
            "raw": Path(self.wiki_raw_dir),
            "pages": Path(self.wiki_pages_dir),
            "index": Path(self.wiki_pages_dir) / "index.md",
            "log": Path(self.wiki_pages_dir) / "log.md",
        }

    def save_to_env(self, updates: dict[str, object]) -> list[str]:
        """将指定字段持久化写入 .env 文件，同时更新内存值"""
        env_path = Path(self.model_config.get("env_file", ".env"))
        if not env_path.is_absolute():
            env_path = Path(os.getcwd()) / env_path

        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        existing_keys: dict[str, int] = {}
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                existing_keys[key.upper()] = i

        saved: list[str] = []
        for key, value in updates.items():
            env_key = key.upper()
            if isinstance(value, bool):
                str_val = "true" if value else "false"
            else:
                str_val = str(value)
            line_str = f"{env_key}={str_val}"

            if env_key in existing_keys:
                lines[existing_keys[env_key]] = line_str
            else:
                lines.append(line_str)

            setattr(self, key, value)
            saved.append(key)

        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return saved

settings = Settings()
