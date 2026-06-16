"""审计日志 — 查询/摄入/鉴权事件记录，禁止记录用户原文"""
import hashlib
import logging

audit_logger = logging.getLogger("audit")


class AuditLogger:
    @staticmethod
    def log_query(question: str, source: str, duration_ms: int, confidence: str,
                  cached: bool, request_id: str = ""):
        question_hash = hashlib.md5(question.encode()).hexdigest()[:8]
        audit_logger.info(
            "query_completed",
            extra={
                "question_hash": question_hash,
                "source": source,
                "duration_ms": duration_ms,
                "confidence": confidence,
                "cached": cached,
                "request_id": request_id,
            },
        )

    @staticmethod
    def log_ingest(filename: str, wiki_pages_count: int, rag_chunks_count: int,
                   duration_ms: int, status: str, request_id: str = ""):
        audit_logger.info(
            "ingest_completed",
            extra={
                "filename": filename,
                "wiki_pages_count": wiki_pages_count,
                "rag_chunks_count": rag_chunks_count,
                "duration_ms": duration_ms,
                "status": status,
                "request_id": request_id,
            },
        )

    @staticmethod
    def log_auth_event(event: str, request_id: str = "", client_ip: str = "",
                       success: bool = True, role: str = ""):
        audit_logger.info(
            "auth_event",
            extra={
                "event": event,
                "request_id": request_id,
                "client_ip": client_ip,
                "success": success,
                "role": role,
            },
        )