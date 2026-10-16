from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services import Scope
from apps.bi.reconcile import reconcile
from apps.core.period import period_from_params


class Command(BaseCommand):
    help = ("Compare the figures Power BI computes from the bi views (the SQL behind each documented DAX measure) "
            "with the application's KPIs for a period. Exit code 1 if any check fails.")

    def add_arguments(self, parser):
        parser.add_argument("--date-from")
        parser.add_argument("--date-to")
        parser.add_argument("--unit", help="Plant unit id")

    def handle(self, *args, **opts):
        params = {k: v for k, v in {"date_from": opts["date_from"], "date_to": opts["date_to"], "unit": opts["unit"]}.items() if v}
        period, plant, unit = period_from_params(params)
        checks = reconcile(Scope(period, plant, unit))
        self.stdout.write(f"Period {period.date_from} to {period.date_to} ({period.tz}){' unit ' + unit.code if unit else ''}")
        self.stdout.write(f"{'Measure':<28}{'Application':>16}{'BI views':>16}  Result")
        def fmt(v):
            return "—" if v is None else f"{float(v):,.2f}"

        for c in checks:
            self.stdout.write(f"{c.measure:<28}{fmt(c.app_value):>16}{fmt(c.bi_value):>16}  {'PASS' if c.ok else 'FAIL'}")
        failed = [c for c in checks if not c.ok]
        if failed:
            raise CommandError(f"{len(failed)} measure(s) do not reconcile.")
        self.stdout.write(self.style.SUCCESS(f"All {len(checks)} measures reconcile."))
