import json
import logging
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
recent_logs: deque = deque(maxlen=200)


class StructuredFormatter(logging.Formatter):
    def format(self, record):
        # Only application-authored messages. Never interpolate request bodies,
        # headers, credentials, third-party exceptions, or arbitrary container logs.
        item = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "message": record.getMessage(),
            "requestId": request_id.get(),
        }
        recent_logs.append(item)
        return json.dumps(item)


def setup_logging(level: str):
    logger = logging.getLogger("mediahub")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
