"""
Seed a working firm for local development and for the frontend team.

Creates one firm with an owner, an accountant and a reviewer, one client with a
chart of accounts, one transactional and one field-configured document source,
a published config version and an open period.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from v1.configuration.models import DocumentSource, DocumentType, ExtractionField
from v1.configuration.services.publish import publish_config
from v1.identity.models import UserProfile
from v1.ledger.models import LedgerAccount
from v1.periods.models import AccountingPeriod
from v1.periods.services.open_period import open_period
from v1.tenancy.models import Client, ClientAssignment, Firm, FirmMembership

User = get_user_model()

PASSWORD = "demo-password-1234"

ACCOUNTS = [
    ("1000", "Operating Cash", "asset"),
    ("1100", "Accounts Receivable", "asset"),
    ("2000", "Accounts Payable", "liability"),
    ("4000", "Sales Revenue", "revenue"),
    ("6000", "Wages Expense", "expense"),
    ("6100", "Payroll Taxes", "expense"),
    ("6200", "Office Supplies", "expense"),
]

PAYROLL_FIELDS = [
    ("gross_wages", "Gross Wages", "Total gross wages on the payroll summary", "debit", "6000"),
    ("employer_taxes", "Employer Taxes", "Employer share of payroll taxes", "debit", "6100"),
    ("net_pay", "Net Pay", "Total net pay disbursed to employees", "credit", "1000"),
]


class Command(BaseCommand):
    help = "Create a demo firm, client, configuration and open period."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the existing demo firm first.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        if Firm.objects.filter(name="Demo Accounting LLP").exists():
            raise SystemExit(
                "Demo data already exists. Re-run with --reset to recreate it."
            )

        firm = Firm.objects.create(
            name="Demo Accounting LLP", city="Austin", state="TX", postal_code="78701"
        )

        owner = self._user("owner@demo.aicounting.app", "Dana", "Ortiz")
        FirmMembership.objects.create(user=owner, firm=firm, role=FirmMembership.Role.OWNER)

        accountant = self._user("accountant@demo.aicounting.app", "Sam", "Okafor")
        assignment_membership = FirmMembership.objects.create(
            user=accountant, firm=firm, role=FirmMembership.Role.ACCOUNTANT
        )

        reviewer = self._user("reviewer@demo.aicounting.app", "Robin", "Ng")
        FirmMembership.objects.create(
            user=reviewer, firm=firm, role=FirmMembership.Role.REVIEWER
        )

        client = Client.objects.create(
            firm=firm,
            name="Brightwater Coffee",
            external_ref="BWC",
            city="Austin",
            state="TX",
            allow_review=True,
        )
        ClientAssignment.objects.create(client=client, membership=assignment_membership)

        accounts = {
            number: LedgerAccount.objects.create(
                client=client, account_number=number, name=name, account_class=account_class
            )
            for number, name, account_class in ACCOUNTS
        }

        DocumentSource.objects.create(
            client=client,
            name="Operating Account 4471",
            document_type=DocumentType.BANK_STATEMENT,
            ledger_account=accounts["1000"],
            default_offset_account=accounts["1000"],
            extraction_notes="Coffee shop. Vendors are mostly food suppliers and utilities.",
        )

        payroll = DocumentSource.objects.create(
            client=client, name="Gusto Payroll", document_type=DocumentType.PAYROLL
        )
        for position, (key, label, hint, direction, account) in enumerate(PAYROLL_FIELDS):
            ExtractionField.objects.create(
                document_source=payroll,
                key=key,
                label=label,
                prompt_hint=hint,
                direction=direction,
                ledger_account=accounts[account],
                offset_ledger_account=accounts["1000"],
                position=position,
            )

        version = publish_config(client, published_by=owner)
        period = open_period(client, 2026, 1, opened_by=owner)

        self.stdout.write(self.style.SUCCESS("\nDemo data created.\n"))
        self.stdout.write(f"  Firm            {firm.name} ({firm.public_id})")
        self.stdout.write(f"  Client          {client.name} ({client.external_ref})")
        self.stdout.write(f"  Config version  v{version.version}, 2 sources")
        self.stdout.write(
            f"  Period          {period.month:02d}/{period.year}, "
            f"{period.documents.count()} documents awaiting upload"
        )
        self.stdout.write("\n  Sign in with any of these; password is the same:\n")
        for user in (owner, accountant, reviewer):
            role = user.firm_memberships.first().get_role_display()
            self.stdout.write(f"    {user.email:<38} {role}")
        self.stdout.write(f"\n  Password        {PASSWORD}\n")

    def _reset(self):
        """
        Remove the demo firm.

        Periods hold a PROTECT reference to their config version, so they have
        to go before the firm's clients can cascade away.
        """
        firms = Firm.objects.filter(name="Demo Accounting LLP")
        if not firms.exists():
            return

        AccountingPeriod.objects.filter(client__firm__in=firms).delete()
        firms.delete()
        User.objects.filter(email__endswith="@demo.aicounting.app").delete()
        self.stdout.write("Removed the previous demo data.")

    def _user(self, email: str, first_name: str, last_name: str):
        user = User.objects.create_user(
            username=email,
            email=email,
            password=PASSWORD,
            first_name=first_name,
            last_name=last_name,
        )
        UserProfile.objects.create(user=user, is_verified=True)
        return user
