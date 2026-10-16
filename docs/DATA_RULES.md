# Data quality and business rules

Data quality is enforced in three layers: the **database** (constraints, see [ERD](ERD.md)), the **service
layer** (business rules inside transactions) and the **API/UI** (input shape and early feedback). The UI is never
the security or integrity boundary.

## Sources of truth

| Quantity | Source of truth | Consequence |
|---|---|---|
| Downtime | `DowntimeEvent` start/end timestamps | Durations are derived, never typed. A work order's downtime is the sum of its linked events. |
| Stock on hand | `StockTransaction` ledger | `InventoryItem.current_stock` is a maintained balance, written only by `post_transaction`; the ledger always re-sums to it. |
| Costs | `OperationalExpense` (cost ledger) | All cost analytics read this one table. |
| Operational performance | `OperationalMeasurement` on **approved** reports | Drafts, submitted and rejected reports never feed analytics. |
| Asset status | Synchronised from downtime (open event ⇒ out of service / under maintenance; last event closed ⇒ operational); can be set manually | Status changes are audited. |
| KPI definitions | `analytics/kpis.py` | Same definitions in the UI, API, docs and Power BI guide. |

## Time and periods

* Timestamps are stored in UTC. Each plant has an IANA time zone; reporting periods are inclusive ranges of
  **plant-local dates**, evaluated as `[00:00 date_from, 00:00 date_to + 1)`.
* A period that includes today is clipped at *now* - an ongoing outage counts up to the current minute, never to
  the end of the day.
* Shift reports carry the business date on which the shift **starts** (a 22:00-06:00 night shift belongs to the
  first day). Report submission is expected by shift end + `report_entry_deadline_hours`.
* Times entered in forms are plant-local wall-clock times with minute precision; ordering rules ("work cannot start
  before it was reported") compare at minute resolution.
* Nothing may be recorded in the future (5-minute clock-skew allowance), except cost *estimates*.

## Edge cases and how they are handled

| Situation | Handling |
|---|---|
| **Work order and its downtime describe the same incident** | Downtime exists only as events; the work order links to them. Totals sum events, so the outage is counted once. |
| **Overlapping faults on one asset** | Rejected: a second event may not overlap an existing one (service check under an asset row lock, and a PostgreSQL exclusion constraint as backstop). Extend or correct the existing event instead. |
| **Simultaneous faults on different assets** | Allowed and additive: KPIs report *equipment-hours* (two assets down for 5 h = 10 h). |
| **Outage still ongoing** | Event has no end; counts until now (or the period end). The work order cannot be completed or cancelled until the equipment is returned to service. |
| **Events crossing midnight or a period boundary** | Clipped exactly to the period (and split per local day in `bi.fact_downtime_daily`). |
| **Multiple equipment states during a shift** | The shift report stores the status *at reporting time*; the downtime timeline holds the detail. |
| **External curtailment (grid / fuel)** | Recorded as `EXTERNAL` downtime: included in total downtime, excluded from failure counts, MTTR and MTBF. |
| **Missing meter reading** | Stored as `NULL` with a mandatory reason; excluded from sums/averages and counted as "missing". **Never replaced by zero.** Required metrics need a value or a reason before submission. |
| **Implausible value** | Rejected against the metric's `valid_min`/`valid_max`. Values outside the *alert* range are accepted and raise a threshold alert. |
| **Duplicate report** | One report per unit, shift and date (unique constraint + friendly validation). |
| **Correction of an approved report** | Only an authorised supervisor/admin can reopen it, with a reason. The approved values are stored in the approval history; the report becomes a new draft revision and must be approved again. |
| **Partial reporting periods** | Budgets are prorated by days; turnover is not reported for periods under 28 days; the dashboard shows the period and freshness timestamps. The latest day may contain only the shifts approved so far. |
| **Insufficient data** | MTTR, MTBF, PM compliance, average repair cost, completion rate, lead time and turnover return `null` with status `insufficient_data`; the UI shows "Insufficient data", never 0. MTBF below three failures is flagged *low confidence*. |
| **PM task completed late / not at all / cancelled** | Late counts as non-compliant; open past due date + grace counts as missed; cancelled stays in the denominator as non-compliant. Tasks still inside their window are not yet counted. |
| **Stock issue larger than stock** | Rejected; stock cannot go negative (service check under row lock + `CHECK` constraint). |
| **Back-dated stock movement** | Rejected if earlier than the item's last movement (keeps running balances valid); corrections use adjustments. |
| **Retried / double-submitted request** | Stock movements and goods receipts accept an idempotency key; the key is re-checked after acquiring the row lock, so a retry returns the original record instead of posting twice. |
| **Over-receipt** | Receipt quantity cannot exceed the outstanding quantity on the order line (row-locked). |
| **Return of parts** | Limited to the net quantity issued to that work order (or department) and valued at the average cost of those issues. |
| **Parts on cancelled work** | A work order cannot be cancelled while it holds issued parts. |
| **Purchases vs expense** | Goods received become inventory at order price (weighted-average cost); the expense is recognised when parts are issued. Open order value is reported separately as a commitment. |
| **Estimates and commitments** | Stored in the cost ledger with `cost_type` ESTIMATE / COMMITMENT; excluded from actual-spend KPIs. |
| **Self-approval** | Nobody approves their own shift report, purchase request, overtime record, or verifies work they completed. |
| **Deleting reference data** | `PROTECT` foreign keys; users, assets, items and schedules are deactivated/archived rather than deleted. |
| **Currency** | Only the base currency is accepted (no silent conversion). |

## Validation summary

* Required fields, numeric ranges, decimal places (money 2 dp, quantities 3 dp, whole numbers for EA/SET/BOX).
* Dates/timestamps: not in the future; end after start; completion after start; receipt after order date.
* Unique business identifiers: asset tags, item codes, employee codes, document numbers (`WO-`, `PR-`, `PO-`,
  `GR-`, `ST-`, `INC-` sequences allocated under a lock).
* Referential integrity checked semantically too (e.g. the asset belongs to the incident's unit, a work order's
  downtime belongs to the same asset, a shift belongs to the unit's plant).

## Audit trail

`AuditLog` records creates, updates (field-level diffs), status changes, approvals/rejections, stock movements,
logins/logouts/failed logins and security events (role changes, token issue/rotation), with actor, timestamp and
client IP. `ApprovalRecord` keeps the workflow history (submit / approve / reject / reopen / verify / return) with a
snapshot of the values at decision time. Both are append-only through the application.
