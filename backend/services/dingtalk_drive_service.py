"""钉钉云盘文件同步服务 — 通过代理服务访问钉盘API"""
from __future__ import annotations
import logging
import time
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class DingTalkDriveService:
    def __init__(self):
        self._proxy_base = None

    @property
    def proxy_base(self) -> str:
        if self._proxy_base:
            return self._proxy_base
        if settings.dingtalk_drive_proxy_url:
            self._proxy_base = settings.dingtalk_drive_proxy_url.rstrip("/")
        else:
            self._proxy_base = ""
        return self._proxy_base

    @property
    def proxy_token(self) -> str:
        return settings.dingtalk_drive_proxy_token

    def _request_with_retry(self, url: str, params: dict, max_retries: int = 3, timeout: int = 30) -> Optional[httpx.Response]:
        for attempt in range(max_retries):
            try:
                resp = httpx.get(url, params=params, timeout=timeout)
                if resp.status_code == 502 and attempt < max_retries - 1:
                    logger.warning(f"Drive proxy 502, retry {attempt+1}/{max_retries}")
                    time.sleep(2 * (attempt + 1))
                    continue
                return resp
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Drive proxy error, retry {attempt+1}/{max_retries}: {e}")
                    time.sleep(2 * (attempt + 1))
                else:
                    raise
        return None

    def _base_params(self) -> dict:
        params = {}
        if self.proxy_token:
            params["token"] = self.proxy_token
        user_id = settings.dingtalk_drive_user_id
        if user_id:
            params["userId"] = user_id
        return params

    def list_folder_files(self, space_id: str, folder_id: str, recursive: bool = False, depth: int = 0) -> list[dict]:
        if not self.proxy_base:
            logger.error("DINGTALK_DRIVE_PROXY_URL not configured")
            return []

        user_id = settings.dingtalk_drive_user_id
        if not user_id:
            logger.error("DINGTALK_DRIVE_USER_ID not configured")
            return []

        files = []
        next_token = None

        while True:
            try:
                params = self._base_params()
                if folder_id:
                    params["parentId"] = folder_id

                resp = self._request_with_retry(f"{self.proxy_base}/list", params)
                if resp.status_code != 200:
                    logger.error(f"Drive list failed: {resp.status_code} {resp.text[:200]}")
                    break

                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"Drive list error: {data}")
                    break

                items = data.get("files", [])
                for item in items:
                    ftype = item.get("fileType", "file")
                    entry = {
                        "file_id": item.get("fileId", ""),
                        "name": item.get("fileName", ""),
                        "type": ftype,
                        "extension": item.get("fileExtension", ""),
                        "size": int(item.get("fileSize", 0) or 0),
                        "modified_time": item.get("modifyTime", item.get("updatedAt", "")),
                        "space_id": space_id,
                    }
                    files.append(entry)

                    if recursive and ftype == "folder" and depth < 3:
                        sub_files = self.list_folder_files(
                            space_id, item["fileId"], recursive=True, depth=depth + 1
                        )
                        files.extend(sub_files)

                next_token = data.get("nextToken")
                if not next_token:
                    break
            except Exception as e:
                logger.error(f"Drive list error: {e}")
                break

        return files

    def download_file_content(self, space_id: str, file_id: str, file_name: str = "") -> Optional[bytes]:
        if not self.proxy_base:
            logger.error("DINGTALK_DRIVE_PROXY_URL not configured")
            return None

        user_id = settings.dingtalk_drive_user_id
        if not user_id:
            logger.error("DINGTALK_DRIVE_USER_ID not configured")
            return None

        try:
            params = self._base_params()
            params["fileId"] = file_id
            resp = httpx.get(
                f"{self.proxy_base}/download",
                params=params,
                timeout=settings.dingtalk_file_download_timeout_seconds,
            )
            if resp.status_code == 200:
                logger.info(f"Downloaded: {file_name or file_id} ({len(resp.content)} bytes)")
                return resp.content
            else:
                logger.error(f"Download failed: {resp.status_code} {resp.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None

    def upload_file(self, space_id: str, file_name: str, content: bytes, parent_id: str = "") -> dict:
        if not self.proxy_base:
            return {"status": "error", "error": "proxy not configured"}

        user_id = settings.dingtalk_drive_user_id
        if not user_id:
            return {"status": "error", "error": "user_id not configured"}

        try:
            params = self._base_params()
            if parent_id:
                params["parentId"] = parent_id

            resp = httpx.post(
                f"{self.proxy_base}/upload",
                params=params,
                files={"files": (file_name, content)},
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return {"status": "success", "file_id": data.get("fileId", "")}
                return {"status": "error", "error": data.get("message", "upload failed")}
            return {"status": "error", "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "error": str(e)[:200]}

    def check_health(self) -> dict:
        if not self.proxy_base:
            return {"healthy": False, "error": "proxy not configured"}
        try:
            resp = httpx.get(f"{self.proxy_base}/health", timeout=10)
            if resp.status_code == 200:
                return {"healthy": True, "status": resp.text[:100]}
            return {"healthy": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"healthy": False, "error": str(e)[:200]}

    def browse_folder(self, parent_id: str = "") -> dict:
        if not self.proxy_base:
            return {"folders": [], "files": []}

        user_id = settings.dingtalk_drive_user_id
        if not user_id:
            return {"folders": [], "files": []}

        try:
            params = self._base_params()
            if parent_id:
                params["parentId"] = parent_id

            resp = self._request_with_retry(f"{self.proxy_base}/list", params)
            if not resp or resp.status_code != 200:
                return {"folders": [], "files": [], "error": f"HTTP {resp.status_code if resp else 'timeout'}"}

            data = resp.json()
            if not data.get("ok"):
                return {"folders": [], "files": [], "error": data.get("message", "unknown")}

            folders = []
            files = []
            for item in data.get("files", []):
                entry = {
                    "fileId": item.get("fileId", ""),
                    "fileName": item.get("fileName", ""),
                    "fileType": item.get("fileType", "file"),
                    "fileSize": int(item.get("fileSize", 0) or 0),
                    "modifyTime": item.get("modifyTime", ""),
                    "fileExtension": item.get("fileExtension", ""),
                }
                if entry["fileType"] == "folder":
                    folders.append(entry)
                else:
                    files.append(entry)

            return {"folders": folders, "files": files}
        except Exception as e:
            return {"folders": [], "files": [], "error": str(e)[:200]}

    def sync_folder(self, space_id: str, folder_id: str, recursive: bool = True, incremental: bool = False, on_progress=None) -> dict:
        folder_ids = [fid.strip() for fid in folder_id.split(",") if fid.strip()] if folder_id else [""]

        scheduler = None
        if incremental:
            from services.drive_sync_scheduler import DriveSyncScheduler
            scheduler = DriveSyncScheduler.get_instance()

        total_synced = 0
        total_skipped = 0
        all_errors = []
        total_files = 0

        for fid in folder_ids:
            result = self._sync_single_folder(space_id, fid, recursive, scheduler, on_progress)
            total_synced += result.get("synced_count", 0)
            total_skipped += result.get("skipped_count", 0)
            all_errors.extend(result.get("errors", []))
            total_files += result.get("total_files", 0)

        if scheduler:
            scheduler._save_state()

        return {
            "synced_count": total_synced,
            "skipped_count": total_skipped,
            "errors": all_errors,
            "total_files": total_files,
        }

    def _sync_single_folder(self, space_id: str, folder_id: str, recursive: bool = True, scheduler=None, on_progress=None) -> dict:
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.available < 100 * 1024 * 1024:
                msg = f"内存不足({mem.available // 1024 // 1024}MB可用)，跳过同步"
                logger.warning(msg)
                if on_progress:
                    on_progress("error", {"name": "sync"}, msg)
                return {"synced_count": 0, "errors": [{"file": "system", "error": msg}], "total_files": 0}
        except ImportError:
            pass

        if on_progress:
            on_progress("listing", {})

        files = self.list_folder_files(space_id, folder_id, recursive=recursive)
        file_items = [f for f in files if f["type"] == "file"]

        if on_progress:
            on_progress("listed", {"total_files": len(file_items)})

        if not files:
            logger.info("No files found in DingTalk drive folder")
            return {"synced_count": 0, "errors": [], "total_files": 0}

        supported_exts = {
            ext.strip().lstrip(".")
            for ext in settings.supported_file_types.split(",")
            if ext.strip()
        }

        synced_count = 0
        skipped_count = 0
        errors = []

        ingest = None

        for file_info in files:
            if file_info["type"] != "file":
                continue

            ext = file_info.get("extension", "").lower()
            name = file_info.get("name", "")
            if supported_exts and ext not in supported_exts and ext:
                skipped_count += 1
                if on_progress:
                    on_progress("skipped", {"name": name, "size": file_info.get("size", 0)}, "不支持格式")
                continue

            file_id = file_info.get("file_id", "")
            modify_time = file_info.get("modified_time", "")

            file_size = file_info.get("size", 0)
            if file_size and file_size > 20 * 1024 * 1024:
                skipped_count += 1
                if on_progress:
                    on_progress("skipped", {"name": name, "size": file_size}, "文件过大(>20MB)")
                logger.info(f"Skipping large file: {name} ({file_size} bytes)")
                continue

            if scheduler and not scheduler.should_sync_file(file_id, modify_time):
                skipped_count += 1
                if on_progress:
                    on_progress("skipped", {"name": name, "size": file_info.get("size", 0)}, "未修改")
                continue

            if on_progress:
                on_progress("downloading", {"name": name, "size": file_info.get("size", 0)})

            content = self.download_file_content(space_id, file_id, name)
            if not content:
                errors.append({"file": name, "error": "download failed"})
                if on_progress:
                    on_progress("error", {"name": name, "size": file_info.get("size", 0)}, "下载失败")
                continue

            if on_progress:
                on_progress("downloaded", {"name": name, "size": len(content)})

            try:
                if ingest is None:
                    from services.ingest_service import IngestService
                    ingest = IngestService()
                result = ingest.ingest_file(content, name)
                if result.get("status") in ("success", "completed", "partial"):
                    synced_count += 1
                    if scheduler:
                        scheduler.mark_file_synced(file_id, modify_time, name)
                    logger.info(f"Synced: {name}")
                    if on_progress:
                        on_progress("synced", {"name": name, "size": len(content)}, "", result)
                else:
                    ingest_error = result.get("rag_error") or result.get("wiki_error") or "ingest failed"
                    errors.append({"file": name, "error": ingest_error})
                    if on_progress:
                        on_progress("error", {"name": name, "size": len(content)}, ingest_error[:100])
            except Exception as e:
                errors.append({"file": name, "error": str(e)[:200]})
                if on_progress:
                    on_progress("error", {"name": name, "size": file_info.get("size", 0)}, str(e)[:100])

        logger.info(
            f"DingTalk drive sync: {synced_count} synced, {skipped_count} skipped, {len(errors)} errors"
        )
        return {
            "synced_count": synced_count,
            "skipped_count": skipped_count,
            "errors": errors,
            "total_files": len([f for f in files if f["type"] == "file"]),
        }
