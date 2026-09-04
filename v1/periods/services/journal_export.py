"""
Journal entry export.

The model already produces double-entry-shaped rows: every classified
``PeriodTransaction`` and every extracted ``PeriodFieldValue`` carries a
resolved ``ledger_account`` and ``offset_ledger_account``. This pairs each
into a balanced two-line entry and renders the result as a plain CSV any
system can import, or QuickBooks Desktop's IIF format — the two things
missing between "the system classified this" and "the firm can file it."

A row with no resolved account (not yet classified, or a field with no
account configured) is left out of the export rather than written with a
blank account, and reported back in ``problems`` instead — see
``build_journal_lines``.
"""

import calendar
import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from v1.periods.models import AccountingPeriod, PeriodDocument, PeriodFieldValue, PeriodTransaction


@dataclass
class JournalLine:
    entry: int
    entry_date: date | None
    account_number: str
    account_name: str
    debit: Decimal
    credit: Decimal
    memo: str
    source_type: str
    source_id: str


def _period_end(period: AccountingPeriod) -> date:
    last_day = calendar.monthrange(period.year, period.month)[1]
    return date(period.year, period.month, last_day)


def _parse_amount(raw: str) -> Decimal:
    """Field values are extracted as free text — strip the punctuation a
    document actually prints (``$1,234.56``) before parsing."""
    cleaned = raw.replace("$", "").replace(",", "").strip()
    return Decimal(cleaned)


def build_journal_lines(period: AccountingPeriod) -> tuple[list[JournalLine], list[str]]:
    """
    Pair every classified transaction and extracted field value in the period
    into a balanced two-line entry.

    Returns ``(lines, problems)``. Entries are numbered in the order they are
    built, which is stable (by document, then by page/line or field key) but
    not meaningful beyond pairing a TRNS to its SPL.
    """
    documents = (
        PeriodDocument.objects.filter(period=period)
        .prefetch_related(
            "transactions__ledger_account",
            "transactions__offset_ledger_account",
            "field_values__ledger_account",
            "field_values__offset_ledger_account",
        )
        .order_by("source_name")
    )

    lines: list[JournalLine] = []
    problems: list[str] = []
    entry = 0
    period_end = _period_end(period)

    for document in documents:
        transactions = sorted(
            document.transactions.all(), key=lambda t: (t.page_number, t.line_number)
        )
        for txn in transactions:
            if txn.ledger_account is None or txn.offset_ledger_account is None:
                when = txn.transaction_date or txn.raw_date or "an unknown date"
                what = txn.description[:60] or "no description"
                problems.append(
                    f"{document.source_name}: a transaction on {when} ({what}) "
                    f"has no resolved account and was left out."
                )
                continue

            amount = txn.amount or Decimal("0")
            if amount == 0:
                continue

            entry += 1
            memo = (
                f"{document.source_name}: {txn.description}"
                if txn.description
                else document.source_name
            )
            debit_account, credit_account = (
                (txn.ledger_account, txn.offset_ledger_account)
                if txn.direction == PeriodTransaction.Direction.DEBIT
                else (txn.offset_ledger_account, txn.ledger_account)
            )
            entry_date = txn.transaction_date or period_end
            lines.append(
                JournalLine(
                    entry, entry_date, debit_account.account_number, debit_account.name,
                    amount, Decimal("0"), memo, "transaction", str(txn.id),
                )
            )
            lines.append(
                JournalLine(
                    entry, entry_date, credit_account.account_number, credit_account.name,
                    Decimal("0"), amount, memo, "transaction", str(txn.id),
                )
            )

        field_values = sorted(
            document.field_values.all(), key=lambda f: (f.field_key, f.page_number)
        )
        for field in field_values:
            if field.ledger_account is None or field.offset_ledger_account is None:
                problems.append(
                    f"{document.source_name}: {field.field_label} has no resolved "
                    f"account and was left out."
                )
                continue

            try:
                amount = _parse_amount(field.value)
            except (InvalidOperation, TypeError):
                problems.append(
                    f"{document.source_name}: {field.field_label} value "
                    f"{field.value!r} is not a number and was left out."
                )
                continue
            if amount == 0:
                continue

            entry += 1
            memo = f"{document.source_name}: {field.field_label}"
            debit_account, credit_account = (
                (field.ledger_account, field.offset_ledger_account)
                if field.direction == PeriodFieldValue.Direction.DEBIT
                else (field.offset_ledger_account, field.ledger_account)
            )
            lines.append(
                JournalLine(
                    entry, period_end, debit_account.account_number, debit_account.name,
                    amount, Decimal("0"), memo, "field_value", str(field.id),
                )
            )
            lines.append(
                JournalLine(
                    entry, period_end, credit_account.account_number, credit_account.name,
                    Decimal("0"), amount, memo, "field_value", str(field.id),
                )
            )

    return lines, problems


def render_csv(lines: list[JournalLine]) -> str:
    """A plain journal — one row per line, two rows per entry."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Entry", "Date", "Account Number", "Account Name", "Debit", "Credit", "Memo"]
    )
    for line in lines:
        writer.writerow(
            [
                line.entry,
                line.entry_date.isoformat() if line.entry_date else "",
                line.account_number,
                line.account_name,
                f"{line.debit:.2f}" if line.debit else "",
                f"{line.credit:.2f}" if line.credit else "",
                line.memo,
            ]
        )
    return buffer.getvalue()


def render_iif(lines: list[JournalLine]) -> str:
    """
    QuickBooks Desktop IIF import, shaped as general journal entries.

    Convention: a debit is a positive amount and a credit is negative, so
    every entry's TRNS line plus its SPL lines sum to zero. This is the
    standard reading for a IIF general journal (a bank register uses the
    opposite convention) — verify against a real QuickBooks import before
    relying on this for anything that posts automatically.
    """
    buffer = io.StringIO()
    buffer.write("!TRNS\tTRNSID\tTRNSTYPE\tDATE\tACCNT\tNAME\tCLASS\tAMOUNT\tMEMO\n")
    buffer.write("!SPL\tSPLID\tTRNSTYPE\tDATE\tACCNT\tNAME\tCLASS\tAMOUNT\tMEMO\n")
    buffer.write("!ENDTRNS\n")

    by_entry: dict[int, list[JournalLine]] = {}
    for line in lines:
        by_entry.setdefault(line.entry, []).append(line)

    def signed_amount(line: JournalLine) -> Decimal:
        return line.debit - line.credit

    for entry_lines in by_entry.values():
        first, *rest = entry_lines
        date_str = first.entry_date.strftime("%m/%d/%Y") if first.entry_date else ""

        buffer.write(
            f"TRNS\t{first.entry}\tGENERAL JOURNAL\t{date_str}\t{first.account_number}"
            f"\t\t\t{signed_amount(first):.2f}\t{first.memo}\n"
        )
        for line in rest:
            buffer.write(
                f"SPL\t\tGENERAL JOURNAL\t{date_str}\t{line.account_number}"
                f"\t\t\t{signed_amount(line):.2f}\t{line.memo}\n"
            )
        buffer.write("ENDTRNS\n")

    return buffer.getvalue()
