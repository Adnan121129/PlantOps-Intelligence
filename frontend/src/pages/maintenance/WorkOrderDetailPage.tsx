import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { newIdempotencyKey, send, type ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { ApprovalHistory, type Approval } from "@/components/ApprovalHistory";
import { Attachments } from "@/components/Attachments";
import { FormGrid, ResourceFormDialog, toFormValues, useOptions, type FormField } from "@/components/data";
import { RecordDowntimeDialog } from "@/components/RecordDowntimeDialog";
import {
  Alert, Badge, Button, Card, DescriptionList, ErrorState, Field, Input, Loading, Modal, PageHeader, PriorityBadge, ReasonDialog,
  Select, StatusBadge, useToast,
} from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate, fmtDateTime, fmtHours, fmtMoney, humanize, localInputToIso, nowLocalInput } from "@/lib/format";

interface WorkOrder {
  id: number; number: string; asset: number; asset_tag: string; asset_name: string; plant_unit_code: string; maintenance_type: string;
  maintenance_type_label: string; title: string; description: string; priority: string; status: string; status_label: string;
  is_overdue: boolean; is_blocked: boolean; blocked_reason: string; assigned_technician: number | null; technician_name: string | null;
  assigned_team: string; due_date: string | null; planned_start: string | null; planned_end: string | null; reported_at: string;
  reported_by_name: string; actual_start: string | null; actual_end: string | null; failure_code: string; root_cause: string;
  actions_performed: string; completion_notes: string; labor_hours: string | null; requires_verification: boolean;
  completed_by_name: string | null; verified_by_name: string | null; verified_at: string | null; verification_comment: string;
  cancelled_reason: string; cancelled_by_name: string | null; incident: number | null; incident_number: string | null; schedule: number | null;
  downtime_hours: number;
  downtime_events: { id: number; downtime_type_label: string; started_at: string; ended_at: string | null; duration_hours: number | null; cause: string; is_ongoing: boolean }[];
  parts: { id: number; txn_number: string; txn_type: string; item: number; item_code: string; item_name: string; uom: string; quantity: string; value: string; occurred_at: string }[];
  costs: { parts: number; labor: number; other: number; total: number };
  expenses: { id: number; expense_date: string; category: string; amount: string; description: string; source: string }[] | null;
  inspections: { id: number; inspected_at: string; result: string; findings: string; readings: string; inspector_name: string }[];
  approvals: Approval[];
  capabilities: Record<"edit" | "assign" | "start" | "complete" | "verify" | "cancel" | "block" | "add_cost" | "issue_parts" | "return_parts" | "record_downtime", boolean>;
}

const LIFECYCLE = ["REPORTED", "ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION", "COMPLETED"];
const FAILURE_CODES = ["MECHANICAL", "ELECTRICAL", "INSTRUMENTATION", "LUBRICATION", "CORROSION", "OPERATIONAL", "EXTERNAL", "UNKNOWN"]
  .map((v) => ({ value: v, label: v === "UNKNOWN" ? "Not established" : humanize(v) }));

type DialogName = "" | "assign" | "start" | "complete" | "verify" | "return" | "cancel" | "block" | "cost" | "issue" | "returnPart" | "downtime" | "edit" | "closeDowntime";

