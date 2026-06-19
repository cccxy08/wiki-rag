from __future__ import annotations
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable

from core.config import settings

logger = logging.getLogger(__name__)


class DriveSyncScheduler:
    _instance: Optional[DriveSyncScheduler] = None

    @classmethod
    def get_instance(cls) -> DriveSyncScheduler:
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._try_auto_start()
        return cls._instance

    def _try_auto_start(self):
        if self._timer:
            return
        if not settings.dingtalk_drive_proxy_url or not settings.dingtalk_drive_folder_id:
            return
        try:
            self.start()
        except Exception as e:
            logger.warning(f"Auto-start scheduler failed: {e}")

    def __init__(self):
        try:
            self._state_path = Path(settings.chroma_persist_dir).parent / "drive_sync_state.json"
        except Exception:
            self._state_path = Path("./drive_sync_state.json")
        self._state = self._load_state()
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._lock = threading.Lock()
        self._progress_version = 0
        self._progress = self._reset_progress()

    def _reset_progress(self) -> dict:
        return {
            "phase": "idle",
            "current_file": "",
            "current_file_size": 0,
            "total_files": 0,
            "processed_files": 0,
            "synced_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "started_at": None,
            "files": [],
            "log": [],
            "error_message": None,
        }

    def _add_log(self, message: str, level: str = "info"):
        with self._lock:
            entry = {
                "time": datetime.utcnow().strftime("%H:%M:%S"),
                "level": level,
                "message": message,
            }
            self._progress["log"].append(entry)
            if len(self._progress["log"]) > 100:
                self._progress["log"] = self._progress["log"][-100:]
            self._progress_version += 1

    def on_progress(self, event: str, file_info: dict, detail: str = "", result: dict = None):
        with self._lock:
            if event == "listing":
                self._progress["phase"] = "listing"
                self._progress["current_file"] = ""
                self._add_log(f"正在列出文件...")
            elif event == "listed":
                total = file_info.get("total_files", 0)
                self._progress["total_files"] = total
                self._progress["phase"] = "syncing"
                self._add_log(f"共发现 {total} 个文件需要处理")
            elif event == "downloading":
                name = file_info.get("name", "")
                size = file_info.get("size", 0)
                self._progress["phase"] = "downloading"
                self._progress["current_file"] = name
                self._progress["current_file_size"] = size
                size_str = f"{size/1024:.0f}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
                self._add_log(f"下载 {name} ({size_str})")
            elif event == "downloaded":
                name = file_info.get("name", "")
                self._progress["phase"] = "ingesting"
                self._add_log(f"消化 {name} → 知识库...")
            elif event == "synced":
                name = file_info.get("name", "")
                chunks = 0
                if result and result.get("rag_chunks"):
                    chunks = result["rag_chunks"]
                self._progress["synced_count"] += 1
                self._progress["processed_files"] += 1
                self._progress["current_file"] = ""
                file_entry = {
                    "name": name,
                    "status": "synced",
                    "chunks": chunks,
                    "size": file_info.get("size", 0),
                }
                self._progress["files"].append(file_entry)
                self._add_log(f"完成 {name} → {chunks}个知识切片", "success")
            elif event == "skipped":
                name = file_info.get("name", "")
                reason = detail or "未修改"
                self._progress["skipped_count"] += 1
                self._progress["processed_files"] += 1
                file_entry = {
                    "name": name,
                    "status": "skipped",
                    "reason": reason,
                    "size": file_info.get("size", 0),
                }
                self._progress["files"].append(file_entry)
                self._add_log(f"跳过 {name} ({reason})", "skip")
            elif event == "error":
                name = file_info.get("name", "")
                error_msg = detail or "unknown error"
                self._progress["error_count"] += 1
                self._progress["processed_files"] += 1
                self._progress["current_file"] = ""
                file_entry = {
                    "name": name,
                    "status": "error",
                    "error": error_msg,
                    "size": file_info.get("size", 0),
                }
                self._progress["files"].append(file_entry)
                self._add_log(f"失败 {name}: {error_msg}", "error")
            elif event == "complete":
                self._progress["phase"] = "complete"
                self._progress["current_file"] = ""
                sc = self._progress["synced_count"]
                sk = self._progress["skipped_count"]
                ec = self._progress["error_count"]
                self._add_log(f"同步完成! 新增{sc} 跳过{sk} 失败{ec}", "success")
            self._progress_version += 1

    def get_progress(self) -> dict:
        with self._lock:
            p = dict(self._progress)
            p["files"] = list(p["files"])
            p["log"] = list(p["log"])
            p["is_syncing"] = self._running
            p["version"] = self._progress_version
            if p["total_files"] > 0:
                p["progress_pct"] = round(p["processed_files"] / p["total_files"] * 100, 1)
            else:
                p["progress_pct"] = 0
            return p

    def _load_state(self) -> dict:
        default = {
            "last_sync_time": None,
            "next_sync_time": None,
            "sync_interval_hours": settings.dingtalk_drive_sync_interval_hours,
            "synced_files": {},
            "last_sync_result": None,
        }
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                default.update(data)
            except Exception as e:
                logger.warning(f"Failed to load sync state: {e}")
        return default

    def _save_state(self):
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to save sync state: {e}")

    def get_status(self) -> dict:
        now = datetime.utcnow()
        last_sync = self._state.get("last_sync_time")
        next_sync = self._state.get("next_sync_time")
        interval = self._state.get("sync_interval_hours", settings.dingtalk_drive_sync_interval_hours)

        countdown_seconds = 0
        if next_sync:
            try:
                next_dt = datetime.fromisoformat(next_sync)
                diff = (next_dt - now).total_seconds()
                countdown_seconds = max(0, int(diff))
            except Exception:
                pass

        synced_files = self._state.get("synced_files", {})
        return {
            "enabled": bool(settings.dingtalk_drive_proxy_url and settings.dingtalk_drive_folder_id),
            "sync_interval_hours": interval,
            "last_sync_time": last_sync,
            "next_sync_time": next_sync,
            "countdown_seconds": countdown_seconds,
            "synced_file_count": len(synced_files),
            "is_syncing": self._running,
            "last_sync_result": self._state.get("last_sync_result"),
        }

    def set_interval(self, hours: int):
        self._state["sync_interval_hours"] = hours
        settings.dingtalk_drive_sync_interval_hours = hours
        self._save_state()
        self._schedule_next()
        logger.info(f"Drive sync interval set to {hours}h")

    def should_sync_file(self, file_id: str, modify_time: str) -> bool:
        synced = self._state.get("synced_files", {})
        if file_id not in synced:
            return True
        last_modify = synced[file_id].get("modify_time", "")
        return modify_time > last_modify

    def mark_file_synced(self, file_id: str, modify_time: str, filename: str):
        if "synced_files" not in self._state:
            self._state["synced_files"] = {}
        self._state["synced_files"][file_id] = {
            "modify_time": modify_time,
            "filename": filename,
            "synced_at": datetime.utcnow().isoformat(),
        }

    def mark_sync_complete(self, result: dict):
        now = datetime.utcnow()
        interval = self._state.get("sync_interval_hours", settings.dingtalk_drive_sync_interval_hours)
        self._state["last_sync_time"] = now.isoformat()
        self._state["next_sync_time"] = (now + timedelta(hours=interval)).isoformat()
        self._state["last_sync_result"] = result
        self._save_state()

    def start(self):
        if self._timer:
            return
        next_sync = self._state.get("next_sync_time")
        if next_sync:
            try:
                next_dt = datetime.fromisoformat(next_sync)
                delay = max(60, (next_dt - datetime.utcnow()).total_seconds())
            except Exception:
                delay = 120
        else:
            delay = 120

        self._schedule_after(delay)
        logger.info(f"Drive sync scheduler started, first sync in {delay:.0f}s")

    def stop(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _schedule_after(self, delay_seconds: float):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(delay_seconds, self._do_sync)
        self._timer.daemon = True
        self._timer.start()

    def _schedule_next(self):
        interval = self._state.get("sync_interval_hours", settings.dingtalk_drive_sync_interval_hours)
        self._schedule_after(interval * 3600)

    def _do_sync(self):
        with self._lock:
            if self._running:
                self._schedule_next()
                return
            self._running = True
            self._progress = self._reset_progress()
            self._progress["started_at"] = datetime.utcnow().isoformat()
            self._progress_version += 1

        try:
            if not settings.dingtalk_drive_proxy_url or not settings.dingtalk_drive_folder_id:
                logger.debug("Drive sync skipped: not configured")
                self._schedule_next()
                return

            from services.dingtalk_drive_service import DingTalkDriveService
            svc = DingTalkDriveService()
            folder_id = settings.dingtalk_drive_folder_id
            result = svc.sync_folder(
                settings.dingtalk_drive_space_id, folder_id,
                incremental=True, on_progress=self.on_progress,
            )

            self.on_progress("complete", {}, "", result)

            self.mark_sync_complete({
                "synced_count": result.get("synced_count", 0),
                "skipped_count": result.get("skipped_count", 0),
                "total_files": result.get("total_files", 0),
                "errors_count": len(result.get("errors", [])),
            })
            logger.info(f"Drive auto-sync done: {result.get('synced_count', 0)} synced, {result.get('skipped_count', 0)} skipped")
        except Exception as e:
            logger.error(f"Drive auto-sync error: {e}")
            self.on_progress("error", {"name": "sync"}, str(e)[:200])
            self._progress["phase"] = "error"
            self._progress["error_message"] = str(e)[:200]
            self.mark_sync_complete({"error": str(e)[:200]})
        finally:
            with self._lock:
                self._running = False
            self._schedule_next()

    def trigger_sync(self) -> dict:
        with self._lock:
            if self._running:
                return {"status": "already_running", "message": "Sync is already in progress"}
            self._running = True
            self._progress = self._reset_progress()
            self._progress["started_at"] = datetime.utcnow().isoformat()
            self._progress_version += 1

        try:
            if not settings.dingtalk_drive_proxy_url:
                self._running = False
                return {"status": "error", "message": "Proxy not configured"}
            if not settings.dingtalk_drive_folder_id:
                self._running = False
                return {"status": "error", "message": "No folder selected"}

            from services.dingtalk_drive_service import DingTalkDriveService
            svc = DingTalkDriveService()
            folder_id = settings.dingtalk_drive_folder_id
            result = svc.sync_folder(
                settings.dingtalk_drive_space_id, folder_id,
                incremental=True, on_progress=self.on_progress,
            )

            self.on_progress("complete", {}, "", result)

            self.mark_sync_complete({
                "synced_count": result.get("synced_count", 0),
                "skipped_count": result.get("skipped_count", 0),
                "total_files": result.get("total_files", 0),
                "errors_count": len(result.get("errors", [])),
            })

            return {
                "status": "ok",
                "synced_files": result.get("synced_count", 0),
                "skipped": result.get("skipped_count", 0),
                "total_files": result.get("total_files", 0),
                "errors": result.get("errors", []),
            }
        except Exception as e:
            logger.error(f"Drive manual sync error: {e}")
            self.on_progress("error", {"name": "sync"}, str(e)[:200])
            self._progress["phase"] = "error"
            self._progress["error_message"] = str(e)[:200]
            return {"status": "error", "message": str(e)[:200]}
        finally:
            with self._lock:
                self._running = False
            self._schedule_next()
