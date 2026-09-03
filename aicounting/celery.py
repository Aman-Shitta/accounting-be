import os

from celery import Celery

# set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aicounting.settings')

app = Celery('aicounting')

# Load config from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Discover tasks from all registered apps
app.autodiscover_tasks()
