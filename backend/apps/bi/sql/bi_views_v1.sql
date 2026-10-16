-- PlantOps Intelligence - BI star schema (version 1)
-- Read-only reporting views in schema "bi". Views execute with their owner's rights, so a
-- reporting role needs SELECT on schema bi only, never on the application tables.
-- Date keys are YYYYMMDD integers in the plant's local time zone, matching the application KPIs.

CREATE SCHEMA IF NOT EXISTS bi;

-- ---------------------------------------------------------------- helpers
CREATE OR REPLACE VIEW bi.v_settings AS
SELECT
    COALESCE((SELECT (value #>> '{}')::int FROM core_systemsetting WHERE key = 'pm_compliance_grace_days'), 0) AS pm_grace_days,
    COALESCE((SELECT (value #>> '{}')::int FROM core_systemsetting WHERE key = 'fiscal_year_start_month'), 1) AS fiscal_year_start_month,
    COALESCE((SELECT value #>> '{}' FROM core_systemsetting WHERE key = 'base_currency'), 'USD') AS base_currency,
    COALESCE(
        (SELECT p.timezone FROM core_plant p
          WHERE p.code = (SELECT value #>> '{}' FROM core_systemsetting WHERE key = 'default_plant_code')),
        (SELECT p.timezone FROM core_plant p WHERE p.is_active ORDER BY p.id LIMIT 1),
        'UTC') AS default_timezone;

-- ---------------------------------------------------------------- dimensions
CREATE OR REPLACE VIEW bi.dim_date AS
SELECT
    to_char(d, 'YYYYMMDD')::int                          AS date_key,
    d::date                                              AS date,
    EXTRACT(YEAR FROM d)::int                            AS year,
    EXTRACT(QUARTER FROM d)::int                         AS quarter,
    EXTRACT(MONTH FROM d)::int                           AS month,
    to_char(d, 'Mon')                                    AS month_short,
    to_char(d, 'YYYY-MM')                                AS year_month,
    date_trunc('month', d)::date                         AS month_start,
    EXTRACT(ISOYEAR FROM d)::int                         AS iso_year,
    EXTRACT(WEEK FROM d)::int                            AS iso_week,
    date_trunc('week', d)::date                          AS week_start,
    EXTRACT(ISODOW FROM d)::int                          AS day_of_week,
    to_char(d, 'Dy')                                     AS day_short,
    EXTRACT(ISODOW FROM d) >= 6                          AS is_weekend,
    EXTRACT(DAY FROM (date_trunc('month', d) + interval '1 month - 1 day'))::int AS days_in_month,
    CASE WHEN EXTRACT(MONTH FROM d) >= s.fiscal_year_start_month
         THEN EXTRACT(YEAR FROM d)::int + CASE WHEN s.fiscal_year_start_month = 1 THEN 0 ELSE 1 END
         ELSE EXTRACT(YEAR FROM d)::int END              AS fiscal_year
FROM generate_series(DATE '2020-01-01', DATE '2032-12-31', interval '1 day') AS g(d)
CROSS JOIN bi.v_settings s;

CREATE OR REPLACE VIEW bi.dim_plant_unit AS
SELECT u.id AS unit_id, u.code AS unit_code, u.name AS unit_name, u.unit_type,
       p.id AS plant_id, p.code AS plant_code, p.name AS plant_name, p.facility_type, p.timezone AS plant_timezone,
       u.capacity, u.capacity_unit, u.is_active
FROM core_plantunit u JOIN core_plant p ON p.id = u.plant_id;

CREATE OR REPLACE VIEW bi.dim_department AS
SELECT id AS department_id, code AS department_code, name AS department_name, is_active FROM core_department
UNION ALL
SELECT -1, 'NONE', 'Unassigned', true;

CREATE OR REPLACE VIEW bi.dim_asset AS
SELECT a.id AS asset_id, a.asset_tag, a.name AS asset_name, c.code AS category_code, c.name AS category_name,
       a.plant_unit_id AS unit_id, a.criticality, a.status AS current_status, a.manufacturer, a.model_number,
       a.commissioned_on, a.archived_at IS NOT NULL AS is_archived
FROM assets_equipmentasset a JOIN assets_equipmentcategory c ON c.id = a.category_id
UNION ALL
SELECT -1, 'NONE', 'No asset', 'NONE', 'No asset', NULL, NULL, NULL, NULL, NULL, NULL, false;

-- Personal contact details and pay rates are intentionally excluded.
CREATE OR REPLACE VIEW bi.dim_employee AS
SELECT e.id AS employee_id, e.employee_code, e.first_name || ' ' || e.last_name AS employee_name,
       e.department_id, e.job_title, e.employment_status
FROM workforce_employee e;

CREATE OR REPLACE VIEW bi.dim_maintenance_type AS
SELECT * FROM (VALUES ('CORRECTIVE', 'Corrective', false), ('PREVENTIVE', 'Preventive', true),
                      ('INSPECTION', 'Inspection', true)) AS t(maintenance_type, maintenance_type_label, is_planned);

CREATE OR REPLACE VIEW bi.dim_cost_category AS
SELECT * FROM (VALUES ('SPARE_PARTS', 'Spare parts'), ('CONSUMABLES', 'Consumables'), ('LABOR', 'Labour'),
                      ('CONTRACTOR', 'Contractors'), ('EQUIPMENT_REPAIR', 'Equipment repair'),
                      ('UTILITIES', 'Utilities'), ('OTHER', 'Other operating expense')) AS t(category, category_label);

CREATE OR REPLACE VIEW bi.dim_inventory_item AS
SELECT i.id AS item_id, i.item_code, i.name AS item_name, c.name AS category_name, c.is_consumable, i.uom,
       i.criticality, i.min_stock_level, i.reorder_quantity, i.current_stock, i.unit_cost,
       round(i.current_stock * i.unit_cost, 2) AS stock_value,
       CASE WHEN i.current_stock <= 0 THEN 'OUT_OF_STOCK'
            WHEN i.current_stock <= i.min_stock_level AND i.criticality = 'CRITICAL' THEN 'CRITICAL_LOW'
            WHEN i.current_stock <= i.min_stock_level THEN 'LOW' ELSE 'OK' END AS stock_status,
       i.preferred_supplier_id AS supplier_id, i.is_active
FROM inventory_inventoryitem i JOIN inventory_itemcategory c ON c.id = i.category_id;

CREATE OR REPLACE VIEW bi.dim_supplier AS
SELECT id AS supplier_id, code AS supplier_code, name AS supplier_name, quoted_lead_time_days, is_active
FROM inventory_supplier;

CREATE OR REPLACE VIEW bi.dim_metric AS
SELECT m.id AS metric_id, m.plant_id, m.code AS metric_code, m.name AS metric_name, m.unit, m.aggregation,
       m.direction, m.target_value, m.is_primary_output, m.is_active
FROM operations_metricdefinition m;

CREATE OR REPLACE VIEW bi.dim_shift AS
SELECT id AS shift_id, plant_id, code AS shift_code, name AS shift_name, start_time, end_time, sequence
FROM workforce_shiftdefinition;

-- ---------------------------------------------------------------- facts
-- Grain: one measurement on one APPROVED report. NULL value = not recorded (never zero).
CREATE OR REPLACE VIEW bi.fact_operational_measurements AS
SELECT om.id AS measurement_id, r.id AS report_id, to_char(r.report_date, 'YYYYMMDD')::int AS date_key,
       r.report_date, r.plant_unit_id AS unit_id, r.shift_id, om.metric_id, om.value,
       om.value IS NULL AS is_missing, om.missing_reason,
       CASE WHEN om.value IS NOT NULL THEN m.target_value END AS target_value, r.revision
FROM operations_operationalmeasurement om
JOIN operations_operationalreport r ON r.id = om.report_id
JOIN operations_metricdefinition m ON m.id = om.metric_id
WHERE r.status = 'APPROVED';

-- Grain: one work order. wo_total_cost is an attribute for per-WO analysis: do NOT add it to
-- fact_operational_costs totals (the cost fact already contains the same ledger rows).
CREATE OR REPLACE VIEW bi.fact_work_orders AS
WITH s AS (SELECT * FROM bi.v_settings)
SELECT w.id AS work_order_id, w.number AS work_order_number, w.asset_id, a.plant_unit_id AS unit_id,
       w.maintenance_type, w.priority, w.status, w.failure_code,
       w.status IN ('REPORTED', 'ASSIGNED', 'IN_PROGRESS', 'AWAITING_VERIFICATION') AS is_open,
       w.schedule_id IS NOT NULL AS is_scheduled,
       w.assigned_technician_id AS employee_id,
       to_char(w.reported_at AT TIME ZONE p.timezone, 'YYYYMMDD')::int AS reported_date_key,
       to_char(w.actual_end AT TIME ZONE p.timezone, 'YYYYMMDD')::int AS completed_date_key,
       to_char(w.due_date, 'YYYYMMDD')::int AS due_date_key,
       w.reported_at, w.actual_start, w.actual_end, w.planned_end, w.due_date,
       round(EXTRACT(EPOCH FROM (w.actual_start - w.reported_at)) / 3600.0, 2) AS response_hours,
       round(EXTRACT(EPOCH FROM (w.actual_end - w.actual_start)) / 3600.0, 2) AS repair_hours,
       w.labor_hours, w.is_blocked,
       (w.status IN ('REPORTED', 'ASSIGNED', 'IN_PROGRESS', 'AWAITING_VERIFICATION') AND (
            (w.schedule_id IS NULL AND w.planned_end < now()) OR
            (w.schedule_id IS NOT NULL AND w.due_date + s.pm_grace_days < (now() AT TIME ZONE p.timezone)::date)
       )) AS is_overdue,
       CASE WHEN w.schedule_id IS NULL THEN NULL
            ELSE (w.status = 'COMPLETED' OR w.due_date + s.pm_grace_days < (now() AT TIME ZONE p.timezone)::date) END
           AS pm_counted,
       CASE WHEN w.schedule_id IS NULL THEN NULL
            ELSE (w.status = 'COMPLETED' AND (w.actual_end AT TIME ZONE p.timezone)::date <= w.due_date + s.pm_grace_days) END
           AS pm_on_time,
       (SELECT COALESCE(sum(x.amount), 0) FROM costs_operationalexpense x
         WHERE x.work_order_id = w.id AND x.cost_type = 'ACTUAL') AS wo_total_cost
FROM maintenance_workorder w
JOIN assets_equipmentasset a ON a.id = w.asset_id
JOIN core_plantunit u ON u.id = a.plant_unit_id
JOIN core_plant p ON p.id = u.plant_id
CROSS JOIN s;

-- Grain: one downtime event (whole event).
CREATE OR REPLACE VIEW bi.fact_downtime_events AS
SELECT e.id AS event_id, e.asset_id, a.plant_unit_id AS unit_id, e.work_order_id, e.downtime_type,
       to_char(e.started_at AT TIME ZONE p.timezone, 'YYYYMMDD')::int AS start_date_key,
       e.started_at, e.ended_at, e.ended_at IS NULL AS is_ongoing,
       round(EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)) / 3600.0, 4) AS duration_hours,
       e.cause
FROM maintenance_downtimeevent e
JOIN assets_equipmentasset a ON a.id = e.asset_id
JOIN core_plantunit u ON u.id = a.plant_unit_id
JOIN core_plant p ON p.id = u.plant_id;

-- Grain: one downtime event x local calendar day. Use this for date-sliced downtime totals: events that
-- cross midnight or a period boundary are split exactly as the application clips them.
CREATE OR REPLACE VIEW bi.fact_downtime_daily AS
SELECT x.event_id, x.asset_id, x.unit_id, x.work_order_id, x.downtime_type, x.date_key, x.date, x.downtime_hours
FROM (
    SELECT e.id AS event_id, e.asset_id, a.plant_unit_id AS unit_id, e.work_order_id, e.downtime_type,
           to_char(d.day, 'YYYYMMDD')::int AS date_key, d.day::date AS date,
           round(EXTRACT(EPOCH FROM (
               LEAST(COALESCE(e.ended_at, now()), (d.day + interval '1 day') AT TIME ZONE p.timezone)
               - GREATEST(e.started_at, d.day AT TIME ZONE p.timezone))) / 3600.0, 6) AS downtime_hours
    FROM maintenance_downtimeevent e
    JOIN assets_equipmentasset a ON a.id = e.asset_id
    JOIN core_plantunit u ON u.id = a.plant_unit_id
    JOIN core_plant p ON p.id = u.plant_id
    CROSS JOIN LATERAL generate_series(
        date_trunc('day', e.started_at AT TIME ZONE p.timezone),
        date_trunc('day', (COALESCE(e.ended_at, now()) AT TIME ZONE p.timezone) - interval '1 microsecond'),
        interval '1 day') AS d(day)
) x
WHERE x.downtime_hours > 0;

-- Grain: one stock-ledger movement. quantity and value are signed (+ into store, - out of store).
CREATE OR REPLACE VIEW bi.fact_inventory_transactions AS
SELECT t.id AS transaction_id, t.txn_number, t.item_id, t.txn_type,
       to_char(t.occurred_at AT TIME ZONE s.default_timezone, 'YYYYMMDD')::int AS date_key,
       t.occurred_at, t.quantity, t.unit_cost, t.total_value, t.balance_after,
       CASE WHEN t.txn_type IN ('ISSUE', 'RETURN') THEN -t.total_value ELSE 0 END AS consumption_value,
       t.work_order_id, COALESCE(t.department_id, -1) AS department_id
FROM inventory_stocktransaction t CROSS JOIN bi.v_settings s;

-- Grain: one cost-ledger row (ACTUAL, ESTIMATE or COMMITMENT; filter cost_type = 'ACTUAL' for spend).
CREATE OR REPLACE VIEW bi.fact_operational_costs AS
SELECT x.id AS expense_id, to_char(x.expense_date, 'YYYYMMDD')::int AS date_key, x.expense_date, x.category,
       x.cost_type, x.amount, x.currency, COALESCE(x.asset_id, -1) AS asset_id, x.work_order_id,
       COALESCE(x.department_id, -1) AS department_id, COALESCE(x.plant_unit_id, a.plant_unit_id) AS unit_id,
       x.source, (x.work_order_id IS NOT NULL OR x.asset_id IS NOT NULL) AS is_maintenance
FROM costs_operationalexpense x LEFT JOIN assets_equipmentasset a ON a.id = x.asset_id;

-- Grain: budget per day (monthly budget / days in month), so any date range prorates exactly like the app.
CREATE OR REPLACE VIEW bi.fact_budget_daily AS
SELECT b.id AS budget_id, to_char(d, 'YYYYMMDD')::int AS date_key, d::date AS date,
       COALESCE(b.department_id, -1) AS department_id, b.category,
       b.amount / EXTRACT(DAY FROM (make_date(b.year, b.month, 1) + interval '1 month - 1 day')) AS budget_amount
FROM costs_budget b
CROSS JOIN LATERAL generate_series(make_date(b.year, b.month, 1),
                                   make_date(b.year, b.month, 1) + interval '1 month - 1 day', interval '1 day') AS g(d);

-- Grain: one goods-receipt line.
CREATE OR REPLACE VIEW bi.fact_purchase_receipts AS
SELECT rl.id AS receipt_line_id, r.receipt_number, po.id AS purchase_order_id, po.po_number, po.supplier_id,
       pl.item_id, to_char(r.received_at AT TIME ZONE s.default_timezone, 'YYYYMMDD')::int AS date_key,
       rl.quantity, pl.unit_price, round(rl.quantity * pl.unit_price, 2) AS received_value,
       po.order_date, po.expected_delivery_date
FROM inventory_goodsreceiptline rl
JOIN inventory_goodsreceipt r ON r.id = rl.receipt_id
JOIN inventory_purchaseorderline pl ON pl.id = rl.order_line_id
JOIN inventory_purchaseorder po ON po.id = r.order_id
CROSS JOIN bi.v_settings s;

-- Grain: one alert.
CREATE OR REPLACE VIEW bi.fact_alerts AS
SELECT al.id AS alert_id, ru.code AS rule_code, ru.name AS rule_name, al.severity, al.status,
       to_char(al.first_detected_at AT TIME ZONE s.default_timezone, 'YYYYMMDD')::int AS date_key,
       al.first_detected_at, al.resolved_at, al.condition_cleared_at IS NULL AS is_live,
       round(EXTRACT(EPOCH FROM (COALESCE(al.resolved_at, now()) - al.first_detected_at)) / 3600.0, 2) AS age_hours
FROM alerts_alert al JOIN alerts_alertrule ru ON ru.id = al.rule_id CROSS JOIN bi.v_settings s;
