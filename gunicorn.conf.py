# Gunicorn configuration
# Deploy: gunicorn aicounting.wsgi -c gunicorn.conf.py

import multiprocessing

# ── Workers ───────────────────────────────────────────────────────────────────
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
bind = "127.0.0.1:8000"

# ── Logging ───────────────────────────────────────────────────────────────────
# Only show WARNING+ in gunicorn-error.log — suppresses the INFO startup noise
# ("Starting gunicorn", "Booting worker", etc.)
loglevel = "warning"

errorlog = "/var/log/aicounting/gunicorn-error.log"
accesslog = "/var/log/aicounting/gunicorn-access.log"

# Access log: method + path + status + response time only.
# Default Apache Combined Log is noisy with IPs, user-agents, etc.
# %(m)s  = HTTP method  (GET, POST, …)
# %(U)s  = URL path     (/api/invoices/, …)
# %(q)s  = query string (empty string if none)
# %(s)s  = status code  (200, 404, 500, …)
# %(D)s  = response time in microseconds
access_log_format = '%(m)s %(U)s%(q)s %(s)s %(D)sµs'
