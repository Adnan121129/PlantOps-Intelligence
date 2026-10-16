"""Operational report workflow.

    DRAFT --submit--> SUBMITTED --approve--> APPROVED --reopen (reason)--> DRAFT (revision + 1)
                           \\--reject (comment)--> REJECTED --edit/submit--> SUBMITTED

* Only Operations Officers assigned to the unit create and edit reports (DRAFT/REJECTED only).
* Only Shift Supervisors assigned to the unit review, and never their own submission.
* Approved reports are immutable. A correction requires an authorised reopen, which stores
  the approved values in the approval history before the report becomes editable again.
* Missing values are stored as NULL with a reason; they are never replaced with zero.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.alerts.notify import notify
from apps.core import clock
from apps.core.models import PlantUnit
from apps.core.numbering import next_number
from apps.core.period import plant_tz
from apps.core.settings_registry import get_setting
from apps.workforce.models import ShiftDefinition

from .models import MetricDefinition, OperationalIncident, OperationalMeasurement, OperationalReport, ReportEquipmentStatus

R = OperationalReport.Status


def applicable_metrics(unit: PlantUnit):
    return [m for m in MetricDefinition.objects.filter(plant=unit.plant, is_active=True) if m.applies_to(unit)]


def _check_unit_access(user, unit: PlantUnit) -> None:
    if not user.assigned_units.filter(pk=unit.pk).exists():
        raise ValidationError({"plant_unit": "You are not assigned to this plant unit."})


def _validate_measurements(unit: PlantUnit, measurements: list[dict]) -> list[dict]:
    metrics = {m.pk: m for m in applicable_metrics(unit)}
    seen: set[int] = set()
    clean: list[dict] = []
    errors: list[str] = []
    for row in measurements:
        metric = row["metric"]
        if metric.pk not in metrics:
            errors.append(f"'{metric.name}' does not apply to {unit.code}.")
            continue
        if metric.pk in seen:
            errors.append(f"'{metric.name}' is listed more than once.")
            continue
        seen.add(metric.pk)
        value = row.get("value")
        reason = (row.get("missing_reason") or "").strip()
        if value is None and not reason:
            continue  # nothing entered yet (allowed in drafts; checked on submit)
        if value is not None:
            if metric.valid_min is not None and value < metric.valid_min:
                errors.append(f"{metric.name}: {value} is below the valid minimum {metric.valid_min} {metric.unit}.")
            if metric.valid_max is not None and value > metric.valid_max:
                errors.append(f"{metric.name}: {value} exceeds the valid maximum {metric.valid_max} {metric.unit}.")
            reason = ""
        clean.append({"metric": metric, "value": value, "missing_reason": reason, "note": row.get("note", "")})
    if errors:
        raise ValidationError({"measurements": errors})
    return clean


def _write_children(report: OperationalReport, measurements, equipment_statuses) -> None:
    if measurements is not None:
        rows = _validate_measurements(report.plant_unit, measurements)
        report.measurements.all().delete()
        OperationalMeasurement.objects.bulk_create([OperationalMeasurement(report=report, **row) for row in rows])
    if equipment_statuses is not None:
        report.equipment_statuses.all().delete()
        seen = set()
        for row in equipment_statuses:
            asset = row["asset"]
            if asset.plant_unit_id != report.plant_unit_id:
                raise ValidationError({"equipment_statuses": f"{asset.asset_tag} is not in unit {report.plant_unit.code}."})
            if asset.pk in seen:
                raise ValidationError({"equipment_statuses": f"{asset.asset_tag} is listed more than once."})
            seen.add(asset.pk)
            ReportEquipmentStatus.objects.create(report=report, asset=asset, status=row["status"], note=row.get("note", ""))


@transaction.atomic
def create_report(*, user, plant_unit: PlantUnit, shift: ShiftDefinition, report_date: dt.date, summary: str = "",
                  observations: str = "", measurements=None, equipment_statuses=None) -> OperationalReport:
    _check_unit_access(user, plant_unit)
    if shift.plant_id != plant_unit.plant_id:
        raise ValidationError({"shift": "The shift belongs to a different plant."})
    if not shift.is_active or not plant_unit.is_active:
        raise ValidationError("Reports cannot be created for inactive units or shifts.")
    tz = plant_tz(plant_unit.plant)
    shift_start, _ = shift.window(report_date, tz)
    if shift_start > timezone.now():
        raise ValidationError({"report_date": "A report cannot be created before its shift has started."})
    if OperationalReport.objects.filter(plant_unit=plant_unit, shift=shift, report_date=report_date).exists():
        raise ValidationError({"report_date": f"A report for {plant_unit.code}, {shift.name}, {report_date} already "
                                              "exists. Open it instead of creating a duplicate."})
    try:
        with transaction.atomic():
            report = OperationalReport.objects.create(
                plant_unit=plant_unit, shift=shift, report_date=report_date, summary=summary,
                observations=observations, created_by=user,
            )
    except IntegrityError as exc:  # concurrent duplicate
        raise ValidationError({"report_date": "A report for this unit, shift and date already exists."}) from exc
    _write_children(report, measurements or [], equipment_statuses or [])
    audit.record(user, AuditLog.Action.CREATE, report)
    return report


@transaction.atomic
def update_report(report: OperationalReport, *, user, summary=None, observations=None, measurements=None,
                  equipment_statuses=None) -> OperationalReport:
    report = OperationalReport.objects.select_for_update().select_related("plant_unit").get(pk=report.pk)
    if not report.is_editable:
        raise ValidationError(f"A report that is '{report.get_status_display()}' cannot be edited. "
                              "Approved reports must be reopened by a supervisor for correction.")
    _check_unit_access(user, report.plant_unit)
    before = _snapshot(report)
    if summary is not None:
        report.summary = summary
    if observations is not None:
        report.observations = observations
    report.save()
    _write_children(report, measurements, equipment_statuses)
    changes = audit.diff(before, _snapshot(report))
    if changes:
        audit.record(user, AuditLog.Action.UPDATE, report, changes=changes)
    return report


def _snapshot(report: OperationalReport) -> dict:
    return {
        "summary": report.summary,
        "observations": report.observations,
        **{f"metric:{m.metric.code}": (str(m.value) if m.value is not None else f"missing ({m.missing_reason})")
           for m in report.measurements.select_related("metric")},
        **{f"equipment:{s.asset.asset_tag}": s.status for s in report.equipment_statuses.select_related("asset")},
    }


def completeness_errors(report: OperationalReport) -> list[str]:
    recorded = {m.metric_id for m in report.measurements.all()}
    return [f"'{m.name}' needs a value or a reason why it is missing."
            for m in applicable_metrics(report.plant_unit) if m.is_required and m.pk not in recorded]


@transaction.atomic
def submit_report(report: OperationalReport, *, user) -> OperationalReport:
    report = OperationalReport.objects.select_for_update().select_related("plant_unit").get(pk=report.pk)
    if report.status not in (R.DRAFT, R.REJECTED):
        raise ValidationError(f"A report that is '{report.get_status_display()}' cannot be submitted.")
    _check_unit_access(user, report.plant_unit)
    errors = completeness_errors(report)
    if errors:
        raise ValidationError({"measurements": errors})
    before = report.status
    report.status, report.submitted_by, report.submitted_at = R.SUBMITTED, user, clock.now()
    report.save()
    audit.record_approval(report, action="SUBMIT", actor=user, from_status=before, to_status=R.SUBMITTED,
                          revision=report.revision, snap=_snapshot(report))
    reviewers = report.plant_unit.responsible_users.filter(role="SUPERVISOR", is_active=True)
    notify(reviewers, f"Operational report awaiting review: {report}", "", f"/operations/reports/{report.pk}")
    return report


def _check_reviewer(user, report: OperationalReport) -> None:
    if not user.assigned_units.filter(pk=report.plant_unit_id).exists():
        raise ValidationError("You are not a reviewer for this plant unit.")
    if report.submitted_by_id == user.pk or report.created_by_id == user.pk:
        raise ValidationError("You cannot review a report you prepared or submitted.")


@transaction.atomic
def review_report(report: OperationalReport, *, user, approve: bool, comment: str = "") -> OperationalReport:
    report = OperationalReport.objects.select_for_update().select_related("plant_unit").get(pk=report.pk)
    if report.status != R.SUBMITTED:
        raise ValidationError("Only submitted reports can be reviewed.")
    _check_reviewer(user, report)
    if not approve and not comment.strip():
        raise ValidationError({"comment": "Explain what must be corrected."})
    report.status = R.APPROVED if approve else R.REJECTED
    report.reviewed_by, report.reviewed_at, report.review_comment = user, clock.now(), comment
    report.save()
    audit.record_approval(report, action="APPROVE" if approve else "REJECT", actor=user, from_status=R.SUBMITTED,
                          to_status=report.status, comment=comment, revision=report.revision, snap=_snapshot(report))
    audit.record(user, AuditLog.Action.APPROVE if approve else AuditLog.Action.REJECT, report, message=comment)
    notify([report.submitted_by], f"Report {report} {report.get_status_display().lower()}", comment,
           f"/operations/reports/{report.pk}")
    return report


@transaction.atomic
def reopen_report(report: OperationalReport, *, user, reason: str) -> OperationalReport:
    report = OperationalReport.objects.select_for_update().select_related("plant_unit").get(pk=report.pk)
    if report.status != R.APPROVED:
        raise ValidationError("Only approved reports can be reopened for correction.")
    if not reason.strip():
        raise ValidationError({"reason": "A reason is required to reopen an approved report."})
    if user.role == "SUPERVISOR" and not user.assigned_units.filter(pk=report.plant_unit_id).exists():
        raise ValidationError("You are not a reviewer for this plant unit.")
    snap = _snapshot(report)
    audit.record_approval(report, action="REOPEN", actor=user, from_status=R.APPROVED, to_status=R.DRAFT,
                          comment=reason, revision=report.revision, snap=snap)
    report.status, report.revision = R.DRAFT, report.revision + 1
    report.reviewed_by = report.reviewed_at = None
    report.review_comment = f"Reopened for correction: {reason}"
    report.save()
    audit.record(user, AuditLog.Action.STATUS, report, changes={"status": {"from": R.APPROVED, "to": R.DRAFT},
                                                                "revision": report.revision}, message=reason)
    notify([report.created_by], f"Report {report} reopened for correction", reason, f"/operations/reports/{report.pk}")
    return report


def target_comparison(report: OperationalReport) -> list[dict]:
    rows = []
    for m in report.measurements.select_related("metric"):
        metric = m.metric
        variance = pct = status = None
        if m.value is not None and metric.target_value is not None:
            variance = m.value - metric.target_value
            pct = (variance / metric.target_value * 100).quantize(Decimal("0.1")) if metric.target_value else None
            if metric.direction == MetricDefinition.Direction.NEUTRAL:
                status = "INFO"
            else:
                good = variance >= 0 if metric.direction == MetricDefinition.Direction.HIGHER_BETTER else variance <= 0
                status = "ON_TARGET" if good else "BELOW_TARGET" if metric.direction == "HIGHER_BETTER" else "ABOVE_TARGET"
        rows.append({
            "metric": metric.code, "name": metric.name, "unit": metric.unit,
            "value": None if m.value is None else str(m.value), "missing_reason": m.missing_reason,
            "target": None if metric.target_value is None else str(metric.target_value),
            "variance": None if variance is None else str(variance),
            "variance_pct": None if pct is None else str(pct), "status": status,
        })
    return rows


def missing_reports(date_from: dt.date, date_to: dt.date, *, unit_ids=None, now: dt.datetime | None = None) -> list[dict]:
    """Expected (unit x shift x date) reports whose submission deadline has passed but are not submitted.

    A report is expected for every active unit with `requires_shift_reports` and every active shift of
    its plant. Deadline = shift end + `report_entry_deadline_hours`. Drafts count as not submitted.
    """
    deadline_hours = get_setting("report_entry_deadline_hours")
    now = now or timezone.now()
    units = PlantUnit.objects.filter(is_active=True, requires_shift_reports=True).select_related("plant")
    if unit_ids:
        units = units.filter(pk__in=unit_ids)
    existing = {
        (r.plant_unit_id, r.shift_id, r.report_date): r
        for r in OperationalReport.objects.filter(report_date__gte=date_from, report_date__lte=date_to)
    }
    shifts_by_plant: dict[int, list[ShiftDefinition]] = {}
    for s in ShiftDefinition.objects.filter(is_active=True):
        shifts_by_plant.setdefault(s.plant_id, []).append(s)
    gaps = []
    for unit in units:
        tz = plant_tz(unit.plant)
        day = date_from
        while day <= date_to:
            for shift in shifts_by_plant.get(unit.plant_id, []):
                _, end = shift.window(day, tz)
                deadline = end + dt.timedelta(hours=deadline_hours)
                if deadline > now:
                    continue
                report = existing.get((unit.pk, shift.pk, day))
                if report is None or report.status == R.DRAFT:
                    gaps.append({
                        "date": day.isoformat(), "plant_unit": unit.pk, "plant_unit_code": unit.code,
                        "shift": shift.pk, "shift_name": shift.name, "deadline": deadline.isoformat(),
                        "state": "DRAFT_NOT_SUBMITTED" if report else "MISSING",
                        "report_id": report.pk if report else None,
                    })
            day += dt.timedelta(days=1)
    return gaps


@transaction.atomic
def create_incident(*, user, **data) -> OperationalIncident:
    occurred_at = data["occurred_at"]
    if occurred_at > timezone.now() + dt.timedelta(minutes=5):
        raise ValidationError({"occurred_at": "Incidents cannot be dated in the future."})
    asset = data.get("asset")
    if asset is not None and asset.plant_unit_id != data["plant_unit"].pk:
        raise ValidationError({"asset": "The asset is not in the selected plant unit."})
    report = data.get("report")
    if report is not None and report.plant_unit_id != data["plant_unit"].pk:
        raise ValidationError({"report": "The report is for a different plant unit."})
    incident = OperationalIncident.objects.create(
        incident_number=next_number("INC", width=4, year=occurred_at.year), reported_by=user, **data)
    audit.record(user, AuditLog.Action.CREATE, incident, changes=audit.snapshot(incident))
    return incident


@transaction.atomic
def resolve_incident(incident: OperationalIncident, *, user, resolution: str) -> OperationalIncident:
    incident = OperationalIncident.objects.select_for_update().get(pk=incident.pk)
    if incident.status == OperationalIncident.Status.RESOLVED:
        raise ValidationError("The incident is already resolved.")
    if not resolution.strip():
        raise ValidationError({"resolution": "Describe how the incident was resolved."})
    before = incident.status
    incident.status, incident.resolution, incident.resolved_at = OperationalIncident.Status.RESOLVED, resolution, clock.now()
    incident.save()
    audit.record(user, AuditLog.Action.STATUS, incident, changes={"status": {"from": before, "to": incident.status}},
                 message=resolution)
    return incident
