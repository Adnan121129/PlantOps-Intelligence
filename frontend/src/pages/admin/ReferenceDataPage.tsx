import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { PageHeader, StatusBadge, Tabs } from "@/components/ui";
import { useUrlState } from "@/hooks/useUrlState";
import { useReference } from "@/lib/ReferenceContext";
import { humanize } from "@/lib/format";

type Row = { id: number } & Record<string, unknown>;
const active = (r: Row) => <StatusBadge status={r.is_active ? "ACTIVE" : "INACTIVE"} />;
const UNIT_TYPES = ["GENERATING_UNIT", "PRODUCTION_LINE", "UTILITY", "AUXILIARY"].map((v) => ({ value: v, label: humanize(v) }));

export default function ReferenceDataPage() {
  const [state, update] = useUrlState({ tab: "units" });
  const { plants, reload } = useReference();
  const plantOptions = plants.map((p) => ({ value: p.id, label: p.code }));
  const metricsPlant = useOptions("/core/plants/", (p) => String(p.code));
  const tabs = [
    { id: "plants", label: "Plants" }, { id: "units", label: "Plant units" }, { id: "departments", label: "Departments" },
    { id: "shifts", label: "Shifts" }, { id: "metrics", label: "Operational metrics" }, { id: "equipment", label: "Equipment categories" },
    { id: "items", label: "Item categories" },
  ];
  const common = { embedded: true, title: "", onSaved: reload } as const;
  return (
    <div>
      <PageHeader title="Reference data" subtitle="Plant structure, shifts, configurable metrics and categories" />
      <Tabs active={state.tab} onChange={(t) => update({ tab: t })} tabs={tabs} />
      {state.tab === "plants" && <ResourcePage<Row> {...common} endpoint="/core/plants/"
        columns={[{ key: "code", header: "Code" }, { key: "name", header: "Name" }, { key: "facility_type_label", header: "Facility type" },
          { key: "timezone", header: "Time zone" }, { key: "currency", header: "Currency" }, { key: "a", header: "Status", render: active }]}
        form={{ perm: "reference.manage", noun: "plant", initial: { facility_type: "POWER_GENERATION", timezone: "UTC", currency: "USD", is_active: true }, fields: [
          { name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true },
          { name: "facility_type", label: "Facility type", type: "select", required: true, options: ["POWER_GENERATION", "MANUFACTURING", "PROCESS", "OTHER"].map((v) => ({ value: v, label: humanize(v) })) },
          { name: "timezone", label: "IANA time zone", required: true, hint: "e.g. Asia/Dubai, Europe/London" }, { name: "currency", label: "Currency", required: true },
          { name: "location", label: "Location" }, { name: "is_active", label: "Active", type: "checkbox", hint: "In use" }] }} />}
      {state.tab === "units" && <ResourcePage<Row> {...common} endpoint="/core/units/" paged={false} search={false}
        columns={[{ key: "plant_code", header: "Plant" }, { key: "code", header: "Code" }, { key: "name", header: "Name" }, { key: "unit_type_label", header: "Type" },
          { key: "r", header: "Shift reports", render: (r) => (r.requires_shift_reports ? "Required" : "Not required") },
          { key: "cap", header: "Capacity", render: (r) => (r.capacity ? `${r.capacity} ${r.capacity_unit}` : "—") }, { key: "a", header: "Status", render: active }]}
        form={{ perm: "reference.manage", noun: "unit", initial: { requires_shift_reports: true, is_active: true, unit_type: "GENERATING_UNIT" }, fields: [
          { name: "plant", label: "Plant", type: "select", options: plantOptions, required: true }, { name: "code", label: "Code", required: true },
          { name: "name", label: "Name", required: true }, { name: "unit_type", label: "Type", type: "select", options: UNIT_TYPES, required: true },
          { name: "capacity", label: "Capacity", type: "number", step: "any" }, { name: "capacity_unit", label: "Capacity unit" },
          { name: "requires_shift_reports", label: "Shift reports", type: "checkbox", hint: "Expect one report per shift" },
          { name: "is_active", label: "Active", type: "checkbox", hint: "In use" }, { name: "description", label: "Description", type: "textarea" }] }} />}
      {state.tab === "departments" && <ResourcePage<Row> {...common} endpoint="/core/departments/" paged={false}
        columns={[{ key: "code", header: "Code" }, { key: "name", header: "Name" }, { key: "a", header: "Status", render: active }]}
        form={{ perm: "reference.manage", noun: "department", initial: { is_active: true }, fields: [
          { name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "is_active", label: "Active", type: "checkbox", hint: "In use" }] }} />}
      {state.tab === "shifts" && <ResourcePage<Row> {...common} endpoint="/workforce/shifts/" paged={false} search={false}
        columns={[{ key: "code", header: "Code" }, { key: "name", header: "Name" }, { key: "t", header: "Hours", render: (r) => `${String(r.start_time).slice(0, 5)}–${String(r.end_time).slice(0, 5)}${r.crosses_midnight ? " (+1 day)" : ""}` },
          { key: "min_staff", header: "Min. staff", align: "right" }, { key: "sequence", header: "Order", align: "right" }, { key: "a", header: "Status", render: active }]}
        form={{ perm: "reference.manage", noun: "shift", initial: { is_active: true, min_staff: 1, sequence: 1 }, fields: [
          { name: "plant", label: "Plant", type: "select", options: plantOptions, required: true }, { name: "code", label: "Code", required: true },
          { name: "name", label: "Name", required: true }, { name: "start_time", label: "Start", type: "time", required: true },
          { name: "end_time", label: "End", type: "time", required: true, hint: "An end before the start means the shift crosses midnight" },
          { name: "min_staff", label: "Minimum staff", type: "number" }, { name: "sequence", label: "Order", type: "number" },
          { name: "is_active", label: "Active", type: "checkbox", hint: "In use" }] }} />}
      {state.tab === "metrics" && <ResourcePage<Row> {...common} endpoint="/operations/metrics/" paged={false} search={false}
        columns={[{ key: "code", header: "Code" }, { key: "name", header: "Name" }, { key: "unit", header: "Unit" }, { key: "aggregation", header: "Aggregation", render: (r) => humanize(String(r.aggregation)) },
          { key: "target_value", header: "Target", align: "right", render: (r) => String(r.target_value ?? "—") },
          { key: "range", header: "Valid range", render: (r) => `${r.valid_min ?? "—"} – ${r.valid_max ?? "—"}` },
          { key: "alert", header: "Alert range", render: (r) => `${r.alert_low ?? "—"} – ${r.alert_high ?? "—"}` },
          { key: "p", header: "Primary", render: (r) => (r.is_primary_output ? "Primary output" : "") }, { key: "a", header: "Status", render: active }]}
        form={{ perm: "reference.manage", noun: "metric", initial: { aggregation: "SUM", direction: "NEUTRAL", is_required: true, is_active: true, unit_types: [], display_order: 10 }, fields: [
          { name: "plant", label: "Plant", type: "select", options: metricsPlant, required: true }, { name: "code", label: "Code", required: true },
          { name: "name", label: "Name", required: true }, { name: "unit", label: "Unit of measure", required: true },
          { name: "aggregation", label: "Aggregation", type: "select", options: [{ value: "SUM", label: "Sum" }, { value: "AVG", label: "Average" }] },
          { name: "direction", label: "Direction", type: "select", options: ["HIGHER_BETTER", "LOWER_BETTER", "NEUTRAL"].map((v) => ({ value: v, label: humanize(v) })) },
          { name: "target_value", label: "Target per report", type: "number", step: "any" },
          { name: "valid_min", label: "Valid minimum", type: "number", step: "any" }, { name: "valid_max", label: "Valid maximum", type: "number", step: "any" },
          { name: "alert_low", label: "Alert below", type: "number", step: "any" }, { name: "alert_high", label: "Alert above", type: "number", step: "any" },
          { name: "unit_types", label: "Applies to unit types", type: "multiselect", options: UNIT_TYPES, hint: "None selected = all units" },
          { name: "display_order", label: "Display order", type: "number" },
          { name: "is_required", label: "Required", type: "checkbox", hint: "Value or reason needed on submit" },
          { name: "is_primary_output", label: "Primary output", type: "checkbox", hint: "Used for cost per unit KPIs" },
          { name: "is_active", label: "Active", type: "checkbox", hint: "In use" }, { name: "description", label: "Description", type: "textarea" }] }} />}
      {state.tab === "equipment" && <ResourcePage<Row> {...common} endpoint="/assets/categories/" paged={false}
        columns={[{ key: "code", header: "Code" }, { key: "name", header: "Name" }, { key: "asset_count", header: "Assets", align: "right" }, { key: "a", header: "Status", render: active }]}
        form={{ perm: "reference.manage", noun: "category", initial: { is_active: true }, fields: [{ name: "code", label: "Code", required: true },
          { name: "name", label: "Name", required: true }, { name: "is_active", label: "Active", type: "checkbox", hint: "In use" }, { name: "description", label: "Description", type: "textarea" }] }} />}
      {state.tab === "items" && <ResourcePage<Row> {...common} endpoint="/inventory/categories/" paged={false} search={false}
        columns={[{ key: "code", header: "Code" }, { key: "name", header: "Name" }, { key: "c", header: "Costed as", render: (r) => (r.is_consumable ? "Consumables" : "Spare parts") }]}
        form={{ perm: "inventory.manage", noun: "item category", fields: [{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true },
          { name: "is_consumable", label: "Consumable", type: "checkbox", hint: "Issues are costed as consumables" }] }} />}
    </div>
  );
}
