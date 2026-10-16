import { useState } from "react";
import { Link } from "react-router-dom";
import { send } from "@/api/client";
import { Can } from "@/auth/AuthContext";
import { CreateWorkOrderDialog } from "@/components/CreateWorkOrderDialog";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { Button, ReasonDialog, StatusBadge, useToast } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDateTime } from "@/lib/format";

interface Incident {
  id: number; incident_number: string; plant_unit: number; plant_unit_code: string; asset: number | null; asset_tag: string | null;
  occurred_at: string; severity: string; category: string; title: string; description: string; status: string; status_label: string;
  reported_by_name: string; work_orders: { id: number; number: string; status: string }[]; resolution: string;
}

const SEVERITY = ["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((v) => ({ value: v, label: v[0] + v.slice(1).toLowerCase() }));
const CATEGORY = [["EQUIPMENT", "Equipment fault"], ["PROCESS", "Process deviation"], ["SAFETY", "Safety"], ["ENVIRONMENT", "Environmental"],
  ["EXTERNAL", "External"], ["OTHER", "Other"]].map(([value, label]) => ({ value, label }));

export default function IncidentsPage() {
  const { units } = useReference();
  const assets = useOptions("/assets/equipment/", (a) => `${a.asset_tag} · ${a.name}`);
  const toast = useToast();
  const [resolving, setResolving] = useState<{ row: Incident; reload: () => void } | null>(null);
  const [raising, setRaising] = useState<Incident | null>(null);
  const unitOptions = units.map((u) => ({ value: u.id, label: `${u.code} · ${u.name}` }));
  return (
    <>
      <ResourcePage<Incident> title="Operational incidents" subtitle="Faults, deviations and unusual events recorded by operations"
        endpoint="/operations/incidents/" defaultOrdering="-occurred_at"
        filters={[
          { name: "open", label: "Open only", type: "boolean" },
          { name: "severity", label: "Severity", type: "select", options: SEVERITY },
          { name: "category", label: "Category", type: "select", options: CATEGORY },
          { name: "unit", label: "Unit", type: "select", options: unitOptions },
        ]}
        columns={[
          { key: "incident_number", header: "Incident", sortKey: "occurred_at", render: (r) => <span className="font-medium">{r.incident_number}</span> },
          { key: "occurred_at", header: "Occurred", render: (r) => fmtDateTime(r.occurred_at) },
          { key: "title", header: "Title", render: (r) => <span title={r.description}>{r.title}</span> },
          { key: "unit", header: "Unit / asset", render: (r) => <>{r.plant_unit_code}{r.asset && <> · <Link className="link" to={`/assets/${r.asset}`}>{r.asset_tag}</Link></>}</> },
          { key: "severity", header: "Severity", sortKey: "severity", render: (r) => <StatusBadge status={r.severity} /> },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} label={r.status_label} /> },
          { key: "wo", header: "Work orders", render: (r) => r.work_orders.length ? r.work_orders.map((w) => (
            <Link key={w.id} className="link mr-2" to={`/maintenance/work-orders/${w.id}`}>{w.number}</Link>)) : "—" },
        ]}
        rowActions={(row, reload) => row.status !== "RESOLVED" && (
          <Can perm="incidents.record">
            {row.work_orders.length === 0 && row.asset && <Button size="sm" variant="ghost" onClick={() => setRaising(row)}>Raise WO</Button>}
            <Button size="sm" variant="ghost" onClick={() => setResolving({ row, reload })}>Resolve</Button>
          </Can>
        )}
        form={{
          perm: "incidents.record", noun: "incident", editable: (r) => r.status !== "RESOLVED",
          fields: [
            { name: "plant_unit", label: "Plant unit", type: "select", options: unitOptions, required: true, readOnlyOnEdit: true },
            { name: "asset", label: "Asset (if equipment related)", type: "select", options: assets },
            { name: "occurred_at", label: "Occurred at", type: "datetime", required: true, readOnlyOnEdit: true },
            { name: "severity", label: "Severity", type: "select", options: SEVERITY, required: true },
            { name: "category", label: "Category", type: "select", options: CATEGORY, required: true },
            { name: "title", label: "Title", required: true, full: true },
            { name: "description", label: "Description", type: "textarea", required: true },
            { name: "immediate_action", label: "Immediate action taken", type: "textarea" },
          ],
          initial: { severity: "MEDIUM", category: "EQUIPMENT" },
        }} />
      <ReasonDialog open={!!resolving} title={`Resolve ${resolving?.row.incident_number ?? ""}`} label="Resolution" confirmLabel="Resolve"
        onClose={() => setResolving(null)}
        onConfirm={async (text) => {
          await send("post", `/operations/incidents/${resolving!.row.id}/resolve/`, { resolution: text });
          toast.success("Incident resolved");
          resolving!.reload();
        }} />
      <CreateWorkOrderDialog open={!!raising} onClose={() => setRaising(null)} assetId={raising?.asset ?? undefined}
        incidentId={raising?.id} title={raising?.title} description={raising?.description} />
    </>
  );
}
