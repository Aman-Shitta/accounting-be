"""
Development logging — used only when DEBUG=True (i.e. runserver).

Writes everything to <repo>/log/django-app.log and errors to
<repo>/log/django-error.log with full tracebacks.
"""

import os
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "log"
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "dev": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
            "datefmt": "%H:%M:%S",
        },
    },

    "handlers": {
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "django-app.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "dev",
            "encoding": "utf-8",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "django-error.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 3,
            "level": "ERROR",
            "formatter": "dev",
            "encoding": "utf-8",
        },
    },

    "loggers": {
        "account":        {"handlers": ["app_file", "error_file"], "level": "DEBUG", "propagate": False},
        "extractor":      {"handlers": ["app_file", "error_file"], "level": "DEBUG", "propagate": False},
        "aicounting":     {"handlers": ["app_file", "error_file"], "level": "DEBUG", "propagate": False},
        "authentication": {"handlers": ["app_file", "error_file"], "level": "DEBUG", "propagate": False},
        "dashboard":      {"handlers": ["app_file", "error_file"], "level": "DEBUG", "propagate": False},
        "user":           {"handlers": ["app_file", "error_file"], "level": "DEBUG", "propagate": False},
        "monthly_accounting_views": {"handlers": ["app_file", "error_file"], "level": "DEBUG", "propagate": False},

        "django":         {"handlers": ["app_file", "error_file"], "level": "INFO",    "propagate": False},
        "django.request": {"handlers": ["app_file", "error_file"], "level": "INFO",    "propagate": False},
        "django.security":{"handlers": ["error_file"],              "level": "WARNING", "propagate": False},
    },

    "root": {
        "handlers": ["app_file", "error_file"],
        "level": "WARNING",
    },
}
