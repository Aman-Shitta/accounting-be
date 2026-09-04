"""
Structured logging and the Sentry wiring built on top of it.

The property that matters for Sentry specifically: request and task handling
throughout this codebase catches its own exceptions and turns them into a
response or a failed-status row rather than letting them propagate (see
v1/common/exceptions.py and v1/periods/tasks.py) — so Sentry's usual "catch
what Django/Celery would otherwise raise" hook has little to catch.
LoggingIntegration is what actually captures these: any existing
logger.error(..., exc_info=True) becomes a Sentry event with no call site
needing to know Sentry exists. These tests exercise that path directly
instead of assuming it works.
"""

import json
import logging

from aicounting.logging import StructuredFormatter


def _formatted(record: logging.LogRecord) -> dict:
    return json.loads(StructuredFormatter().format(record))


def _record(level=logging.INFO, msg="hello", exc_info=None, **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="v1.periods.tasks",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_a_plain_message_becomes_one_json_object_with_the_core_fields():
    payload = _formatted(_record(msg="Document does not exist: abc"))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "v1.periods.tasks"
    assert payload["message"] == "Document does not exist: abc"
    assert "exception" not in payload
    assert "extra" not in payload


def test_extra_fields_ride_along_under_their_own_key():
    payload = _formatted(
        _record(document_id="abc-123", firm_id=42)
    )

    assert payload["extra"] == {"document_id": "abc-123", "firm_id": 42}


def test_an_exception_is_rendered_as_a_full_traceback_string():
    try:
        raise ValueError("bad amount")
    except ValueError:
        import sys

        payload = _formatted(
            _record(level=logging.ERROR, msg="boom", exc_info=sys.exc_info())
        )

    assert "ValueError: bad amount" in payload["exception"]
    assert payload["level"] == "ERROR"


def test_output_is_a_single_line_of_valid_json():
    """A log shipper reads one JSON object per line — a stray newline breaks that."""
    line = StructuredFormatter().format(_record())
    assert "\n" not in line
    json.loads(line)  # does not raise


# ---- Sentry wiring ----------------------------------------------------------


def test_sentry_is_not_initialized_without_a_dsn(settings):
    """The whole point: tests and local dev never need a DSN to run cleanly."""
    import sentry_sdk

    assert settings.SENTRY_DSN is None or settings.SENTRY_DSN == ""
    assert sentry_sdk.get_client().is_active() is False


def test_the_logging_integration_turns_an_error_log_into_a_sentry_event():
    """
    Exercises the exact pattern used throughout v1/periods/tasks.py:
    logger.error(..., exc_info=True) inside an except block that otherwise
    swallows the exception. If this stopped working, Sentry would go quiet
    while the application kept behaving exactly the same — the worst kind of
    regression to miss.
    """
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    captured = []
    sentry_sdk.init(
        dsn="https://public@o0.ingest.sentry.io/0",
        integrations=[LoggingIntegration(level=None, event_level=logging.ERROR)],
        before_send=lambda event, hint: captured.append(event) or None,
    )
    try:
        logger = logging.getLogger("v1.periods.tasks")
        try:
            raise ZeroDivisionError("division by zero")
        except ZeroDivisionError:
            logger.error("Error processing document abc: division by zero", exc_info=True)

        assert len(captured) == 1
        assert captured[0]["level"] == "error"
        assert captured[0]["exception"]["values"][0]["type"] == "ZeroDivisionError"
    finally:
        sentry_sdk.init(dsn=None)  # don't leak this client into later tests


def test_a_plain_info_log_does_not_become_a_sentry_event():
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    captured = []
    sentry_sdk.init(
        dsn="https://public@o0.ingest.sentry.io/0",
        integrations=[LoggingIntegration(level=None, event_level=logging.ERROR)],
        before_send=lambda event, hint: captured.append(event) or None,
    )
    try:
        logging.getLogger("v1.periods.tasks").info("Queued extraction for document abc")
        assert captured == []
    finally:
        sentry_sdk.init(dsn=None)
