import { Link } from "react-router-dom";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { StatusBadge } from "@/components/ui";
import { fmtDate, fmtMoney } from "@/lib/format";

interface PO { id: number; po_number: string; supplier_name: string; pr_number: string | null; status: string; status_label: string; order_date: string | null;
  expected_delivery_date: string | null; order_total: string; received_value: string; purchase_request: number | null }

export default function PurchaseOrdersPage() {
  const suppliers = useOptions("/inventory/suppliers/", (s) => String(s.name));
  return (
    <ResourcePage<PO> title="Purchase orders" subtitle="Orders are created from approved purchase requests" endpoint="/inventory/purchase-orders/" defaultOrdering="-created_at"
      filters={[{ name: "open", label: "Open", type: "boolean" }, { name: "supplier", label: "Supplier", type: "select", options: suppliers },
        { name: "status", label: "Status", type: "select", options: ["DRAFT", "ISSUED", "PARTIALLY_RECEIVED", "RECEIVED", "CLOSED", "CANCELLED"].map((s) => ({ value: s, label: s.replace("_", " ").toLowerCase() })) }]}
      columns={[
        { key: "po", header: "Order", render: (o) => <Link className="link font-medium" to={`/procurement/orders/${o.id}`}>{o.po_number}</Link> },
        { key: "supplier", header: "Supplier", render: (o) => o.supplier_name },
        { key: "status", header: "Status", render: (o) => <StatusBadge status={o.status} label={o.status_label} /> },
        { key: "pr", header: "Request", render: (o) => o.purchase_request ? <Link className="link" to={`/procurement/requests/${o.purchase_request}`}>{o.pr_number}</Link> : "—" },
        { key: "ordered", header: "Order date", sortKey: "order_date", render: (o) => fmtDate(o.order_date) },
        { key: "expected", header: "Expected", sortKey: "expected_delivery_date", render: (o) => fmtDate(o.expected_delivery_date) },
        { key: "total", header: "Order value", align: "right", render: (o) => fmtMoney(o.order_total) },
        { key: "received", header: "Received value", align: "right", render: (o) => fmtMoney(o.received_value) },
      ]} />
  );
}
