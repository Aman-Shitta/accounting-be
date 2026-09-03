"""
Clear the way for firm-scoped reviewers.

Drops the constraint that let reviewers exist without a firm, and removes any
membership still relying on it. Split from the schema change in 0003 because
the delete has to commit before the column can be altered — Postgres refuses to
ALTER a table with pending trigger events from the same transaction.
"""

from django.db import migrations


def drop_firmless_memberships(apps, schema_editor):
    """
    Remove memberships with no firm.

    A firmless reviewer has no firm to be scoped to and no way to guess one, so
    there is nothing to migrate them onto. Re-invite them into the firms they
    should review for.
    """
    FirmMembership = apps.get_model("tenancy", "FirmMembership")
    dropped = FirmMembership.objects.filter(firm__isnull=True).delete()[0]
    if dropped:
        print(f"  Removed {dropped} firmless membership(s); re-invite per firm.")


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="firmmembership",
            name="only_reviewers_may_be_firmless",
        ),
        migrations.RunPython(
            drop_firmless_memberships,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
