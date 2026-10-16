import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { newIdempotencyKey, send } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Alert, Button, Card, DescriptionList, ErrorState, Field, Input, Loading, Modal, PageHeader, ReasonDialog, StatusBadge, useToast } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate, fmtDateTime, fmtMoney, fmtNumber } from "@/lib/format";

interface PO {
  id: number; po_number: string; supplier_name: string; purchase_request: number | null; pr_number: string | null; status: string; status_label: string;
  order_date: string | null; expected_delivery_date: string | null; currency: string; notes: string; created_by_name: string; fully_received_at: string | null;
  closed_at: string | null; close_reason: string; order_total: string; received_value: string;
  lines: { id: number; item: number; item_code: string; item_name: string; uom: string; quantity_ordered: string; unit_price: string; quantity_received: string; outstanding: string; line_total: string }[];
  receipts: { id: number; receipt_number: string; received_at: string; received_by_name: string; delivery_note: string; lines: { item_code: string; quantity: string }[] }[];
}

export default function PurchaseOrderDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const toast = useToast();
  const { data: po, error, reload, setData } = useApi<PO>(`/inventory/purchase-orders/${id}/`);
  const [dialog, setDialog] = useState<"" | "receive" | "close" | "cancel">("");
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!po) return <Loading />;
  const act = async (path: string, body: object, msg: string) => { setData(await send<PO>("post", `/inventory/purchase-orders/${po.id}/${path}/`, body)); toast.success(msg); };
  const receivable = ["ISSUED", "PARTIALLY_RECEIVED"].includes(po.status);
  return (
    <div>
      <PageHeader title={`Purchase order ${po.po_number}`} subtitle={<span className="flex items-center gap-2"><StatusBadge status={po.status} label={po.status_label} />{po.supplier_name}</span>}
        actions={<>
          {po.status === "DRAFT" && can("procurement.order") && <Button variant="primary" onClick={() => act("issue", {}, "Order issued to supplier").catch((e) => toast.error(e.message))}>Issue to supplier</Button>}
          {receivable && can("stock.receive") && <Button variant="primary" icon="box" onClick={() => setDialog("receive")}>Receive goods</Button>}
          {["RECEIVED", "PARTIALLY_RECEIVED"].includes(po.status) && can("procurement.order") && <Button onClick={() => setDialog("close")}>Close order</Button>}
          {["DRAFT", "ISSUED"].includes(po.status) && po.receipts.length === 0 && can("procurement.order") && <Button variant="ghost" onClick={() => setDialog("cancel")}>Cancel order</Button>}
        </>} />
      {po.close_reason && <div className="mb-3"><Alert tone="info" title={po.status === "CANCELLED" ? "Cancelled" : "Closed"}>{po.close_reason}</Alert></div>}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card title="Order lines" subtitle={`Order value ${fmtMoney(po.order_total)} · received ${fmtMoney(po.received_value)}`} bodyClass="p-0">
            <table className="w-full text-sm"><thead className="border-b border-border bg-raised"><tr><th className="th">Item</th><th className="th text-right">Ordered</th>
              <th className="th text-right">Received</th><th className="th text-right">Outstanding</th><th className="th text-right">Unit price</th><th className="th text-right">Line total</th></tr></thead>
              <tbody>{po.lines.map((l) => (
                <tr key={l.id} className="border-b border-border last:border-0"><td className="td"><Link className="link" to={`/inventory/items/${l.item}`}>{l.item_code}</Link> {l.item_name}</td>
                  <td className="td text-right tabular">{fmtNumber(l.quantity_ordered, 3)} {l.uom}</td><td className="td text-right tabular">{fmtNumber(l.quantity_received, 3)}</td>
                  <td className="td text-right tabular">{fmtNumber(l.outstanding, 3)}</td><td className="td text-right tabular">{fmtMoney(l.unit_price)}</td>
                  <td className="td text-right tabular">{fmtMoney(l.line_total)}</td></tr>))}</tbody></table>
          </Card>
          <Card title="Goods receipts" bodyClass="p-0">
            <table className="w-full text-sm"><tbody>
              {po.receipts.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0"><td className="td font-medium">{r.receipt_number}</td><td className="td">{fmtDateTime(r.received_at)}</td>
                  <td className="td">{r.lines.map((l) => `${l.item_code} × ${Number(l.quantity)}`).join(", ")}</td><td className="td">{r.delivery_note || "—"}</td>
                  <td className="td">{r.received_by_name}</td></tr>))}
              {!po.receipts.length && <tr><td className="td text-muted">Nothing received yet.</td></tr>}
            </tbody></table>
          </Card>
        </div>
        <Card title="Order details">
          <DescriptionList items={[["Supplier", po.supplier_name], ["Request", po.purchase_request ? <Link className="link" to={`/procurement/requests/${po.purchase_request}`}>{po.pr_number}</Link> : "—"],
            ["Order date", fmtDate(po.order_date)], ["Expected delivery", fmtDate(po.expected_delivery_date)], ["Fully received", fmtDateTime(po.fully_received_at)],
            ["Closed", fmtDateTime(po.closed_at)], ["Currency", po.currency], ["Created by", po.created_by_name]]} />
        </Card>
      </div>
      <ReceiveDialog open={dialog === "receive"} po={po} onClose={() => setDialog("")} onDone={(u) => { setData(u); }} />
      <ReasonDialog open={dialog === "close"} title="Close purchase order" label="Reason (required if not fully received)" required={po.status === "PARTIALLY_RECEIVED"}
        confirmLabel="Close order" onClose={() => setDialog("")} onConfirm={(r) => act("close", { reason: r }, "Order closed")} />
      <ReasonDialog open={dialog === "cancel"} title="Cancel purchase order" label="Reason" confirmLabel="Cancel order" tone="danger"
        onClose={() => setDialog("")} onConfirm={(r) => act("cancel", { reason: r }, "Order cancelled")} />
    </div>
  );
}

