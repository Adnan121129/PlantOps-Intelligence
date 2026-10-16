import { useState } from "react";
import { Link } from "react-router-dom";
import { exportUrl, newIdempotencyKey, send, type ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { FormGrid, toFormValues, useOptions, type FormField } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { Alert, Badge, Button, Modal, useToast } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDateTime, fmtMoney, fmtNumber, humanize, localInputToIso } from "@/lib/format";

interface Txn {
  id: number; txn_number: string; item: number; item_code: string; item_name: string; uom: string; txn_type: string; quantity: string; unit_cost: string;
  total_value: string; balance_after: string; occurred_at: string; reference: string; work_order: number | null; work_order_number: string | null;
  department_name: string | null; recorded_by_name: string; notes: string;
}

const TYPES = [["RECEIPT", "stock.receive", "Receipt (non-PO)"], ["ISSUE", "stock.issue", "Issue"], ["RETURN", "stock.return", "Return to store"],
  ["ADJUSTMENT", "stock.adjust", "Adjustment"]] as const;

export default function TransactionsPage() {
  const { can } = useAuth();
  const items = useOptions("/inventory/items/", (i) => `${i.item_code} · ${i.name}`);
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState(0);
  const allowed = TYPES.filter(([, perm]) => can(perm));
  return (
    <>
      <ResourcePage<Txn> key={key} title="Stock ledger" subtitle="Immutable record of every stock movement. Corrections are made with adjustments."
        endpoint="/inventory/transactions/" defaultOrdering="-occurred_at" pageSize={50}
        headerActions={<>
          <a className="inline-flex h-8 items-center rounded-md border border-border-strong bg-surface px-3 text-sm font-medium hover:bg-sunken"
            href={exportUrl("/analytics/reports/stock_movements/", { export: "csv" })}>Export CSV</a>
          {allowed.length > 0 && <Button variant="primary" icon="plus" onClick={() => setOpen(true)}>Record movement</Button>}
        </>}
        filters={[{ name: "item", label: "Item", type: "select", options: items },
          { name: "txn_type", label: "Type", type: "select", options: TYPES.map(([v, , l]) => ({ value: v, label: l })) },
          { name: "date_from", label: "From", type: "date" }, { name: "date_to", label: "To", type: "date" }]}
        columns={[
          { key: "txn_number", header: "Txn", sortKey: "txn_number" },
          { key: "occurred_at", header: "Date", sortKey: "occurred_at", render: (t) => fmtDateTime(t.occurred_at) },
          { key: "item", header: "Item", render: (t) => <Link className="link" to={`/inventory/items/${t.item}`}>{t.item_code}</Link> },
          { key: "type", header: "Type", render: (t) => <Badge icon={null} tone={Number(t.quantity) > 0 ? "good" : "info"}>{humanize(t.txn_type)}</Badge> },
          { key: "qty", header: "Quantity", align: "right", render: (t) => `${Number(t.quantity) > 0 ? "+" : ""}${fmtNumber(t.quantity, 3)} ${t.uom}` },
          { key: "value", header: "Value", align: "right", render: (t) => fmtMoney(t.total_value) },
          { key: "bal", header: "Balance", align: "right", render: (t) => fmtNumber(t.balance_after, 3) },
          { key: "ref", header: "Reference", render: (t) => t.work_order ? <Link className="link" to={`/maintenance/work-orders/${t.work_order}`}>{t.work_order_number}</Link> : t.department_name ?? (t.reference || "—") },
          { key: "by", header: "Recorded by", render: (t) => t.recorded_by_name },
        ]} />
      <MovementDialog open={open} onClose={() => setOpen(false)} types={allowed.map(([v, , l]) => ({ value: v, label: l }))} onDone={() => setKey((k) => k + 1)} />
    </>
  );
}

function MovementDialog({ open, onClose, types, onDone }: { open: boolean; onClose: () => void; types: { value: string; label: string }[]; onDone: () => void }) {
  const { departments } = useReference();
  const toast = useToast();
  const items = useOptions(open ? "/inventory/items/" : null, (i) => `${i.item_code} · ${i.name} (${Number(i.current_stock)} ${i.uom})`, { is_active: true });
  const wos = useOptions(open ? "/maintenance/work-orders/" : null, (w) => `${w.number} · ${w.asset_tag}`, { open: true });
  const fields: FormField[] = [
    { name: "txn_type", label: "Movement type", type: "select", options: types, required: true },
    { name: "item", label: "Item", type: "select", options: items, required: true },
    { name: "quantity", label: "Quantity", type: "number", step: "any", required: true,
      hint: "Adjustments: positive to add, negative to remove" },
    { name: "unit_cost", label: "Unit cost", type: "number", step: "0.0001", showIf: (v) => v.txn_type === "RECEIPT", required: true },
    { name: "work_order", label: "Work order", type: "select", options: wos, showIf: (v) => v.txn_type === "ISSUE" || v.txn_type === "RETURN" },
    { name: "department", label: "Department (if no work order)", type: "select", options: departments.map((d) => ({ value: d.id, label: d.name })),
      showIf: (v) => v.txn_type === "ISSUE" || v.txn_type === "RETURN" },
    { name: "reference", label: "Reference document", showIf: (v) => v.txn_type === "RECEIPT" || v.txn_type === "ADJUSTMENT", required: false },
    { name: "notes", label: "Notes / reason", type: "textarea", hint: "A reason is required for adjustments" },
  ];
  const [values, setValues] = useState(() => toFormValues(fields, { txn_type: types[0]?.value }));
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const submit = async () => {
    setBusy(true); setErrors({}); setMessage(null);
    try {
      const body: Record<string, unknown> = { ...values, idempotency_key: key };
      for (const k of Object.keys(body)) if (body[k] === "") body[k] = null;
      if (body.occurred_at) body.occurred_at = localInputToIso(String(body.occurred_at));
      const res = await send<{ txn_number: string; duplicate: boolean }>("post", "/inventory/transactions/", body);
      toast.success(res.duplicate ? `Already recorded as ${res.txn_number}` : `Recorded ${res.txn_number}`);
      setKey(newIdempotencyKey());
      setValues(toFormValues(fields, { txn_type: values.txn_type }));
      onDone(); onClose();
    } catch (e) { const err = e as ApiError; setErrors(err.fieldErrors ?? {}); setMessage(err.message); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Record stock movement" size="lg"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Post movement</Button></>}>
      {message && <div className="mb-3"><Alert tone="bad">{message}</Alert></div>}
      <p className="mb-3 text-xs text-muted">Movements are posted atomically; stock may not go negative. Purchase-order deliveries are received from the purchase order.</p>
      <FormGrid fields={fields} values={values} setValues={setValues} errors={errors} />
    </Modal>
  );
}
