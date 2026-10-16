from pathlib import Path

from django.db import migrations

SQL = (Path(__file__).resolve().parent.parent / "sql" / "bi_views_v2.sql").read_text()
V1 = (Path(__file__).resolve().parent.parent / "sql" / "bi_views_v1.sql").read_text()


class Migration(migrations.Migration):
    dependencies = [("bi", "0001_bi_views")]
    # Reverse: drop and recreate the v1 definitions (v2 only appended columns/rows).
    operations = [migrations.RunSQL(SQL, reverse_sql="DROP SCHEMA IF EXISTS bi CASCADE;\n" + V1)]
