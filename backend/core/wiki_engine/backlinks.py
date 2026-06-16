"""WikiEngine 交叉引用 Mixin — backlinks.json 双向引用维护"""
from __future__ import annotations
import re
import json


class WikiBacklinksMixin:
    def _get_backlinks_data(self) -> dict:
        try:
            return json.loads(self._backlinks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_backlinks_data(self, data: dict):
        self._backlinks_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def get_backlinks(self, page_name: str) -> dict:
        data = self._get_backlinks_data()
        return data.get(page_name, {"incoming": [], "outgoing": []})

    def _update_backlinks_for_page(self, title: str, content: str) -> list[str]:
        refs = re.findall(r"\[\[(.+?)\]\]", content)
        refs = list(set(refs))

        data = self._get_backlinks_data()
        modified = []

        if title not in data:
            data[title] = {"incoming": [], "outgoing": []}

        old_outgoing = set(data[title].get("outgoing", []))
        new_outgoing = set(refs)
        if old_outgoing != new_outgoing:
            data[title]["outgoing"] = sorted(new_outgoing)
            modified.append(title)

        for ref in refs:
            if ref not in data:
                data[ref] = {"incoming": [], "outgoing": []}
            incoming = set(data[ref].get("incoming", []))
            incoming.add(title)
            data[ref]["incoming"] = sorted(incoming)

        removed = old_outgoing - new_outgoing
        for ref in removed:
            if ref in data:
                incoming = set(data[ref].get("incoming", []))
                incoming.discard(title)
                data[ref]["incoming"] = sorted(incoming)

        self._save_backlinks_data(data)
        return modified