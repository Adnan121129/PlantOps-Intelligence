import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { ResourceFormDialog, useOptions, type FormField } from "./data";
import { useToast } from "./ui";

const PRIORITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((p) => ({ value: p, label: p[0] + p.slice(1).toLowerCase() }));

/** Raise a work order. Fault reporters (operations/supervisors) can only raise corrective work; planning is maintenance-only. */
export function CreateWorkOrderDialog({ open, onClose, assetId, incidentId, title, description }: {
  open: boolean; onClose: () => void; assetId?: number; incidentId?: number; title?: string; description?: string;
}) {
  const { can } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const assets = useOptions(open ? "/assets/equipment/" : null, (a) => `${a.asset_tag} · ${a.name}`);
  const techs = useOptions(open && can("workorders.manage") ? "/workforce/employees/" : null,
    (e) => `${e.employee_code} · ${e.full_name}`, { department: "", employment_status: "ACTIVE" });
  const planner = can("workorders.manage");
  const fields: FormField[] = [
    { name: "asset", label: "Asset", type: "select", options: assets, required: true },
    { name: "maintenance_type", label: "Type", type: "select", required: true,
      options: planner ? [{ value: "CORRECTIVE", label: "Corrective" }, { value: "PREVENTIVE", label: "Preventive" }, { value: "INSPECTION", label: "Inspection" }]
        : [{ value: "CORRECTIVE", label: "Corrective (fault report)" }] },
    { name: "priority", label: "Priority", type: "select", options: PRIORITIES, required: true },
    { name: "title", label: "Title", required: true, full: true },
    { name: "description", label: "Problem description", type: "textarea", required: true },
    ...(planner ? [
      { name: "assigned_technician", label: "Assign technician", type: "select" as const, options: techs },
      { name: "assigned_team", label: "Team" },
      { name: "planned_start", label: "Planned start", type: "datetime" as const },
      { name: "planned_end", label: "Planned completion", type: "datetime" as const },
    ] : []),
  ];
  return (
    <ResourceFormDialog open={open} onClose={onClose} title="Raise work order" endpoint="/maintenance/work-orders/" fields={fields}
      initial={{ asset: assetId ?? "", maintenance_type: "CORRECTIVE", priority: "MEDIUM", title: title ?? "", description: description ?? "" }}
      transform={(p) => ({ ...p, incident: incidentId ?? null })}
      onSaved={(row) => { toast.success("Work order raised"); navigate(`/maintenance/work-orders/${(row as { id: number }).id}`); }} />
  );
}
