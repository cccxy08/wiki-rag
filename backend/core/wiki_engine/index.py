"""WikiEngine 索引管理 Mixin — index.md 维护、页面列表、日志"""
from __future__ import annotations
import re
import time
from pathlib import Path
from typing import Optional


class WikiIndexMixin:
    def _list_pages(self) -> list[Path]:
        return [f for f in self.paths["pages"].glob("*.md")
                if f.name not in ("index.md", "log.md")]

    def page_count(self) -> int:
        return len(self._list_pages())

    def get_index(self) -> str:
        p = self.paths["index"]
        if p.exists():
            return p.read_text(encoding="utf-8")
        pages = sorted(self._list_pages())
        lines = ["# Wiki index\n", "> Auto-generated\n"]
        for fp in pages:
            title = fp.stem
            lines.append(f"- [{title}](./{fp.name}) | {title} | | {title}")
        return "\n".join(lines)

    def read_page(self, title: str) -> Optional[str]:
        if title in self._page_cache:
            return self._page_cache[title]
        safe = self._safe_filename(title)
        p = self.paths["pages"] / f"{safe}.md"
        if p.exists():
            content = p.read_text(encoding="utf-8")
            self._page_cache[title] = content
            return content
        for f in self.paths["pages"].glob("*.md"):
            if f.stem == safe or f.stem.lower() == title.lower():
                content = f.read_text(encoding="utf-8")
                self._page_cache[title] = content
                return content
        return None

    def _update_index(self, title, fn, source_name):
        p = self.paths["index"]
        current = p.read_text(encoding="utf-8") if p.exists() else ""
        entry = f"- [{title}](./{fn}) | {title} | | {source_name}"
        if entry not in current:
            p.write_text(current.rstrip() + "\n" + entry + "\n", encoding="utf-8")

    def _append_log(self, action, detail):
        p = self.paths["log"]
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"## [{ts}] {action}\n{detail}\n\n"
        current = p.read_text(encoding="utf-8") if p.exists() else ""
        p.write_text(current + entry, encoding="utf-8")
        return f"[{ts}] {action}: {detail}"

    _log = _append_log