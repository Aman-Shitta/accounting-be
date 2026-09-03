"""
Config versioning — the replacement for the four snapshot tables.

The property that matters: a period pins the configuration it was opened
against, so later edits cannot rewrite a month in progress. And opening a
period writes no files, where the old implementation copied every source file
into blob storage every month.
"""

import pytest
from django.core.files.storage import default_storage
from django.db.models import ProtectedError

from v1.configuration.models import ConfigVersion, DocumentSource, DocumentType, ExtractionField
from v1.configuration.services.publish import (
    ConfigurationIncomplete,
    current_version,
    publish_config,
    validate_configuration,
)
from v1.periods.models import AccountingPeriod, PeriodDocument
from v1.periods.services.open_period import PeriodAlreadyOpen, open_period, resolved_source

pytestmark = pytest.mark.django_db


def test_publishing_freezes_sources_fields_and_accounts(configured_client):
    version = publish_config(configured_client["client"])

    sources = {s["name"]: s for s in version.payload["document_sources"]}
    assert set(sources) == {"ADP Payroll", "Operating Account"}

    bank = sources["Operating Account"]
    assert bank["is_transactional"] is True
    assert bank["fields"] == []
    assert bank["ledger_account"]["account_number"] == "1000"

    payroll = sources["ADP Payroll"]
    assert [f["key"] for f in payroll["fields"]] == ["gross_wages", "employer_taxes"]
    assert payroll["fields"][0]["prompt_hint"].startswith("Total gross wages")
    assert payroll["fields"][0]["ledger_account"]["account_number"] == "6000"


def test_versions_increment_per_client(configured_client, two_firms):
    client = configured_client["client"]

    assert publish_config(client).version == 1
    assert publish_config(client).version == 2
    assert current_version(client).version == 2


def test_publishing_refuses_a_field_configured_source_with_no_fields(configured_client):
    configured_client["payroll_source"].fields.all().delete()

    with pytest.raises(ConfigurationIncomplete):
        publish_config(configured_client["client"])


def test_publishing_refuses_a_transactional_source_with_no_account(configured_client):
    bank = configured_client["bank_source"]
    bank.ledger_account = None
    bank.save()

    problems = validate_configuration(configured_client["client"])
    assert any("no ledger account" in p for p in problems)


def test_publishing_refuses_a_client_with_nothing_configured(two_firms):
    with pytest.raises(ConfigurationIncomplete):
        publish_config(two_firms["b"]["clients"][0])


# ---- opening a period -------------------------------------------------------


def test_opening_a_period_pins_the_current_version(configured_client):
    client = configured_client["client"]
    version = publish_config(client)

    period = open_period(client, 2026, 3)

    assert period.config_version == version
    assert period.status == AccountingPeriod.Status.INITIATED


def test_opening_a_period_publishes_a_first_version_if_needed(configured_client):
    client = configured_client["client"]
    assert current_version(client) is None

    period = open_period(client, 2026, 3)

    assert period.config_version.version == 1


def test_opening_a_period_creates_one_document_per_source(configured_client):
    period = open_period(configured_client["client"], 2026, 3)

    documents = PeriodDocument.objects.filter(period=period)
    assert documents.count() == 2
    assert set(documents.values_list("source_name", flat=True)) == {
        "ADP Payroll",
        "Operating Account",
    }
    assert all(d.status == PeriodDocument.Status.PENDING for d in documents)


def test_opening_a_period_copies_no_files(configured_client, tmp_path, settings):
    """
    The old implementation wrote a byte copy of every source file into blob
    storage on every period open. Nothing should be written now.
    """
    settings.MEDIA_ROOT = tmp_path
    before = set(default_storage.listdir("")[1]) if default_storage.exists("") else set()

    open_period(configured_client["client"], 2026, 3)

    after = set(default_storage.listdir("")[1]) if default_storage.exists("") else set()
    assert after == before


def test_a_month_cannot_be_opened_twice(configured_client):
    client = configured_client["client"]
    open_period(client, 2026, 3)

    with pytest.raises(PeriodAlreadyOpen):
        open_period(client, 2026, 3)


def test_a_deleted_period_frees_the_month(configured_client):
    client = configured_client["client"]
    period = open_period(client, 2026, 3)
    period.soft_delete()

    reopened = open_period(client, 2026, 3)
    assert reopened.pk != period.pk


# ---- the property the whole design exists for -------------------------------


def test_editing_config_after_opening_leaves_the_period_untouched(configured_client):
    client = configured_client["client"]
    period = open_period(client, 2026, 3)

    ExtractionField.objects.create(
        document_source=configured_client["payroll_source"],
        key="bonus",
        label="Bonus",
        direction=ExtractionField.Direction.DEBIT,
    )
    DocumentSource.objects.create(
        client=client, name="Amex", document_type=DocumentType.CREDIT_CARD
    )
    configured_client["payroll_source"].fields.filter(key="gross_wages").update(
        label="Renamed"
    )

    frozen = {s["name"]: s for s in period.config_version.payload["document_sources"]}
    assert "Amex" not in frozen
    assert [f["key"] for f in frozen["ADP Payroll"]["fields"]] == [
        "gross_wages",
        "employer_taxes",
    ]
    assert frozen["ADP Payroll"]["fields"][0]["label"] == "Gross Wages"


def test_a_later_period_picks_up_the_new_config(configured_client):
    client = configured_client["client"]
    march = open_period(client, 2026, 3)

    DocumentSource.objects.create(
        client=client,
        name="Amex",
        document_type=DocumentType.CREDIT_CARD,
        ledger_account=configured_client["cash"],
    )
    publish_config(client)

    april = open_period(client, 2026, 4)

    assert april.config_version.version > march.config_version.version
    assert april.documents.count() == 3
    assert march.documents.count() == 2


def test_a_pinned_version_cannot_be_deleted(configured_client):
    client = configured_client["client"]
    period = open_period(client, 2026, 3)

    with pytest.raises(ProtectedError):
        period.config_version.delete()


def test_a_document_resolves_its_frozen_source(configured_client):
    period = open_period(configured_client["client"], 2026, 3)
    document = period.documents.get(source_name="ADP Payroll")

    frozen = resolved_source(document)
    assert frozen["document_type"] == DocumentType.PAYROLL
    assert len(frozen["fields"]) == 2


def test_one_version_row_replaces_the_old_mirror_tables(configured_client):
    """
    Two sources, two fields, no templates would have meant roughly six mirror
    rows plus two copied files per period. It is one row now.
    """
    client = configured_client["client"]
    for month in (1, 2, 3):
        open_period(client, 2026, month)

    assert ConfigVersion.objects.filter(client=client).count() == 1
    assert AccountingPeriod.objects.filter(client=client).count() == 3
