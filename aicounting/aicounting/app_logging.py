import os
from django.conf import settings


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
    },

    'handlers': {
        'info_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(settings.BASE_DIR, 'aicounting.log'),
            'formatter': 'verbose',
        },
        'error_file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': os.path.join(settings.BASE_DIR, 'error.log'),
            'formatter': 'verbose',
        },
    },

    'root': {
        'handlers': ['info_file', 'error_file'],
        'level': 'INFO',
    },

    'loggers': {
        'django': {
            'handlers': ['info_file', 'error_file'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.server': {
            'handlers': ['info_file', 'error_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}