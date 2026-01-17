import os
from django.conf import settings


class MaxLevelFilter:
    def __init__(self, max_level):
        self.max_level = max_level

    def filter(self, record):
        return record.levelno <= self.max_level

LOG_DIR = os.getenv("LOG_DIR", str(settings.BASE_DIR / "logs"))

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    'formatters': {
        'simple': {
            'format': '[{asctime}] {levelname} {name} | {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },

    'handlers': {
        'app_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOG_DIR, 'app.log'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'simple',
            'filters': ['exclude_errors'],
        },
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(LOG_DIR, 'error.log'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'simple',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },

    'filters': {
        'exclude_errors': {
            '()': 'aicounting.app_logging.MaxLevelFilter',
            'max_level': 39,  # WARNING and below
        },
    },

    'root': {
        'handlers': ['app_file', 'error_file'],
        'level': 'INFO',
    },

    'loggers': {
        'django': {
            'handlers': ['app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

if settings.DEBUG:
    LOGGING['root']['handlers'].append('console')