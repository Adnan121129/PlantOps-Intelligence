"""Seed a reproducible, entirely synthetic demonstration environment.

    python manage.py seed_demo                 # create demo data (refuses if it already exists)
    python manage.py seed_demo --reset         # wipe ALL data and rebuild (only when PLANTOPS_DEMO_MODE=true)
    python manage.py seed_demo --days 120 --seed 42

History is produced by a chronological event simulation that calls the same service
layer as the API (work-order lifecycle, stock ledger, procurement, report approvals),
so every KPI, ledger balance and audit record reconciles. Events that would fall after
"now" are not executed, which naturally leaves open work orders, ongoing outages,
pending approvals and in-transit purchase orders.

All names, codes and values are invented. No real people, plants or credentials.
"""
from __future__ import annotations

import datetime as dt
import heapq
import math
import os
import random
import zoneinfo
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import ApprovalRecord, User
from apps.alerts import engine
from apps.alerts.models import Alert, AlertActivity
from apps.alerts.notify import muted
from apps.assets.models import EquipmentAsset, EquipmentCategory
from apps.core import clock
from apps.core.models import Department, Plant, PlantUnit, SystemSetting
from apps.core.timeutils import overlap_hours
from apps.costs.models import Budget, OperationalExpense
from apps.inventory import services as inv
from apps.inventory.models import InventoryItem, ItemCategory, PurchaseOrder, PurchaseRequest, Supplier
from apps.maintenance import services as mnt
from apps.maintenance.models import DowntimeEvent, InspectionRecord, MaintenanceSchedule, WorkOrder
from apps.operations import services as ops
from apps.operations.models import MetricDefinition, OperationalIncident, OperationalReport
from apps.workforce.models import Employee, OvertimeRecord, ShiftAssignment, ShiftDefinition, ShiftHandover
from apps.workforce.services import decide_overtime

PLANT_CODE = "DEMO-CCPP"
TZ = zoneinfo.ZoneInfo("Asia/Dubai")
H = dt.timedelta(hours=1)
M = dt.timedelta(minutes=1)
D = dt.timedelta(days=1)

FIRST = ["Aiden", "Bilal", "Chen", "Dana", "Elif", "Farid", "Grace", "Hamza", "Iris", "Jonas", "Kiran", "Lena",
         "Marco", "Nadia", "Omar", "Priya", "Quinn", "Rami", "Sara", "Tariq", "Uma", "Victor", "Wen", "Yusuf",
         "Zara", "Arjun", "Beatriz", "Daniel", "Hana", "Leo", "Mei", "Nikhil", "Olga", "Pavel"]
LAST = ["Abbott", "Barlow", "Castell", "Dorsey", "Ellery", "Fenwick", "Garrow", "Hollis", "Ingram", "Jessop",
        "Kendal", "Lister", "Marsh", "Norwood", "Oakes", "Pryor", "Quayle", "Redfern", "Stroud", "Thorne",
        "Upton", "Vance", "Whitby", "Yardley"]


def q(value, places="0.01") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


class Sim:
    """Minimal discrete-event scheduler; events after `end` are discarded (they are the future)."""

    def __init__(self, end: dt.datetime):
        self.end = end
        self.heap: list = []
        self.seq = 0
        self.skipped: dict[str, list[str]] = {}

    def at(self, when: dt.datetime, fn, *args) -> None:
        if when <= self.end:
            self.seq += 1
            heapq.heappush(self.heap, (when, self.seq, fn, args))

    def run(self) -> int:
        n = 0
        while self.heap:
            when, _, fn, args = heapq.heappop(self.heap)
            with clock.at(when):
                try:
                    with transaction.atomic():
                        fn(when, *args)
                except ValidationError as exc:
                    # A business rule rejected a simulated action (e.g. insufficient stock): skip it, as a
                    # real user would have been told to do something else.
                    self.skipped.setdefault(fn.__name__, []).append("; ".join(exc.messages)[:160])
            n += 1
        return n


