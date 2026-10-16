# Testing

| Suite | Location | Runs against | Command |
|---|---|---|---|
| Backend unit/integration | `backend/apps/*/tests/` | real PostgreSQL (test database `test_plantops`) | `cd backend && pytest` |
| Frontend unit | `frontend/src/__tests__/` | jsdom | `cd frontend && npm test` |
| End-to-end | `e2e/tests/` | real Django + Vite + PostgreSQL (`plantops_e2e`) | `cd e2e && npm ci && ./run-e2e.sh` |
| Static checks | — | — | `cd backend && ruff check .` · `cd frontend && npm run typecheck` |

Results in the build environment: **76 backend tests passed, 20 frontend tests passed, 4 end-to-end tests
passed**, ruff and TypeScript clean.

## Backend coverage (pytest)

* **Authentication & authorisation**: login/logout, failed-login audit, CSRF enforcement, no self role escalation,
  admin self-protection, password validation, a parametrised role × endpoint matrix, BI token scope.
* **Assets**: create/update with audit diff, duplicate tags, no deletion, archive rules.
* **Operational reports**: full workflow including rejection and audited reopen (revision 2, snapshot of approved
  values), duplicate prevention, range validation, future dates, missing values with reasons, reviewer unit
  assignment and segregation, management sees approved only, missing-report detection, target variance.
* **Maintenance**: end-to-end corrective lifecycle through the API (downtime, parts, costs, verification), invalid
  transitions, cancellation rules, fault-reporter restrictions, downtime validation and overlap protection
  (service and exclusion constraint), locked downtime on closed work, PM generation idempotency and uniqueness,
  calendar projection, schedule validation.
* **Inventory**: weighted-average cost, issue/return/adjust, return limits, ledger re-sum, negative stock and
  back-dating rejection, DB constraint backstop, read-only stock fields, per-type permissions, idempotent retries,
  **12 concurrent threads competing for 10 units** (exactly 10 succeed), full procurement flow with partial
  receipts, duplicate receipt detection, over-receipt rejection, self-approval prevention.
* **Alerts**: creation, dedup across evaluations, auto-resolve on clear, recurrence creates a new alert,
  reopen after premature manual resolution, dismissed stays dismissed, audience filtering, parameter validation,
  disabled rules, downtime and overdue rules, like-for-like expense trend detection.
* **KPIs & BI**: clipped downtime, trend buckets, MTTR/MTBF/repeat failures on a hand-calculated scenario,
  insufficient data returns null, PM compliance formula, actual-only cost scope, budget proration, dashboard values
  and role-restricted cost KPIs, period validation, **BI views reconcile with the app**, every documented DAX
  measure reconciles (`bi.reconcile`).
* **Reports & exports**: CSV content and metadata headers, XLSX data and info sheets, JSON pagination, report
  permissions, spreadsheet formula injection.
* **Workforce, costs, core**: contact-data privacy, roster uniqueness and coverage, overtime approval costing
  into the ledger, handover acknowledgement, manual expense validation, immutability of system costs, budget
  uniqueness, settings validation, invalid time zones, attachment validation and permissions.

## Frontend coverage (Vitest + Testing Library)

Protected routes (redirect when anonymous), permission-aware rendering (`<Can>`, route guard), theme toggle /
persistence / system preference, data table empty / loading / error / sorting states, pagination, KPI card
definition and "insufficient data" rendering, period presets and unit filter, API error normalisation, form
required-field validation, server field-error mapping, PATCH submission.

## End-to-end (Playwright)

1. **Corrective maintenance end to end** - maintenance creates an asset; operations records an incident and raises
   a work order from it (and cannot assign it); maintenance assigns, starts, records downtime, issues a spare part,
   adds labour cost, is blocked from completing while the outage is open, returns the asset to service and
   completes; the engineer cannot verify their own work; the supervisor verifies; the test then checks the stock
   balance, work-order costs, dashboard KPIs (maintenance cost, asset count, downtime), the asset's history, and
   downloads the maintenance-history CSV from the report centre and verifies its contents.
2. **Shift-report approval** - admin configures a unit; operations submits a report with a missing reading and a
   reason; a duplicate is refused; management cannot see it until a supervisor approves; afterwards the author
   cannot edit it (UI and API).
3. **Theme persistence** across reloads and navigation.
4. **Server-side RBAC** when the UI is bypassed (store officer cannot raise a work order or change their role).

`run-e2e.sh` uses an isolated database and relaxes the login rate limit for that run only (the suite signs in
more than ten times a minute).
