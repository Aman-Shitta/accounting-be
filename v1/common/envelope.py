"""
Response envelope.

Every response is ``{"status", "status_code", "message", "data"|"errors"}``.

This is applied in ``finalize_response`` rather than in a renderer, because a
renderer only runs at serialization time — the envelope would exist on the
wire but not on ``response.data``, so tests and any server-side inspection
would see a different shape than clients do.
"""

ENVELOPE_KEYS = {"status", "status_code", "message"}

DEFAULT_MESSAGES = {
    "GET": "OK.",
    "POST": "Created.",
    "PUT": "Updated.",
    "PATCH": "Updated.",
    "DELETE": "Deleted.",
}


def wrap(data, status_code: int, method: str = "GET") -> dict:
    """Build the envelope around a view's payload."""
    if status_code >= 400:
        return {
            "status": "error",
            "status_code": status_code,
            "message": _error_message(data),
            "errors": data,
        }

    return {
        "status": "success",
        "status_code": status_code,
        "message": DEFAULT_MESSAGES.get(method, "OK."),
        "data": data,
    }


def _error_message(data) -> str:
    """Prefer DRF's own `detail` when there is one; otherwise stay generic."""
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return "Request failed."


class EnvelopeMixin:
    """
    Applies :func:`wrap` to every response a view returns.

    Skips responses that are already enveloped — the exception handler in
    :mod:`v1.common.exceptions` builds its own — and skips bodyless responses
    such as 204.
    """

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        data = getattr(response, "data", None)
        already_wrapped = isinstance(data, dict) and ENVELOPE_KEYS <= set(data)

        if data is not None and not already_wrapped:
            response.data = wrap(data, response.status_code, request.method)

        return response
