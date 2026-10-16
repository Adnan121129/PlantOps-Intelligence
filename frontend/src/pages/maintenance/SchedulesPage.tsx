import { send } from "@/api/client";
import { Can } from "@/auth/AuthContext";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { Button, StatusBadge, useToast } from "@/components/ui";
import { fmtDate, fmtDateTime, humanize } from "@/lib/format";

interface Schedule {
  id: number; asset: number; asset_tag: string; asset_name: string; title: string; task_type: string; interval_days: number; start_date: string;
  lead_days: number; reminder_days: number; technician_name: string | null; is_active: boolean; next_due_date: string;
  last_completed_at: string | null; open_work_orders: number;
}

export default function SchedulesPage() {
  const toast = useToast();
  const assets = useOptions("/assets/equipment/", (a) => `${a.asset_tag} · ${a.name}`);
  const techs = useOptions("/workforce/directory/", (e) => `${e.employee_code} · ${e.full_name}`);
  return (
    <ResourcePage<Schedule> title="Preventive maintenance schedules"
      subtitle="Fixed calendar intervals. Work orders are generated within the lead time; late completion does not shift later due dates."
      endpoint="/maintenance/schedules/"
      headerActions={<Can perm="pm.manage"><Button icon="refresh" onClick={async () => {
        const r = await send<{ created: number }>("post", "/maintenance/schedules/generate/");
        toast.success(r.created ? `${r.created} work order(s) generated` : "No new work orders were due for generation");
      }}>Generate due work orders</Button></Can>}
      filters={[{ name: "task_type", label: "Type", type: "select", options: [{ value: "PREVENTIVE", label: "Preventive" }, { value: "INSPECTION", label: "Inspection" }] },
        { name: "is_active", label: "Active", type: "boolean" }]}
      columns={[
        { key: "asset", header: "Asset", render: (s) => s.asset_tag },
        { key: "title", header: "Task" },
        { key: "type", header: "Type", render: (s) => humanize(s.task_type) },
        { key: "interval", header: "Interval", align: "right", render: (s) => `${s.interval_days} d` },
        { key: "next", header: "Next due", render: (s) => fmtDate(s.next_due_date) },
        { key: "last", header: "Last completed", render: (s) => fmtDateTime(s.last_completed_at) },
        { key: "open", header: "Open WOs", align: "right", render: (s) => s.open_work_orders },
        { key: "tech", header: "Default technician", render: (s) => s.technician_name ?? "—" },
        { key: "active", header: "Status", render: (s) => <StatusBadge status={s.is_active ? "ACTIVE" : "INACTIVE"} /> },
      ]}
      form={{
        perm: "pm.manage", noun: "schedule", initial: { task_type: "PREVENTIVE", lead_days: 7, reminder_days: 3, priority: "MEDIUM", is_active: true },
        fields: [
          { name: "asset", label: "Asset", type: "select", options: assets, required: true, readOnlyOnEdit: true },
          { name: "title", label: "Task title", required: true },
          { name: "task_type", label: "Type", type: "select", options: [{ value: "PREVENTIVE", label: "Preventive" }, { value: "INSPECTION", label: "Inspection" }] },
          { name: "interval_days", label: "Interval (days)", type: "number", required: true, readOnlyOnEdit: true },
          { name: "start_date", label: "First due date", type: "date", required: true, readOnlyOnEdit: true },
          { name: "lead_days", label: "Generate work order (days before due)", type: "number" },
          { name: "reminder_days", label: "Upcoming reminder (days before due)", type: "number" },
          { name: "estimated_hours", label: "Estimated hours", type: "number", step: "0.5" },
          { name: "default_technician", label: "Default technician", type: "select", options: techs },
          { name: "priority", label: "Priority", type: "select", options: ["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((p) => ({ value: p, label: humanize(p) })) },
          { name: "is_active", label: "Active", type: "checkbox", hint: "Generate work orders" },
          { name: "description", label: "Instructions", type: "textarea" },
        ],
      }} />
  );
}
