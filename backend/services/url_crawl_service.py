"""URL 抓取服务 — httpx + trafilatura 提取网页正文并摄入"""
from __future__ import annotations
import hashlib
import ipaddress
import logging
import time
from typing import Optional
from urllib.parse import urlparse

from core.config import settings

logger = logging.getLogger(__name__)


class URLCrawlService:
    def crawl_single(self, url: str) -> dict:
        validation = self._validate_url(url)
        if not validation["valid"]:
            return {"error": validation["reason"], "status": "failed"}

        html = self._fetch_html(url)
        if not html:
            return {"error": "Failed to fetch URL", "status": "failed"}

        content = self._extract_content(html, url)
        if not content:
            return {"error": "Failed to extract content", "status": "failed"}

        source_name = self._url_to_source_name(url)
        try:
            from services.ingest_service import IngestService
            ingest = IngestService()
            result = ingest.ingest_text(content, source_name)
            result["url"] = url
            return result
        except Exception as e:
            logger.error(f"URL crawl ingest failed for {url}: {e}")
            return {"error": str(e), "status": "failed", "url": url}

    def crawl_batch(self, urls: list[str]) -> str:
        from services.batch_ingest_service import BatchIngestService
        from db.import_db import ImportDB
        from pathlib import Path

        db_path = Path(settings.wiki_data_dir) / "import_tasks.db"
        from services.progress_service import ProgressService
        db = ImportDB(db_path)
        progress = ProgressService()
        batch_service = BatchIngestService(db, progress)

        task_id = f"url-{hashlib.md5(','.join(urls).encode()).hexdigest()[:8]}"
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        db._conn.execute(
            """INSERT INTO import_tasks (taskId, sourceType, status, totalFiles, successCount, partialCount, failedCount, skippedCount, createdAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, "url_batch", "processing", len(urls), 0, 0, 0, 0, now),
        )
        db._conn.commit()

        import threading
        def _process():
            success = 0
            failed = 0
            for i, url in enumerate(urls):
                result = self.crawl_single(url)
                if result.get("status") in ("success", "partial"):
                    success += 1
                else:
                    failed += 1
                progress.emit(task_id, url, result.get("status", "failed"))
                progress.emit_progress(task_id, len(urls), i + 1, success, 0, failed)

            db.update_task_status(task_id, "completed" if failed == 0 else "partial",
                                  successCount=success, failedCount=failed,
                                  completedAt=time.strftime("%Y-%m-%dT%H:%M:%S"))
            progress.emit_completed(task_id, {"total": len(urls), "success": success, "failed": failed})

        t = threading.Thread(target=_process, daemon=True)
        t.start()
        return task_id

    def _validate_url(self, url: str) -> dict:
        try:
            parsed = urlparse(url)
        except Exception:
            return {"valid": False, "reason": "Invalid URL format"}

        allowed_schemes = [s.strip() for s in settings.url_allowed_schemes.split(",") if s.strip()]
        if parsed.scheme not in allowed_schemes:
            return {"valid": False, "reason": f"Scheme '{parsed.scheme}' not allowed"}

        hostname = parsed.hostname
        if not hostname:
            return {"valid": False, "reason": "Missing hostname"}

        try:
            import socket
            ip = socket.getaddrinfo(hostname, None)
            for addr_info in ip:
                ip_addr = ipaddress.ip_address(addr_info[4][0])
                if ip_addr.is_private or ip_addr.is_loopback or ip_addr.is_reserved:
                    return {"valid": False, "reason": "Internal/private IP addresses not allowed (SSRF protection)"}
        except Exception:
            return {"valid": False, "reason": "Cannot resolve hostname"}

        return {"valid": True}

    def _fetch_html(self, url: str) -> Optional[str]:
        try:
            import httpx
            timeout = settings.url_fetch_timeout_seconds
            max_size = settings.url_max_response_size_mb * 1024 * 1024

            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()

                content_length = int(response.headers.get("content-length", 0))
                if content_length > max_size:
                    logger.warning(f"URL response too large: {url} ({content_length} bytes)")
                    return None

                return response.text

        except httpx.TimeoutException:
            logger.warning(f"URL fetch timeout: {url}")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"URL fetch HTTP error: {url} -> {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"URL fetch failed: {url} -> {e}")
            return None

    def _extract_content(self, html: str, url: str) -> Optional[str]:
        try:
            import trafilatura
            content = trafilatura.extract(html, url=url, include_tables=True, favor_precision=True)
            if not content or len(content.strip()) < 50:
                return None
            return content
        except ImportError:
            logger.warning("trafilatura not installed, using raw HTML text extraction")
            from bs4 import BeautifulSoup
            try:
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                return text if len(text.strip()) >= 50 else None
            except ImportError:
                return None
        except Exception as e:
            logger.error(f"Content extraction failed for {url}: {e}")
            return None

    def _url_to_source_name(self, url: str) -> str:
        parsed = urlparse(url)
        name = parsed.hostname or "unknown"
        path = (parsed.path or "/").strip("/").replace("/", "-")[:40]
        if path:
            name = f"{name}-{path}"
        return f"url-{name}.md"