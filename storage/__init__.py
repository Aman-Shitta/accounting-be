"""
File storage: path conventions, ``upload_to`` callables, artifact writers.

Backend-agnostic — everything goes through ``django.core.files.storage
.default_storage``, so moving from the local filesystem to GCS is a
``STORAGES`` setting change.
"""
