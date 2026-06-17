"""钉钉机器人服务 — Stream 长连接 + Webhook 双模式"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import time
import threading
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class DingTalkBotService:
    def __init__(self):
        self._stream_client = None
        self._running = False
        self._access_token = None
        self._token_expires_at = 0.0

    def _get_access_token(self) -> str:
        """获取企业内部应用 access_token（带缓存）"""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        if not settings.dingtalk_client_id or not settings.dingtalk_client_secret:
            logger.warning("DingTalk credentials not configured")
            return ""

        try:
            resp = httpx.post(
                "https://api.dingtalk.com/v1.0/oauth2/accessToken",
                json={
                    "appKey": settings.dingtalk_client_id,
                    "appSecret": settings.dingtalk_client_secret,
                },
                timeout=10,
            )
            data = resp.json()
            if data.get("accessToken"):
                self._access_token = data["accessToken"]
                expire_in = data.get("expireIn", 7200)
                self._token_expires_at = time.time() + expire_in - 300
                return self._access_token
            else:
                logger.error(f"DingTalk getAccessToken failed: {data}")
                return ""
        except Exception as e:
            logger.error(f"DingTalk getAccessToken error: {e}")
            return ""

    def start_stream(self):
        if settings.dingtalk_mode != "stream":
            logger.info(f"DingTalk mode={settings.dingtalk_mode}, skipping stream start")
            return
        if not settings.dingtalk_enabled:
            logger.info("DingTalk bot disabled, skipping stream start")
            return
        if not settings.dingtalk_client_id or not settings.dingtalk_client_secret:
            logger.warning("DingTalk credentials not configured, skipping stream start")
            return

        try:
            from dingtalk_stream import DingTalkStreamClient, Credential, ChatBotHandler, Callback

            credential = Credential(settings.dingtalk_client_id, settings.dingtalk_client_secret)
            handler = _DingTalkChatBotHandler(self)

            self._stream_client = DingTalkStreamClient(credential)
            self._stream_client.register_callback_handler(ChatBotHandler.TOPIC, handler)

            self._running = True
            t = threading.Thread(target=self._run_stream, daemon=True)
            t.start()
            logger.info("DingTalk Stream client started")

        except ImportError:
            logger.warning("dingtalk-stream not installed, DingTalk bot unavailable")
        except Exception as e:
            logger.error(f"Failed to start DingTalk Stream: {e}")

    def _run_stream(self):
        reconnect_interval = 1
        max_interval = settings.dingtalk_stream_reconnect_max_interval_seconds

        while self._running:
            try:
                self._stream_client.start()
                reconnect_interval = 1
            except Exception as e:
                logger.error(f"DingTalk Stream disconnected: {e}, reconnecting in {reconnect_interval}s...")
                time.sleep(reconnect_interval)
                reconnect_interval = min(reconnect_interval * 2, max_interval)

    def stop_stream(self):
        self._running = False
        if self._stream_client:
            try:
                self._stream_client.stop()
            except Exception:
                pass

    def map_user_role(self, dingtalk_user_id: str) -> str:
        admin_ids = [i.strip() for i in settings.dingtalk_admin_ids.split(",") if i.strip()]
        return "admin" if dingtalk_user_id in admin_ids else "user"

    def send_markdown(self, conversation_id: str, text: str):
        """发送 markdown 消息到钉钉对话"""
        logger.info(f"Sending markdown to {conversation_id}: {text[:100]}...")

        if not conversation_id:
            logger.warning("No conversation_id, cannot send message")
            return

        token = self._get_access_token()
        if not token:
            logger.error("No access token, cannot send message")
            return

        try:
            resp = httpx.post(
                "https://api.dingtalk.com/v1.0/robot/oToMessage/batchSend",
                headers={"x-acs-dingtalk-access-token": token},
                json={
                    "robotCode": settings.dingtalk_robot_code,
                    "userIds": [conversation_id] if not conversation_id.startswith("cid") else [],
                    "conversationId": conversation_id if conversation_id.startswith("cid") else "",
                    "msgKey": "sampleMarkdown",
                    "msgParam": json.dumps({"title": "知识库回答", "text": text}, ensure_ascii=False),
                },
                timeout=settings.dingtalk_message_timeout_seconds,
            )
            result = resp.json()
            if result.get("code") != "OK" and resp.status_code != 200:
                logger.error(f"DingTalk send_markdown failed: {result}")
            else:
                logger.info(f"DingTalk send_markdown success to {conversation_id}")
        except Exception as e:
            logger.error(f"DingTalk send_markdown error: {e}")

    def send_interactive_card(self, conversation_id: str, card_data: dict):
        logger.info(f"Sending interactive card to {conversation_id}")

    def update_interactive_card(self, card_instance_id: str, card_data: dict):
        logger.info(f"Updating interactive card {card_instance_id}")

    def download_media(self, download_code: str) -> Optional[bytes]:
        """下载钉钉文件/图片"""
        logger.info(f"Downloading media: {download_code}")

        token = self._get_access_token()
        if not token:
            logger.error("No access token, cannot download media")
            return None

        try:
            resp = httpx.post(
                "https://api.dingtalk.com/v1.0/file/download",
                headers={"x-acs-dingtalk-access-token": token},
                json={"downloadCode": download_code},
                timeout=settings.dingtalk_file_download_timeout_seconds,
            )
            if resp.status_code == 200:
                return resp.content
            else:
                logger.error(f"DingTalk download_media failed: status={resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"DingTalk download_media error: {e}")
            return None

    def verify_webhook_signature(self, timestamp: str, sign: str) -> bool:
        if not settings.dingtalk_client_secret:
            return False
        string_to_sign = f"{timestamp}\n{settings.dingtalk_client_secret}"
        hmac_code = hmac.new(
            settings.dingtalk_client_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac_code == sign


class _DingTalkChatBotHandler:
    TOPIC = "dingtalk"

    def __init__(self, service: DingTalkBotService):
        self._service = service

    async def process(self, callback: dict) -> dict:
        try:
            event_type = callback.get("type", "")
            if event_type == "text":
                return await self._handle_text(callback)
            elif event_type == "file":
                return await self._handle_file(callback)
            elif event_type == "interactive":
                return await self._handle_card_action(callback)
            else:
                return {"success": True}
        except Exception as e:
            logger.error(f"DingTalk callback process error: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_text(self, callback: dict) -> dict:
        data = callback.get("data", {})
        text = data.get("text", "").strip()
        conversation_id = data.get("conversationId", "")
        user_id = data.get("senderId", "")

        if not text:
            return {"success": True}

        try:
            from services.query_service import QueryService
            qs = QueryService()
            result = qs.query_with_mode(text, mode="auto", top_k=5)

            answer = result.get("answer", "未找到相关信息")
            source = result.get("source", "unknown")
            confidence = result.get("confidence", "medium")

            reply = f"**回答:** {answer}\n\n> 来源: {source} | 置信度: {confidence}"

            if result.get("precipitation_record_id"):
                reply += "\n\n💡 此回答已提交沉淀审核"

            self._service.send_markdown(conversation_id, reply)

            return {"success": True}
        except Exception as e:
            logger.error(f"DingTalk text handler error: {e}")
            self._service.send_markdown(conversation_id, f"处理失败: {str(e)}")
            return {"success": False}

    async def _handle_file(self, callback: dict) -> dict:
        data = callback.get("data", {})
        download_code = data.get("downloadCode", "")
        file_name = data.get("fileName", "unknown")
        conversation_id = data.get("conversationId", "")

        try:
            content = self._service.download_media(download_code)
            if not content:
                self._service.send_markdown(conversation_id, f"文件下载失败: {file_name}")
                return {"success": False}

            from services.ingest_service import IngestService
            ingest = IngestService()
            result = ingest.ingest_file(content, file_name)

            status = result.get("status", "failed")
            self._service.send_markdown(
                conversation_id,
                f"文件摄入完成: {file_name}\n状态: {status}\nWiki页面: {', '.join(result.get('wiki_pages', []))}",
            )
            return {"success": True}
        except Exception as e:
            logger.error(f"DingTalk file handler error: {e}")
            return {"success": False}

    async def _handle_card_action(self, callback: dict) -> dict:
        data = callback.get("data", {})
        action = data.get("action", "")
        card_instance_id = data.get("cardInstanceId", "")

        logger.info(f"DingTalk card action: {action} on card {card_instance_id}")
        return {"success": True}
