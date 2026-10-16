import { Link } from "react-router-dom";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { StatusBadge } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDate, fmtDateTime } from "@/lib/format";

interface Asset {
  id: number; asset_tag: string; name: string; category: number; category_name: string; plant_unit: number; plant_unit_code: string;
  status: string; status_label: string; criticality: string; criticality_label: string; manufacturer: string; model_number: string;
  last_maintenance_at: string | null; next_maintenance_due: string | null; open_work_orders: number; is_archived: boolean;
}

export const STATUS_OPTIONS = [["OPERATIONAL", "Operational"], ["UNDER_MAINTENANCE", "Under maintenance"], ["OUT_OF_SERVICE", "Out of service"]]
  .map(([value, label]) => ({ value, label }));
export const CRITICALITY = [["HIGH", "High (A)"], ["MEDIUM", "Medium (B)"], ["LOW", "Low (C)"]].map(([value, label]) => ({ value, label }));

export default function AssetListPage() {
  const { units } = useReference();
  const categories = useOptions("/assets/categories/", (c) => String(c.name));
  const unitOptions = units.map((u) => ({ value: u.id, label: `${u.code} · ${u.name}` }));
  return (
    <ResourcePage<Asset> title="Equipment register" subtitle="Assets, status, criticality and maintenance position"
      endpoint="/assets/equipment/" defaultOrdering="asset_tag"
      filters={[
        { name: "plant_unit", label: "Unit", type: "select", options: unitOptions },
        { name: "category", label: "Category", type: "select", options: categories },
        { name: "status", label: "Status", type: "select", options: STATUS_OPTIONS },
        { name: "criticality", label: "Criticality", type: "select", options: CRITICALITY },
        { name: "out_of_service", label: "Unavailable", type: "boolean" },
        { name: "archived", label: "Archived", type: "boolean" },
      ]}
      columns={[
        { key: "asset_tag", header: "Asset", sortKey: "asset_tag", render: (a) => <Link className="link font-medium" to={`/assets/${a.id}`}>{a.asset_tag}</Link> },
        { key: "name", header: "Name", sortKey: "name" },
        { key: "unit", header: "Unit", render: (a) => a.plant_unit_code },
        { key: "category", header: "Category", render: (a) => a.category_name },
        { key: "criticality", header: "Criticality", sortKey: "criticality", render: (a) => a.criticality_label.split(" ")[0] },
        { key: "status", header: "Status", sortKey: "status", render: (a) => <StatusBadge status={a.status} label={a.status_label} /> },
        { key: "open", header: "Open WOs", align: "right", render: (a) => a.open_work_orders },
        { key: "last", header: "Last maintenance", sortKey: "last_maintenance_at", render: (a) => fmtDateTime(a.last_maintenance_at) },
        { key: "next", header: "Next PM due", sortKey: "next_maintenance_due", render: (a) => fmtDate(a.next_maintenance_due) },
      ]}
      form={{
        perm: "assets.manage", noun: "asset", editable: (a) => !a.is_archived,
        initial: { criticality: "MEDIUM", status: "OPERATIONAL" },
        fields: [
          { name: "asset_tag", label: "Asset ID", required: true, readOnlyOnEdit: true },
          { name: "name", label: "Name", required: true },
          { name: "category", label: "Category", type: "select", options: categories, required: true },
          { name: "plant_unit", label: "Plant unit", type: "select", options: unitOptions, required: true },
          { name: "location", label: "Location" },
          { name: "criticality", label: "Criticality", type: "select", options: CRITICALITY, required: true },
          { name: "status", label: "Status", type: "select", options: STATUS_OPTIONS, required: true,
            hint: "Normally synchronised from downtime records" },
          { name: "manufacturer", label: "Manufacturer" },
          { name: "model_number", label: "Model" },
          { name: "serial_number", label: "Serial number" },
          { name: "commissioned_on", label: "Commissioned on", type: "date" },
          { name: "technical_notes", label: "Technical notes", type: "textarea" },
        ],
      }} />
  );
}
