"""
Document categories, and the transactional/field-configured distinction.

Categories are configuration, not a fixed enum: a firm picks from the system
defaults or adds its own, and a source just points at one. What's genuinely
fixed is the *behavior* a category declares — transactional or fields — since
that is a statement about what a pipeline can produce, not about a client's
business.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from v1.configuration.models import (
    DocumentCategory,
    DocumentSource,
    ExtractionField,
    JournalTemplate,
    JournalTemplateLine,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def bank_statement_category(db):
    return DocumentCategory.objects.get(firm=None, key="bank_statement")


@pytest.fixture
def payroll_category(db):
    return DocumentCategory.objects.get(firm=None, key="payroll")


# ------------------------------------------------------------- system defaults


def test_the_six_system_defaults_exist_with_no_firm():
    defaults = DocumentCategory.objects.filter(firm=None)
    assert {c.key for c in defaults} == {
        "bank_statement",
        "credit_card",
        "check_register",
        "payroll",
        "sales",
        "misc",
    }


def test_every_system_default_falls_into_exactly_one_mode():
    defaults = DocumentCategory.objects.filter(firm=None)
    modes = {c.key: c.extraction_mode for c in defaults}

    assert modes["bank_statement"] == DocumentCategory.ExtractionMode.TRANSACTIONAL
    assert modes["credit_card"] == DocumentCategory.ExtractionMode.TRANSACTIONAL
    assert modes["check_register"] == DocumentCategory.ExtractionMode.TRANSACTIONAL
    assert modes["payroll"] == DocumentCategory.ExtractionMode.FIELDS
    assert modes["sales"] == DocumentCategory.ExtractionMode.FIELDS
    assert modes["misc"] == DocumentCategory.ExtractionMode.FIELDS


# ------------------------------------------------------- configurability itself


def test_a_firm_can_add_its_own_category(two_firms):
    category = DocumentCategory.objects.create(
        firm=two_firms["a"]["firm"],
        key="rent_roll",
        label="Rent Roll",
        extraction_mode=DocumentCategory.ExtractionMode.FIELDS,
    )
    assert category in DocumentCategory.available_to(two_firms["a"]["firm"])


def test_a_firms_custom_category_is_invisible_to_another_firm(two_firms):
    category = DocumentCategory.objects.create(
        firm=two_firms["a"]["firm"],
        key="rent_roll",
        label="Rent Roll",
        extraction_mode=DocumentCategory.ExtractionMode.FIELDS,
    )
    assert category not in DocumentCategory.available_to(two_firms["b"]["firm"])


def test_system_defaults_are_visible_to_every_firm(two_firms, bank_statement_category):
    assert bank_statement_category in DocumentCategory.available_to(two_firms["a"]["firm"])
    assert bank_statement_category in DocumentCategory.available_to(two_firms["b"]["firm"])


def test_two_firms_may_each_add_a_category_with_the_same_key(two_firms):
    """The old schema made this a fixed platform-wide enum; it no longer is."""
    for tag in ("a", "b"):
        DocumentCategory.objects.create(
            firm=two_firms[tag]["firm"],
            key="rent_roll",
            label="Rent Roll",
            extraction_mode=DocumentCategory.ExtractionMode.FIELDS,
        )
    assert DocumentCategory.objects.filter(key="rent_roll").count() == 2


def test_one_firm_cannot_reuse_a_key_twice(two_firms):
    DocumentCategory.objects.create(
        firm=two_firms["a"]["firm"],
        key="rent_roll",
        label="Rent Roll",
        extraction_mode=DocumentCategory.ExtractionMode.FIELDS,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentCategory.objects.create(
            firm=two_firms["a"]["firm"],
            key="rent_roll",
            label="Rent Roll (duplicate)",
            extraction_mode=DocumentCategory.ExtractionMode.TRANSACTIONAL,
        )


def test_an_inactive_category_drops_out_of_the_picker_but_a_source_keeps_it(
    configured_client, bank_statement_category
):
    bank_statement_category.is_active = False
    bank_statement_category.save()

    firm = configured_client["client"].firm
    assert bank_statement_category not in DocumentCategory.available_to(firm)
    # The source that already uses it is untouched.
    assert configured_client["bank_source"].category == bank_statement_category


# ---------------------------------------------------- the behavior distinction


def test_a_transactional_category_reports_itself_correctly(bank_statement_category):
    source = DocumentSource(category=bank_statement_category)
    assert source.is_transactional
    assert not source.is_field_configured


def test_a_field_configured_category_reports_itself_correctly(payroll_category):
    source = DocumentSource(category=payroll_category)
    assert source.is_field_configured
    assert not source.is_transactional


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


def test_a_transactional_source_with_fields_fails_validation(
    configured_client, bank_statement_category
):
    """Guards the case where a source's category is changed after fields exist."""
    payroll = configured_client["payroll_source"]
    payroll.category = bank_statement_category

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
