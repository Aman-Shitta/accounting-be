"""
Make ``FirmMembership.firm`` required.

Reviewers were the only role allowed to exist without a firm. Now every
membership belongs to one, so the round-robin that hands out review work can be
scoped to the firm that owns the document, and a reviewer never sees another
firm's clients.
"""


import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0002_drop_firmless_memberships'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='firmmembership',
            name='firm',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='tenancy.firm'),
        ),
        migrations.AddIndex(
            model_name='firmmembership',
            index=models.Index(fields=['firm', 'role', 'is_active'], name='firm_member_firm_id_bad6e6_idx'),
        ),
    ]
