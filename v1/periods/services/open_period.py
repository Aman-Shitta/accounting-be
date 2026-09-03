"""
Opening an accounting period.

Replaces ``create_monthly_accounting_with_snapshots`` and the four
``_create_*_snapshot`` helpers it called. Opening a period now writes one
period row and one document row per configured source — and, crucially, copies
no files. The old implementation read every source file out of blob storage and
wrote a byte-for-byte copy back under a new key, every month, for every client.
"""

import logging

from django.core.exceptions import ValidationError
from django.db import transaction

from v1.configuration.services.publish import current_version, publish_config
from v1.periods.models import AccountingPeriod, PeriodDocument

logger = logging.getLogger(__name__)


class PeriodAlreadyOpen(ValidationError):
    """A period for this client, year and month already exists."""


@transaction.atomic
def open_period(client, year: int, month: int, opened_by=None) -> AccountingPeriod:
    """
    Open a month for a client, pinned to their current configuration.

    Publishes a first config version if the client has never published one, so
    opening a period is a single action rather than two.
    """
    if not 1 <= month <= 12:
        raise ValidationError({"month": "Must be between 1 and 12."})

    if AccountingPeriod.objects.filter(
        client=client, year=year, month=month, is_deleted=False
    ).exists():
        raise PeriodAlreadyOpen(
            f"{month:02d}/{year} is already open for {client.name}."
        )

    config = current_version(client) or publish_config(client, published_by=opened_by)

    period = AccountingPeriod.objects.create(
        client=client,
        config_version=config,
        year=year,
        month=month,
        created_by=opened_by,
    )

    documents = create_documents(period)
    logger.info(
        f"Opened {month:02d}/{year} for client {client.id} against config "
        f"v{config.version} with {len(documents)} documents"
    )
    return period


def create_documents(period: AccountingPeriod) -> list[PeriodDocument]:
    """
    One document slot per source in the period's frozen configuration.

    ``source_key`` and ``source_name`` are copied from the payload so the slot
    keeps its identity even if the live source is later renamed or removed.
    """
    sources = period.config_version.payload.get("document_sources", [])

    return PeriodDocument.objects.bulk_create(
        [
            PeriodDocument(
                period=period,
                document_source_id=source["id"],
                source_key=source["key"],
                source_name=source["name"],
                document_type=source["document_type"],
                status=PeriodDocument.Status.PENDING,
            )
            for source in sources
        ]
    )


def resolved_source(document: PeriodDocument) -> dict | None:
    """
    The frozen configuration for a document's source.

    Read this rather than ``document.document_source`` wherever the answer
    must reflect how the period was set up, not how the client is configured
    now.
    """
    return document.period.config_version.source_by_key(document.source_key)
