"""WikiEngine 版本快照 Mixin — 页面写入前自动保存快照，支持版本列表和回滚"""
from __future__ import annotations
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class WikiVersionMixin:
    def _get_versions_dir(self, page_title: str) -> Path:
        safe = self._safe_filename(page_title)
        versions_dir = self.paths["data"] / "versions" / safe
        versions_dir.mkdir(parents=True, exist_ok=True)
        return versions_dir

    def save_version_snapshot(self, page_title: str) -> Optional[str]:
        content = self.read_page(page_title)
        if not content:
            return None
        versions_dir = self._get_versions_dir(page_title)
        ts = time.strftime("%Y%m%d_%H%M%S")
        snapshot_path = versions_dir / f"{ts}.md"
        snapshot_path.write_text(content, encoding="utf-8")
        logger.info(f"Version snapshot saved: {page_title} -> {snapshot_path.name}")
        return str(snapshot_path)

    def list_versions(self, page_title: str) -> list[dict]:
        versions_dir = self._get_versions_dir(page_title)
        snapshots = sorted(versions_dir.glob("*.md"))
        result = []
        for sp in snapshots:
            name = sp.stem
            try:
                dt = time.strptime(name, "%Y%m%d_%H%M%S")
                display = time.strftime("%Y-%m-%d %H:%M:%S", dt)
            except ValueError:
                display = name
            result.append({
                "filename": sp.name,
                "path": str(sp),
                "timestamp": display,
                "size": sp.stat().st_size,
            })
        return result

    def get_version_content(self, page_title: str, version_filename: str) -> Optional[str]:
        versions_dir = self._get_versions_dir(page_title)
        path = versions_dir / version_filename
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def restore_version(self, page_title: str, version_filename: str) -> bool:
        content = self.get_version_content(page_title, version_filename)
        if content is None:
            return False
        self.save_version_snapshot(page_title)
        safe = self._safe_filename(page_title)
        page_path = self.paths["pages"] / f"{safe}.md"
        page_path.write_text(content, encoding="utf-8")
        self._page_cache.pop(page_title, None)
        logger.info(f"Wiki page restored: {page_title} from version {version_filename}")
        return True

    def delete_version(self, page_title: str, version_filename: str) -> bool:
        versions_dir = self._get_versions_dir(page_title)
        path = versions_dir / version_filename
        if not path.exists():
            return False
        path.unlink()
        return True