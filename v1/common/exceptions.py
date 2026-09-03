"""
One exception handler for the whole API.

Replaces 178 bare ``except Exception`` blocks that turned every error — a
missing row, a validation failure, a genuine bug — into a 500 carrying a
stringified traceback.
"""

import logging

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.views import exception_handler as drf_exception_handler

from v1.common.responses import create_api_response

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    """
    Map an exception to the standard envelope.

    Unrecognised exceptions are logged with a full traceback and returned as a
    500 with a generic message — the traceback goes to the log, never to the
    client.
    """
    view = context.get("view")
    where = f"{view.__class__.__name__}" if view else "unknown view"

    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(detail=getattr(exc, "message_dict", None) or exc.messages)

    if isinstance(exc, Http404 | ObjectDoesNotExist):
        return create_api_response(status.HTTP_404_NOT_FOUND, "Not found.")

    if isinstance(exc, PermissionDenied):
        return create_api_response(status.HTTP_403_FORBIDDEN, str(exc.detail))

    if isinstance(exc, ValidationError):
        return create_api_response(
            status.HTTP_400_BAD_REQUEST, "Validation failed.", errors=exc.detail
        )

    if isinstance(exc, IntegrityError):
        logger.warning(f"Integrity error in {where}: {exc}")
        return create_api_response(
            status.HTTP_409_CONFLICT,
            "That conflicts with something that already exists.",
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        return create_api_response(
            response.status_code,
            str(detail) if detail else "Request failed.",
            errors=None if detail else response.data,
        )

    if isinstance(exc, APIException):
        return create_api_response(exc.status_code, str(exc.detail))

    logger.exception(f"Unhandled exception in {where}")
    return create_api_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "Something went wrong on our end."
    )
