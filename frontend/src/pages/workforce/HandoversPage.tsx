import { send } from "@/api/client";
import { Can, useAuth } from "@/auth/AuthContext";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { Badge, Button, useToast } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDate, fmtDateTime, plantToday } from "@/lib/format";

interface Handover { id: number; plant_unit: number; plant_unit_code: string; shift: number; shift_name: string; date: string; summary: string;
  outstanding_issues: string; safety_notes: string; handed_over_by: number; handed_over_by_name: string; received_by_name: string | null; received_at: string | null }

export default function HandoversPage() {
  const { units } = useReference();
  const { user } = useAuth();
  const toast = useToast();
  const shifts = useOptions("/workforce/shifts/", (s) => String(s.name));
  const unitOpts = units.map((u) => ({ value: u.id, label: u.code }));
  return (
    <ResourcePage<Handover> title="Shift handovers" subtitle="Outgoing shift notes, acknowledged by the incoming shift" endpoint="/workforce/handovers/" search
      filters={[{ name: "plant_unit", label: "Unit", type: "select", options: unitOpts }, { name: "date_from", label: "From", type: "date" }, { name: "date_to", label: "To", type: "date" }]}
      columns={[
        { key: "date", header: "Date", render: (h) => fmtDate(h.date) }, { key: "shift_name", header: "Shift" }, { key: "plant_unit_code", header: "Unit" },
        { key: "summary", header: "Summary", render: (h) => <span className="line-clamp-2" title={h.summary}>{h.summary}</span> },
        { key: "issues", header: "Outstanding issues", render: (h) => h.outstanding_issues || "—" },
        { key: "safety", header: "Safety", render: (h) => h.safety_notes ? <Badge tone="warn">{h.safety_notes}</Badge> : "—" },
        { key: "by", header: "Handed over by", render: (h) => h.handed_over_by_name },
        { key: "rx", header: "Acknowledged", render: (h) => h.received_at ? `${h.received_by_name}, ${fmtDateTime(h.received_at)}` : <Badge tone="warn">Pending</Badge> },
      ]}
      rowActions={(h, reload) => !h.received_at && h.handed_over_by !== user?.id && (
        <Can perm="handovers.write"><Button size="sm" variant="ghost" onClick={async () => {
          try { await send("post", `/workforce/handovers/${h.id}/acknowledge/`); toast.success("Handover acknowledged"); reload(); } catch (e) { toast.error((e as Error).message); }
        }}>Acknowledge</Button></Can>)}
      form={{ perm: "handovers.write", noun: "handover", editable: (h) => !h.received_at && h.handed_over_by === user?.id, initial: { date: plantToday() }, fields: [
        { name: "plant_unit", label: "Unit", type: "select", options: unitOpts, required: true, readOnlyOnEdit: true },
        { name: "shift", label: "Shift", type: "select", options: shifts, required: true, readOnlyOnEdit: true },
        { name: "date", label: "Date", type: "date", required: true, readOnlyOnEdit: true },
        { name: "summary", label: "Summary", type: "textarea", required: true },
        { name: "outstanding_issues", label: "Outstanding issues", type: "textarea" },
        { name: "safety_notes", label: "Safety notes", type: "textarea" },
      ] }} />
  );
}
