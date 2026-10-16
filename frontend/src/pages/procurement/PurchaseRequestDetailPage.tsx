import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { send } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { ApprovalHistory, type Approval } from "@/components/ApprovalHistory";
import { ResourceFormDialog, useOptions } from "@/components/data";
import { Alert, Button, Card, DescriptionList, ErrorState, Loading, PageHeader, ReasonDialog, StatusBadge, useToast } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate, fmtDateTime, fmtMoney, fmtNumber } from "@/lib/format";
import { PurchaseRequestDialog } from "./shared";

interface PR {
  id: number; pr_number: string; status: string; status_label: string; requested_by: number; requested_by_name: string; department: number | null;
  department_name: string | null; justification: string; needed_by: string | null; submitted_at: string | null; decided_by_name: string | null;
  decided_at: string | null; decision_comment: string; estimated_total: string; purchase_order: { id: number; po_number: string; status: string } | null;
  lines: { id: number; item: number; item_code: string; item_name: string; uom: string; quantity: string; estimated_unit_cost: string | null; note: string }[];
  approvals: Approval[];
}

export default function PurchaseRequestDetailPage() {
  const { id } = useParams();
  const { user, can } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const { data: pr, error, reload, setData } = useApi<PR>(`/inventory/purchase-requests/${id}/`);
  const suppliers = useOptions("/inventory/suppliers/", (s) => String(s.name), { is_active: true });
  const [dialog, setDialog] = useState<"" | "edit" | "approve" | "reject" | "convert" | "cancel">("");
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!pr) return <Loading />;
  const mine = pr.requested_by === user?.id;
  const act = async (path: string, body: object, msg: string) => { setData(await send<PR>("post", `/inventory/purchase-requests/${pr.id}/${path}/`, body)); toast.success(msg); };
  const editable = mine && ["DRAFT", "REJECTED"].includes(pr.status) && can("procurement.request");

  return (
    <div>
      <PageHeader title={`Purchase request ${pr.pr_number}`} subtitle={<StatusBadge status={pr.status} label={pr.status_label} />}
        actions={<>
          {editable && <Button onClick={() => setDialog("edit")}>Edit</Button>}
          {editable && <Button variant="primary" onClick={() => act("submit", {}, "Submitted for approval").catch((e) => toast.error(e.message))}>Submit for approval</Button>}
          {mine && ["DRAFT", "SUBMITTED", "REJECTED"].includes(pr.status) && <Button variant="ghost" onClick={() => setDialog("cancel")}>Cancel request</Button>}
          {pr.status === "SUBMITTED" && can("procurement.approve") && !mine && <>
            <Button variant="danger" onClick={() => setDialog("reject")}>Reject</Button>
            <Button variant="primary" icon="check" onClick={() => setDialog("approve")}>Approve</Button></>}
          {pr.status === "APPROVED" && can("procurement.order") && <Button variant="primary" onClick={() => setDialog("convert")}>Create purchase order</Button>}
        </>} />
      {pr.status === "SUBMITTED" && mine && <div className="mb-3"><Alert tone="info">Awaiting approval by management. You cannot approve your own request.</Alert></div>}
      {pr.status === "REJECTED" && <div className="mb-3"><Alert tone="bad" title="Rejected">{pr.decision_comment}</Alert></div>}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card title="Request">
            <p className="mb-3 text-sm">{pr.justification}</p>
            <DescriptionList cols={3} items={[["Requested by", pr.requested_by_name], ["Department", pr.department_name ?? "—"], ["Needed by", fmtDate(pr.needed_by)],
              ["Submitted", fmtDateTime(pr.submitted_at)], ["Decision", pr.decided_by_name ? `${pr.decided_by_name}, ${fmtDateTime(pr.decided_at)}` : "—"],
              ["Purchase order", pr.purchase_order ? <Link className="link" to={`/procurement/orders/${pr.purchase_order.id}`}>{pr.purchase_order.po_number}</Link> : "—"]]} />
          </Card>
          <Card title="Lines" subtitle={`Estimated total ${fmtMoney(pr.estimated_total)}`} bodyClass="p-0">
            <table className="w-full text-sm"><thead className="border-b border-border bg-raised"><tr><th className="th">Item</th>
              <th className="th text-right">Quantity</th><th className="th text-right">Est. unit cost</th><th className="th text-right">Est. value</th></tr></thead>
              <tbody>{pr.lines.map((l) => (
                <tr key={l.id} className="border-b border-border last:border-0"><td className="td"><Link className="link" to={`/inventory/items/${l.item}`}>{l.item_code}</Link> {l.item_name}</td>
                  <td className="td text-right tabular">{fmtNumber(l.quantity, 3)} {l.uom}</td><td className="td text-right tabular">{fmtMoney(l.estimated_unit_cost)}</td>
                  <td className="td text-right tabular">{l.estimated_unit_cost ? fmtMoney(Number(l.estimated_unit_cost) * Number(l.quantity)) : "—"}</td></tr>))}</tbody></table>
          </Card>
        </div>
        <ApprovalHistory records={pr.approvals} />
      </div>
      <PurchaseRequestDialog open={dialog === "edit"} onClose={() => { setDialog(""); reload(); }} existing={pr} />
      <ReasonDialog open={dialog === "approve"} title="Approve purchase request" label="Comment" required={false} confirmLabel="Approve"
        onClose={() => setDialog("")} onConfirm={(c) => act("decide", { decision: "approve", comment: c }, "Request approved")} />
      <ReasonDialog open={dialog === "reject"} title="Reject purchase request" label="Reason" confirmLabel="Reject" tone="danger"
        onClose={() => setDialog("")} onConfirm={(c) => act("decide", { decision: "reject", comment: c }, "Request rejected")} />
      <ReasonDialog open={dialog === "cancel"} title="Cancel purchase request" label="Reason" required={false} confirmLabel="Cancel request" tone="danger"
        onClose={() => setDialog("")} onConfirm={() => act("cancel", {}, "Request cancelled")} />
      <ResourceFormDialog open={dialog === "convert"} onClose={() => setDialog("")} title="Create purchase order" endpoint={`/inventory/purchase-requests/${pr.id}/convert/`}
        fields={[{ name: "supplier", label: "Supplier", type: "select", options: suppliers, required: true },
          { name: "expected_delivery_date", label: "Expected delivery", type: "date" }]}
        onSaved={(po) => { toast.success("Purchase order created (draft)"); navigate(`/procurement/orders/${(po as { id: number }).id}`); }} />
    </div>
  );
}
