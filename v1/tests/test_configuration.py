"""
The document-type distinction.

A transactional document is a list of transactions and has nothing to name in
advance; a field-configured document yields a fixed set of named values that
must be declared before extraction can run. The old schema treated both as
"input files with attributes", so nothing stopped someone configuring
attributes on a bank statement, where they were silently ignored.
"""

import pytest
from django.core.exceptions import ValidationError

from v1.configuration.models import (
    DocumentSource,
    DocumentType,
    ExtractionField,
    JournalTemplate,
    JournalTemplateLine,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "doc_type",
    [DocumentType.BANK_STATEMENT, DocumentType.CREDIT_CARD, DocumentType.CHECK_REGISTER],
)
def test_transactional_types_are_classified_as_such(doc_type):
    source = DocumentSource(document_type=doc_type)
    assert source.is_transactional
    assert not source.is_field_configured


@pytest.mark.parametrize(
    "doc_type", [DocumentType.PAYROLL, DocumentType.SALES, DocumentType.MISC]
)
def test_field_configured_types_are_classified_as_such(doc_type):
    source = DocumentSource(document_type=doc_type)
    assert source.is_field_configured
    assert not source.is_transactional


def test_every_document_type_falls_into_exactly_one_group():
    transactional = DocumentType.transactional()
    field_configured = DocumentType.field_configured()

    assert not transactional & field_configured
    assert transactional | field_configured == {t.value for t in DocumentType}


def test_a_field_cannot_be_added_to_a_transactional_source(configured_client):
    field = ExtractionField(
        document_source=configured_client["bank_source"],
        key="total",
        label="Total",
        direction=ExtractionField.Direction.DEBIT,
    )

    with pytest.raises(ValidationError, match="transaction list"):
        field.full_clean()


def test_a_field_is_accepted_on_a_field_configured_source(configured_client):
    field = ExtractionField(
        document_source=configured_client["payroll_source"],
        key="net_pay",
        label="Net Pay",
        direction=ExtractionField.Direction.CREDIT,
    )
    field.full_clean()  # does not raise


def test_a_transactional_source_with_fields_fails_validation(configured_client):
    """Guards the case where a source's type is changed after fields exist."""
    payroll = configured_client["payroll_source"]
    payroll.document_type = DocumentType.BANK_STATEMENT

    with pytest.raises(ValidationError, match="transaction list"):
        payroll.clean()


def test_a_transactional_source_carries_its_accounts_instead_of_fields(configured_client):
    bank = configured_client["bank_source"]

    assert bank.fields.count() == 0
    assert bank.ledger_account == configured_client["cash"]
    assert bank.default_offset_account == configured_client["cash"]


def test_fields_keep_their_configured_order(configured_client):
    keys = list(
        configured_client["payroll_source"].fields.values_list("key", flat=True)
    )
    assert keys == ["gross_wages", "employer_taxes"]


# ---- journal template lines -------------------------------------------------


def test_a_field_backed_line_needs_a_field(configured_client):
    template = JournalTemplate.objects.create(
        client=configured_client["client"], name="Payroll JE"
    )
    line = JournalTemplateLine(
        template=template,
        side=JournalTemplateLine.Side.DEBIT,
        amount_source=JournalTemplateLine.AmountSource.EXTRACTED_FIELD,
    )

    with pytest.raises(ValidationError, match="extracted field"):
        line.clean()


def test_a_fixed_line_needs_an_amount(configured_client):
    template = JournalTemplate.objects.create(
        client=configured_client["client"], name="Rent JE"
    )
    line = JournalTemplateLine(
        template=template,
        side=JournalTemplateLine.Side.DEBIT,
        amount_source=JournalTemplateLine.AmountSource.FIXED,
    )

    with pytest.raises(ValidationError, match="fixed"):
        line.clean()


def test_a_manual_line_needs_neither(configured_client):
    template = JournalTemplate.objects.create(
        client=configured_client["client"], name="Accrual JE"
    )
    line = JournalTemplateLine(
        template=template,
        side=JournalTemplateLine.Side.CREDIT,
        amount_source=JournalTemplateLine.AmountSource.MANUAL,
    )
    line.clean()  # does not raise