function ReceiveDialog({ open, po, onClose, onDone }: { open: boolean; po: PO; onClose: () => void; onDone: (p: PO) => void }) {
  const toast = useToast();
  const [qty, setQty] = useState<Record<number, string>>({});
  const [note, setNote] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const res = await send<PO & { receipt: { receipt_number: string; duplicate: boolean } }>("post", `/inventory/purchase-orders/${po.id}/receive/`,
        { idempotency_key: key, delivery_note: note, lines: Object.entries(qty).filter(([, q]) => q && Number(q) > 0).map(([l, q]) => ({ order_line: Number(l), quantity: q })) });
      toast.success(res.receipt.duplicate ? `This delivery was already recorded as ${res.receipt.receipt_number}` : `Receipt ${res.receipt.receipt_number} posted to stock`);
      setKey(newIdempotencyKey()); setQty({}); setNote("");
      onDone(res); onClose();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Receive goods" size="lg"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Post receipt</Button></>}>
      {err && <div className="mb-3"><Alert tone="bad">{err}</Alert></div>}
      <p className="mb-3 text-xs text-muted">Received quantities are added to stock at the order price. Re-submitting the same delivery is detected and not posted twice.</p>
      <table className="mb-3 w-full text-sm"><thead><tr><th className="th">Item</th><th className="th text-right">Outstanding</th><th className="th">Received now</th></tr></thead>
        <tbody>{po.lines.filter((l) => Number(l.outstanding) > 0).map((l) => (
          <tr key={l.id}><td className="td">{l.item_code} {l.item_name}</td><td className="td text-right tabular">{fmtNumber(l.outstanding, 3)} {l.uom}</td>
            <td className="td"><Input aria-label={`Quantity received for ${l.item_code}`} type="number" min="0" max={l.outstanding} step="any" className="w-28"
              value={qty[l.id] ?? ""} onChange={(e) => setQty({ ...qty, [l.id]: e.target.value })} />
              <button className="ml-2 text-xs link" onClick={() => setQty({ ...qty, [l.id]: String(Number(l.outstanding)) })}>All</button></td></tr>))}</tbody></table>
      <Field label="Delivery note" htmlFor="dn"><Input id="dn" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </Modal>
  );
}
