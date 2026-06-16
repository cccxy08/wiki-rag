"""WikiEngine 标签管理 Mixin — tags.json 读写、页面标签提取与同步"""
from __future__ import annotations
import re
import json


class WikiTagsMixin:
    def _read_tags(self) -> list[str]:
        try:
            return json.loads(self._tags_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _extract_tags_from_page(self, content: str) -> list[str]:
        m = re.search(r"^tags:\s*\[(.+?)\]", content, re.MULTILINE)
        if m:
            return [t.strip().strip('"\'') for t in m.group(1).split(",") if t.strip()]
        m = re.search(r"^tags:\s*(.+)$", content, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            if val and val != "[]":
                return [t.strip() for t in val.split(",") if t.strip()]
        return []

    def _sync_tags_from_page(self, content: str):
        page_tags = self._extract_tags_from_page(content)
        if not page_tags:
            return
        existing = self._read_tags()
        merged = list(set(existing + page_tags))
        if sorted(merged) != sorted(existing):
            self._tags_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    def _format_tags_context(self) -> str:
        tags = self._read_tags()
        if not tags:
            return ""
        return f"已有页面使用的 tags：{json.dumps(tags, ensure_ascii=False)}。优先使用已有 tags，含义不匹配时可以创建新 tag。"

    def get_page_tags(self, page_title: str) -> list[str]:
        content = self.read_page(page_title)
        if not content:
            return []
        return self._extract_tags_from_page(content)