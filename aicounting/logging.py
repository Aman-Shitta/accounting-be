"""
JSON log formatting.

Development keeps plain text (see ``LOGGING`` in settings.py) because a human
is reading it directly in a terminal. Anything past a real deployment — Cloud
Logging, Datadog, whatever ships stdout off the box — wants one JSON object
per line instead, so it can be queried by field rather than grepped.
"""

import json
import logging
import traceback

# Every attribute a bare LogRecord carries, so anything left over after
# subtracting this set came from `extra={...}` at the call site — a document
# id, a firm id, whatever the caller thought was worth filtering on later.
_RECORD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))

        extra = {
            key: value for key, value in record.__dict__.items() if key not in _RECORD_ATTRS
        }
        if extra:
            payload["extra"] = extra

        return json.dumps(payload, default=str)
