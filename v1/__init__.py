"""
Version 1 of the aicounting API.

Each subpackage is a Django app; app labels come from the last path segment
(``v1.tenancy`` -> ``tenancy``). The auth app is named ``identity`` to avoid
colliding with ``django.contrib.auth``'s label.
"""
