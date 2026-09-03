"""
Freezing a client's configuration.

Publishing serialises the client's document sources, extraction fields,
journal templates and template lines into one immutable JSONB document. An
accounting period pins the version current at the moment it was opened, so
configuration edits afterwards cannot rewrite a month that is already in
progress.

This replaces four mirror tables that duplicated every configuration row on
every period open — and copied the source files alongside them.
"""

import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from v1.configuration.models import (
    ConfigVersion,
    DocumentSource,
    JournalTemplate,
)

logger = logging.getLogger(__name__)

PAYLOAD_SCHEMA_VERSION = 1


class ConfigurationIncomplete(ValidationError):
    """The configuration cannot be published as it stands."""


def build_payload(client) -> dict:
    """
    Serialise a client's live configuration.

    Read whole at period open and at journal-entry generation, never queried
    across periods — which is why it is a document rather than a set of rows.
    """
    sources = (
        DocumentSource.objects.filter(client=client, is_active=True)
        .select_related("ledger_account", "default_offset_account")
        .prefetch_related("fields__ledger_account", "fields__offset_ledger_account")
        .order_by("name")
    )

    templates = (
        JournalTemplate.objects.filter(client=client)
        .prefetch_related("lines__extraction_field", "lines__ledger_account", "sources")
        .order_by("name")
    )

    return {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "client": {
            "id": str(client.id),
            "name": client.name,
            "external_ref": client.external_ref,
        },
        "document_sources": [_serialize_source(s) for s in sources],
        "journal_templates": [_serialize_template(t) for t in templates],
    }


def _account_ref(account) -> dict | None:
    """
    A ledger account as it appears in the frozen payload.

    Ids are stringified: the payload is JSONB, and a UUID is not JSON.
    """
    if account is None:
        return None
    return {
        "id": str(account.id),
        "account_number": account.account_number,
        "name": account.name,
    }


def _serialize_source(source: DocumentSource) -> dict:
    return {
        # `key` is what a PeriodDocument stores, so it must stay stable for the
        # life of the source. The primary key is the only thing that does.
        "key": str(source.id),
        "id": str(source.id),
        "name": source.name,
        "document_type": source.document_type,
        "is_transactional": source.is_transactional,
        "ledger_account": _account_ref(source.ledger_account),
        "default_offset_account": _account_ref(source.default_offset_account),
        "extraction_notes": source.extraction_notes,
        "fields": [
            {
                "id": str(field.id),
                "key": field.key,
                "label": field.label,
                "prompt_hint": field.prompt_hint,
                "direction": field.direction,
                "ledger_account": _account_ref(field.ledger_account),
                "offset_ledger_account": _account_ref(field.offset_ledger_account),
                "position": field.position,
            }
            for field in source.fields.all()
        ],
    }


def _serialize_template(template: JournalTemplate) -> dict:
    return {
        "key": str(template.id),
        "id": str(template.id),
        "name": template.name,
        "reference": template.reference,
        "frequency": template.frequency,
        "entry_type": template.entry_type,
        "uses_extracted_fields": template.uses_extracted_fields,
        "description": template.description,
        "source_keys": [str(s.id) for s in template.sources.all()],
        "lines": [
            {
                "key": str(line.id),
                "id": str(line.id),
                "side": line.side,
                "amount_source": line.amount_source,
                "extraction_field_key": (
                    line.extraction_field.key if line.extraction_field else None
                ),
                "fixed_amount": (
                    str(line.fixed_amount) if line.fixed_amount is not None else None
                ),
                "ledger_account": _account_ref(line.ledger_account),
                "label": line.label,
                "comment": line.comment,
                "position": line.position,
            }
            for line in template.lines.all()
        ],
    }


def validate_configuration(client) -> list[str]:
    """
    Reasons the configuration cannot be published, as human-readable strings.
    Empty means it is publishable.
    """
    problems = []

    sources = list(
        DocumentSource.objects.filter(client=client, is_active=True).prefetch_related("fields")
    )
    if not sources:
        problems.append("No document sources are configured.")

    for source in sources:
        fields = list(source.fields.all())

        if source.is_field_configured and not fields:
            problems.append(
                f"'{source.name}' is a {source.get_document_type_display()} and needs "
                f"at least one extraction field."
            )
        if source.is_transactional and fields:
            problems.append(
                f"'{source.name}' produces a transaction list and cannot have "
                f"extraction fields."
            )
        if source.is_transactional and source.ledger_account is None:
            problems.append(f"'{source.name}' has no ledger account set.")

    return problems


@transaction.atomic
def publish_config(client, published_by=None) -> ConfigVersion:
    """
    Freeze the client's current configuration as a new version.

    Raises :class:`ConfigurationIncomplete` when the configuration is not
    publishable — better to refuse than to open a period against a
    configuration that cannot extract anything.
    """
    problems = validate_configuration(client)
    if problems:
        raise ConfigurationIncomplete(problems)

    next_version = (
        ConfigVersion.objects.filter(client=client).aggregate(Max("version"))["version__max"]
        or 0
    ) + 1

    version = ConfigVersion.objects.create(
        client=client,
        version=next_version,
        payload=build_payload(client),
        published_by=published_by,
    )

    logger.info(f"Published config v{next_version} for client {client.id}")
    return version


def current_version(client) -> ConfigVersion | None:
    """The most recently published version, or ``None`` if never published."""
    return ConfigVersion.objects.filter(client=client).order_by("-version").first()
