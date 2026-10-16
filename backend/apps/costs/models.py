"""Operational cost ledger and budgets.

`OperationalExpense` is the single source of truth for maintenance and operating cost
analytics. Rows come from three sources:

* MANUAL      - entered by authorised users (contractors, repairs, other expenses);
* WORK_ORDER  - labour / contractor / other costs entered against a work order;
* STOCK       - posted automatically when parts are issued (positive) or returned
                (negative credit) against a work order or department;
* OVERTIME    - posted when an overtime record with a known rate is approved.

Purchases are *not* expenses: received goods become inventory (an asset) and are
expensed when issued. Open purchase-order value is reported separately as a
commitment, so nothing is counted twice.

`cost_type` distinguishes actual spend from estimates and commitments. Analytics use
ACTUAL rows unless stated otherwise.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.assets.models import EquipmentAsset
from apps.core.models import Department, PlantUnit, TimeStampedModel


class CostCategory(models.TextChoices):
    SPARE_PARTS = "SPARE_PARTS", "Spare parts"
    CONSUMABLES = "CONSUMABLES", "Consumables"
    LABOR = "LABOR", "Labour"
    CONTRACTOR = "CONTRACTOR", "Contractors"
    EQUIPMENT_REPAIR = "EQUIPMENT_REPAIR", "Equipment repair"
    UTILITIES = "UTILITIES", "Utilities"
    OTHER = "OTHER", "Other operating expense"


class OperationalExpense(TimeStampedModel):
    class CostType(models.TextChoices):
        ACTUAL = "ACTUAL", "Actual"
        ESTIMATE = "ESTIMATE", "Estimate"
        COMMITMENT = "COMMITMENT", "Commitment"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual entry"
        WORK_ORDER = "WORK_ORDER", "Work order cost entry"
        STOCK = "STOCK", "Stock issue / return"
        OVERTIME = "OVERTIME", "Approved overtime"

    expense_date = models.DateField(db_index=True)
    category = models.CharField(max_length=20, choices=CostCategory.choices, db_index=True)
    cost_type = models.CharField(max_length=10, choices=CostType.choices, default=CostType.ACTUAL)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    description = models.CharField(max_length=255)
    reference = models.CharField(max_length=80, blank=True, help_text="Invoice or supporting document reference.")
    asset = models.ForeignKey(EquipmentAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="expenses")
    work_order = models.ForeignKey("maintenance.WorkOrder", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="expenses")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT, related_name="expenses")
    plant_unit = models.ForeignKey(PlantUnit, null=True, blank=True, on_delete=models.PROTECT, related_name="expenses")
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.MANUAL)
    stock_transaction = models.OneToOneField("inventory.StockTransaction", null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="expense")
    overtime = models.OneToOneField("workforce.OvertimeRecord", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="expense")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-expense_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=~Q(amount=0), name="expense_amount_non_zero"),
            # Only system-generated stock returns may be negative (credits).
            models.CheckConstraint(condition=Q(amount__gt=0) | Q(source="STOCK"), name="expense_negative_only_stock"),
        ]
        indexes = [
            models.Index(fields=["expense_date", "category"]),
            models.Index(fields=["work_order"]),
            models.Index(fields=["asset", "expense_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.expense_date} {self.category} {self.amount}"


class Budget(TimeStampedModel):
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT, related_name="budgets")
    category = models.CharField(max_length=20, choices=CostCategory.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-year", "-month", "category"]
        constraints = [
            models.UniqueConstraint(fields=["year", "month", "department", "category"], name="uniq_budget_line",
                                    nulls_distinct=False),
            models.CheckConstraint(condition=Q(month__gte=1) & Q(month__lte=12), name="budget_month_valid"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="budget_amount_non_negative"),
        ]
