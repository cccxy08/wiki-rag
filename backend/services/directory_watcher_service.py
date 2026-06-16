"""目录监控服务 — watchdog 驱动的文件新增自动摄入"""
from __future__ import annotations
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)


class _IngestEventHandler:
    def __init__(self, service: DirectoryWatcherService, dir_id: str, directory: str, file_patterns: list[str] = None):
        self._service = service
        self._dir_id = dir_id
        self._directory = directory
        self._file_patterns = file_patterns
        self._seen_hashes: set[str] = set()

    def dispatch(self, event):
        if event.is_directory:
            return
        if not hasattr(event, 'src_path'):
            return
        if event.event_type != 'created':
            return
        self._on_created(event.src_path)

    def _on_created(self, src_path: str):
        path = Path(src_path)
        if not self._is_supported(path):
            return
        if not self._wait_for_stable(path):
            return
        if self._is_duplicate(path):
            logger.info(f"Duplicate file skipped: {path}")
            return
        self._trigger_ingest(path)

    def _is_supported(self, path: Path) -> bool:
        supported = settings.supported_file_types.split(",")
        return any(path.suffix.lower() == ext.strip().lower() for ext in supported if ext.strip())

    def _wait_for_stable(self, path: Path, max_wait: float = 30.0) -> bool:
        wait = settings.watcher_stable_wait_seconds
        deadline = time.time() + max_wait
        prev_size = -1
        while time.time() < deadline:
            try:
                current_size = path.stat().st_size
            except OSError:
                time.sleep(0.5)
                continue
            if current_size == prev_size and current_size > 0:
                return True
            prev_size = current_size
            time.sleep(wait / 3)
        return prev_size > 0

    def _is_duplicate(self, path: Path) -> bool:
        try:
            content = path.read_bytes()
            file_hash = hashlib.md5(content).hexdigest()
            if file_hash in self._seen_hashes:
                return True
            self._seen_hashes.add(file_hash)
            if len(self._seen_hashes) > 1000:
                self._seen_hashes = set(list(self._seen_hashes)[-500:])
            return False
        except Exception:
            return False

    def _trigger_ingest(self, path: Path):
        try:
            from services.ingest_service import IngestService
            ingest = IngestService()
            content = path.read_bytes()
            result = ingest.ingest_file(content, path.name)
            logger.info(f"Auto-ingested from watcher [{self._dir_id}]: {path.name} -> {result.get('status', 'unknown')}")
        except Exception as e:
            logger.error(f"Auto-ingest failed for {path.name}: {e}")


class DirectoryWatcherService:
    def __init__(self):
        self._watchers: dict[str, dict] = {}

    def add_watcher(self, directory_path: str, file_patterns: list[str] = None) -> dict:
        allowed = [d.strip() for d in settings.watcher_allowed_dirs.split(",") if d.strip()]
        if allowed:
            resolved = str(Path(directory_path).resolve())
            if not any(resolved.startswith(str(Path(d).resolve())) for d in allowed):
                return {"error": "Directory not in allowed list", "status": "forbidden"}

        dir_path = Path(directory_path)
        if not dir_path.exists() or not dir_path.is_dir():
            return {"error": "Directory does not exist", "status": "not_found"}

        dir_id = str(uuid.uuid4())[:8]
        handler = _IngestEventHandler(self, dir_id, directory_path, file_patterns)

        try:
            from watchdog.observers import Observer
            observer = Observer(daemon=True)
            observer.schedule(handler, directory_path, recursive=False)
            observer.start()
        except ImportError:
            return {"error": "watchdog not installed", "status": "dependency_missing"}

        self._watchers[dir_id] = {
            "dirId": dir_id,
            "directoryPath": directory_path,
            "filePatterns": file_patterns or [],
            "observer": observer,
            "handler": handler,
            "status": "running",
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "lastProcessedFile": None,
        }
        logger.info(f"Directory watcher started: {dir_id} -> {directory_path}")
        return {"dirId": dir_id, "directoryPath": directory_path, "status": "running"}

    def remove_watcher(self, dir_id: str) -> dict:
        watcher = self._watchers.get(dir_id)
        if not watcher:
            return {"error": "Watcher not found", "status": "not_found"}
        try:
            watcher["observer"].stop()
            watcher["observer"].join(timeout=5)
        except Exception as e:
            logger.warning(f"Error stopping watcher {dir_id}: {e}")
        del self._watchers[dir_id]
        logger.info(f"Directory watcher stopped: {dir_id}")
        return {"dirId": dir_id, "status": "stopped"}

    def list_watchers(self) -> list[dict]:
        result = []
        for dir_id, w in self._watchers.items():
            result.append({
                "dirId": w["dirId"],
                "directoryPath": w["directoryPath"],
                "filePatterns": w["filePatterns"],
                "status": w["status"],
                "startedAt": w["startedAt"],
                "lastProcessedFile": w.get("lastProcessedFile"),
            })
        return result

    def health_check(self):
        for dir_id, w in list(self._watchers.items()):
            observer = w["observer"]
            if not observer.is_alive():
                logger.warning(f"Watcher {dir_id} observer died, restarting...")
                try:
                    observer.stop()
                except Exception:
                    pass
                new_handler = _IngestEventHandler(self, dir_id, w["directoryPath"], w["filePatterns"])
                try:
                    from watchdog.observers import Observer
                    new_observer = Observer(daemon=True)
                    new_observer.schedule(new_handler, w["directoryPath"], recursive=False)
                    new_observer.start()
                    w["observer"] = new_observer
                    w["handler"] = new_handler
                    w["status"] = "running"
                    logger.info(f"Watcher {dir_id} restarted successfully")
                except Exception as e:
                    logger.error(f"Failed to restart watcher {dir_id}: {e}")
                    w["status"] = "error"

    def stop_all(self):
        for dir_id in list(self._watchers.keys()):
            self.remove_watcher(dir_id)