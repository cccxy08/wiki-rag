"""钉钉云盘文件同步服务"""
from __future__ import annotations
import logging
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class DingTalkDriveService:
    def __init__(self):
        self._access_token = None
        self._token_expires_at = 0.0

    def _get_access_token(self) -> str:
        if self._access_token and __import__('time').time() < self._token_expires_at:
            return self._access_token

        if not settings.dingtalk_client_id or not settings.dingtalk_client_secret:
            logger.warning("DingTalk credentials not configured")
            return ""

        try:
            resp = httpx.post(
                "https://oapi.dingtalk.com/gettoken",
                params={
                    "appkey": settings.dingtalk_client_id,
                    "appsecret": settings.dingtalk_client_secret,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode") == 0:
                self._access_token = data["access_token"]
                self._token_expires_at = __import__('time').time() + data.get("expires_in", 7200) - 300
                return self._access_token
            else:
                logger.error(f"DingTalk gettoken failed: {data}")
                return ""
        except Exception as e:
            logger.error(f"DingTalk gettoken error: {e}")
            return ""

    def list_spaces(self) -> list[dict]:
        """列出钉钉云盘所有空间"""
        token = self._get_access_token()
        if not token:
            return []

        try:
            resp = httpx.get(
                "https://oapi.dingtalk.com/v1.0/drive/spaces",
                headers={"x-acs-dingtalk-access-token": token},
                params={"maxResults": 50},
                timeout=15,
            )
            data = resp.json()
            spaces = []
            for item in data.get("items", []):
                spaces.append({
                    "space_id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "type": item.get("type", ""),
                })
            return spaces
        except Exception as e:
            logger.error(f"DingTalk list spaces error: {e}")
            return []

    def list_folders(self, space_id: str, parent_folder_id: str = "") -> list[dict]:
        """列出指定空间下的文件夹（用于选择同步目录）"""
        token = self._get_access_token()
        if not token:
            return []

        folder_id = parent_folder_id or "0"
        try:
            body = {
                "parentId": folder_id,
                "maxResults": 100,
            }
            resp = httpx.post(
                f"https://oapi.dingtalk.com/v1.0/drive/spaces/{space_id}/files/{folder_id}/children",
                headers={"x-acs-dingtalk-access-token": token},
                json=body,
                timeout=15,
            )
            data = resp.json()
            folders = []
            for item in data.get("items", []):
                if item.get("type") == "folder":
                    folders.append({
                        "folder_id": item.get("id", ""),
                        "name": item.get("name", ""),
                        "modified_time": item.get("modifiedTime", ""),
                    })
            return folders
        except Exception as e:
            logger.error(f"DingTalk list folders error: {e}")
            return []

    def list_folder_files(self, space_id: str, folder_id: str) -> list[dict]:
        """列出钉钉云盘指定文件夹下的文件"""
        token = self._get_access_token()
        if not token:
            return []

        files = []
        next_token = None

        while True:
            try:
                body = {
                    "parentId": folder_id,
                    "maxResults": 50,
                }
                if next_token:
                    body["nextToken"] = next_token

                resp = httpx.post(
                    f"https://oapi.dingtalk.com/v1.0/drive/spaces/{space_id}/files/{folder_id}/children",
                    headers={"x-acs-dingtalk-access-token": token},
                    json=body,
                    timeout=30,
                )
                data = resp.json()
                items = data.get("items", [])
                for item in items:
                    files.append({
                        "file_id": item.get("id", ""),
                        "name": item.get("name", ""),
                        "type": item.get("type", ""),
                        "size": item.get("size", 0),
                        "modified_time": item.get("modifiedTime", ""),
                    })

                next_token = data.get("nextToken")
                if not next_token:
                    break
            except Exception as e:
                logger.error(f"DingTalk list folder files error: {e}")
                break

        return files

    def download_file(self, space_id: str, file_id: str) -> Optional[bytes]:
        """下载钉钉云盘文件"""
        token = self._get_access_token()
        if not token:
            return None

        try:
            resp = httpx.post(
                f"https://oapi.dingtalk.com/v1.0/drive/spaces/{space_id}/files/{file_id}/download",
                headers={"x-acs-dingtalk-access-token": token},
                json={},
                timeout=settings.dingtalk_file_download_timeout_seconds,
            )
            if resp.status_code == 200:
                return resp.content
            else:
                logger.error(f"DingTalk download file failed: status={resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"DingTalk download file error: {e}")
            return None

    def sync_folder(self, space_id: str, folder_id: str) -> dict:
        """同步钉钉云盘文件夹到知识库"""
        files = self.list_folder_files(space_id, folder_id)
        if not files:
            logger.info("No files found in DingTalk drive folder")
            return {"synced_count": 0, "errors": []}

        synced_count = 0
        errors = []

        from services.ingest_service import IngestService
        ingest = IngestService()

        for file_info in files:
            file_name = file_info["name"]
            file_type = file_info.get("type", "")
            if file_type == "folder":
                continue

            content = self.download_file(space_id, file_info["file_id"])
            if not content:
                errors.append({"file": file_name, "error": "download failed"})
                continue

            try:
                result = ingest.ingest_file(content, file_name)
                if result.get("status") in ("success", "completed"):
                    synced_count += 1
                else:
                    errors.append({"file": file_name, "error": result.get("error", "ingest failed")})
            except Exception as e:
                errors.append({"file": file_name, "error": str(e)[:200]})

        logger.info(f"DingTalk drive sync complete: {synced_count} files, {len(errors)} errors")
        return {"synced_count": synced_count, "errors": errors}
