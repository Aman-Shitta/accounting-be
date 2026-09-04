"""
Seed the system default document categories.

These are the six kinds every deployment ships with, so a firm's first
document source isn't blocked on configuring a category from nothing. A firm
is free to retire any of these it doesn't use and add its own — see
``DocumentCategory``.
"""

from django.db import migrations

DEFAULTS = [
    ("bank_statement", "Bank Statement", "transactional"),
    ("credit_card", "Credit Card", "transactional"),
    ("check_register", "Check Register", "transactional"),
    ("payroll", "Payroll", "fields"),
    ("sales", "Sales", "fields"),
    ("misc", "Misc", "fields"),
]


def seed_categories(apps, schema_editor):
    DocumentCategory = apps.get_model("configuration", "DocumentCategory")
    for key, label, mode in DEFAULTS:
        DocumentCategory.objects.get_or_create(
            firm=None,
            key=key,
            defaults={"label": label, "extraction_mode": mode},
        )


def remove_categories(apps, schema_editor):
    DocumentCategory = apps.get_model("configuration", "DocumentCategory")
    DocumentCategory.objects.filter(
        firm__isnull=True, key__in=[key for key, _, _ in DEFAULTS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("configuration", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_categories, reverse_code=remove_categories),
    ]
