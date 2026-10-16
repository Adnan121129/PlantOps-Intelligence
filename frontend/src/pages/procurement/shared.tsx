import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { send, type ApiError } from "@/api/client";
import { useOptions } from "@/components/data";
import { Alert, Button, Field, Input, Modal, Select, Textarea, useToast } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";

export interface PRLine { item: string; quantity: string; estimated_unit_cost: string; note: string }

/** Create or edit a purchase request with item lines. */
export function PurchaseRequestDialog({ open, onClose, existing }: {
  open: boolean; onClose: () => void;
  existing?: { id: number; justification: string; needed_by: string | null; department: number | null; lines: { item: number; quantity: string; estimated_unit_cost: string | null; note: string }[] };
}) {
  const { departments } = useReference();
  const items = useOptions(open ? "/inventory/items/" : null, (i) => `${i.item_code} · ${i.name} (stock ${Number(i.current_stock)} / min ${Number(i.min_stock_level)} ${i.uom})`, { is_active: true });
  const navigate = useNavigate();
  const toast = useToast();
  const [justification, setJustification] = useState("");
  const [neededBy, setNeededBy] = useState("");
  const [department, setDepartment] = useState("");
  const [lines, setLines] = useState<PRLine[]>([{ item: "", quantity: "", estimated_unit_cost: "", note: "" }]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    setError(null);
    setJustification(existing?.justification ?? "");
    setNeededBy(existing?.needed_by ?? "");
    setDepartment(existing?.department ? String(existing.department) : "");
    setLines(existing?.lines.map((l) => ({ item: String(l.item), quantity: l.quantity, estimated_unit_cost: l.estimated_unit_cost ?? "", note: l.note }))
      ?? [{ item: "", quantity: "", estimated_unit_cost: "", note: "" }]);
  }, [open, existing]);
  const setLine = (i: number, patch: Partial<PRLine>) => setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const save = async () => {
    setBusy(true); setError(null);
    const body = { justification, needed_by: neededBy || null, department: department || null,
      lines: lines.filter((l) => l.item).map((l) => ({ item: Number(l.item), quantity: l.quantity, estimated_unit_cost: l.estimated_unit_cost || null, note: l.note })) };
    try {
      const pr = existing ? await send<{ id: number }>("patch", `/inventory/purchase-requests/${existing.id}/`, body)
        : await send<{ id: number }>("post", "/inventory/purchase-requests/", body);
      toast.success("Purchase request saved as draft");
      onClose();
      navigate(`/procurement/requests/${pr.id}`);
    } catch (e) { setError(e as ApiError); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title={existing ? "Edit purchase request" : "New purchase request"} size="xl"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save draft</Button></>}>
      {error && <div className="mb-3"><Alert tone="bad">{error.message}</Alert></div>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Justification" required className="sm:col-span-3" htmlFor="just" error={error?.fieldErrors.justification}>
          <Textarea id="just" value={justification} onChange={(e) => setJustification(e.target.value)} />
        </Field>
        <Field label="Needed by" htmlFor="nb" error={error?.fieldErrors.needed_by}><Input id="nb" type="date" value={neededBy} onChange={(e) => setNeededBy(e.target.value)} /></Field>
        <Field label="Department" htmlFor="dp"><Select id="dp" value={department} onChange={(e) => setDepartment(e.target.value)}>
          <option value="">—</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
      </div>
      <h3 className="mb-2 mt-4 text-sm font-semibold">Lines</h3>
      <div className="space-y-2">
        {lines.map((l, i) => (
          <div key={i} className="grid grid-cols-12 gap-2">
            <Select aria-label={`Line ${i + 1} item`} className="col-span-12 sm:col-span-6" value={l.item} onChange={(e) => setLine(i, { item: e.target.value })}>
              <option value="">Select item…</option>{items.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select>
            <Input aria-label={`Line ${i + 1} quantity`} className="col-span-4 sm:col-span-2" type="number" step="any" placeholder="Qty" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} />
            <Input aria-label={`Line ${i + 1} estimated unit cost`} className="col-span-5 sm:col-span-3" type="number" step="0.01" placeholder="Est. unit cost (optional)" value={l.estimated_unit_cost} onChange={(e) => setLine(i, { estimated_unit_cost: e.target.value })} />
            <Button className="col-span-3 sm:col-span-1" variant="ghost" aria-label={`Remove line ${i + 1}`} disabled={lines.length === 1}
              onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</Button>
          </div>
        ))}
      </div>
      {error?.fieldErrors.lines && <p className="mt-1 text-xs text-bad">{error.fieldErrors.lines.join(" ")}</p>}
      <Button size="sm" icon="plus" className="mt-2" onClick={() => setLines([...lines, { item: "", quantity: "", estimated_unit_cost: "", note: "" }])}>Add line</Button>
    </Modal>
  );
}
