# Generated by Django 4.1.2 on 2023-01-02 20:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shows", "0005_add_notes_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="show",
            name="rate",
            field=models.DecimalField(null=True, blank=True),
        ),
    ]
