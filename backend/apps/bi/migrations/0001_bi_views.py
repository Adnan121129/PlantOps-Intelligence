"""Creates the read-only `bi` reporting schema (star-schema views for Power BI).

If a later migration alters a column used by these views, drop and recreate the views
around it (add a new versioned SQL file and migration rather than editing this one).
"""
from pathlib import Path

from django.db import migrations

SQL = (Path(__file__).resolve().parent.parent / "sql" / "bi_views_v1.sql").read_text()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("assets", "0002_initial"),
        ("workforce", "0001_initial"),
        ("operations", "0001_initial"),
        ("maintenance", "0002_initial"),
        ("inventory", "0002_initial"),
        ("costs", "0002_initial"),
        ("alerts", "0001_initial"),
    ]

    operations = [migrations.RunSQL(SQL, reverse_sql="DROP SCHEMA IF EXISTS bi CASCADE;")]
