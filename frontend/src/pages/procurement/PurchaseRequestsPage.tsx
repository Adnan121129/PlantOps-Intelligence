import { useState } from "react";
import { Link } from "react-router-dom";
import { Can } from "@/auth/AuthContext";
import { ResourcePage } from "@/components/ResourcePage";
import { Button, StatusBadge } from "@/components/ui";
import { fmtDate, fmtDateTime, fmtMoney } from "@/lib/format";
import { PurchaseRequestDialog } from "./shared";

interface PR { id: number; pr_number: string; status: string; status_label: string; requested_by_name: string; justification: string; needed_by: string | null;
  submitted_at: string | null; decided_by_name: string | null; estimated_total: string; lines: unknown[]; purchase_order: { id: number; po_number: string } | null }

export const PR_STATUS = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "ORDERED", "CANCELLED"].map((s) => ({ value: s, label: s === "SUBMITTED" ? "Pending approval" : s[0] + s.slice(1).toLowerCase() }));

export default function PurchaseRequestsPage() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <ResourcePage<PR> title="Purchase requests" subtitle="Purchase request → approval → purchase order → receipt → closed"
        endpoint="/inventory/purchase-requests/" defaultOrdering="-created_at"
        headerActions={<Can perm="procurement.request"><Button variant="primary" icon="plus" onClick={() => setOpen(true)}>New request</Button></Can>}
        filters={[{ name: "status", label: "Status", type: "select", options: PR_STATUS }]}
        columns={[
          { key: "pr", header: "Request", render: (r) => <Link className="link font-medium" to={`/procurement/requests/${r.id}`}>{r.pr_number}</Link> },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} label={r.status_label} /> },
          { key: "just", header: "Justification", render: (r) => <span className="line-clamp-1">{r.justification}</span> },
          { key: "lines", header: "Lines", align: "right", render: (r) => r.lines.length },
          { key: "total", header: "Est. value", align: "right", render: (r) => fmtMoney(r.estimated_total) },
          { key: "by", header: "Requested by", render: (r) => r.requested_by_name },
          { key: "needed", header: "Needed by", sortKey: "needed_by", render: (r) => fmtDate(r.needed_by) },
          { key: "submitted", header: "Submitted", render: (r) => fmtDateTime(r.submitted_at) },
          { key: "po", header: "PO", render: (r) => r.purchase_order ? <Link className="link" to={`/procurement/orders/${r.purchase_order.id}`}>{r.purchase_order.po_number}</Link> : "—" },
        ]} />
      <PurchaseRequestDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
