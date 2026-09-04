"""
Django settings for the aicounting API.

This project serves JSON and nothing else — there is no template layer, no
Django admin and no static-file pipeline. See ``documentation/02-decisions.md``.
"""

import logging
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: str = "False") -> bool:
    return os.environ.get(name, default).strip().lower() in ("true", "1", "yes")


def _env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEBUG = _env_bool("DJANGO_DEBUG", "True")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is off")
    SECRET_KEY = "django-insecure-local-development-only-do-not-deploy"

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

ROOT_URLCONF = "aicounting.urls"
WSGI_APPLICATION = "aicounting.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    # `auth` provides the User model and permissions; `contenttypes` backs both
    # auth and auditlog. Neither pulls in a template or static-file dependency.
    "django.contrib.auth",
    "django.contrib.contenttypes",

    "corsheaders",
    "auditlog",

    "v1.common",
    "v1.identity",
    "v1.tenancy",
    "v1.ledger",
    "v1.configuration",
    "v1.periods",
    "v1.review",
    "v1.dashboard",
    "v1.platform",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Resolves the bearer token before auditlog reads request.user.
    "v1.common.middleware.JWTUserMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
]

# No SessionMiddleware, CsrfViewMiddleware or django.contrib.auth's
# AuthenticationMiddleware: auth is bearer-token only, so there is no cookie
# session for CSRF to protect, and that middleware hard-requires one.
# JWTUserMiddleware fills the same role for tokens.

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "aicounting"),
        "USER": os.environ.get("POSTGRES_USER", "aicounting"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.environ.get("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

# Argon2 first: new passwords use it, and existing PBKDF2 hashes are upgraded
# on next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

# Local filesystem for now. Moving to GCS is a backend swap here plus
# django-storages[google] — every call site already goes through
# django.core.files.storage.default_storage.
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}

FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("FILE_UPLOAD_MAX_MEMORY_SIZE", 15 * 1024 * 1024))
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

# An explicit origin list. `CORS_ALLOW_ALL_ORIGINS` cannot be combined with
# credentials — browsers reject the wildcard on a credentialed request.
CORS_ALLOWED_ORIGINS = _env_list(
    "CORS_ALLOWED_ORIGINS", "http://localhost:4200,http://localhost:3000"
)
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "EXCEPTION_HANDLER": "v1.common.exceptions.api_exception_handler",
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ),
    # Filtering and pagination are handled by v1.common (ListCreateMixin and
    # v1.common.pagination): DRF's backends only apply to generic views.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/min",
        "user": "60/min",
        # Credential endpoints are the ones worth guessing at.
        "login": "10/min",
        "set_password": "5/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.environ.get("ACCESS_TOKEN_LIFETIME_MINUTES", "30"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.environ.get("REFRESH_TOKEN_LIFETIME_DAYS", "7"))
    ),
    "ROTATE_REFRESH_TOKENS": False,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Plain text in dev — a person is reading this directly in a terminal.
# Structured JSON otherwise, so a real log sink can be queried by field
# instead of grepped. See aicounting/logging.py.
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {"format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s"},
        "structured": {"()": "aicounting.logging.StructuredFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console" if DEBUG else "structured",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Django's own request log is noisy at INFO (one line per request);
        # a 4xx/5xx is already visible through the response, and a genuine
        # server error still reaches here at ERROR.
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "celery": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "v1": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "extractor": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

CELERY_BEAT_SCHEDULE = {
    "process-classification-queue": {
        "task": "v1.periods.tasks.process_classification_queue_task",
        "schedule": 60.0,
    },
}

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Email — invites and password resets
# ---------------------------------------------------------------------------

# The frontend origin that renders the set-password screen.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@aicounting.app")

if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", "True")
else:
    # Development: invite and reset links are printed to the console.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# ---------------------------------------------------------------------------
# Provider credentials and other environment settings
# ---------------------------------------------------------------------------

from .env_settings import *  # noqa: E402,F401,F403

# ---------------------------------------------------------------------------
# Error tracking
# ---------------------------------------------------------------------------
#
# The request/task exception handling throughout this codebase is deliberately
# "catch it, log it, turn it into a response or a failed-status row" — see
# v1/common/exceptions.py and every `except Exception` in v1/periods/tasks.py.
# That is right for the caller (nobody gets a 500 for a provider timeout), but
# it means an exception is almost never left to propagate, so Sentry's usual
# hook — catching what Django or Celery would otherwise raise — has very
# little to catch. LoggingIntegration is what actually does the work here: it
# turns every existing `logger.error(...)` / `logger.exception(...)` call
# already scattered through v1/ and extractor/ into a Sentry event, with no
# call site needing to know Sentry exists.
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT,
        release=SENTRY_RELEASE,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(monitor_beat_tasks=True),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        # Request bodies and user PII stay out of error reports by default —
        # a captured exception is not a place client financial data belongs.
        send_default_pii=False,
    )
