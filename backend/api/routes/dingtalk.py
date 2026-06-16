"""钉钉 Webhook 回调端点 — 签名校验 + 消息处理"""
import time
import logging
from fastapi import APIRouter, Request, HTTPException, Header

from core.config import settings

router = APIRouter(prefix="/api/dingtalk", tags=["dingtalk"])

logger = logging.getLogger(__name__)


_dingtalk_service = None


def _get_dingtalk_service():
    global _dingtalk_service
    if _dingtalk_service is None:
        from services.dingtalk_service import DingTalkBotService
        _dingtalk_service = DingTalkBotService()
    return _dingtalk_service


@router.post("/callback")
async def dingtalk_callback(
    request: Request,
    timestamp: str = Header(None),
    sign: str = Header(None),
):
    if not settings.dingtalk_enabled:
        raise HTTPException(status_code=404, detail="DingTalk not enabled")

    svc = _get_dingtalk_service()

    if timestamp and sign:
        if not svc.verify_webhook_signature(timestamp, sign):
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    msg_type = body.get("msgtype", body.get("type", ""))

    conversation_id = body.get("conversationId", body.get("chatbotConversationId", ""))
    user_id = body.get("senderStaffId", body.get("senderId", ""))
    user_role = svc.map_user_role(user_id) if user_id else "user"

    if msg_type == "text":
        text_content = body.get("text", {})
        if isinstance(text_content, dict):
            question = text_content.get("content", "").strip()
        else:
            question = str(text_content).strip()

        if not question:
            return {"msgtype": "empty", "empty": {}}

        try:
            from api.deps import _get_query_service
            qs = _get_query_service()
            result = qs.query_with_mode(question, mode="auto", top_k=5, session_id=user_id)

            answer = result.get("answer", "未找到相关信息")
            source = result.get("source", "unknown")
            confidence = result.get("confidence", "medium")

            reply_text = f"**回答:** {answer}\n\n> 来源: {source} | 置信度: {confidence}"
            if result.get("precipitation_record_id"):
                reply_text += "\n\n💡 此回答已提交沉淀审核"

            if settings.dingtalk_mode == "webhook":
                return {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": "知识库回答",
                        "text": reply_text,
                    },
                }
            else:
                svc.send_markdown(conversation_id, reply_text)
                return {"success": True}

        except Exception as e:
            logger.error(f"DingTalk callback query error: {e}")
            error_msg = f"处理失败: {str(e)[:200]}"
            if settings.dingtalk_mode == "webhook":
                return {
                    "msgtype": "markdown",
                    "markdown": {"title": "错误", "text": error_msg},
                }
            svc.send_markdown(conversation_id, error_msg)
            return {"success": False}

    elif msg_type == "richText" or msg_type == "file":
        rich_text_content = body.get("content", body.get("richText", {}))
        download_code = body.get("downloadCode", "")
        file_name = body.get("fileName", body.get("downloadCode", "unknown"))

        if download_code:
            content = svc.download_media(download_code)
            if content:
                try:
                    from api.deps import _get_ingest_service
                    ingest = _get_ingest_service()
                    result = ingest.ingest_file(content, file_name)
                    status = result.get("status", "failed")
                    reply = f"文件摄入完成: {file_name}\n状态: {status}"
                except Exception as e:
                    reply = f"文件摄入失败: {str(e)[:200]}"
            else:
                reply = f"文件下载失败: {file_name}"

            if settings.dingtalk_mode == "webhook":
                return {
                    "msgtype": "markdown",
                    "markdown": {"title": "文件处理", "text": reply},
                }
            svc.send_markdown(conversation_id, reply)
            return {"success": True}

    return {"success": True}


@router.post("/sync-drive")
async def sync_drive():
    """触发钉钉云盘文件同步（供外部cron调用）"""
    if not settings.dingtalk_enabled:
        raise HTTPException(status_code=404, detail="DingTalk not enabled")
    if not settings.dingtalk_drive_folder_id:
        raise HTTPException(status_code=400, detail="DINGTALK_DRIVE_FOLDER_ID not configured")
    if not settings.dingtalk_drive_space_id:
        raise HTTPException(status_code=400, detail="DINGTALK_DRIVE_SPACE_ID not configured")

    try:
        from services.dingtalk_drive_service import DingTalkDriveService
        svc = DingTalkDriveService()
        result = svc.sync_folder(settings.dingtalk_drive_space_id, settings.dingtalk_drive_folder_id)
        return {"status": "ok", "synced_files": result.get("synced_count", 0), "errors": result.get("errors", [])}
    except Exception as e:
        logger.error(f"DingTalk drive sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract-knowledge")
async def extract_knowledge():
    """触发对话知识提取（供外部cron调用）"""
    if not settings.dingtalk_enabled:
        raise HTTPException(status_code=404, detail="DingTalk not enabled")

    try:
        from services.knowledge_extract_service import KnowledgeExtractService
        svc = KnowledgeExtractService()
        result = svc.extract_all()
        return {"status": "ok", "extracted": result.get("extracted_count", 0), "errors": result.get("errors", [])}
    except Exception as e:
        logger.error(f"Knowledge extract error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
