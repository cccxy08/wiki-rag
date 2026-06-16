"""沉淀审核服务 — 人工确认 + 管理员审核 + 撤回 + 版本快照"""
from __future__ import annotations
import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

from core.config import settings
from db.precipitation_db import PrecipitationDB

logger = logging.getLogger(__name__)


class PrecipitationService:
    def __init__(self, db: PrecipitationDB):
        self._db = db

    def create_from_query(self, question: str, answer: str, llm_score: int, source: str) -> Optional[str]:
        if not settings.precipitation_enabled:
            return None
        if llm_score < settings.precipitation_score_threshold:
            return None

        question_hash = hashlib.md5(question.encode()).hexdigest()[:8]
        answer_summary = answer[:200] + "..." if len(answer) > 200 else answer

        record_id = self._db.create_record({
            "questionHash": question_hash,
            "answerSummary": answer_summary,
            "answerContent": answer,
            "llmScore": llm_score,
            "source": source,
        })
        logger.info(f"Precipitation record created: {record_id}, score={llm_score}, status=pending_confirm")
        return record_id

    def confirm(self, record_id: str, user: str = "anonymous") -> dict:
        record = self._db.get_record(record_id)
        if not record:
            return {"error": "Record not found"}
        if record["status"] != "pending_confirm":
            return {"error": f"Invalid status: {record['status']}, expected pending_confirm"}

        self._db.update_record(record_id, status="pending_review", confirmedBy=user, confirmedAt=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._db._add_log(record_id, "confirmed", user)
        return {"recordId": record_id, "status": "pending_review"}

    def ignore(self, record_id: str, user: str = "anonymous") -> dict:
        record = self._db.get_record(record_id)
        if not record:
            return {"error": "Record not found"}
        if record["status"] != "pending_confirm":
            return {"error": f"Invalid status: {record['status']}"}

        self._db.update_record(record_id, status="ignored")
        self._db._add_log(record_id, "ignored", user)
        return {"recordId": record_id, "status": "ignored"}

    def review_approve(self, record_id: str, reviewer: str = "admin") -> dict:
        record = self._db.get_record(record_id)
        if not record:
            return {"error": "Record not found"}
        if record["status"] != "pending_review":
            return {"error": f"Invalid status: {record['status']}, expected pending_review"}

        wiki_result = self._write_to_wiki(record)

        self._db.update_record(
            record_id,
            status="approved",
            reviewedBy=reviewer,
            reviewedAt=time.strftime("%Y-%m-%dT%H:%M:%S"),
            reviewAction="approve",
            wikiPageTitle=wiki_result.get("page_title"),
            wikiWrittenAt=time.strftime("%Y-%m-%dT%H:%M:%S") if wiki_result.get("page_title") else None,
            snapshotPath=wiki_result.get("snapshot_path"),
        )
        self._db._add_log(record_id, "approved", reviewer, {"wikiPage": wiki_result.get("page_title")})
        return {"recordId": record_id, "status": "approved", "wikiPage": wiki_result.get("page_title")}

    def review_reject(self, record_id: str, reviewer: str = "admin", reason: str = "") -> dict:
        record = self._db.get_record(record_id)
        if not record:
            return {"error": "Record not found"}
        if record["status"] != "pending_review":
            return {"error": f"Invalid status: {record['status']}"}

        self._db.update_record(
            record_id,
            status="rejected",
            reviewedBy=reviewer,
            reviewedAt=time.strftime("%Y-%m-%dT%H:%M:%S"),
            reviewAction="reject",
            reviewReason=reason,
        )
        self._db._add_log(record_id, "rejected", reviewer, {"reason": reason})
        return {"recordId": record_id, "status": "rejected"}

    def revoke(self, record_id: str, operator: str = "admin", reason: str = "") -> dict:
        record = self._db.get_record(record_id)
        if not record:
            return {"error": "Record not found"}
        if record["status"] not in ("approved", "pending_review"):
            return {"error": f"Cannot revoke record with status: {record['status']}"}

        if record.get("wikiPageTitle") and record["status"] == "approved":
            self._restore_wiki_snapshot(record)

        self._db.update_record(
            record_id,
            status="revoked",
            revokedBy=operator,
            revokedAt=time.strftime("%Y-%m-%dT%H:%M:%S"),
            revokeReason=reason,
        )
        self._db._add_log(record_id, "revoked", operator, {"reason": reason})
        return {"recordId": record_id, "status": "revoked"}

    def get_pending_reviews(self, page: int = 1, page_size: int = 20) -> dict:
        records = self._db.list_records("pending_review", page, page_size)
        total = self._db.count_records("pending_review")
        return {"records": records, "total": total, "page": page, "pageSize": page_size}

    def _write_to_wiki(self, record: dict) -> dict:
        try:
            from core.wiki_engine import WikiEngine
            wiki = WikiEngine.get_instance()

            content = record.get("answerContent", "")
            source_name = f"qa-{record['recordId']}.md"

            self._save_version_snapshot(wiki, record.get("wikiPageTitle", ""))

            result = wiki.ingest(content, source_name)
            page_title = result.get("wiki_pages", [None])[0] if result.get("wiki_pages") else None

            return {
                "page_title": page_title,
                "snapshot_path": self._get_snapshot_path(wiki, page_title) if page_title else None,
            }
        except Exception as e:
            logger.error(f"Failed to write precipitation to wiki: {e}")
            return {"error": str(e)}

    def _save_version_snapshot(self, wiki, page_title: str):
        if not page_title:
            return
        try:
            wiki.save_version_snapshot(page_title)
        except Exception as e:
            logger.warning(f"Failed to save version snapshot: {e}")

    def _get_snapshot_path(self, wiki, page_title: str) -> Optional[str]:
        if not page_title:
            return None
        try:
            versions = wiki.list_versions(page_title)
            if versions:
                return versions[-1]["path"]
        except Exception:
            pass
        return None

    def _restore_wiki_snapshot(self, record: dict):
        snapshot_path = record.get("snapshotPath")
        page_title = record.get("wikiPageTitle", "")
        if not page_title:
            logger.warning(f"No wiki page title for record {record['recordId']}, cannot restore")
            return
        try:
            from core.wiki_engine import WikiEngine
            wiki = WikiEngine.get_instance()
            if snapshot_path:
                version_filename = Path(snapshot_path).name
                restored = wiki.restore_version(page_title, version_filename)
                if restored:
                    logger.info(f"Wiki page restored from snapshot: {page_title}")
                else:
                    logger.warning(f"Failed to restore wiki page: {page_title}")
            else:
                logger.warning(f"No snapshot path for record {record['recordId']}, cannot restore")
        except Exception as e:
            logger.error(f"Failed to restore wiki snapshot: {e}")