"""WikiEngine 健康检查 Mixin — 孤儿页面、断链、过期页面检测"""
from __future__ import annotations
import re
from datetime import datetime


class WikiLintMixin:
    def lint(self) -> list:
        issues = []
        all_pages = {f.stem: f for f in self._list_pages()}

        index_path = self.paths["index"]
        index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        indexed = set()
        for line in index_text.split("\n"):
            if "](" in line:
                m = re.search(r"\(\.?/?(.+?\.md)\)", line)
                if m:
                    indexed.add(m.group(1).replace(".md", ""))

        for name in all_pages:
            if name not in indexed and len(all_pages) > 1:
                issues.append({
                    "type": "orphan",
                    "pages": [name],
                    "description": f"页面「{name}」未被索引",
                    "severity": "warning"
                })

        for name, fp in all_pages.items():
            content = fp.read_text(encoding="utf-8")
            content_clean = re.sub(r"```[\s\S]*?```", "", content)
            content_clean = re.sub(r"`[^`]+`", "", content_clean)
            refs = re.findall(r"\[\[(.+?)\]\]", content_clean)
            for ref in refs:
                if ref not in all_pages:
                    issues.append({
                        "type": "missing_crossref",
                        "pages": [name, ref],
                        "description": f"「{name}」引用了不存在的页面「{ref}」",
                        "severity": "error"
                    })

        for name, fp in all_pages.items():
            content = fp.read_text(encoding="utf-8")
            m = re.search(r"valid_until:\s*(\d{4}-\d{2}-\d{2})", content)
            if m:
                try:
                    deadline = datetime.strptime(m.group(1), "%Y-%m-%d")
                    if deadline < datetime.now():
                        issues.append({
                            "type": "expired",
                            "pages": [name],
                            "description": f"页面「{name}」有效期已过 ({m.group(1)})",
                            "severity": "warning"
                        })
                except ValueError:
                    pass

        return issues