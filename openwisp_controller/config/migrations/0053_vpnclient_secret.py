# Generated by Django 3.2.19 on 2023-07-27 12:14

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("config", "0052_vpn_node_network_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="vpnclient",
            name="secret",
            field=models.TextField(blank=True),
        ),
    ]
