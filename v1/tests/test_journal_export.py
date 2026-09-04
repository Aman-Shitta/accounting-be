"""
Journal entry export.

The property that matters: every classified transaction and extracted field
value becomes a balanced two-line entry, an unclassified one is left out and
reported rather than exported with a blank account, and the two file formats
actually render.
"""

from decimal import Decimal

import pytest

from v1.periods.models import PeriodDocument, PeriodFieldValue, PeriodTransaction
from v1.periods.services.journal_export import build_journal_lines, render_csv, render_iif
from v1.periods.services.open_period import open_period
from v1.tests.conftest import api_client_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def period_with_activity(configured_client):
    """An open period with one classified transaction and one payroll field."""
    client = configured_client["client"]
    cash = configured_client["cash"]
    wages = configured_client["wages"]

    period = open_period(client, 2026, 3)
    bank_doc = period.documents.get(category_key="bank_statement")
    payroll_doc = period.documents.get(category_key="payroll")

    PeriodTransaction.objects.create(
        document=bank_doc,
        page_number=1,
        line_number=1,
        transaction_date="2026-03-05",
        description="Coffee supplier payment",
        amount=Decimal("250.00"),
        direction=PeriodTransaction.Direction.CREDIT,
        ledger_account=cash,
        offset_ledger_account=wages,
    )
    # No resolved account — should be left out and reported.
    PeriodTransaction.objects.create(
        document=bank_doc,
        page_number=1,
        line_number=2,
        description="Unclassified line",
        amount=Decimal("40.00"),
        direction=PeriodTransaction.Direction.DEBIT,
    )

    PeriodFieldValue.objects.create(
        document=payroll_doc,
        field_key="gross_wages",
        field_label="Gross Wages",
        value="$1,500.00",
        direction=PeriodFieldValue.Direction.DEBIT,
        ledger_account=wages,
        offset_ledger_account=cash,
    )

    return {"period": period, "bank_doc": bank_doc, "payroll_doc": payroll_doc}


def test_a_classified_transaction_becomes_a_balanced_entry(period_with_activity):
    lines, problems = build_journal_lines(period_with_activity["period"])

    txn_lines = [line for line in lines if line.source_type == "transaction"]
    assert len(txn_lines) == 2
    assert {line.debit for line in txn_lines} == {Decimal("0"), Decimal("250.00")}
    assert {line.credit for line in txn_lines} == {Decimal("0"), Decimal("250.00")}
    # A credit-direction transaction debits the offset (wages) and credits the
    # ledger account it was classified against (cash).
    debit_line = next(line for line in txn_lines if line.debit)
    assert debit_line.account_number == "6000"
    credit_line = next(line for line in txn_lines if line.credit)
    assert credit_line.account_number == "1000"


def test_an_unclassified_transaction_is_left_out_and_reported(period_with_activity):
    lines, problems = build_journal_lines(period_with_activity["period"])

    assert not any(line.memo == "Unclassified line" for line in lines)
    assert any("Unclassified line" in p for p in problems)


def test_a_field_value_with_punctuation_parses_and_balances(period_with_activity):
    lines, _problems = build_journal_lines(period_with_activity["period"])

    field_lines = [line for line in lines if line.source_type == "field_value"]
    assert len(field_lines) == 2
    assert {line.debit for line in field_lines} == {Decimal("0"), Decimal("1500.00")}


def test_a_field_value_that_is_not_a_number_is_left_out_and_reported(
    period_with_activity,
):
    PeriodFieldValue.objects.filter(field_key="gross_wages").update(value="see attached")

    lines, problems = build_journal_lines(period_with_activity["period"])

    assert not any(line.source_type == "field_value" for line in lines)
    assert any("is not a number" in p for p in problems)


def test_entries_are_all_internally_balanced(period_with_activity):
    lines, _problems = build_journal_lines(period_with_activity["period"])

    by_entry: dict[int, list] = {}
    for line in lines:
        by_entry.setdefault(line.entry, []).append(line)

    for entry_lines in by_entry.values():
        debits = sum((line.debit for line in entry_lines), Decimal("0"))
        credits = sum((line.credit for line in entry_lines), Decimal("0"))
        assert debits == credits


def test_csv_renders_a_header_and_one_row_per_line(period_with_activity):
    lines, _problems = build_journal_lines(period_with_activity["period"])

    csv_text = render_csv(lines)
    rows = csv_text.strip().splitlines()

    assert rows[0] == "Entry,Date,Account Number,Account Name,Debit,Credit,Memo"
    assert len(rows) == 1 + len(lines)


def test_iif_renders_one_trns_and_spl_pair_per_entry(period_with_activity):
    lines, _problems = build_journal_lines(period_with_activity["period"])

    iif_text = render_iif(lines)

    entry_count = len({line.entry for line in lines})
    # Header lines are "!TRNS\t.../!SPL\t...", so anchor on the leading
    # newline to count only the data rows.
    assert iif_text.count("\nTRNS\t") == entry_count
    assert iif_text.count("\nSPL\t") == entry_count
    assert iif_text.count("\nENDTRNS\n") == entry_count


# ---- the API ----------------------------------------------------------------


def test_check_endpoint_reports_entry_count_and_problems(period_with_activity, two_firms):
    period = period_with_activity["period"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get(f"/api/v1/periods/{period.id}/journal-export/check/")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["entry_count"] == 2
    assert len(data["problems"]) == 1


def test_csv_export_downloads_as_an_attachment(period_with_activity, two_firms):
    period = period_with_activity["period"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get(f"/api/v1/periods/{period.id}/journal-export/")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert "attachment" in response["Content-Disposition"]
    assert b"Coffee supplier payment" in response.content


def test_iif_export_uses_the_iif_content_type(period_with_activity, two_firms):
    period = period_with_activity["period"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get(f"/api/v1/periods/{period.id}/journal-export/?type=iif")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-iif"
    assert b"GENERAL JOURNAL" in response.content


def test_an_unsupported_format_is_rejected(period_with_activity, two_firms):
    period = period_with_activity["period"]
    api = api_client_for(two_firms["a"]["owner"])

    response = api.get(f"/api/v1/periods/{period.id}/journal-export/?type=xlsx")

    assert response.status_code == 400


def test_a_firm_cannot_export_another_firms_period(period_with_activity, two_firms):
    period = period_with_activity["period"]
    api = api_client_for(two_firms["b"]["owner"])

    response = api.get(f"/api/v1/periods/{period.id}/journal-export/")

    assert response.status_code == 404
