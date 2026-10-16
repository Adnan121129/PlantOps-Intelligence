from django.core.management.base import BaseCommand

from apps.maintenance.services import generate_pm_work_orders


class Command(BaseCommand):
    help = "Generate preventive-maintenance work orders that fall within their lead time. Idempotent."

    def handle(self, *args, **opts):
        created = generate_pm_work_orders()
        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} work order(s)."))
        for wo in created:
            self.stdout.write(f"  {wo.number} {wo.asset.asset_tag} due {wo.due_date}")