class Command(BaseCommand):
    help = "Create a reproducible synthetic demonstration dataset (see module docstring)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=120, help="Days of history to simulate (30-365).")
        parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible data.")
        parser.add_argument("--reset", action="store_true", help="Delete ALL existing data first (demo mode only).")

    # ------------------------------------------------------------------ entry point
    def handle(self, *args, **opts):
        days = opts["days"]
        if not 30 <= days <= 365:
            raise CommandError("--days must be between 30 and 365.")
        if opts["reset"]:
            if not settings.PLANTOPS_DEMO_MODE:
                raise CommandError("--reset is only allowed when PLANTOPS_DEMO_MODE=true.")
            self.stdout.write("Flushing existing data ...")
            call_command("flush", interactive=False, verbosity=0)
        elif Plant.objects.filter(code=PLANT_CODE).exists():
            self.stdout.write(self.style.WARNING("Demo data already present; nothing done. Use --reset to rebuild."))
            return
        elif Plant.objects.exists():
            raise CommandError("The database already contains non-demo data. Refusing to mix demo records into it.")

        self.rng = random.Random(opts["seed"])
        self.now = timezone.now().replace(second=0, microsecond=0)
        self.start = (self.now.astimezone(TZ) - D * days).replace(hour=0, minute=0, second=0, microsecond=0)
        self.password = os.environ.get("PLANTOPS_DEMO_PASSWORD", "PlantOps-Demo-2026")
        timezone.activate(TZ)
        with muted(), engine.suspended():
            with clock.at(self.start - D * 2):
                self.reference_data()
                self.opening_stock()
            self.sim = Sim(self.now)
            day = self.start
            while day <= self.now:
                self.sim.at(day + 5 * M, self.day_start)
                day += D
            self.stdout.write(f"Simulating {days} days of plant history ...")
            events = self.sim.run()
            self.stdout.write(f"  processed {events} events")
            for name, messages in sorted(self.sim.skipped.items()):
                self.stdout.write(f"  skipped {len(messages)} x {name} (business rule), e.g. {messages[0]}")
            self.current_situation()
            self.rosters()
            self.manual_costs_and_budgets()
        engine.evaluate_rules(force=True)
        self.finish_alerts()
        self.welcome_notifications()
        self.summary()

    # ------------------------------------------------------------------ reference data
    def reference_data(self):
        SystemSetting.objects.update_or_create(key="default_plant_code", defaults={"value": PLANT_CODE})
        SystemSetting.objects.update_or_create(key="base_currency", defaults={"value": "USD"})
        self.plant = Plant.objects.create(code=PLANT_CODE, name="Demo Combined-Cycle Power Station (synthetic)",
                                          facility_type=Plant.FacilityType.POWER_GENERATION, timezone=str(TZ),
                                          currency="USD", location="Synthetic demo site")
        U = PlantUnit.UnitType
        unit_rows = [("GT1", "Gas Turbine Unit 1", U.GENERATING_UNIT, 150, True),
                     ("GT2", "Gas Turbine Unit 2", U.GENERATING_UNIT, 150, True),
                     ("ST1", "Steam Turbine Unit 1", U.GENERATING_UNIT, 120, True),
                     ("WTP", "Water Treatment Plant", U.UTILITY, None, True),
                     ("BOP", "Balance of Plant", U.AUXILIARY, None, False)]
        self.units = {}
        for code, name, utype, cap, reports in unit_rows:
            self.units[code] = PlantUnit.objects.create(
                plant=self.plant, code=code, name=name, unit_type=utype, capacity=cap, capacity_unit="MW" if cap else "",
                requires_shift_reports=reports)
        self.depts = {c: Department.objects.create(code=c, name=n) for c, n in [
            ("OPS", "Operations"), ("MNT", "Maintenance"), ("STR", "Stores & Procurement"), ("MGT", "Management"),
            ("HSE", "Health, Safety & Environment")]}
        self.shifts = [ShiftDefinition.objects.create(plant=self.plant, code=c, name=n, start_time=s, end_time=e,
                                                      min_staff=3, sequence=i + 1)
                       for i, (c, n, s, e) in enumerate([("A", "Morning", dt.time(6), dt.time(14)),
                                                          ("B", "Evening", dt.time(14), dt.time(22)),
                                                          ("C", "Night", dt.time(22), dt.time(6))])]

        def user(username, first, last, role, dept, title, units=()):
            u = User.objects.create(username=username, first_name=first, last_name=last, role=role,
                                    department=self.depts[dept], job_title=title, email=f"{username}@example.invalid")
            u.set_password(self.password)
            u.save()
            u.assigned_units.set([self.units[c] for c in units])
            return u

        rep_units = ("GT1", "GT2", "ST1", "WTP")
        self.u = {
            "admin": user("admin", "Alex", "Admin", "ADMIN", "MGT", "System administrator"),
            "ops": user("operations", "Olivia", "Operator", "OPERATIONS", "OPS", "Operations officer", rep_units),
            "ops2": user("operations2", "Owen", "Oakes", "OPERATIONS", "OPS", "Operations officer", rep_units),
            "maint": user("maintenance", "Mira", "Mechanic", "MAINTENANCE", "MNT", "Maintenance engineer"),
            "maint2": user("maintenance2", "Malik", "Marsh", "MAINTENANCE", "MNT", "Maintenance engineer"),
            "store": user("store", "Stella", "Stores", "STORE", "STR", "Store & procurement officer"),
            "sup": user("supervisor", "Sam", "Supervisor", "SUPERVISOR", "OPS", "Shift supervisor", rep_units),
            "sup2": user("supervisor2", "Sofia", "Stroud", "SUPERVISOR", "OPS", "Shift supervisor", rep_units),
            "mgr": user("manager", "Morgan", "Manager", "MANAGEMENT", "MGT", "Plant manager"),
        }
        User.objects.create_superuser("django-admin", "django-admin@example.invalid", self.password, role="ADMIN")

        # Employees (synthetic). Four operating crews of four, eight technicians, plus staff linked to users.
        names = [(f, l) for f in FIRST for l in LAST]
        self.rng.shuffle(names)
        self.operators, self.techs = [], []
        code = 100
        for _crew in range(4):
            for _ in range(4):
                f, l = names.pop()
                code += 1
                self.operators.append(Employee.objects.create(
                    employee_code=f"E{code}", first_name=f, last_name=l, department=self.depts["OPS"],
                    job_title="Control room operator" if _ == 0 else "Field operator",
                    hourly_rate=q(self.rng.uniform(24, 32)), email=f"e{code}@example.invalid",
                    phone=f"+000-555-{code:04d}"))
        for i in range(8):
            f, l = names.pop()
            code += 1
            self.techs.append(Employee.objects.create(
                employee_code=f"E{code}", first_name=f, last_name=l, department=self.depts["MNT"],
                job_title=["Mechanical technician", "Electrical technician", "I&C technician"][i % 3],
                hourly_rate=q(self.rng.uniform(30, 40)), email=f"e{code}@example.invalid", phone=f"+000-555-{code:04d}"))
        for user_obj in self.u.values():
            code += 1
            Employee.objects.create(employee_code=f"E{code}", first_name=user_obj.first_name, last_name=user_obj.last_name,
                                    department=user_obj.department, job_title=user_obj.job_title, user=user_obj,
                                    hourly_rate=q(45))
        Employee.objects.create(employee_code="E900", first_name="Former", last_name="Employee",
                                department=self.depts["OPS"], job_title="Field operator", employment_status="INACTIVE")

        # Metrics
        G, UT = [U.GENERATING_UNIT], [U.UTILITY]
        mk = lambda **kw: MetricDefinition.objects.create(plant=self.plant, **kw)  # noqa: E731
        self.metrics = {
            "ENERGY_GEN": mk(code="ENERGY_GEN", name="Gross energy generated", unit="MWh", aggregation="SUM",
                             direction="HIGHER_BETTER", target_value=950, valid_min=0, valid_max=1300,
                             is_primary_output=True, unit_types=G, display_order=1),
            "AUX_CONS": mk(code="AUX_CONS", name="Auxiliary consumption", unit="MWh", aggregation="SUM",
                           direction="LOWER_BETTER", valid_min=0, valid_max=150, unit_types=G, display_order=2),
            "AVAILABILITY": mk(code="AVAILABILITY", name="Unit availability", unit="%", aggregation="AVG",
                               direction="HIGHER_BETTER", target_value=95, valid_min=0, valid_max=100, alert_low=60,
                               unit_types=G + UT, display_order=3),
            "FUEL_GAS": mk(code="FUEL_GAS", name="Fuel gas consumed", unit="kNm3", aggregation="SUM",
                           direction="LOWER_BETTER", valid_min=0, valid_max=400, is_required=False, unit_types=G,
                           display_order=4),
            "HEAT_RATE": mk(code="HEAT_RATE", name="Net heat rate", unit="kJ/kWh", aggregation="AVG",
                            direction="LOWER_BETTER", target_value=9800, valid_min=7000, valid_max=14000,
                            alert_high=10600, is_required=False, unit_types=G, display_order=5),
            "WATER_PROD": mk(code="WATER_PROD", name="Demineralised water produced", unit="m3", aggregation="SUM",
                             direction="HIGHER_BETTER", target_value=600, valid_min=0, valid_max=1500, unit_types=UT,
                             display_order=6),
            "CONDUCTIVITY": mk(code="CONDUCTIVITY", name="Demin water conductivity", unit="uS/cm", aggregation="AVG",
                               direction="LOWER_BETTER", valid_min=0, valid_max=5, alert_high=0.2, unit_types=UT,
                               display_order=7),
        }

        # Equipment
        cats = {c: EquipmentCategory.objects.create(code=c, name=n) for c, n in [
            ("GT", "Gas turbine"), ("ST", "Steam turbine"), ("GEN", "Generator"), ("PUMP", "Pump"),
            ("COMP", "Compressor"), ("XFMR", "Transformer"), ("HRSG", "Heat recovery steam generator"),
            ("VALVE", "Valve & actuator"), ("IC", "Instrumentation & control"), ("COOL", "Cooling system"),
            ("WTE", "Water treatment equipment"), ("FAN", "Fan & blower")]}
        A = EquipmentAsset.Criticality
        asset_rows = [
            ("GT1", "GT1-TUR-001", "Gas turbine GT1", "GT", A.HIGH, "Siemvolt", "SGT-150X"),
            ("GT1", "GT1-GEN-001", "Generator GT1", "GEN", A.HIGH, "Elektra", "GX-180"),
            ("GT1", "GT1-CMP-001", "Fuel gas compressor GT1", "COMP", A.HIGH, "Kompro", "FGC-22"),
            ("GT1", "GT1-LOP-001", "Lube oil pump GT1", "PUMP", A.MEDIUM, "Flowtek", "LP-40"),
            ("GT1", "GT1-FAN-001", "Enclosure ventilation fan GT1", "FAN", A.LOW, "Aeromax", "EV-9"),
            ("GT1", "GT1-IC-001", "Turbine control system GT1", "IC", A.HIGH, "Controlix", "TCS-5"),
            ("GT2", "GT2-TUR-001", "Gas turbine GT2", "GT", A.HIGH, "Siemvolt", "SGT-150X"),
            ("GT2", "GT2-GEN-001", "Generator GT2", "GEN", A.HIGH, "Elektra", "GX-180"),
            ("GT2", "GT2-CMP-001", "Fuel gas compressor GT2", "COMP", A.HIGH, "Kompro", "FGC-22"),
            ("GT2", "GT2-LOP-001", "Lube oil pump GT2", "PUMP", A.MEDIUM, "Flowtek", "LP-40"),
            ("GT2", "GT2-FAN-001", "Enclosure ventilation fan GT2", "FAN", A.LOW, "Aeromax", "EV-9"),
            ("GT2", "GT2-IC-001", "Turbine control system GT2", "IC", A.HIGH, "Controlix", "TCS-5"),
            ("ST1", "ST1-TUR-001", "Steam turbine ST1", "ST", A.HIGH, "Turbodyne", "ST-120"),
            ("ST1", "ST1-GEN-001", "Generator ST1", "GEN", A.HIGH, "Elektra", "GX-140"),
            ("ST1", "ST1-HRSG-001", "HRSG 1", "HRSG", A.HIGH, "Thermaflux", "HR-3P"),
            ("ST1", "ST1-HRSG-002", "HRSG 2", "HRSG", A.HIGH, "Thermaflux", "HR-3P"),
            ("ST1", "ST1-BFP-001", "Boiler feed pump A", "PUMP", A.HIGH, "Flowtek", "BFP-900"),
            ("ST1", "ST1-BFP-002", "Boiler feed pump B", "PUMP", A.HIGH, "Flowtek", "BFP-900"),
            ("ST1", "ST1-CEP-001", "Condensate extraction pump", "PUMP", A.MEDIUM, "Flowtek", "CEP-300"),
            ("ST1", "ST1-VLV-001", "Main steam stop valve", "VALVE", A.HIGH, "Valvecraft", "MSV-16"),
            ("ST1", "ST1-IC-001", "DCS controllers ST1", "IC", A.MEDIUM, "Controlix", "DCS-8"),
            ("WTP", "WTP-RO-001", "Reverse osmosis train 1", "WTE", A.MEDIUM, "Aquapure", "RO-60"),
            ("WTP", "WTP-RO-002", "Reverse osmosis train 2", "WTE", A.MEDIUM, "Aquapure", "RO-60"),
            ("WTP", "WTP-EDI-001", "Electrodeionisation unit", "WTE", A.MEDIUM, "Aquapure", "EDI-20"),
            ("WTP", "WTP-PMP-001", "Demin transfer pump", "PUMP", A.LOW, "Flowtek", "TP-50"),
            ("WTP", "WTP-DOS-001", "Chemical dosing skid", "WTE", A.LOW, "Dosetech", "CDS-4"),
            ("BOP", "BOP-CT-001", "Cooling tower cell 1", "COOL", A.MEDIUM, "Coolwave", "CT-8"),
            ("BOP", "BOP-CT-002", "Cooling tower cell 2", "COOL", A.MEDIUM, "Coolwave", "CT-8"),
            ("BOP", "BOP-CWP-001", "Circulating water pump A", "PUMP", A.HIGH, "Flowtek", "CWP-2000"),
            ("BOP", "BOP-CWP-002", "Circulating water pump B", "PUMP", A.HIGH, "Flowtek", "CWP-2000"),
            ("BOP", "BOP-AIR-001", "Instrument air compressor", "COMP", A.MEDIUM, "Kompro", "IA-75"),
            ("BOP", "BOP-XFMR-001", "Generator step-up transformer GT1", "XFMR", A.HIGH, "Voltamax", "GSU-200"),
            ("BOP", "BOP-XFMR-002", "Generator step-up transformer GT2", "XFMR", A.HIGH, "Voltamax", "GSU-200"),
            ("BOP", "BOP-XFMR-003", "Station auxiliary transformer", "XFMR", A.MEDIUM, "Voltamax", "SAT-20"),
            ("BOP", "BOP-FIRE-001", "Fire water pump (diesel)", "PUMP", A.HIGH, "Flowtek", "FWP-D"),
        ]
        self.assets = {}
        for unit, tag, name, cat, crit, make, model in asset_rows:
            self.assets[tag] = EquipmentAsset.objects.create(
                asset_tag=tag, name=name, category=cats[cat], plant_unit=self.units[unit], criticality=crit,
                manufacturer=make, model_number=model, serial_number=f"SN-{self.rng.randint(10000, 99999)}",
                location=f"{self.units[unit].name}", commissioned_on=dt.date(2016 + self.rng.randint(0, 5),
                                                                            self.rng.randint(1, 12), 1))
        retired = EquipmentAsset.objects.create(
            asset_tag="BOP-AIR-000", name="Old instrument air compressor (replaced)", category=cats["COMP"],
            plant_unit=self.units["BOP"], criticality=A.LOW, status=EquipmentAsset.Status.RETIRED,
            archived_at=self.start - D * 200, commissioned_on=dt.date(2009, 5, 1),
            technical_notes="Replaced by BOP-AIR-001.")
        del retired
        self.main_asset = {"GT1": self.assets["GT1-TUR-001"], "GT2": self.assets["GT2-TUR-001"],
                           "ST1": self.assets["ST1-TUR-001"], "WTP": self.assets["WTP-RO-001"]}
        # Failure propensity (failures per year). A few deliberately poor performers ("bad actors").
        self.failure_rate = {a.pk: {"HIGH": 3.0, "MEDIUM": 2.6, "LOW": 2.0}[a.criticality] for a in self.assets.values()}
        for tag, rate in [("ST1-BFP-002", 14), ("GT2-CMP-001", 11), ("WTP-RO-002", 9), ("BOP-AIR-001", 8),
                          ("GT1-LOP-001", 6)]:
            self.failure_rate[self.assets[tag].pk] = rate

        # Inventory
        icats = {c: ItemCategory.objects.create(code=c, name=n, is_consumable=cons) for c, n, cons in [
            ("MECH", "Mechanical spares", False), ("ELEC", "Electrical spares", False),
            ("INST", "Instrumentation spares", False), ("SEAL", "Seals & gaskets", False),
            ("LUBE", "Lubricants", True), ("FILT", "Filters", True), ("CHEM", "Water-treatment chemicals", True)]}
        self.suppliers = [Supplier.objects.create(code=c, name=n, contact_name=cn, email=f"orders@{c.lower()}.example.invalid",
                                                  quoted_lead_time_days=lt)
                          for c, n, cn, lt in [("SUP01", "Northwind Industrial Supply", "J. Doe", 7),
                                               ("SUP02", "Atlas Turbine Parts", "A. Rivera", 21),
                                               ("SUP03", "Volt Electrical Wholesale", "K. Osei", 10),
                                               ("SUP04", "ClearFlow Chemicals", "M. Haddad", 5),
                                               ("SUP05", "Precision Instruments Co.", "L. Moreau", 14),
                                               ("SUP06", "Seal & Bearing Depot", "R. Banerjee", 6)]]
        S = self.suppliers
        item_rows = [
            # code, name, cat, uom, cost, min, reorder, critical, supplier, compatible
            ("MECH-BRG-6316", "Bearing 6316 C3", "MECH", "EA", 185, 4, 8, True, S[5], ["ST1-BFP-001", "ST1-BFP-002"]),
            ("MECH-BRG-6220", "Bearing 6220", "MECH", "EA", 120, 4, 8, False, S[5], ["BOP-CWP-001", "BOP-CWP-002"]),
            ("MECH-IMP-BFP", "BFP impeller assembly", "MECH", "EA", 6800, 1, 1, True, S[1], ["ST1-BFP-001", "ST1-BFP-002"]),
            ("MECH-CPL-LP40", "Flexible coupling LP-40", "MECH", "EA", 340, 2, 4, False, S[0], ["GT1-LOP-001", "GT2-LOP-001"]),
            ("MECH-VLV-SEAT", "Control valve seat kit", "MECH", "SET", 760, 2, 3, False, S[0], ["ST1-VLV-001"]),
            ("MECH-CMP-VLV", "Compressor valve plate set", "MECH", "SET", 1450, 2, 4, True, S[1], ["GT1-CMP-001", "GT2-CMP-001", "BOP-AIR-001"]),
            ("MECH-BELT-B68", "V-belt B68", "MECH", "EA", 18, 10, 20, False, S[0], ["GT1-FAN-001", "GT2-FAN-001", "BOP-CT-001", "BOP-CT-002"]),
            ("MECH-BURNER-TIP", "Combustor burner tip", "MECH", "EA", 2900, 4, 6, True, S[1], ["GT1-TUR-001", "GT2-TUR-001"]),
            ("SEAL-MECH-BFP", "Mechanical seal BFP-900", "SEAL", "EA", 2350, 2, 2, True, S[5], ["ST1-BFP-001", "ST1-BFP-002"]),
            ("SEAL-GSK-DN150", "Spiral-wound gasket DN150", "SEAL", "EA", 42, 12, 24, False, S[5], []),
            ("SEAL-ORING-KIT", "O-ring kit (assorted)", "SEAL", "BOX", 95, 3, 5, False, S[5], []),
            ("SEAL-RO-MEMB", "RO membrane element 8in", "SEAL", "EA", 640, 6, 12, True, S[3], ["WTP-RO-001", "WTP-RO-002"]),
            ("ELEC-MTR-75KW", "Motor 75 kW spare", "ELEC", "EA", 7400, 1, 1, True, S[2], ["BOP-AIR-001", "ST1-CEP-001"]),
            ("ELEC-CONT-200A", "Contactor 200 A", "ELEC", "EA", 410, 3, 4, False, S[2], []),
            ("ELEC-FUSE-63", "HRC fuse 63 A", "ELEC", "EA", 14, 20, 40, False, S[2], []),
            ("ELEC-BRUSH-GEN", "Generator carbon brush set", "ELEC", "SET", 520, 2, 4, True, S[2], ["GT1-GEN-001", "GT2-GEN-001", "ST1-GEN-001"]),
            ("ELEC-RELAY-PROT", "Protection relay module", "ELEC", "EA", 2150, 1, 2, True, S[2], ["BOP-XFMR-001", "BOP-XFMR-002"]),
            ("INST-PT-0-100", "Pressure transmitter 0-100 bar", "INST", "EA", 980, 3, 4, False, S[4], []),
            ("INST-TC-K", "Thermocouple type K", "INST", "EA", 75, 10, 20, False, S[4], []),
            ("INST-VIB-PROBE", "Vibration probe", "INST", "EA", 690, 4, 4, True, S[4], ["GT1-TUR-001", "GT2-TUR-001", "ST1-TUR-001"]),
            ("INST-IO-CARD", "DCS I/O card", "INST", "EA", 1850, 2, 2, True, S[4], ["GT1-IC-001", "GT2-IC-001", "ST1-IC-001"]),
            ("INST-COND-CELL", "Conductivity cell", "INST", "EA", 430, 2, 3, False, S[4], ["WTP-EDI-001"]),
            ("LUBE-ISO46", "Turbine oil ISO VG 46", "LUBE", "L", 6.8, 400, 800, True, S[0], ["GT1-TUR-001", "GT2-TUR-001", "ST1-TUR-001"]),
            ("LUBE-GREASE-EP2", "EP2 grease", "LUBE", "KG", 9.5, 30, 60, False, S[0], []),
            ("FILT-GT-INLET", "GT inlet air filter cartridge", "FILT", "EA", 145, 40, 80, True, S[0], ["GT1-TUR-001", "GT2-TUR-001"]),
            ("FILT-LUBE-10U", "Lube oil filter 10 micron", "FILT", "EA", 88, 12, 24, False, S[0], ["GT1-LOP-001", "GT2-LOP-001"]),
            ("FILT-CART-5U", "Cartridge filter 5 micron", "FILT", "EA", 22, 40, 80, False, S[3], ["WTP-RO-001", "WTP-RO-002"]),
            ("CHEM-ANTISCAL", "RO antiscalant", "CHEM", "KG", 7.2, 200, 400, False, S[3], ["WTP-DOS-001"]),
            ("CHEM-NAOH-50", "Sodium hydroxide 50%", "CHEM", "KG", 0.9, 500, 1000, False, S[3], ["WTP-DOS-001"]),
            ("CHEM-HCL-33", "Hydrochloric acid 33%", "CHEM", "KG", 0.7, 400, 800, False, S[3], ["WTP-DOS-001"]),
            ("CHEM-BIOCIDE", "Cooling water biocide", "CHEM", "KG", 11.5, 80, 160, False, S[3], ["BOP-CT-001", "BOP-CT-002"]),
            ("MECH-PACKING", "Gland packing 12mm", "MECH", "M", 16, 15, 30, False, S[5], []),
        ]
        self.items = {}
        for code_, name, cat, uom, cost, mn, ro, crit, sup, compat in item_rows:
            item = InventoryItem.objects.create(
                item_code=code_, name=name, category=icats[cat], uom=uom, min_stock_level=mn, reorder_quantity=ro,
                criticality="CRITICAL" if crit else "STANDARD", preferred_supplier=sup,
                storage_location=f"Store {cat[0]}-{self.rng.randint(1, 9)}{self.rng.choice('ABCD')}")
            item.base_cost = Decimal(str(cost))
            item.compatible_assets.set([self.assets[t] for t in compat])
            self.items[code_] = item
        InventoryItem.objects.create(item_code="OBS-GSK-OLD", name="Obsolete gasket set (superseded)",
                                     category=icats["SEAL"], uom="SET", min_stock_level=0, reorder_quantity=0,
                                     is_active=False)

        # Preventive-maintenance schedules (fixed calendar). `shutdown` tasks take the asset off line.
        self.shutdown_schedules = set()
        pm_rows = [
            ("GT1-TUR-001", "GT inlet filter inspection & replacement", "PREVENTIVE", 30, 6, False, ["FILT-GT-INLET"]),
            ("GT2-TUR-001", "GT inlet filter inspection & replacement", "PREVENTIVE", 30, 6, False, ["FILT-GT-INLET"]),
            ("GT1-TUR-001", "Borescope inspection", "INSPECTION", 90, 10, True, []),
            ("GT2-TUR-001", "Borescope inspection", "INSPECTION", 90, 10, True, []),
            ("GT1-LOP-001", "Lube oil filter change", "PREVENTIVE", 30, 2, False, ["FILT-LUBE-10U"]),
            ("GT2-LOP-001", "Lube oil filter change", "PREVENTIVE", 30, 2, False, ["FILT-LUBE-10U"]),
            ("GT1-GEN-001", "Generator brush gear inspection", "INSPECTION", 60, 3, False, []),
            ("GT2-GEN-001", "Generator brush gear inspection", "INSPECTION", 60, 3, False, []),
            ("GT1-CMP-001", "Fuel gas compressor valve check", "PREVENTIVE", 45, 5, True, []),
            ("GT2-CMP-001", "Fuel gas compressor valve check", "PREVENTIVE", 45, 5, True, []),
            ("ST1-TUR-001", "Turbine vibration survey", "INSPECTION", 14, 2, False, []),
            ("ST1-BFP-001", "BFP lubrication & alignment check", "PREVENTIVE", 30, 3, False, ["LUBE-GREASE-EP2"]),
            ("ST1-BFP-002", "BFP lubrication & alignment check", "PREVENTIVE", 30, 3, False, ["LUBE-GREASE-EP2"]),
            ("ST1-VLV-001", "Valve stroke test", "INSPECTION", 30, 2, False, []),
            ("ST1-HRSG-001", "HRSG water chemistry & drum inspection", "INSPECTION", 60, 6, False, []),
            ("ST1-HRSG-002", "HRSG water chemistry & drum inspection", "INSPECTION", 60, 6, False, []),
            ("WTP-RO-001", "RO cartridge filter change", "PREVENTIVE", 14, 2, False, ["FILT-CART-5U"]),
            ("WTP-RO-002", "RO cartridge filter change", "PREVENTIVE", 14, 2, False, ["FILT-CART-5U"]),
            ("WTP-EDI-001", "EDI conductivity calibration", "INSPECTION", 30, 1, False, []),
            ("BOP-CWP-001", "CW pump bearing inspection", "INSPECTION", 30, 2, False, []),
            ("BOP-CWP-002", "CW pump bearing inspection", "INSPECTION", 30, 2, False, []),
            ("BOP-CT-001", "Cooling tower fan belt & gearbox check", "PREVENTIVE", 30, 3, False, ["MECH-BELT-B68"]),
            ("BOP-AIR-001", "Instrument air compressor service", "PREVENTIVE", 30, 4, False, ["LUBE-GREASE-EP2"]),
            ("BOP-XFMR-001", "Transformer oil sample & thermography", "INSPECTION", 90, 3, False, []),
            ("BOP-XFMR-002", "Transformer oil sample & thermography", "INSPECTION", 90, 3, False, []),
            ("BOP-FIRE-001", "Fire pump weekly run test", "INSPECTION", 7, 1, False, []),
        ]
        self.pm_parts = {}
        for i, (tag, title, ttype, interval, hours, shutdown, parts) in enumerate(pm_rows):
            first_due = (self.start + D * (7 + self.rng.randint(0, interval - 1))).date()
            sched = MaintenanceSchedule.objects.create(
                asset=self.assets[tag], title=title, task_type=ttype, interval_days=interval, start_date=first_due,
                lead_days=min(7, interval - 1), reminder_days=min(3, interval - 1), estimated_hours=hours,
                default_technician=self.techs[i % len(self.techs)] if i % 3 else None, priority="MEDIUM",
                created_by=self.u["maint"], description=f"{title} per OEM maintenance manual (synthetic).")
            if shutdown:
                self.shutdown_schedules.add(sched.pk)
            self.pm_parts[sched.pk] = parts

    def opening_stock(self):
        for item in self.items.values():
            lo, hi = float(item.min_stock_level) * 1.3, float(item.min_stock_level) * 3.2 + 1
            qty = self.rng.uniform(lo, hi)
            qty = Decimal(math.ceil(qty)) if item.uom in inv.INTEGRAL_UOMS else q(qty, "1")
            if qty <= 0:
                continue
            inv.post_transaction(item_id=item.pk, txn_type="RECEIPT", quantity=qty, unit_cost=item.base_cost,
                                 user=self.u["store"], occurred_at=self.start - D, reference="OPENING-BALANCE",
                                 notes="Opening balance at go-live (synthetic)")

    # ------------------------------------------------------------------ daily simulation
    def day_start(self, t):
        day = t.astimezone(TZ).date()
        rng = self.rng
        for wo in mnt.generate_pm_work_orders(as_of=day, user=self.u["maint"]):
            self.plan_pm(wo)
        # Random failures (Poisson per asset).
        for asset in self.assets.values():
            if rng.random() < self.failure_rate[asset.pk] / 365:
                self.sim.at(t + M * rng.randint(30, 23 * 60), self.failure, asset.pk)
        # Grid curtailment (external downtime) on gas turbines.
        if rng.random() < 0.05:
            unit = rng.choice(["GT1", "GT2"])
            start = t + H * rng.randint(8, 18)
            self.sim.at(start, self.external_outage, self.main_asset[unit].pk, rng.uniform(1.5, 6))
        # Shift reports, handovers.
        for shift in self.shifts:
            start, end = shift.window(day, TZ)
            for code in ("GT1", "GT2", "ST1", "WTP"):
                self.sim.at(end + M * rng.randint(10, 50), self.shift_report, code, shift.pk, day)
            for code in ("GT1", "ST1"):
                self.sim.at(end - M * rng.randint(5, 20), self.handover, code, shift.pk, day)
        # Consumables issued to departments.
        for _ in range(rng.randint(2, 4)):
            self.sim.at(t + H * rng.randint(7, 16), self.consumable_issue)
        # Procurement review twice a week; overtime; manual costs.
        if day.weekday() in (0, 3):
            self.sim.at(t + H * 9, self.procurement_review)
        if rng.random() < 0.45:
            self.sim.at(t + H * 21, self.overtime)
        if day.weekday() == 6:
            self.sim.at(t + H * 23 + M * 30, self.weekly_alert_evaluation)

    # --- maintenance
    def failure(self, t, asset_id):
        rng = self.rng
        asset = EquipmentAsset.objects.select_related("plant_unit").get(pk=asset_id)
        if DowntimeEvent.objects.filter(asset=asset, ended_at__isnull=True).exists():
            return
        if asset.work_orders.filter(status__in=WorkOrder.OPEN_STATUSES, maintenance_type="CORRECTIVE").exists():
            return
        symptoms = {"PUMP": ["high vibration", "seal leak", "bearing temperature high", "low discharge pressure"],
                    "COMP": ["valve failure", "high discharge temperature", "trip on low oil pressure"],
                    "GT": ["combustion dynamics alarm", "flame-out trip", "exhaust spread high"],
                    "ST": ["vibration trip", "governor valve hunting"],
                    "GEN": ["brush sparking", "stator temperature high"],
                    "IC": ["controller fault", "I/O card failure", "signal loss on transmitter"],
                    "WTE": ["membrane fouling", "high differential pressure", "conductivity excursion"],
                    "XFMR": ["Buchholz alarm", "oil temperature high"],
                    "VALVE": ["actuator failure", "passing valve"],
                    "COOL": ["gearbox noise", "fan imbalance"], "FAN": ["belt failure", "motor overload"],
                    "HRSG": ["tube leak suspected", "drum level control fault"]}
        symptom = rng.choice(symptoms.get(asset.category.code, ["unexpected trip"]))
        crit = asset.criticality
        priority = {"HIGH": rng.choice(["HIGH", "CRITICAL"]), "MEDIUM": rng.choice(["MEDIUM", "HIGH"]), "LOW": "LOW"}[crit]
        reporter = rng.choice([self.u["ops"], self.u["ops2"]])
        incident = None
        if rng.random() < 0.6:
            incident = ops.create_incident(
                user=reporter, plant_unit=asset.plant_unit, asset=asset, occurred_at=t,
                severity={"CRITICAL": "HIGH", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}[priority],
                category="EQUIPMENT", title=f"{asset.name}: {symptom}",
                description=f"Operator observed {symptom} on {asset.asset_tag}. Equipment stopped for safety.",
                immediate_action="Equipment isolated; standby started where available.")
        wo = mnt.create_work_order(user=reporter, asset=asset, maintenance_type="CORRECTIVE",
                                   title=f"{symptom.capitalize()} - {asset.name}",
                                   description=f"Reported by operations: {symptom}.", priority=priority,
                                   reported_at=t, incident=incident)
        event = mnt.record_downtime(user=reporter, asset=asset, downtime_type="UNPLANNED_FAILURE", started_at=t,
                                    cause=symptom, work_order=wo, incident=incident)
        repair = max(0.75, rng.lognormvariate(math.log(6), 0.8))
        assign_at = t + M * rng.randint(20, 90)
        self.sim.at(assign_at, self.wo_assign, wo.pk, repair)
        self.sim.at(assign_at + M * rng.randint(15, 60), self.wo_start, wo.pk, event.pk, repair)

    def wo_assign(self, t, wo_id, repair_hours):
        wo = WorkOrder.objects.get(pk=wo_id)
        tech = self.rng.choice(self.techs)
        mnt.assign(wo, user=self.rng.choice([self.u["maint"], self.u["maint2"]]), technician=tech,
                   team="Mechanical crew" if "Mechanical" in tech.job_title else "E&I crew",
                   planned_start=t + H, planned_end=t + H * (repair_hours * 1.4 + 4))

    def wo_start(self, t, wo_id, event_id, repair_hours):
        rng = self.rng
        wo = WorkOrder.objects.get(pk=wo_id)
        if wo.status != "ASSIGNED":
            return
        mnt.start(wo, user=wo_user(self, wo), actual_start=t)
        extra = 0.0
        compatible = list(InventoryItem.objects.filter(compatible_assets=wo.asset, is_active=True))
        for item in rng.sample(compatible, k=min(len(compatible), rng.randint(0, 2))):
            qty = Decimal(1 if item.uom in inv.INTEGRAL_UOMS else rng.randint(5, 40))
            try:
                inv.post_transaction(item_id=item.pk, txn_type="ISSUE", quantity=qty, user=self.u["store"],
                                     work_order=wo, occurred_at=t, notes="Issued against work order")
            except ValidationError:
                # Part not in stock: the job waits for a delivery.
                mnt.set_blocked(wo, user=self.u["maint"], blocked=True, reason=f"Awaiting spare part {item.item_code}")
                extra = rng.uniform(24, 96)
        end = t + H * (repair_hours + extra)
        if wo.is_blocked:
            self.sim.at(end - H * 2, self.wo_unblock, wo.pk)
        self.sim.at(end, self.downtime_end, event_id)
        self.sim.at(end + M * rng.randint(10, 60), self.wo_complete, wo.pk, repair_hours + extra)

    def wo_unblock(self, t, wo_id):
        wo = WorkOrder.objects.get(pk=wo_id)
        if wo.is_open and wo.is_blocked:
            mnt.set_blocked(wo, user=self.u["maint"], blocked=False)

    def downtime_end(self, t, event_id):
        event = DowntimeEvent.objects.get(pk=event_id)
        if event.ended_at is None:
            mnt.close_downtime(event, user=self.u["maint"], ended_at=t)

    def wo_complete(self, t, wo_id, hours):
        rng = self.rng
        wo = WorkOrder.objects.select_related("asset").get(pk=wo_id)
        if wo.status != "IN_PROGRESS":
            return
        labor = q(min(hours, 12) * rng.uniform(1.2, 2.0), "0.5")
        engineer = wo_user(self, wo)
        mnt.add_cost(wo, user=engineer, category="LABOR", amount=q(labor * Decimal("42.00")),
                     description=f"Technician labour {labor} h", expense_date=t.astimezone(TZ).date())
        if wo.priority in ("HIGH", "CRITICAL") and rng.random() < 0.3:
            mnt.add_cost(wo, user=engineer, category="CONTRACTOR", amount=q(rng.uniform(1200, 6500)),
                         description="OEM field service engineer call-out", reference=f"INV-{rng.randint(10000, 99999)}",
                         expense_date=t.astimezone(TZ).date())
        codes = ["MECHANICAL", "ELECTRICAL", "INSTRUMENTATION", "LUBRICATION", "CORROSION", "OPERATIONAL", "UNKNOWN"]
        mnt.complete(wo, user=engineer, actual_end=t, labor_hours=labor, failure_code=rng.choice(codes),
                     actions_performed="Fault diagnosed, defective component replaced, equipment tested and returned "
                                       "to service.", root_cause=rng.choice(["Wear beyond service limit", "Contamination",
                                                                             "Loose connection", "Misalignment", ""]))
        wo.refresh_from_db()
        if wo.status == "AWAITING_VERIFICATION":
            self.sim.at(t + H * rng.uniform(2, 18), self.wo_verify, wo.pk)
        elif wo.incident_id:
            self.sim.at(t + H, self.incident_resolve, wo.incident_id)

    def wo_verify(self, t, wo_id):
        wo = WorkOrder.objects.get(pk=wo_id)
        if wo.status != "AWAITING_VERIFICATION":
            return
        verifier = self.rng.choice([self.u["sup"], self.u["sup2"]])
        if self.rng.random() < 0.06:
            mnt.verify(wo, user=verifier, approve=False, comment="Vibration still above limit; please re-check alignment.")
            self.sim.at(t + H * 2, self.wo_complete, wo.pk, 2)
            return
        mnt.verify(wo, user=verifier, approve=True, comment="Equipment observed running normally.")
        if wo.incident_id:
            self.sim.at(t + M * 30, self.incident_resolve, wo.incident_id)

    def incident_resolve(self, t, incident_id):
        incident = OperationalIncident.objects.get(pk=incident_id)
        if incident.status != "RESOLVED":
            ops.resolve_incident(incident, user=self.u["ops"], resolution="Equipment repaired under the linked work order.")

    def external_outage(self, t, asset_id, hours):
        asset = EquipmentAsset.objects.get(pk=asset_id)
        end = t + H * hours
        if end > self.now or mnt._overlap_exists(asset.pk, t, end):
            return
        mnt.record_downtime(user=self.u["ops"], asset=asset, downtime_type="EXTERNAL", started_at=t, ended_at=end,
                            cause="Grid operator curtailment instruction",
                            description="Unit shut down on dispatch instruction (synthetic).")

    def plan_pm(self, wo):
        rng = self.rng
        WorkOrder.objects.filter(pk=wo.pk).update(reported_at=clock.now())
        due_start = dt.datetime.combine(wo.due_date, dt.time(8), tzinfo=TZ)
        r = rng.random()
        if r < 0.80:
            begin = due_start - D * rng.randint(0, 2) + M * rng.randint(0, 120)
        elif r < 0.93:
            begin = due_start + D * rng.randint(1, 6) + M * rng.randint(0, 120)
        elif r < 0.97:
            return  # never done -> becomes overdue
        else:
            self.sim.at(due_start + D * 3, self.pm_cancel, wo.pk)
            return
        self.sim.at(begin - H, self.pm_start, wo.pk, begin)

    def pm_cancel(self, t, wo_id):
        wo = WorkOrder.objects.get(pk=wo_id)
        if wo.is_open:
            mnt.cancel(wo, user=self.u["maint"], reason="Asset not released by operations; deferred to next cycle.")

    def pm_start(self, t, wo_id, begin):
        rng = self.rng
        wo = WorkOrder.objects.select_related("schedule", "asset").get(pk=wo_id)
        if not wo.is_open:
            return
        if wo.status == "REPORTED":
            mnt.assign(wo, user=self.u["maint"], technician=rng.choice(self.techs))
        begin = max(begin, t + M)
        hours = float(wo.schedule.estimated_hours or 2) * rng.uniform(0.8, 1.4)
        self.sim.at(begin, self.pm_execute, wo.pk, hours)

    def pm_execute(self, t, wo_id, hours):
        rng = self.rng
        wo = WorkOrder.objects.select_related("schedule", "asset").get(pk=wo_id)
        if wo.status != "ASSIGNED":
            return
        mnt.start(wo, user=self.u["maint"], actual_start=t)
        end = t + H * hours
        if wo.schedule_id in self.shutdown_schedules and end <= self.now and not mnt._overlap_exists(wo.asset_id, t, end):
            mnt.record_downtime(user=self.u["maint"], asset=wo.asset, downtime_type="PLANNED_MAINTENANCE", started_at=t,
                                ended_at=end, cause=f"Planned outage: {wo.title}", work_order=wo)
        for code_ in self.pm_parts.get(wo.schedule_id, []):
            item = self.items[code_]
            qty = Decimal(rng.randint(2, 6)) if item.uom in inv.INTEGRAL_UOMS else Decimal(rng.randint(2, 8))
            try:
                inv.post_transaction(item_id=item.pk, txn_type="ISSUE", quantity=qty, user=self.u["store"],
                                     work_order=wo, occurred_at=t, notes="PM kit")
            except ValidationError:
                pass
        self.sim.at(end, self.pm_complete, wo.pk, hours)

    def pm_complete(self, t, wo_id, hours):
        rng = self.rng
        wo = WorkOrder.objects.select_related("asset").get(pk=wo_id)
        if wo.status != "IN_PROGRESS":
            return
        labor = q(hours * rng.uniform(1, 2), "0.5")
        mnt.add_cost(wo, user=self.u["maint"], category="LABOR", amount=q(labor * Decimal("42.00")),
                     description=f"PM labour {labor} h", expense_date=t.astimezone(TZ).date())
        if wo.maintenance_type == "INSPECTION":
            result = rng.choices(["PASS", "ATTENTION", "FAIL"], [0.85, 0.12, 0.03])[0]
            InspectionRecord.objects.create(
                asset=wo.asset, work_order=wo, inspected_at=t - M * 15, inspector=self.u["maint"], result=result,
                findings={"PASS": "Within limits.", "ATTENTION": "Minor wear observed; monitor at next inspection.",
                          "FAIL": "Defect found; corrective work order recommended."}[result],
                readings=f"Vibration {rng.uniform(1.2, 4.8):.1f} mm/s; temperature {rng.uniform(45, 78):.0f} C")
        mnt.complete(wo, user=self.u["maint"], actual_end=t, labor_hours=labor,
                     actions_performed="Task completed per checklist; no abnormalities requiring immediate action.")

    # --- operations
    def shift_report(self, t, unit_code, shift_id, day):
        rng = self.rng
        recent = (self.now.astimezone(TZ).date() - day).days <= 6
        if recent and rng.random() < 0.04:
            return  # never written: shows up as a missing report
        unit = self.units[unit_code]
        shift = ShiftDefinition.objects.get(pk=shift_id)
        start, end = shift.window(day, TZ)
        main = self.main_asset[unit_code]
        down = sum((overlap_hours(e.started_at, e.ended_at, start, end) for e in DowntimeEvent.objects.filter(
            asset=main, started_at__lt=end).exclude(ended_at__lte=start)), Decimal(0))
        ext = sum((overlap_hours(e.started_at, e.ended_at, start, end) for e in DowntimeEvent.objects.filter(
            asset=main, started_at__lt=end, downtime_type="EXTERNAL").exclude(ended_at__lte=start)), Decimal(0))
        hours = Decimal(8)
        avail = max(Decimal(0), (hours - (down - ext)) / hours * 100)
        running = max(Decimal(0), hours - down)
        values = {}
        if unit.unit_type == "GENERATING_UNIT":
            energy = float(unit.capacity) * float(running) * rng.uniform(0.80, 0.94)
            values["ENERGY_GEN"] = q(energy, "0.1")
            values["AUX_CONS"] = q(energy * rng.uniform(0.035, 0.055), "0.1")
            values["AVAILABILITY"] = q(avail, "0.1")
            if unit_code.startswith("GT"):
                values["FUEL_GAS"] = q(energy * rng.uniform(0.255, 0.275), "0.1")
                hr = rng.uniform(9400, 10150) if rng.random() > 0.03 else rng.uniform(10650, 11200)
                values["HEAT_RATE"] = q(hr, "1") if running > 0 else None
        else:
            values["WATER_PROD"] = q(rng.uniform(480, 720) * float(running) / 8, "1")
            values["AVAILABILITY"] = q(avail, "0.1")
            values["CONDUCTIVITY"] = q(rng.uniform(0.06, 0.16) if rng.random() > 0.03 else rng.uniform(0.22, 0.35), "0.001")
        measurements = []
        for code_, value in values.items():
            metric = self.metrics[code_]
            if value is None:
                continue
            if rng.random() < 0.015:
                measurements.append({"metric": metric, "value": None, "missing_reason": "Meter communication fault"})
            else:
                measurements.append({"metric": metric, "value": value})
        author = self.u["ops"] if shift.sequence != 2 else self.u["ops2"]
        statuses = [{"asset": a, "status": a.status} for a in EquipmentAsset.objects.filter(
            plant_unit=unit, archived_at__isnull=True)]
        report = ops.create_report(
            user=author, plant_unit=unit, shift=shift, report_date=day, measurements=measurements,
            equipment_statuses=statuses,
            summary=("Unit operated normally." if down == 0 else f"Unit unavailable for {q(down, '0.1')} h during the shift."),
            observations="" if rng.random() > 0.1 else "Minor steam leak noted at drain valve; reported to maintenance.")
        OperationalIncident.objects.filter(plant_unit=unit, occurred_at__gte=start, occurred_at__lt=end,
                                           report__isnull=True).update(report=report)
        if recent and rng.random() < 0.03:
            return  # left in draft
        self.sim.at(t + M * rng.randint(5, 40), self.report_submit, report.pk)

    def report_submit(self, t, report_id):
        report = OperationalReport.objects.get(pk=report_id)
        ops.submit_report(report, user=report.created_by)
        self.sim.at(t + H * self.rng.uniform(1, 9), self.report_review, report.pk)

    def report_review(self, t, report_id):
        report = OperationalReport.objects.get(pk=report_id)
        if report.status != "SUBMITTED":
            return
        reviewer = self.rng.choice([self.u["sup"], self.u["sup2"]])
        if self.rng.random() < 0.06:
            ops.review_report(report, user=reviewer, approve=False,
                              comment="Auxiliary consumption looks inconsistent with output; please verify the meter reading.")
            self.sim.at(t + H * self.rng.uniform(1, 4), self.report_correct, report.pk)
        else:
            ops.review_report(report, user=reviewer, approve=True)

    def report_correct(self, t, report_id):
        report = OperationalReport.objects.get(pk=report_id)
        ops.update_report(report, user=report.created_by,
                          observations=(report.observations + " Meter reading re-checked and confirmed.").strip())
        self.sim.at(t + M * 10, self.report_submit, report.pk)

    def handover(self, t, unit_code, shift_id, day):
        rng = self.rng
        author, receiver = (self.u["ops"], self.u["ops2"]) if rng.random() < 0.5 else (self.u["ops2"], self.u["ops"])
        open_wos = WorkOrder.objects.filter(asset__plant_unit=self.units[unit_code], status__in=WorkOrder.OPEN_STATUSES,
                                            maintenance_type="CORRECTIVE").values_list("number", flat=True)[:3]
        h = ShiftHandover.objects.create(
            plant_unit=self.units[unit_code], shift_id=shift_id, date=day, handed_over_by=author,
            summary="Plant stable. Load as per dispatch schedule." if not open_wos else "Running with open defects.",
            outstanding_issues=", ".join(open_wos), safety_notes="" if rng.random() > 0.15 else "Hot work permit active in turbine hall.")
        if t + M * 20 <= self.now:
            h.received_by, h.received_at = receiver, t + M * 20
            h.save(update_fields=["received_by", "received_at"])

    # --- inventory & procurement
    def consumable_issue(self, t):
        rng = self.rng
        code_, dept, lo, hi = rng.choice([("LUBE-ISO46", "OPS", 10, 40), ("CHEM-ANTISCAL", "OPS", 8, 25),
                                          ("CHEM-NAOH-50", "OPS", 20, 60), ("CHEM-HCL-33", "OPS", 15, 45),
                                          ("CHEM-BIOCIDE", "OPS", 3, 10), ("LUBE-GREASE-EP2", "MNT", 1, 4),
                                          ("ELEC-FUSE-63", "MNT", 1, 3), ("SEAL-GSK-DN150", "MNT", 1, 4),
                                          ("INST-TC-K", "MNT", 1, 2)])
        inv.post_transaction(item_id=self.items[code_].pk, txn_type="ISSUE", quantity=rng.randint(lo, hi),
                             user=self.u["store"], department=self.depts[dept], occurred_at=t,
                             notes="Routine consumption")

    def procurement_review(self, t):
        from django.db.models import F

        open_items = set(PurchaseRequest.objects.filter(status__in=["DRAFT", "SUBMITTED", "APPROVED"])
                         .values_list("lines__item", flat=True))
        open_items |= set(PurchaseOrder.objects.filter(status__in=["DRAFT", "ISSUED", "PARTIALLY_RECEIVED"])
                          .values_list("lines__item", flat=True))
        low = [i for i in InventoryItem.objects.filter(is_active=True, current_stock__lte=F("min_stock_level"))
               if i.pk not in open_items]
        by_supplier: dict[int, list] = {}
        for item in low:
            if item.preferred_supplier_id:
                by_supplier.setdefault(item.preferred_supplier_id, []).append(item)
        for supplier_id, items in by_supplier.items():
            if self.rng.random() < 0.15:
                continue  # sometimes reorders slip, leaving shortages visible
            requester = self.u["store"] if self.rng.random() < 0.8 else self.u["maint"]
            pr = inv.create_purchase_request(
                user=requester, department=self.depts["STR"],
                justification="Replenishment: items at or below reorder point.",
                lines=[{"item": i, "quantity": i.reorder_quantity,
                        "estimated_unit_cost": self.items[i.item_code].base_cost} for i in items])
            PurchaseRequest.objects.filter(pk=pr.pk).update(created_at=t)
            self.sim.at(t + H, self.pr_submit, pr.pk, supplier_id)

    def pr_submit(self, t, pr_id, supplier_id):
        pr = PurchaseRequest.objects.get(pk=pr_id)
        inv.submit_purchase_request(pr, user=pr.requested_by)
        self.sim.at(t + H * self.rng.uniform(3, 30), self.pr_decide, pr.pk, supplier_id)

    def pr_decide(self, t, pr_id, supplier_id):
        pr = PurchaseRequest.objects.get(pk=pr_id)
        if self.rng.random() < 0.07:
            inv.decide_purchase_request(pr, user=self.u["mgr"], approve=False,
                                        comment="Consolidate with next week's order to reduce freight cost.")
            return
        inv.decide_purchase_request(pr, user=self.u["mgr"], approve=True, comment="Approved.")
        self.sim.at(t + H * self.rng.uniform(1, 20), self.po_create, pr.pk, supplier_id)

    def po_create(self, t, pr_id, supplier_id):
        rng = self.rng
        pr = PurchaseRequest.objects.get(pk=pr_id)
        supplier = Supplier.objects.get(pk=supplier_id)
        prices = {l.item_id: q(float(self.items_by_id(l.item_id).base_cost) * rng.uniform(0.94, 1.09), "0.0001")
                  for l in pr.lines.all()}
        lead = (supplier.quoted_lead_time_days or 7) + rng.randint(-2, 6)
        today = t.astimezone(TZ).date()
        po = inv.convert_to_purchase_order(pr, user=self.u["store"], supplier=supplier, prices=prices,
                                           expected_delivery_date=today + D * (supplier.quoted_lead_time_days or 7))
        PurchaseOrder.objects.filter(pk=po.pk).update(created_at=t)
        inv.issue_purchase_order(po, user=self.u["store"], order_date=today)
        arrive = dt.datetime.combine(today + D * max(lead, 1), dt.time(rng.randint(9, 14)), tzinfo=TZ)
        self.sim.at(arrive, self.po_receive, po.pk, rng.random() < 0.2)

    def items_by_id(self, item_id):
        if not hasattr(self, "_items_by_id"):
            self._items_by_id = {i.pk: i for i in self.items.values()}
        return self._items_by_id[item_id]

    def po_receive(self, t, po_id, partial):
        rng = self.rng
        po = PurchaseOrder.objects.get(pk=po_id)
        lines = []
        for line in po.lines.all():
            qty = line.outstanding
            if partial:
                qty = Decimal(max(1, int(qty * Decimal("0.6")))) if qty > 1 else qty
            lines.append({"order_line": line.pk, "quantity": qty})
        inv.receive_goods(po, user=self.u["store"], lines=lines, received_at=t,
                          delivery_note=f"DN-{rng.randint(100000, 999999)}")
        po.refresh_from_db()
        if po.status == "PARTIALLY_RECEIVED":
            self.sim.at(t + D * rng.randint(3, 7), self.po_receive, po.pk, False)
        else:
            self.sim.at(t + D, self.po_close, po.pk)

    def po_close(self, t, po_id):
        inv.close_purchase_order(PurchaseOrder.objects.get(pk=po_id), user=self.u["store"])

    # --- workforce
    def overtime(self, t):
        rng = self.rng
        emp = rng.choice(self.operators + self.techs)
        wo = WorkOrder.objects.filter(status__in=["IN_PROGRESS", "COMPLETED"], actual_start__lte=t).order_by(
            "-actual_start").first() if emp in self.techs else None
        rec = OvertimeRecord.objects.create(
            employee=emp, date=t.astimezone(TZ).date(), hours=q(rng.choice([2, 3, 4, 4, 6]), "0.5"),
            rate_multiplier=Decimal("1.50"), reason="Covering absence" if emp in self.operators else "Breakdown repair",
            work_order=wo, recorded_by=self.u["sup"])
        self.sim.at(t + H * rng.uniform(8, 30), self.overtime_decide, rec.pk)

    def overtime_decide(self, t, rec_id):
        rec = OvertimeRecord.objects.get(pk=rec_id)
        approve = self.rng.random() < 0.9
        decide_overtime(rec, user=self.u["sup2"], approve=approve,
                        comment="" if approve else "Not pre-authorised; discuss with shift supervisor.")

    def weekly_alert_evaluation(self, t):
        engine.evaluate_rules(force=True, now=t)

    def current_situation(self):
        """A deterministic live breakdown so the demo always opens with an outage being worked on."""
        candidates = ["ST1-BFP-001", "BOP-CWP-002", "GT1-CMP-001"]
        asset = next((self.assets[t] for t in candidates
                      if not DowntimeEvent.objects.filter(asset=self.assets[t], ended_at__isnull=True).exists()
                      and not mnt._overlap_exists(self.assets[t].pk, self.now - H * 5, None)), None)
        if asset is None:
            return
        t0 = self.now - H * 5
        with clock.at(t0):
            incident = ops.create_incident(
                user=self.u["ops"], plant_unit=asset.plant_unit, asset=asset, occurred_at=t0, severity="HIGH",
                category="EQUIPMENT", title=f"{asset.name}: high vibration and seal leak",
                description="Vibration alarm followed by visible seal leakage; pump stopped, standby started.",
                immediate_action="Pump isolated and drained.")
            wo = mnt.create_work_order(user=self.u["ops"], asset=asset, maintenance_type="CORRECTIVE",
                                       title=f"High vibration and seal leak - {asset.name}",
                                       description="Reported by operations: high vibration, seal leak.",
                                       priority="CRITICAL", reported_at=t0, incident=incident)
            mnt.record_downtime(user=self.u["ops"], asset=asset, downtime_type="UNPLANNED_FAILURE", started_at=t0,
                                cause="High vibration and mechanical seal leak", work_order=wo, incident=incident)
        with clock.at(t0 + M * 40):
            mnt.assign(wo, user=self.u["maint"], technician=self.techs[0], team="Mechanical crew",
                       planned_start=t0 + H, planned_end=self.now + H * 6)
        with clock.at(t0 + H):
            mnt.start(wo, user=self.u["maint"], actual_start=t0 + H)
            for code_ in ("SEAL-MECH-BFP", "MECH-BRG-6316"):
                try:
                    with transaction.atomic():
                        inv.post_transaction(item_id=self.items[code_].pk, txn_type="ISSUE", quantity=1,
                                             user=self.u["store"], work_order=wo, occurred_at=t0 + H,
                                             notes="Issued for breakdown repair")
                except ValidationError:
                    mnt.set_blocked(wo, user=self.u["maint"], blocked=True, reason=f"Awaiting spare part {code_}")

    # ------------------------------------------------------------------ bulk records
    def rosters(self):
        rng = self.rng
        crews = [self.operators[i * 4:(i + 1) * 4] for i in range(4)]
        rows = []
        today = self.now.astimezone(TZ).date()
        day, n = self.start.date(), 0
        while day <= today + D * 13:
            for s_idx, shift in enumerate(self.shifts):
                if day > today + D * 7 and shift.code == "C":
                    continue  # night shifts beyond next week not yet rostered
                crew = crews[(n + s_idx) % 4]
                for emp in crew:
                    absent = rng.random() < (0.04 if day <= today else 0.12)
                    if not absent:
                        rows.append(ShiftAssignment(employee=emp, shift=shift, date=day, duty="OPERATIONS",
                                                    plant_unit=self.units[rng.choice(["GT1", "GT2", "ST1", "WTP"])],
                                                    assigned_by=self.u["sup"]))
            if day.weekday() < 5:
                for tech in self.techs[:6]:
                    rows.append(ShiftAssignment(employee=tech, shift=self.shifts[0], date=day, duty="MAINTENANCE",
                                                assigned_by=self.u["sup"]))
            day += D
            n += 1
        ShiftAssignment.objects.bulk_create(rows)

    def manual_costs_and_budgets(self):
        rng = self.rng
        today = self.now.astimezone(TZ).date()
        month = self.start.date().replace(day=1)
        admin = self.u["admin"]
        while month <= today:
            def add(day, month=month, **kw):
                d = month.replace(day=day)
                if self.start.date() <= d <= today:
                    with clock.at(dt.datetime.combine(d, dt.time(10), tzinfo=TZ)):
                        OperationalExpense.objects.create(expense_date=d, currency="USD", recorded_by=admin,
                                                          source="MANUAL", cost_type="ACTUAL", **kw)
            add(5, category="UTILITIES", amount=q(rng.uniform(6200, 7900)), description="Raw water supply (monthly)",
                department=self.depts["OPS"], plant_unit=self.units["WTP"], reference=f"UTL-{month:%Y%m}")
            add(6, category="OTHER", amount=q(4500), description="Site security services (monthly)",
                department=self.depts["OPS"], reference=f"SEC-{month:%Y%m}")
            add(12, category="CONTRACTOR", amount=q(rng.uniform(2100, 2900)),
                description="Fire-protection system service contract", department=self.depts["HSE"],
                asset=self.assets["BOP-FIRE-001"], plant_unit=self.units["BOP"], reference=f"FPS-{month:%Y%m}")
            for day in (9, 23):
                asset = rng.choice(list(self.assets.values()))
                add(day, category="EQUIPMENT_REPAIR", amount=q(rng.uniform(700, 3200)),
                    description=f"Workshop repair of motor/component for {asset.asset_tag}",
                    department=self.depts["MNT"], asset=asset, plant_unit=asset.plant_unit,
                    reference=f"WSR-{rng.randint(1000, 9999)}")
            month = (month + D * 32).replace(day=1)
        # One deliberately unusual expense, 9 days ago (feeds the expense-anomaly alert).
        d = today - D * 9
        OperationalExpense.objects.create(
            expense_date=d, category="EQUIPMENT_REPAIR", amount=q(46500), currency="USD", recorded_by=admin,
            description="Generator rotor rewind at vendor workshop (unplanned)", asset=self.assets["GT2-GEN-001"],
            plant_unit=self.units["GT2"], department=self.depts["MNT"], reference="WSR-REWIND-01")
        # Estimates and commitments are recorded but excluded from actual-spend KPIs.
        OperationalExpense.objects.create(
            expense_date=today + D * 45, category="CONTRACTOR", cost_type="ESTIMATE", amount=q(180000), currency="USD",
            recorded_by=admin, description="Estimate: GT1 hot-gas-path inspection (planned outage)",
            asset=self.assets["GT1-TUR-001"], plant_unit=self.units["GT1"], department=self.depts["MNT"])
        # Monthly budgets for the simulated months plus the next two.
        budget = {("MNT", "SPARE_PARTS"): 16000, ("MNT", "CONSUMABLES"): 3500, ("MNT", "LABOR"): 7000,
                  ("MNT", "CONTRACTOR"): 5000, ("MNT", "EQUIPMENT_REPAIR"): 4500, ("OPS", "UTILITIES"): 7200,
                  ("OPS", "CONSUMABLES"): 4500, ("OPS", "OTHER"): 4600, ("OPS", "LABOR"): 1500,
                  ("HSE", "CONTRACTOR"): 2600}
        month = self.start.date().replace(day=1)
        end_month = (today.replace(day=1) + D * 65).replace(day=1)
        while month <= end_month:
            for (dept, cat), amount in budget.items():
                Budget.objects.create(year=month.year, month=month.month, department=self.depts[dept], category=cat,
                                      amount=q(amount), currency="USD", notes="Synthetic demo budget")
            month = (month + D * 32).replace(day=1)

    # ------------------------------------------------------------------ final touches
    def finish_alerts(self):
        active = list(Alert.objects.filter(status="OPEN").order_by("-severity", "first_detected_at"))
        for alert in active[:3]:
            alert.status, alert.acknowledged_by, alert.acknowledged_at = "ACKNOWLEDGED", self.u["maint"], self.now - H * 3
            alert.save()
            AlertActivity.objects.create(alert=alert, action="ACKNOWLEDGED", actor=self.u["maint"], at=self.now - H * 3,
                                         note="Investigating.")
        low = Alert.objects.filter(status="OPEN", rule__code="LOW_STOCK").first()
        if low:
            low.status, low.resolved_by, low.resolved_at = "DISMISSED", self.u["store"], self.now - H
            low.resolution_note = "Usage is seasonal; current stock sufficient until the next scheduled order."
            low.save()
            AlertActivity.objects.create(alert=low, action="DISMISSED", actor=self.u["store"], at=self.now - H,
                                         note=low.resolution_note)

    def welcome_notifications(self):
        from apps.alerts.models import Notification

        for user in self.u.values():
            Notification.objects.create(recipient=user, title="Welcome to the PlantOps Intelligence demo",
                                        message="All records in this environment are synthetic demonstration data.",
                                        link="/")
        pending = OperationalReport.objects.filter(status="SUBMITTED").count()
        if pending:
            for key in ("sup", "sup2"):
                Notification.objects.create(recipient=self.u[key], title=f"{pending} operational report(s) awaiting review",
                                            link="/approvals")

    def summary(self):
        from apps.inventory.models import StockTransaction

        counts = {
            "assets": EquipmentAsset.objects.count(), "work orders": WorkOrder.objects.count(),
            "open work orders": WorkOrder.objects.filter(status__in=WorkOrder.OPEN_STATUSES).count(),
            "downtime events": DowntimeEvent.objects.count(),
            "operational reports": OperationalReport.objects.count(),
            "stock transactions": StockTransaction.objects.count(),
            "purchase orders": PurchaseOrder.objects.count(), "expenses": OperationalExpense.objects.count(),
            "alerts": Alert.objects.count(), "approval records": ApprovalRecord.objects.count(),
        }
        for k, v in counts.items():
            self.stdout.write(f"  {k:<22} {v}")
        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready. Log in as admin / operations / maintenance / store / supervisor / manager "
            f"with password '{self.password}' (demo only)."))


def wo_user(cmd: Command, wo: WorkOrder) -> User:
    """Maintenance engineer acting on a work order (alternates deterministically by number)."""
    return cmd.u["maint"] if int(wo.number[-1]) % 2 == 0 else cmd.u["maint2"]
