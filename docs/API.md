# REST API reference

Base path `/api/`. JSON in and out. Authentication: session cookie (browser) - send `X-CSRFToken` on
`POST/PUT/PATCH/DELETE`; or `Authorization: Token <key>` on `/api/bi/*` only. With `DJANGO_DEBUG=true` every
endpoint also renders DRF's browsable API.

**Conventions**

* Lists are paginated: `?page=2&page_size=50` (max 200) → `{count, next, previous, results}`. A few reference lists
  (units, departments, shifts, metrics, categories, rules) are unpaginated arrays.
* Filtering by query parameters as listed; `?search=` full-text over key fields; `?ordering=field` / `-field`.
* Errors: `{"detail": "...", "errors": {"field": ["message"]}}` with 400 (validation / business rule), 401/403
  (not signed in / not permitted), 404, 409 (integrity conflict, e.g. deleting referenced data).
* Workflow transitions are explicit `POST` actions - status fields are never writable directly.
* Period parameters (analytics, reports): `date_from`, `date_to` (plant-local `YYYY-MM-DD`, inclusive; default
  last 30 days), `unit`, `plant`.

## Authentication - `/api/auth/`

| Method & path | Permission | Notes |
|---|---|---|
| `GET csrf/` | public | Sets the CSRF cookie |
| `POST login/` `{username, password}` | public, rate-limited | Returns the current user with `permissions[]` |
| `POST logout/` | signed in | |
| `GET / PATCH me/` | signed in | PATCH accepts only `first_name`, `last_name`, `theme_preference` |
| `POST me/password/` `{current_password, new_password}` | signed in | |
| `GET directory/?role=` | signed in | Active users (id, name, role) for pickers |
| `GET/POST/PATCH users/` | `users.manage` | Filters `role`, `is_active`, `department`. No DELETE (deactivate instead) |
| `GET audit-log/` | `audit.view` | Filters `action`, `entity_type`, `entity_id`, `actor`, `date_from`, `date_to` |

## Core - `/api/core/`

| Endpoint | Read / write permission | Notes |
|---|---|---|
| `plants/` | all / `reference.manage` | Time zone validated (IANA) |
| `units/` | all / `reference.manage` | Filters `plant`, `unit_type`, `requires_shift_reports` |
| `departments/` | all / `reference.manage` | |
| `GET settings/`, `PUT settings/<key>/` `{value}` | all / `reference.manage` | Typed, validated keys (grace days, base currency, fiscal year start, slow-moving days, ...) |
| `attachments/` `?target_type=&object_id=` | derived from the parent record | Multipart `POST {target_type, object_id, file}`; `GET <id>/download/`; `DELETE` |

## Assets - `/api/assets/`

| Endpoint | Permission | Notes |
|---|---|---|
| `categories/` | all / `reference.manage` | |
| `equipment/` | `assets.view` / `assets.manage` | Filters `plant_unit`, `plant`, `category`, `criticality`, `status`, `out_of_service`, `archived`. Annotated with `last_maintenance_at`, `next_maintenance_due`, `open_work_orders` |
| `POST equipment/<id>/archive/` `{reason}` | `assets.manage` | Requires no open work orders or ongoing downtime |
| `GET equipment/<id>/summary/` | `assets.view` | Lifetime/90-day downtime, failures, MTTR, costs, WO counts, monthly cost |

## Operations - `/api/operations/`

| Endpoint | Permission | Notes |
|---|---|---|
| `metrics/` | all / `reference.manage` | Configurable metric definitions |
| `reports/` (GET) | `dashboard.view` | Roles without `opsreports.view_all` see APPROVED only. Filters `status`, `unit`, `plant`, `shift`, `date_from`, `date_to`, `mine` |
| `POST reports/` | `opsreports.edit` | `{plant_unit, shift, report_date, summary, observations, measurements:[{metric, value, missing_reason}], equipment_statuses:[{asset, status}]}` |
| `PATCH reports/<id>/` | `opsreports.edit` | Draft / rejected only |
| `POST reports/<id>/submit/` | `opsreports.edit` | Completeness check |
| `POST reports/<id>/review/` `{decision: approve\|reject, comment}` | `opsreports.review` | Assigned unit, not own report; reject needs comment |
| `POST reports/<id>/reopen/` `{reason}` | `opsreports.reopen` | Approved → draft revision n+1 |
| `GET reports/template/?unit=` | `opsreports.edit` | Shifts, applicable metrics, unit assets |
| `GET reports/missing/?date_from&date_to&unit` | `dashboard.view` | Expected reports not submitted after the deadline |
| `incidents/` | all / `incidents.record` | `POST <id>/resolve/ {resolution}`; filters `open`, `severity`, `category`, `unit`, `asset` |

## Maintenance - `/api/maintenance/`

