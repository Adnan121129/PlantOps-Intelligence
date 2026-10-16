from django.conf import settings
from django.db import models


class ReportRun(models.Model):
    """Metadata about each generated report or export (who, what, which period, how many rows)."""

    report_code = models.CharField(max_length=40, db_index=True)
    output_format = models.CharField(max_length=5)
    params = models.JSONField(default=dict)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    row_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-generated_at"]
