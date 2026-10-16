"""Alert evaluation engine: runs rule evaluators and synchronises Alert rows.

Deduplication: one *live* alert per (rule, dedup_key) - enforced by a partial unique
index. While a condition persists the live alert is refreshed, not duplicated. When the
condition disappears the alert is marked `condition_cleared_at` and, if nobody has closed
it yet, auto-resolved. A later recurrence creates a new alert, so history is preserved.

User states: OPEN -> ACKNOWLEDGED -> RESOLVED, or DISMISSED. A user-resolved alert whose
condition is still detected is reopened (the problem is evidently not fixed); a dismissed
alert stays dismissed until its condition clears.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import logging

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import connection, transaction
from django.db.models import Min
from django.utils import timezone

from .models import Alert, AlertActivity, AlertRule, Severity
from .notify import notify
from .rules import SPECS, Condition, validate_params

logger = logging.getLogger("plantops.alerts")
_suspended: contextvars.ContextVar[bool] = contextvars.ContextVar("alerts_suspended", default=False)
ADVISORY_LOCK_KEY = 74_210_001


@contextlib.contextmanager
def suspended():
    """Bulk loaders (seed data) suspend implicit evaluation and run it once at the end."""
    token = _suspended.set(True)
    try:
        yield
    finally:
        _suspended.reset(token)


def ensure_rules() -> None:
    existing = set(AlertRule.objects.values_list("code", flat=True))
    AlertRule.objects.bulk_create([
        AlertRule(code=s.code, name=s.name, description=s.description, severity=s.severity, params=dict(s.defaults),
                  audience_roles=list(s.audience))
        for code, s in SPECS.items() if code not in existing
    ])


def evaluate_rules(codes: list[str] | None = None, *, now: dt.datetime | None = None, force: bool = False) -> dict:
    if _suspended.get() and not force:
        return {}
    ensure_rules()
    now = now or timezone.now()
    rules = AlertRule.objects.filter(is_enabled=True)
    if codes:
        rules = rules.filter(code__in=codes)
    summary = {}
    with transaction.atomic():
        # One evaluator at a time across processes; others simply skip this run.
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", [ADVISORY_LOCK_KEY])
            if not cur.fetchone()[0]:
                return {"skipped": "evaluation already running"}
        for rule in rules:
            spec = SPECS.get(rule.code)
            if spec is None:
                continue
            params = validate_params(rule.code, rule.params or {})
            try:
                with transaction.atomic():
                    conditions = spec.evaluate(params, now)
                    summary[rule.code] = _sync(rule, spec, conditions, now)
            except Exception:  # one faulty rule must not stop the others
                logger.exception("Alert rule %s failed", rule.code)
                summary[rule.code] = {"error": True}
    return summary


def maybe_auto_evaluate() -> None:
    """Throttled evaluation triggered by reads of the alert centre."""
    oldest = AlertRule.objects.filter(is_enabled=True).aggregate(m=Min("last_evaluated_at"))["m"]
    if oldest is None or (timezone.now() - oldest).total_seconds() >= settings.PLANTOPS_ALERT_AUTO_EVALUATE_SECONDS:
        evaluate_rules()


def _sync(rule: AlertRule, spec, conditions: list[Condition], now: dt.datetime) -> dict:
    from apps.accounts.models import User

    live = {a.dedup_key: a for a in Alert.objects.select_for_update().filter(rule=rule, condition_cleared_at__isnull=True)}
    created = refreshed = cleared = 0
    new_critical: list[Alert] = []
    for cond in {c.dedup_key: c for c in conditions}.values():
        severity = cond.severity or rule.severity
        alert = live.pop(cond.dedup_key, None)
        if alert is None:
            ct = ContentType.objects.get_for_model(cond.related) if cond.related is not None else None
            alert = Alert.objects.create(
                rule=rule, dedup_key=cond.dedup_key, severity=severity, title=cond.title[:200], message=cond.message,
                context=cond.context, related_content_type=ct,
                related_object_id=cond.related.pk if cond.related is not None else None,
                related_label=str(cond.related)[:150] if cond.related is not None else "",
                link=cond.link[:200], first_detected_at=now, last_detected_at=now,
            )
            AlertActivity.objects.create(alert=alert, action=AlertActivity.Action.CREATED, note=cond.message, at=now)
            created += 1
            if severity == Severity.CRITICAL:
                new_critical.append(alert)
            continue
        alert.title, alert.message, alert.context = cond.title[:200], cond.message, cond.context
        alert.last_detected_at = now
        alert.occurrence_count += 1
        if severity != alert.severity:
            alert.severity = severity
        if alert.status == Alert.Status.RESOLVED:
            alert.status = Alert.Status.OPEN
            alert.resolved_at = alert.resolved_by = None
            AlertActivity.objects.create(alert=alert, action=AlertActivity.Action.REOPENED, at=now,
                                         note="Condition still detected after manual resolution.")
        alert.save()
        refreshed += 1
    for alert in live.values():
        alert.condition_cleared_at = now
        if alert.status in Alert.ACTIVE_STATUSES:
            alert.status = Alert.Status.RESOLVED
            alert.resolved_at = now
            alert.resolution_note = "Condition no longer detected; resolved automatically."
        alert.save()
        AlertActivity.objects.create(alert=alert, action=AlertActivity.Action.CLEARED, at=now)
        cleared += 1
    rule.last_evaluated_at = now
    rule.save(update_fields=["last_evaluated_at"])
    if new_critical:
        recipients = User.objects.filter(role__in=rule.audience_roles, is_active=True)
        for alert in new_critical:
            notify(recipients, f"Critical alert: {alert.title}", alert.message, alert.link)
    return {"created": created, "refreshed": refreshed, "cleared": cleared, "active": created + refreshed}
