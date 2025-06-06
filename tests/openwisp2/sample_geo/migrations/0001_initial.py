# Generated by Django 3.0.6 on 2020-05-10 18:15

import uuid

import django.contrib.gis.db.models.fields
import django.db.models.deletion
import django.utils.timezone
import django_loci.storage
import model_utils.fields
import swapper
from django.conf import settings
from django.db import migrations, models

import openwisp_users.mixins


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("sample_config", "0002_default_groups_permissions"),
        swapper.dependency(
            *swapper.split(settings.AUTH_USER_MODEL), version="0004_default_groups"
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="Location",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text=(
                            "A descriptive name of the location "
                            "(building name, company name, etc.)"
                        ),
                        max_length=75,
                        verbose_name="name",
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            (
                                "outdoor",
                                (
                                    "Outdoor environment (eg: street, square, "
                                    "garden, land)"
                                ),
                            ),
                            (
                                "indoor",
                                (
                                    "Indoor environment (eg: building, roofs, subway, "
                                    "large vehicles)"
                                ),
                            ),
                        ],
                        db_index=True,
                        help_text=(
                            "indoor locations can have floorplans associated to them"
                        ),
                        max_length=8,
                    ),
                ),
                (
                    "is_mobile",
                    models.BooleanField(
                        db_index=True,
                        default=False,
                        help_text="is this location a moving object?",
                        verbose_name="is mobile?",
                    ),
                ),
                (
                    "address",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        max_length=256,
                        verbose_name="address",
                    ),
                ),
                (
                    "geometry",
                    django.contrib.gis.db.models.fields.GeometryField(
                        blank=True, null=True, srid=4326, verbose_name="geometry"
                    ),
                ),
                ("details", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name("openwisp_users", "Organization"),
                        verbose_name="organization",
                    ),
                ),
            ],
            options={"abstract": False},
            bases=(openwisp_users.mixins.ValidateOrgMixin, models.Model),
        ),
        migrations.CreateModel(
            name="FloorPlan",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("floor", models.SmallIntegerField(verbose_name="floor")),
                (
                    "image",
                    models.ImageField(
                        help_text="floor plan image",
                        storage=django_loci.storage.OverwriteStorage(),
                        upload_to=django_loci.storage.OverwriteStorage.upload_to,
                        verbose_name="image",
                    ),
                ),
                ("details", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "location",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="sample_geo.Location",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name("openwisp_users", "Organization"),
                        verbose_name="organization",
                    ),
                ),
            ],
            options={"abstract": False, "unique_together": {("location", "floor")}},
            bases=(openwisp_users.mixins.ValidateOrgMixin, models.Model),
        ),
        migrations.CreateModel(
            name="DeviceLocation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "indoor",
                    models.CharField(
                        blank=True,
                        max_length=64,
                        null=True,
                        verbose_name="indoor position",
                    ),
                ),
                ("details", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "content_object",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="sample_config.Device",
                    ),
                ),
                (
                    "floorplan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="sample_geo.FloorPlan",
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="sample_geo.Location",
                    ),
                ),
            ],
            options={"abstract": False},
            bases=(openwisp_users.mixins.ValidateOrgMixin, models.Model),
        ),
    ]
