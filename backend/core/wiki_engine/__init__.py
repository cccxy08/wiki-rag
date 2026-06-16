"""WikiEngine — 门面类，继承所有 Mixin，保持导入路径不变

Usage:
    from core.wiki_engine import WikiEngine
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

from core.config import settings
from core.llm_provider import get_llm, LLMProvider

from .core import WikiQueryMixin
from .ingest import WikiIngestMixin
from .index import WikiIndexMixin
from .backlinks import WikiBacklinksMixin
from .lint import WikiLintMixin
from .tags import WikiTagsMixin
from .version import WikiVersionMixin


class WikiEngine(WikiQueryMixin, WikiIngestMixin, WikiIndexMixin, WikiBacklinksMixin, WikiLintMixin, WikiTagsMixin, WikiVersionMixin):
    _instance: Optional["WikiEngine"] = None

    @classmethod
    def get_instance(cls) -> "WikiEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.paths = settings.get_wiki_paths()
        self.llm = get_llm()
        self._ensure_dirs()
        self._ensure_base_files()
        self._page_cache = {}

    def _ensure_dirs(self):
        for key in ["raw", "pages"]:
            self.paths[key].mkdir(parents=True, exist_ok=True)
        (self.paths["raw"] / "assets").mkdir(exist_ok=True)

    def _ensure_base_files(self):
        if not self.paths["index"].exists():
            self.paths["index"].write_text("# Wiki index\n\n> Auto-maintained\n\n", encoding="utf-8")
        if not self.paths["log"].exists():
            self.paths["log"].write_text("# Operation log\n\n> Chronological\n\n", encoding="utf-8")
        bl_path = self.paths["data"] / "backlinks.json"
        if not bl_path.exists():
            bl_path.write_text("{}", encoding="utf-8")
        tp = self.paths["data"] / "tags.json"
        if not tp.exists():
            tp.write_text("[]", encoding="utf-8")

    @property
    def _backlinks_path(self) -> Path:
        return self.paths["data"] / "backlinks.json"

    @property
    def _tags_path(self) -> Path:
        return self.paths["data"] / "tags.json"

    def _get_schema(self) -> str:
        sp = self.paths["data"] / "WIKI-SCHEMA.md"
        return sp.read_text(encoding="utf-8") if sp.exists() else ""

    @staticmethod
    def _safe_filename(name: str) -> str:
        return re.sub(r'[\\/*?:"<>|]', "_", name).strip()