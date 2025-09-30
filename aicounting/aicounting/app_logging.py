# import os
# from django.conf import settings

# LOGGING = {
#     'version': 1,
#     'disable_existing_loggers': False,

#     'formatters': {
#         'verbose': {
#             'format': '[{asctime}] {levelname} {name} {message}',
#             'style': '{',
#         },
#     },

#     'handlers': {
#         'info_file': {
#             'level': 'INFO',
#             'class': 'logging.FileHandler',
#             'filename': os.path.join(settings.BASE_DIR, 'aicounting.log'),
#             'formatter': 'verbose',
#         },
#         'error_file': {
#             'level': 'ERROR',
#             'class': 'logging.FileHandler',
#             'filename': os.path.join(settings.BASE_DIR, 'error.log'),
#             'formatter': 'verbose',
#         },
#     },

#     'root': {
#         'handlers': ['info_file', 'error_file'],
#         'level': 'INFO',
#     },

#     'loggers': {
#         'django': {
#             'handlers': ['info_file', 'error_file'],
#             'level': 'INFO',
#             'propagate': True,
#         },
#         'django.request': {
#             'handlers': ['error_file'],
#             'level': 'ERROR',
#             'propagate': False,
#         },
#         'django.server': {
#             'handlers': ['info_file', 'error_file'],
#             'level': 'INFO',
#             'propagate': False,
#         },
#     },
# }


# LOGGING = {
#     'version': 1,
#     'disable_existing_loggers': False,
#     'handlers': {
#         'console': {
#             'class': 'logging.StreamHandler',
#         },
#     },
#     'root': {
#         'handlers': ['console'],
#         'level': 'DEBUG',
#     },
#     'loggers': {
#         'django': {
#             'handlers': ['console'],
#             'level': 'INFO',  # You can set this to 'DEBUG' if you want Django internals too
#             # 'propagate': False,
#         },
#         # Your app logger
#         'aicounting': {
#             'handlers': ['console'],
#             'level': 'DEBUG',
#             # 'propagate': False,
#         },
#     },
# }


import sys
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',  # Or 'DEBUG' for more detailed logs
            'class': 'logging.StreamHandler',
            'stream': sys.stdout,
            'formatter': 'verbose'
        },
    },
    'loggers': {
        '': {  # This is the root logger, catching all messages
            'handlers': ['console'],
            'level': 'INFO',  # Or 'DEBUG'
            'propagate': True,
        },
        'django': { # Example for specific logger
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True, # Prevent messages from being handled by the root logger again
        },
    },
}