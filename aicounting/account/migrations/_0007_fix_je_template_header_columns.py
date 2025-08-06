# Generated manually to fix database schema mismatch
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0006_rename_je_freq_id_dimaicjefreq_id_and_more'),
    ]

    operations = [
        # Fix the column names to match the model
        migrations.RunSQL(
            """
            ALTER TABLE dim_aic_je_template_header 
            CHANGE COLUMN client_id client_id int NOT NULL;
            """,
            reverse_sql="-- Cannot reverse column changes"
        ),
        migrations.RunSQL(
            """
            ALTER TABLE dim_aic_je_template_header 
            CHANGE COLUMN customer_id customer_id int NOT NULL;
            """,
            reverse_sql="-- Cannot reverse column changes"
        ),
        migrations.RunSQL(
            """
            ALTER TABLE dim_aic_je_template_header 
            CHANGE COLUMN je_freq_id je_freq_id int NOT NULL;
            """,
            reverse_sql="-- Cannot reverse column changes"
        ),
        migrations.RunSQL(
            """
            ALTER TABLE dim_aic_je_template_header 
            CHANGE COLUMN je_type_id_id je_type_id int NULL;
            """,
            reverse_sql="-- Cannot reverse column changes"
        ),
    ]
