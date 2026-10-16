from django.core.management.base import BaseCommand

from apps.alerts.engine import evaluate_rules


class Command(BaseCommand):
    help = "Evaluate all enabled alert rules (schedule every 5-15 minutes with cron / Task Scheduler)."

    def add_arguments(self, parser):
        parser.add_argument("--rule", action="append", help="Evaluate only this rule code (repeatable).")

    def handle(self, *args, **opts):
        summary = evaluate_rules(opts.get("rule"), force=True)
        for code, result in summary.items():
            self.stdout.write(f"{code}: {result}")
