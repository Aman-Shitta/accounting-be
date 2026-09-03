"""
Limit/offset pagination.

DRF's pagination classes are wired to generic views; with plain ``APIView``
this one function does the same job and keeps the response shape identical.
"""

from django.db.models import QuerySet
from rest_framework.request import Request

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def _int_param(request: Request, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        # A junk value is a client bug, not a reason to 500.
        return default


def paginate(queryset: QuerySet, request: Request) -> tuple[list, dict]:
    """
    Return one page of rows and the metadata that accompanies it.

    ``next`` and ``previous`` are absolute URLs so a client can follow them
    without reassembling query strings.
    """
    limit = max(1, min(_int_param(request, "limit", DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, _int_param(request, "offset", 0))

    count = queryset.count()
    rows = list(queryset[offset : offset + limit])

    return rows, {
        "count": count,
        "next": _page_url(request, offset + limit, limit)
        if offset + limit < count
        else None,
        "previous": _page_url(request, max(0, offset - limit), limit)
        if offset > 0
        else None,
    }


def _page_url(request: Request, offset: int, limit: int) -> str:
    query = request.query_params.copy()
    query["limit"] = str(limit)
    query["offset"] = str(offset)
    return request.build_absolute_uri(f"{request.path}?{query.urlencode()}")
