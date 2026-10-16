# Case study: a Monday morning at the (synthetic) demo station

*All figures below come from the bundled demonstration dataset (`seed_demo --days 120 --seed 42`); your numbers
will differ slightly because the history is generated relative to the day you seed it.*

The plant manager opens the **executive dashboard** for the last 30 days.

1. **Is the plant performing?** Approved output is about 240 GWh, roughly 100 % of target - but the energy trend
   shows two dips. The **downtime trend** lines them up with spikes of unplanned failure on the gas turbines. Total
   downtime is ~117 equipment-hours, of which ~87 are unplanned failures.
2. **Where is availability being lost?** *Top equipment by downtime* ranks **ST1-BFP-002 (Boiler feed pump B)**
   first with ~24 hours. One click opens the asset: a single long failure, and its historical repair time (about
   15.6 h) is well above the plant's average failure duration (about 9.2 h) - the problem is time to restore, not
   frequency. **Management insights** separately reports that a third of the period's failures were *repeat
   failures* within 30 days, on **WTP-RO-002** (twice) and **BOP-CWP-001**, and labels its explanation as a
   **hypothesis** ("the root cause may not have been removed") with a **recommendation** (root-cause analysis).
   *Decisions:* a root-cause analysis for the reverse-osmosis train; for the feed pump, a review of spares
   availability and repair method to shorten restoration time.
3. **Is preventive maintenance under control?** PM compliance is ~82 %. The KPI card's definition explains the
   rule (completed by due date + grace; cancelled tasks count against compliance). The *overdue work orders* card
   drills straight into the 8 overdue items, including a missed valve stroke test.
   *Decision:* the maintenance lead prioritises overdue PM before new routine work this week.
4. **What is driving cost?** Maintenance expenditure jumped ~100 % versus the previous period. *Cost analytics*
   shows why: a single **unplanned generator rotor rewind (46.5 k)**, flagged by the expense-anomaly rule as 19×
   the category median. Ordinary consumption is in line with budget once this one-off is set aside.
   *Decision:* the rewind is reviewed as a capital/insurance question rather than a run-rate problem; the
   generator's inspection interval is checked.
5. **Will a spare part stop us?** The **critical stock** card shows one critical spare at its reorder point with
   nothing on order - the BFP bearing just consumed by a live breakdown that the dashboard also shows (one asset
   out of service, one open incident). The alert centre lists the same condition with the reason it fired.
   *Decision:* the store officer raises a purchase request from the item page; the manager approves it from the
   **Approvals** queue (they cannot approve their own requests); the order is tracked through receipt.
6. **Can I trust the numbers?** Every KPI tile carries its definition, formula and period type; data-freshness
   timestamps show when shift reports were last approved. For the monthly board pack, the BI analyst refreshes the
   Power BI model and runs `python manage.py bi_reconcile`: all 15 measures match the application.

The same records serve every level: the operator's shift report, the supervisor's approval, the engineer's work
order and the manager's KPI are one chain of evidence, with an audit trail behind each step.
