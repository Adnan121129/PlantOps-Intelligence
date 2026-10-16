-- BI views v2: model refinements for an unambiguous Power BI star schema.
--  * dim_plant_unit gains a -1 "Plant-wide" member and facts use COALESCE(unit_id, -1), so plant-wide
--    costs are never lost in a unit slicer;
--  * dim_asset carries unit_code (so the model does not need an asset->unit relationship, which would
--    create a second filter path from units to facts);
--  * fact_downtime_events gains end_date_key (MTTR is measured on events that ended in the period).
-- CREATE OR REPLACE VIEW only appends columns, so existing Power BI queries keep working.

CREATE OR REPLACE VIEW bi.dim_plant_unit AS
SELECT u.id AS unit_id, u.code AS unit_code, u.name AS unit_name, u.unit_type,
       p.id AS plant_id, p.code AS plant_code, p.name AS plant_name, p.facility_type, p.timezone AS plant_timezone,
       u.capacity, u.capacity_unit, u.is_active
FROM core_plantunit u JOIN core_plant p ON p.id = u.plant_id
UNION ALL
-- literals are cast to the base columns' exact types (CREATE OR REPLACE VIEW cannot change column types)
SELECT -1::bigint, 'PLANT'::varchar(20), 'Plant-wide (no unit)'::varchar(150), 'NONE'::varchar(30), NULL::bigint,
       NULL::varchar(20), NULL::varchar(150), NULL::varchar(30), NULL::varchar(64), NULL::numeric(12,3), NULL::varchar(20), true;

CREATE OR REPLACE VIEW bi.dim_asset AS
SELECT a.id AS asset_id, a.asset_tag, a.name AS asset_name, c.code AS category_code, c.name AS category_name,
       a.plant_unit_id AS unit_id, a.criticality, a.status AS current_status, a.manufacturer, a.model_number,
       a.commissioned_on, a.archived_at IS NOT NULL AS is_archived, u.code AS unit_code
FROM assets_equipmentasset a
JOIN assets_equipmentcategory c ON c.id = a.category_id
JOIN core_plantunit u ON u.id = a.plant_unit_id
UNION ALL
SELECT -1, 'NONE', 'No asset', 'NONE', 'No asset', -1, NULL, NULL, NULL, NULL, NULL, false, 'PLANT';

CREATE OR REPLACE VIEW bi.fact_downtime_events AS
SELECT e.id AS event_id, e.asset_id, a.plant_unit_id AS unit_id, e.work_order_id, e.downtime_type,
       to_char(e.started_at AT TIME ZONE p.timezone, 'YYYYMMDD')::int AS start_date_key,
       e.started_at, e.ended_at, e.ended_at IS NULL AS is_ongoing,
       round(EXTRACT(EPOCH FROM (COALESCE(e.ended_at, now()) - e.started_at)) / 3600.0, 4) AS duration_hours,
       e.cause,
       to_char(e.ended_at AT TIME ZONE p.timezone, 'YYYYMMDD')::int AS end_date_key
FROM maintenance_downtimeevent e
JOIN assets_equipmentasset a ON a.id = e.asset_id
JOIN core_plantunit u ON u.id = a.plant_unit_id
JOIN core_plant p ON p.id = u.plant_id;

CREATE OR REPLACE VIEW bi.fact_operational_costs AS
SELECT x.id AS expense_id, to_char(x.expense_date, 'YYYYMMDD')::int AS date_key, x.expense_date, x.category,
       x.cost_type, x.amount, x.currency, COALESCE(x.asset_id, -1) AS asset_id, x.work_order_id,
       COALESCE(x.department_id, -1) AS department_id, COALESCE(x.plant_unit_id, a.plant_unit_id, -1) AS unit_id,
       x.source, (x.work_order_id IS NOT NULL OR x.asset_id IS NOT NULL) AS is_maintenance
FROM costs_operationalexpense x LEFT JOIN assets_equipmentasset a ON a.id = x.asset_id;
