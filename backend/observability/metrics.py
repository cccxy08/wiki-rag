"""Prometheus 指标收集器"""
import logging

logger = logging.getLogger(__name__)


class MetricsCollector:
    _instance = None

    def __init__(self):
        self._instrumentator = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def setup(self, app):
        try:
            from prometheus_fastapi_instrumentator import Instrumentator

            self._instrumentator = Instrumentator()
            self._instrumentator.instrument(app)
            self._instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)
            logger.info("Prometheus metrics enabled at /metrics")
        except ImportError:
            logger.warning("prometheus-fastapi-instrumentator not installed, metrics disabled")
        except Exception as e:
            logger.warning(f"Failed to setup Prometheus metrics: {e}")