| Endpoint | Permission | Notes |
|---|---|---|
| `work-orders/` (GET) | `workorders.view` | Filters `status` (multi), `open`, `overdue`, `is_blocked`, `maintenance_type`, `priority`, `asset`, `unit`, `category`, `preventive`, `reported_from/to`, `due_from/to`, `assigned_technician` |
| `POST work-orders/` | `workorders.report` | Fault reporters create corrective work only; planning fields require `workorders.manage` |
| `PATCH work-orders/<id>/` | `workorders.manage` | Title, description, priority, planning, verification flag |
| `POST <id>/assign/` `{assigned_technician, assigned_team, planned_start, planned_end}` | `workorders.manage` | |
| `POST <id>/start/` `{actual_start}` · `POST <id>/complete/` `{actual_end, actions_performed, failure_code, root_cause, labor_hours}` | `workorders.manage` | Completion requires closed downtime |
| `POST <id>/verify/` `{decision: approve\|return, comment}` | `workorders.verify` | Not the person who completed it |
| `POST <id>/cancel/` `{reason}` · `POST <id>/block/` `{blocked, reason}` | `workorders.cancel` / `workorders.manage` | |
| `POST <id>/costs/` `{category, amount, description, expense_date, reference}` | `workorders.manage` | Labour / contractor / repair / other into the cost ledger |
| `POST <id>/issue-part/`, `POST <id>/return-part/` `{item, quantity, idempotency_key}` | `stock.issue` / `stock.return` | Posts to the stock ledger and the cost ledger |
| `downtime/` | `assets.view` / `downtime.record` | `POST <id>/close/ {ended_at}`; overlap-checked; filters `asset`, `unit`, `category`, `downtime_type`, `ongoing`, `date_from/to` (overlap semantics) |
| `schedules/` | `workorders.view` / `pm.manage` | `POST schedules/generate/`; `GET schedules/calendar/?start&end&unit` |
| `inspections/` | `workorders.view` / `workorders.manage` | Immutable records |

## Inventory & procurement - `/api/inventory/`

| Endpoint | Permission | Notes |
|---|---|---|
| `categories/`, `suppliers/`, `items/` | `inventory.view` / `inventory.manage` | `current_stock`, `unit_cost` read-only. Items filter `stock_status` (LOW / CRITICAL_LOW / OUT_OF_STOCK / OK), `category`, `criticality`, `asset` (compatible) |
| `GET items/<id>/insight/` | `inventory.view` | On order, usage, cover, recent movements |
| `transactions/` (GET) | `inventory.view` | The ledger; filters `item`, `txn_type`, `work_order`, `department`, `date_from/to` |
| `POST transactions/` `{item, txn_type, quantity, unit_cost?, work_order?, department?, reference, notes, idempotency_key}` | per type: `stock.receive` / `stock.issue` / `stock.return` / `stock.adjust` | 201 new, 200 duplicate key |
| `purchase-requests/` | `procurement.view` / `procurement.request` | `POST` with `lines:[{item, quantity, estimated_unit_cost}]`; actions `submit/`, `decide/ {decision, comment}` (`procurement.approve`), `convert/ {supplier, expected_delivery_date, prices}` (`procurement.order`), `cancel/` |
| `purchase-orders/` | `procurement.view` / `procurement.order` | Actions `issue/`, `receive/ {lines:[{order_line, quantity}], delivery_note, idempotency_key}` (`stock.receive`), `close/ {reason}`, `cancel/ {reason}` |
| `receipts/` | `procurement.view` | |

## Workforce - `/api/workforce/`

`employees/` (contact fields only with `employees.view_contact`), `shifts/`, `assignments/` (+ `GET coverage/?date_from&date_to`),
`handovers/` (+ `POST <id>/acknowledge/`), `overtime/` (+ `POST <id>/decide/ {approve, comment}`), `GET directory/`.

## Costs - `/api/costs/`

`expenses/` (read `costs.view`, write `costs.record`; system-generated rows are immutable; filters `date_from/to`, `category`,
`cost_type`, `source`, `asset`, `work_order`, `department`, `unit`, `maintenance`, `min_amount`), `budgets/` (`budgets.manage`).

## Alerts - `/api/alerts/`

| Endpoint | Notes |
|---|---|
| `alerts/` | Filtered to the user's role audience. Filters `active`, `status`, `severity`, `rule`. Actions `acknowledge/`, `resolve/ {note}`, `dismiss/ {note}`; `GET summary/`; `POST evaluate/` (`alerts.evaluate`) |
| `rules/` | `PATCH` (`alerts.rules.manage`): `is_enabled`, `severity`, `params`, `audience_roles` |
| `notifications/` | Current user's notifications; `POST <id>/read/`, `POST read-all/` |

## Analytics - `/api/analytics/`

| Endpoint | Permission | Returns |
|---|---|---|
| `dashboard/?granularity=day\|week\|month` | `dashboard.view` | `kpis[]` (value + definition + link), `charts{}`, `freshness`, `period`, `restricted[]` |
| `maintenance/`, `inventory/`, `costs/`, `operations/?metric=` | module permission | Module KPIs and series |
| `insights/` | `insights.view` | Rule-based insights (observation / hypothesis / recommendation) |
| `kpi-dictionary/` | `dashboard.view` | KPI definitions |
| `reports/`, `reports/<code>/?export=json\|csv\|xlsx&page&page_size` | per report | JSON with `columns` and paginated `results`; CSV streamed with `X-Report-*` headers; XLSX with info sheet |
| `search/?q=` | `dashboard.view` | Assets, work orders, items, incidents (max 5 each, permission-aware) |

## BI - `/api/bi/` (read-only)

| Endpoint | Notes |
|---|---|
| `datasets/` | List of the 20 views with descriptions |
| `datasets/<name>/?limit=50000&offset=0&output=json\|csv` | Whitelisted view names only |
| `GET/POST/DELETE token/` | Session only. Issue/rotate (shown once) or revoke your token (`bi.access`) |
