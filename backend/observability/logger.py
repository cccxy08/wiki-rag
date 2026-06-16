"""结构化日志配置器 — JSON 格式化、脱敏过滤、request_id 注入"""
import re
import logging
import os
from pathlib import Path

from middleware.request_id import request_id_var


class SensitiveDataFilter(logging.Filter):
    _PATTERNS = [
        re.compile(r'(sk-)[a-zA-Z0-9]{20,}'),
        re.compile(r'(api[_-]?key["\s:=]+)[a-zA-Z0-9\-]{20,}', re.IGNORECASE),
        re.compile(r'(token["\s:=]+)[a-zA-Z0-9\-]{20,}', re.IGNORECASE),
        re.compile(r'(Bearer\s+)[a-zA-Z0-9\-._~+/]+=*'),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern in self._PATTERNS:
                record.msg = pattern.sub(r'\1***REDACTED***', record.msg)
        return True


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("")
        return True


class StructuredLogger:
    @staticmethod
    def setup():
        log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
        log_format = os.environ.get("LOG_FORMAT", "json")

        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        if log_format == "json":
            try:
                from pythonjsonlogger import json as jsonlogger

                formatter = jsonlogger.JsonFormatter(
                    "%(timestamp)s %(level)s %(name)s %(message)s %(request_id)s",
                    rename_fields={"timestamp": "timestamp", "level": "level", "name": "module"},
                )
            except ImportError:
                formatter = logging.Formatter(
                    "%(asctime)s %(levelname)s %(name)s %(message)s [request_id=%(request_id)s]"
                )
        else:
            formatter = logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s [request_id=%(request_id)s]"
            )

        stdout_handler = logging.StreamHandler()
        stdout_handler.setFormatter(formatter)
        stdout_handler.addFilter(SensitiveDataFilter())
        stdout_handler.addFilter(RequestIdFilter())
        root_logger.addHandler(stdout_handler)

        try:
            from core.config import settings
            log_dir = Path(settings.log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.addFilter(SensitiveDataFilter())
            file_handler.addFilter(RequestIdFilter())
            root_logger.addHandler(file_handler)
        except Exception:
            pass