export default function WorkOrderDetailPage() {
  const { id } = useParams();
  const { data: wo, error, reload, setData } = useApi<WorkOrder>(`/maintenance/work-orders/${id}/`);
  const { can } = useAuth();
  const toast = useToast();
  const [dialog, setDialog] = useState<DialogName>("");
  const [closingEvent, setClosingEvent] = useState<number | null>(null);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!wo) return <Loading />;
  const c = wo.capabilities;
  const act = async (path: string, body: object, msg: string) => {
    const updated = await send<WorkOrder>("post", `/maintenance/work-orders/${wo.id}/${path}/`, body);
    setData(updated);
    toast.success(msg);
  };
  const close = () => setDialog("");
  const stepIndex = LIFECYCLE.indexOf(wo.status);

  return (
    <div>
      <PageHeader title={`${wo.number} · ${wo.title}`}
        subtitle={<span className="flex flex-wrap items-center gap-2">
          <StatusBadge status={wo.status} label={wo.status_label} /><PriorityBadge priority={wo.priority} />
          {wo.is_overdue && <Badge tone="bad">Overdue</Badge>}
          {wo.is_blocked && <Badge tone="warn" icon="pause">Blocked: {wo.blocked_reason}</Badge>}
          <span>{wo.maintenance_type_label} · <Link className="link" to={`/assets/${wo.asset}`}>{wo.asset_tag}</Link> {wo.asset_name}</span>
        </span>}
        actions={<>
          {c.edit && <Button size="sm" variant="ghost" onClick={() => setDialog("edit")}>Edit details</Button>}
          {c.block && <Button size="sm" variant="ghost" onClick={() => (wo.is_blocked ? act("block", { blocked: false }, "Block removed") : setDialog("block"))}>
            {wo.is_blocked ? "Unblock" : "Mark blocked"}</Button>}
          {c.cancel && <Button size="sm" variant="ghost" onClick={() => setDialog("cancel")}>Cancel WO</Button>}
          {c.assign && <Button onClick={() => setDialog("assign")}>{wo.status === "REPORTED" ? "Assign" : "Reassign"}</Button>}
          {c.start && <Button variant="primary" onClick={() => setDialog("start")}>Start work</Button>}
          {c.complete && <Button variant="primary" icon="check" onClick={() => setDialog("complete")}>Complete</Button>}
          {c.verify && <>
            <Button variant="danger" onClick={() => setDialog("return")}>Return for rework</Button>
            <Button variant="primary" icon="check" onClick={() => setDialog("verify")}>Verify</Button>
          </>}
        </>} />

      {wo.status !== "CANCELLED" ? (
        <ol className="mb-4 flex flex-wrap gap-1" aria-label="Lifecycle">
          {LIFECYCLE.map((s, i) => (
            <li key={s} aria-current={i === stepIndex ? "step" : undefined}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs ${i < stepIndex ? "border-good/40 bg-good-soft text-good"
                : i === stepIndex ? "border-accent bg-accent-soft font-medium text-accent" : "border-border text-muted"}`}>
              {i < stepIndex ? "✓" : i + 1} {humanize(s)}
            </li>
          ))}
        </ol>
      ) : <div className="mb-4"><Alert tone="warn" title={`Cancelled by ${wo.cancelled_by_name ?? "—"}`}>{wo.cancelled_reason}</Alert></div>}
      {wo.verification_comment && wo.status === "IN_PROGRESS" && (
        <div className="mb-3"><Alert tone="bad" title="Returned for rework">{wo.verification_comment}</Alert></div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card title="Work details">
            <p className="mb-3 whitespace-pre-line text-sm">{wo.description}</p>
            <DescriptionList cols={3} items={[
              ["Reported", `${fmtDateTime(wo.reported_at)} by ${wo.reported_by_name}`],
              ["Assigned to", wo.technician_name ?? (wo.assigned_team || "Unassigned")], ["Team", wo.assigned_team || "—"],
              ["Due date", fmtDate(wo.due_date)], ["Planned start", fmtDateTime(wo.planned_start)], ["Planned completion", fmtDateTime(wo.planned_end)],
              ["Actual start", fmtDateTime(wo.actual_start)], ["Actual completion", fmtDateTime(wo.actual_end)],
              ["Labour hours", wo.labor_hours ?? "—"],
              ["Failure code", wo.failure_code ? humanize(wo.failure_code) : "—"], ["Root cause", wo.root_cause || "—"],
              ["Verification", wo.requires_verification ? (wo.verified_by_name ? `${wo.verified_by_name}, ${fmtDateTime(wo.verified_at)}` : "Required") : "Not required"],
              ["Source incident", wo.incident ? <Link className="link" to={`/operations/incidents?search=${wo.incident_number}`}>{wo.incident_number}</Link> : "—"],
            ]} />
            {wo.actions_performed && <div className="mt-3 border-t border-border pt-3"><p className="text-xs text-muted">Actions performed</p>
              <p className="whitespace-pre-line text-sm">{wo.actions_performed}</p>
              {wo.completion_notes && <p className="mt-1 text-sm text-ink-2">{wo.completion_notes}</p>}</div>}
          </Card>

          <Card title="Downtime" subtitle={`Total ${fmtHours(wo.downtime_hours)} from linked events (the only source of downtime for this work order)`}
            actions={c.record_downtime && <Button size="sm" icon="plus" onClick={() => setDialog("downtime")}>Record downtime</Button>} bodyClass="p-0">
            <table className="w-full text-sm"><tbody>
              {wo.downtime_events.map((d) => (
                <tr key={d.id} className="border-b border-border last:border-0">
                  <td className="td">{d.downtime_type_label}</td><td className="td">{fmtDateTime(d.started_at)} → {d.ended_at ? fmtDateTime(d.ended_at) : <Badge tone="bad">Ongoing</Badge>}</td>
                  <td className="td text-right tabular">{fmtHours(d.duration_hours)}</td><td className="td">{d.cause}</td>
                  <td className="td text-right">{d.is_ongoing && can("downtime.record") &&
                    <Button size="sm" onClick={() => { setClosingEvent(d.id); setDialog("closeDowntime"); }}>Return to service</Button>}</td>
                </tr>
              ))}
              {!wo.downtime_events.length && <tr><td className="td text-muted">No downtime linked to this work order.</td></tr>}
            </tbody></table>
          </Card>

          <Card title="Spare parts" subtitle="Issued from the stock ledger; parts cost is posted automatically"
            actions={<>
              {c.return_parts && wo.parts.length > 0 && <Button size="sm" onClick={() => setDialog("returnPart")}>Return part</Button>}
              {c.issue_parts && <Button size="sm" icon="plus" onClick={() => setDialog("issue")}>Issue part</Button>}
            </>} bodyClass="p-0">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-raised"><tr><th className="th">Txn</th><th className="th">Item</th>
                <th className="th">Type</th><th className="th text-right">Qty</th><th className="th text-right">Value</th><th className="th">Date</th></tr></thead>
              <tbody>
                {wo.parts.map((p) => (
                  <tr key={p.id} className="border-b border-border last:border-0">
                    <td className="td text-xs">{p.txn_number}</td>
                    <td className="td"><Link className="link" to={`/inventory/items/${p.item}`}>{p.item_code}</Link> {p.item_name}</td>
                    <td className="td"><Badge tone={p.txn_type === "ISSUE" ? "info" : "neutral"} icon={null}>{humanize(p.txn_type)}</Badge></td>
                    <td className="td text-right tabular">{p.quantity} {p.uom}</td>
                    <td className="td text-right tabular">{can("costs.view") ? fmtMoney(p.value) : "—"}</td>
                    <td className="td">{fmtDateTime(p.occurred_at)}</td>
                  </tr>
                ))}
                {!wo.parts.length && <tr><td colSpan={6} className="td text-muted">No parts issued.</td></tr>}
              </tbody>
            </table>
          </Card>

          {wo.inspections.length > 0 && (
            <Card title="Inspection findings">
              {wo.inspections.map((i) => (
                <div key={i.id} className="mb-2 flex flex-wrap gap-2 text-sm">
                  <StatusBadge status={i.result === "PASS" ? "ON_TIME" : i.result === "FAIL" ? "MISSED" : "LATE"} label={humanize(i.result)} />
                  <span>{i.findings}</span><span className="text-muted">{i.readings}</span>
                  <span className="text-xs text-muted">{i.inspector_name}, {fmtDateTime(i.inspected_at)}</span>
                </div>
              ))}
            </Card>
          )}
        </div>

        <div className="space-y-4">
          {wo.expenses !== null && (
            <Card title="Costs" subtitle="Actual entries in the cost ledger"
              actions={c.add_cost && <Button size="sm" icon="plus" onClick={() => setDialog("cost")}>Add cost</Button>}>
              <DescriptionList cols={2} items={[["Parts", fmtMoney(wo.costs.parts)], ["Labour", fmtMoney(wo.costs.labor)],
                ["Contractor / other", fmtMoney(wo.costs.other)], ["Total", <strong key="t">{fmtMoney(wo.costs.total)}</strong>]]} />
              {wo.expenses.length > 0 && (
                <ul className="mt-3 space-y-1 border-t border-border pt-2 text-xs">
                  {wo.expenses.map((e) => (
                    <li key={e.id} className="flex justify-between gap-2"><span className="truncate">{fmtDate(e.expense_date)} · {e.description}</span>
                      <span className="tabular">{fmtMoney(e.amount)}</span></li>
                  ))}
                </ul>
              )}
            </Card>
          )}
          <ApprovalHistory title="Verification history" records={wo.approvals} />
          <Attachments targetType="workorder" objectId={wo.id} canAdd={can("workorders.report") && wo.status !== "CANCELLED"} />
        </div>
      </div>

      <AssignDialog open={dialog === "assign"} onClose={close} wo={wo} onDone={(u) => { setData(u); toast.success("Work order assigned"); }} />
      <TimeDialog open={dialog === "start"} title="Start work" label="Actual start" confirm="Start" onClose={close}
        onSubmit={(t) => act("start", { actual_start: t }, "Work started")} />
      <CompleteDialog open={dialog === "complete"} onClose={close} wo={wo} onSubmit={(body) => act("complete", body, wo.requires_verification ? "Submitted for verification" : "Work order completed")} />
      <ReasonDialog open={dialog === "verify"} title="Verify completed work" label="Comment" required={false} confirmLabel="Verify & close"
        onClose={close} onConfirm={(t) => act("verify", { decision: "approve", comment: t }, "Work verified and closed")} />
      <ReasonDialog open={dialog === "return"} title="Return for rework" label="What must be reworked?" confirmLabel="Return" tone="danger"
        onClose={close} onConfirm={(t) => act("verify", { decision: "return", comment: t }, "Returned for rework")} />
      <ReasonDialog open={dialog === "cancel"} title="Cancel work order" label="Cancellation reason" confirmLabel="Cancel work order" tone="danger"
        description="Issued parts must be returned and linked downtime closed before cancelling."
        onClose={close} onConfirm={(t) => act("cancel", { reason: t }, "Work order cancelled")} />
      <ReasonDialog open={dialog === "block"} title="Mark as blocked" label="What is the work waiting for?" confirmLabel="Mark blocked"
        onClose={close} onConfirm={(t) => act("block", { blocked: true, reason: t }, "Marked as blocked")} />
      <ResourceFormDialog open={dialog === "cost"} onClose={close} title="Add cost" endpoint={`/maintenance/work-orders/${wo.id}/costs/`}
        fields={[
          { name: "category", label: "Category", type: "select", required: true, options: [
            { value: "LABOR", label: "Labour" }, { value: "CONTRACTOR", label: "Contractor" },
            { value: "EQUIPMENT_REPAIR", label: "External repair" }, { value: "OTHER", label: "Other" }] },
          { name: "amount", label: "Amount", type: "number", step: "0.01", required: true },
          { name: "expense_date", label: "Cost date", type: "date" },
          { name: "reference", label: "Invoice / reference" },
          { name: "description", label: "Description", required: true, full: true },
        ]} initial={{ category: "LABOR" }} onSaved={(u) => { setData(u as WorkOrder); toast.success("Cost recorded"); }} />
      <StockDialog open={dialog === "issue" || dialog === "returnPart"} mode={dialog === "returnPart" ? "return" : "issue"} wo={wo} onClose={close}
        onDone={(u) => { setData(u); toast.success(dialog === "returnPart" ? "Part returned to store" : "Part issued"); }} />
      <RecordDowntimeDialog open={dialog === "downtime"} onClose={close} assetId={wo.asset} workOrderId={wo.id} onSaved={reload} />
      <TimeDialog open={dialog === "closeDowntime"} title="Return equipment to service" label="Returned to service at" confirm="Close downtime"
        onClose={close} onSubmit={async (t) => {
          await send("post", `/maintenance/downtime/${closingEvent}/close/`, { ended_at: t });
          toast.success("Downtime closed"); reload();
        }} />
      <EditDialog open={dialog === "edit"} onClose={close} wo={wo} onDone={(u) => { setData(u); toast.success("Saved"); }} />
    </div>
  );
}

function TimeDialog({ open, title, label, confirm, onClose, onSubmit }: {
  open: boolean; title: string; label: string; confirm: string; onClose: () => void; onSubmit: (iso: string) => Promise<void>;
}) {
  const [value, setValue] = useState(nowLocalInput());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (open) { setValue(nowLocalInput()); setErr(null); } }, [open]);
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={async () => {
        setBusy(true); setErr(null);
        try { await onSubmit(localInputToIso(value)); onClose(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
      }}>{confirm}</Button></>}>
      {err && <div className="mb-2"><Alert tone="bad">{err}</Alert></div>}
      <Field label={label} htmlFor="t" hint="Plant local time"><Input id="t" type="datetime-local" value={value} onChange={(e) => setValue(e.target.value)} /></Field>
    </Modal>
  );
}

function AssignDialog({ open, onClose, wo, onDone }: { open: boolean; onClose: () => void; wo: WorkOrder; onDone: (w: WorkOrder) => void }) {
  const techs = useOptions(open ? "/workforce/directory/" : null, (e) => `${e.employee_code} · ${e.full_name} (${e.job_title})`);
  const fields: FormField[] = [
    { name: "assigned_technician", label: "Technician", type: "select", options: techs },
    { name: "assigned_team", label: "Team" },
    { name: "planned_start", label: "Planned start", type: "datetime" },
    { name: "planned_end", label: "Planned completion", type: "datetime" },
  ];
  return (
    <ResourceFormDialog open={open} onClose={onClose} title="Assign work order" endpoint={`/maintenance/work-orders/${wo.id}/assign/`} fields={fields}
      initial={{ assigned_technician: wo.assigned_technician ?? "", assigned_team: wo.assigned_team, planned_start: wo.planned_start, planned_end: wo.planned_end }}
      onSaved={(u) => onDone(u as WorkOrder)} />
  );
}

function CompleteDialog({ open, onClose, wo, onSubmit }: { open: boolean; onClose: () => void; wo: WorkOrder; onSubmit: (b: object) => Promise<void> }) {
  const fields: FormField[] = [
    { name: "actual_end", label: "Completed at", type: "datetime", required: true },
    { name: "labor_hours", label: "Labour hours", type: "number", step: "0.5" },
    ...(wo.maintenance_type === "CORRECTIVE" ? [{ name: "failure_code", label: "Failure classification", type: "select" as const, options: FAILURE_CODES, required: true }] : []),
    { name: "root_cause", label: "Root cause", type: "textarea" },
    { name: "actions_performed", label: "Actions performed", type: "textarea", required: true },
    { name: "completion_notes", label: "Completion notes", type: "textarea" },
  ];
  const [values, setValues] = useState(() => toFormValues(fields, { actual_end: new Date().toISOString(), failure_code: wo.failure_code, root_cause: wo.root_cause }));
  useEffect(() => {
    if (open) setValues((v) => ({ ...v, actual_end: nowLocalInput() }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const open_downtime = wo.downtime_events.some((d) => d.is_ongoing);
  return (
    <Modal open={open} onClose={onClose} title="Complete work order" size="lg"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={open_downtime} onClick={async () => {
        setBusy(true); setErrors({}); setMessage(null);
        try {
          await onSubmit({ ...values, actual_end: localInputToIso(String(values.actual_end)) });
          onClose();
        } catch (e) { const err = e as ApiError; setErrors(err.fieldErrors ?? {}); setMessage(err.message); } finally { setBusy(false); }
      }}>{wo.requires_verification ? "Submit for verification" : "Complete"}</Button></>}>
      {open_downtime && <div className="mb-3"><Alert tone="warn">Close the linked downtime event (return to service) before completing.</Alert></div>}
      {message && <div className="mb-3"><Alert tone="bad">{message}</Alert></div>}
      <FormGrid fields={fields} values={values} setValues={setValues} errors={errors} />
    </Modal>
  );
}

function StockDialog({ open, mode, wo, onClose, onDone }: { open: boolean; mode: "issue" | "return"; wo: WorkOrder; onClose: () => void; onDone: (w: WorkOrder) => void }) {
  const items = useOptions(open && mode === "issue" ? "/inventory/items/" : null,
    (i) => `${i.item_code} · ${i.name} (${Number(i.current_stock)} ${i.uom} in stock)`, { is_active: true, asset: wo.asset });
  const allItems = useOptions(open && mode === "issue" ? "/inventory/items/" : null,
    (i) => `${i.item_code} · ${i.name} (${Number(i.current_stock)} ${i.uom} in stock)`, { is_active: true });
  const issued = Array.from(new Map(wo.parts.filter((p) => p.txn_type === "ISSUE").map((p) => [p.item, { value: p.item, label: `${p.item_code} · ${p.item_name}` }])).values());
  const [item, setItem] = useState("");
  const [qty, setQty] = useState("1");
  const [notes, setNotes] = useState("");
  const [key] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const compatibleIds = new Set(items.map((i) => i.value));
  const options = mode === "return" ? issued : [...items, ...allItems.filter((i) => !compatibleIds.has(i.value))];
  return (
    <Modal open={open} onClose={onClose} title={mode === "issue" ? "Issue spare part" : "Return part to store"} size="md"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={async () => {
        setBusy(true); setErr(null);
        try {
          const updated = await send<WorkOrder>("post", `/maintenance/work-orders/${wo.id}/${mode === "issue" ? "issue-part" : "return-part"}/`,
            { item: Number(item), quantity: qty, notes, idempotency_key: key });
          onDone(updated); onClose();
        } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
      }}>{mode === "issue" ? "Issue" : "Return"}</Button></>}>
      {err && <div className="mb-2"><Alert tone="bad">{err}</Alert></div>}
      <div className="grid gap-3">
        <Field label="Item" htmlFor="si" hint={mode === "issue" ? "Compatible spares for this asset are listed first" : undefined}>
          <Select id="si" value={item} onChange={(e) => setItem(e.target.value)}>
            <option value="">Select…</option>
            {options.map((o) => <option key={o.value} value={o.value}>{o.label}{compatibleIds.has(o.value) && mode === "issue" ? " ★" : ""}</option>)}
          </Select>
        </Field>
        <Field label="Quantity" htmlFor="sq"><Input id="sq" type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Notes" htmlFor="sn"><Input id="sn" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function EditDialog({ open, onClose, wo, onDone }: { open: boolean; onClose: () => void; wo: WorkOrder; onDone: (w: WorkOrder) => void }) {
  return (
    <ResourceFormDialog open={open} onClose={onClose} title="Edit work order" endpoint="/maintenance/work-orders/" id={wo.id}
      fields={[
        { name: "title", label: "Title", required: true, full: true },
        { name: "description", label: "Description", type: "textarea", required: true },
        { name: "priority", label: "Priority", type: "select", options: ["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((p) => ({ value: p, label: humanize(p) })) },
        { name: "assigned_team", label: "Team" },
        { name: "planned_start", label: "Planned start", type: "datetime" },
        { name: "planned_end", label: "Planned completion", type: "datetime" },
        { name: "requires_verification", label: "Supervisor verification", type: "checkbox", hint: "Required before closing" },
      ]}
      initial={{ ...wo, planned_start: wo.planned_start, planned_end: wo.planned_end }} onSaved={(u) => onDone(u as WorkOrder)} />
  );
}

