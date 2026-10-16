import { useState } from "react";
import { send } from "@/api/client";
import { Can, useAuth } from "@/auth/AuthContext";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { Button, ReasonDialog, StatusBadge, useToast } from "@/components/ui";
import { fmtDate, fmtMoney, plantToday } from "@/lib/format";

interface OT { id: number; employee_name: string; employee_code: string; date: string; hours: string; rate_multiplier: string; cost: string | null;
  reason: string; work_order_number: string | null; status: string; recorded_by: number; recorded_by_name: string; decided_by_name: string | null }

export default function OvertimePage() {
  const { user } = useAuth();
  const toast = useToast();
  const employees = useOptions("/workforce/directory/", (e) => `${e.employee_code} · ${e.full_name}`);
  const [rejecting, setRejecting] = useState<{ row: OT; reload: () => void } | null>(null);
  const decide = async (row: OT, approve: boolean, reload: () => void, comment = "") => {
    try { await send("post", `/workforce/overtime/${row.id}/decide/`, { approve, comment }); toast.success(approve ? "Overtime approved and costed" : "Overtime rejected"); reload(); }
    catch (e) { toast.error((e as Error).message); }
  };
  return (
    <>
      <ResourcePage<OT> title="Overtime" subtitle="Approved overtime is costed (hours x rate x multiplier) and posted to the cost ledger as labour"
        endpoint="/workforce/overtime/" search={false}
        filters={[{ name: "status", label: "Status", type: "select", options: [{ value: "PENDING", label: "Pending" }, { value: "APPROVED", label: "Approved" }, { value: "REJECTED", label: "Rejected" }] },
          { name: "date_from", label: "From", type: "date" }, { name: "date_to", label: "To", type: "date" }]}
        columns={[{ key: "date", header: "Date", render: (o) => fmtDate(o.date) }, { key: "emp", header: "Employee", render: (o) => `${o.employee_code} · ${o.employee_name}` },
          { key: "hours", header: "Hours", align: "right" }, { key: "rate_multiplier", header: "Multiplier", align: "right" },
          { key: "cost", header: "Cost", align: "right", render: (o) => fmtMoney(o.cost) }, { key: "reason", header: "Reason" },
          { key: "wo", header: "Work order", render: (o) => o.work_order_number ?? "—" },
          { key: "status", header: "Status", render: (o) => <StatusBadge status={o.status} /> },
          { key: "by", header: "Recorded / decided", render: (o) => `${o.recorded_by_name}${o.decided_by_name ? ` / ${o.decided_by_name}` : ""}` }]}
        rowActions={(o, reload) => o.status === "PENDING" && o.recorded_by !== user?.id && (
          <Can perm="overtime.manage">
            <Button size="sm" variant="ghost" onClick={() => setRejecting({ row: o, reload })}>Reject</Button>
            <Button size="sm" variant="ghost" onClick={() => decide(o, true, reload)}>Approve</Button>
          </Can>)}
        form={{ perm: "overtime.manage", noun: "overtime record", editable: (o) => o.status === "PENDING", initial: { date: plantToday(), rate_multiplier: "1.50" }, fields: [
          { name: "employee", label: "Employee", type: "select", options: employees, required: true },
          { name: "date", label: "Date", type: "date", required: true },
          { name: "hours", label: "Hours", type: "number", step: "0.25", required: true },
          { name: "rate_multiplier", label: "Rate multiplier", type: "number", step: "0.05" },
          { name: "reason", label: "Reason", required: true, full: true },
        ] }} />
      <ReasonDialog open={!!rejecting} title="Reject overtime" label="Reason" confirmLabel="Reject" tone="danger" onClose={() => setRejecting(null)}
        onConfirm={(c) => decide(rejecting!.row, false, rejecting!.reload, c)} />
    </>
  );
}
