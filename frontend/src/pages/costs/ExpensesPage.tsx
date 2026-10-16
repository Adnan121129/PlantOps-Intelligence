import { Link } from "react-router-dom";
import { exportUrl } from "@/api/client";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { Badge } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDate, fmtMoney, plantToday } from "@/lib/format";
import { COST_CATEGORIES, COST_TYPES } from "./common";

interface Expense { id: number; expense_date: string; category: string; category_label: string; cost_type: string; cost_type_label: string; amount: string;
  currency: string; description: string; reference: string; asset: number | null; asset_tag: string | null; work_order: number | null; work_order_number: string | null;
  department_name: string | null; plant_unit_code: string | null; source: string; source_label: string; recorded_by_name: string }

export default function ExpensesPage() {
  const { departments, units } = useReference();
  const assets = useOptions("/assets/equipment/", (a) => `${a.asset_tag} · ${a.name}`);
  const depts = departments.map((d) => ({ value: d.id, label: d.name }));
  return (
    <ResourcePage<Expense> title="Cost ledger"
      subtitle="Single source of cost truth. Parts are costed when issued; work-order and overtime entries are posted by their workflows and are read-only here."
      endpoint="/costs/expenses/" defaultOrdering="-expense_date" pageSize={50}
      headerActions={<a className="inline-flex h-8 items-center rounded-md border border-border-strong bg-surface px-3 text-sm font-medium hover:bg-sunken"
        href={exportUrl("/analytics/reports/maintenance_cost/", { export: "xlsx" })}>Export XLSX</a>}
      filters={[
        { name: "date_from", label: "From", type: "date" }, { name: "date_to", label: "To", type: "date" },
        { name: "category", label: "Category", type: "select", options: COST_CATEGORIES },
        { name: "cost_type", label: "Type", type: "select", options: COST_TYPES },
        { name: "department", label: "Department", type: "select", options: depts },
        { name: "unit", label: "Unit", type: "select", options: units.map((u) => ({ value: u.id, label: u.code })) },
        { name: "maintenance", label: "Maintenance-related", type: "boolean" },
        { name: "source", label: "Source", type: "select", options: [{ value: "MANUAL", label: "Manual" }, { value: "WORK_ORDER", label: "Work order" },
          { value: "STOCK", label: "Stock issue/return" }, { value: "OVERTIME", label: "Overtime" }] },
      ]}
      columns={[
        { key: "date", header: "Date", sortKey: "expense_date", render: (e) => fmtDate(e.expense_date) },
        { key: "category", header: "Category", sortKey: "category", render: (e) => e.category_label },
        { key: "type", header: "Type", render: (e) => e.cost_type === "ACTUAL" ? "Actual" : <Badge tone="info" icon={null}>{e.cost_type_label}</Badge> },
        { key: "description", header: "Description", render: (e) => <span className="line-clamp-2">{e.description}</span> },
        { key: "amount", header: "Amount", align: "right", sortKey: "amount", render: (e) => fmtMoney(e.amount, { currency: e.currency }) },
        { key: "link", header: "Asset / WO", render: (e) => <>{e.asset && <Link className="link mr-1" to={`/assets/${e.asset}`}>{e.asset_tag}</Link>}
          {e.work_order && <Link className="link" to={`/maintenance/work-orders/${e.work_order}`}>{e.work_order_number}</Link>}{!e.asset && !e.work_order && "—"}</> },
        { key: "dept", header: "Department", render: (e) => e.department_name ?? "—" },
        { key: "source", header: "Source", render: (e) => e.source_label },
        { key: "ref", header: "Reference", render: (e) => e.reference || "—" },
      ]}
      form={{ perm: "costs.record", noun: "expense", editable: (e) => e.source === "MANUAL",
        initial: { expense_date: plantToday(), cost_type: "ACTUAL", category: "CONTRACTOR" },
        fields: [
          { name: "expense_date", label: "Date", type: "date", required: true },
          { name: "category", label: "Category", type: "select", options: COST_CATEGORIES, required: true },
          { name: "cost_type", label: "Type", type: "select", options: COST_TYPES, required: true, hint: "Only actuals count as spend" },
          { name: "amount", label: "Amount", type: "number", step: "0.01", required: true },
          { name: "description", label: "Description", required: true, full: true },
          { name: "asset", label: "Asset", type: "select", options: assets },
          { name: "department", label: "Department", type: "select", options: depts },
          { name: "plant_unit", label: "Unit", type: "select", options: units.map((u) => ({ value: u.id, label: u.code })) },
          { name: "reference", label: "Invoice / reference" },
        ] }} />
  );
}
