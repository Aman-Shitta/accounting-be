from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0029_alter_factaicmonthlyaccounting_unique_together_and_more'),
    ]

    operations = [
        # DimAICJETemplateGL: no other model references it
        migrations.DeleteModel(
            name='DimAICJETemplateGL',
        ),
        # FactAICJETransBank: no other model references it
        migrations.DeleteModel(
            name='FactAICJETransBank',
        ),
        # FactAICJEMonthlyStat: no other model references it
        migrations.DeleteModel(
            name='FactAICJEMonthlyStat',
        ),
        # MonthlyDocumentBankKeyItem: no other model references it
        migrations.DeleteModel(
            name='MonthlyDocumentBankKeyItem',
        ),
        # ClassificationQueue: no other model references it
        migrations.DeleteModel(
            name='ClassificationQueue',
        ),
    ]
