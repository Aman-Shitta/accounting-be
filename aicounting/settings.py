"""
Django settings for the aicounting API.

This project serves JSON and nothing else — there is no template layer, no
Django admin and no static-file pipeline. See ``documentation/02-decisions.md``.
"""

import os
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

    "authentication",
    "user",
    "account",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # Authenticates the bearer token once and caches it on the request, so DRF
    # does not re-verify. Always sets request.user, which auditlog relies on.
    "authentication.middleware.JWTAuthenticationMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
]

# No SessionMiddleware, CsrfViewMiddleware or AuthenticationMiddleware: auth is
# bearer-token only, so there is no cookie session for CSRF to protect.

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
        "authentication.authenticate.JSONWebTokenAuthentication",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ),
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "30/min", "user": "60/min"},
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

CELERY_BEAT_SCHEDULE = {
    "process-classification-queue": {
        "task": "account.tasks.process_classification_queue_task",
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
# Provider credentials and other environment settings
# ---------------------------------------------------------------------------

from .env_settings import *  # noqa: E402,F401,F403
