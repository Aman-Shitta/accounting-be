"""
Django logging configuration.

Files:
- debug.log      → ALL logs (DEBUG+), single rotating file
- access.log     → Access/request logs (INFO+)
- error.log      → Error logs only (ERROR+)

Console:
- All logs (DEBUG+) go to console in one stream.

Set LOG_DIR env var to override the default path (useful for local dev).
"""

import os

LOG_DIR = os.environ.get("LOG_DIR", "/Users/amanshitta/Work/zygoon/aicounting/aicounting-backend/logs/")
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    # Django only recognises version 1 — this field is mandatory and must always be 1.
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] [{levelname:<8}] [{name}] [{process:d}:{thread:d}] "
                "[{filename}:{lineno}] — {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "filters": {
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        # ── Console: everything in one stream ──────────────────────────
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        # ── File: ALL logs (debug.log) ─────────────────────────────────
        "debug_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "aicounting-debug.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        # ── File: access/request logs (access.log) ─────────────────────
        "access_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "aicounting-access.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        # ── File: errors only (error.log) ──────────────────────────────
        "error_file": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "aicounting-error.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        # ── Root logger: console + debug file + error file ─────────────
        "": {
            "handlers": ["console", "debug_file", "error_file"],
            "level": "INFO",
        },
        # ── Django request/access logger → access file ─────────────────
        "django.request": {
            "handlers": ["console", "debug_file", "access_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        # ── Django server (runserver access lines) ─────────────────────
        "django.server": {
            "handlers": ["console", "debug_file", "access_file"],
            "level": "INFO",
            "propagate": False,
        },
        # ── Django general ─────────────────────────────────────────────
        "django": {
            "handlers": ["console", "debug_file", "error_file"],
            "level": "INFO",
            "propagate": False,
        },
        "azure": {
            "handlers": ["console", "debug_file", "error_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "landing": {
            "handlers": ["console", "debug_file", "error_file"],
            "level": "WARNING",
            "propagate": False,
        }
    },
}
