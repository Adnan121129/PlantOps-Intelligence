import { Link, useParams } from "react-router-dom";
import { Badge, Card, DescriptionList, ErrorState, LinkButton, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDateTime, fmtMoney, fmtNumber, humanize } from "@/lib/format";
import type { Item } from "./ItemListPage";

interface Insight {
  on_order: string; issued_last_365d: string; avg_monthly_usage: string; months_of_cover: string | null;
  recent: { id: number; txn_number: string; txn_type: string; quantity: string; balance_after: string; occurred_at: string; work_order: number | null; work_order_number: string | null; department_name: string | null; reference: string; recorded_by_name: string; total_value: string }[];
  compatible_assets: { id: number; asset_tag: string; name: string }[];
}

export default function ItemDetailPage() {
  const { id } = useParams();
  const item = useApi<Item>(`/inventory/items/${id}/`);
  const insight = useApi<Insight>(`/inventory/items/${id}/insight/`);
  if (item.error) return <ErrorState error={item.error} onRetry={item.reload} />;
  if (!item.data) return <Loading />;
  const i = item.data;
  const s = insight.data;
  return (
    <div>
      <PageHeader title={`${i.item_code} · ${i.name}`}
        subtitle={<span className="flex items-center gap-2"><StatusBadge status={i.stock_status} />{i.criticality === "CRITICAL" && <Badge tone="accent" icon="flag">Critical spare</Badge>}{i.category_name}</span>}
        actions={<LinkButton to={`/inventory/transactions?item=${i.id}`}>Full ledger</LinkButton>} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {[["Stock on hand", `${fmtNumber(i.current_stock, 3)} ${i.uom}`], ["Reorder point", `${fmtNumber(i.min_stock_level, 3)} ${i.uom}`],
          ["On order", s ? `${fmtNumber(s.on_order, 3)} ${i.uom}` : "—"], ["Avg monthly usage", s ? `${fmtNumber(s.avg_monthly_usage, 2)} ${i.uom}` : "—"],
          ["Months of cover", s?.months_of_cover ?? "No usage"], ["Stock value", fmtMoney(i.stock_value)]].map(([k, v]) => (
          <div key={k} className="card p-3"><p className="text-xs text-ink-2">{k}</p><p className="mt-1 text-lg font-semibold">{v}</p></div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Recent movements" className="xl:col-span-2" bodyClass="p-0">
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead className="border-b border-border bg-raised"><tr><th className="th">Txn</th><th className="th">Date</th><th className="th">Type</th>
              <th className="th text-right">Qty</th><th className="th text-right">Balance</th><th className="th">Reference</th></tr></thead>
            <tbody>{s?.recent.map((t) => (
              <tr key={t.id} className="border-b border-border last:border-0">
                <td className="td text-xs">{t.txn_number}</td><td className="td">{fmtDateTime(t.occurred_at)}</td>
                <td className="td"><Badge icon={null} tone={Number(t.quantity) > 0 ? "good" : "info"}>{humanize(t.txn_type)}</Badge></td>
                <td className="td text-right tabular">{Number(t.quantity) > 0 ? "+" : ""}{fmtNumber(t.quantity, 3)}</td>
                <td className="td text-right tabular">{fmtNumber(t.balance_after, 3)}</td>
                <td className="td">{t.work_order ? <Link className="link" to={`/maintenance/work-orders/${t.work_order}`}>{t.work_order_number}</Link> : t.department_name ?? t.reference ?? "—"}</td>
              </tr>))}</tbody>
          </table></div>
        </Card>
        <Card title="Item details">
          <DescriptionList items={[["Unit cost (weighted avg.)", fmtMoney(i.unit_cost)], ["Reorder quantity", `${fmtNumber(i.reorder_quantity, 3)} ${i.uom}`],
            ["Preferred supplier", i.supplier_name ?? "—"], ["Location", i.storage_location || "—"], ["Last movement", fmtDateTime(i.last_movement_at)],
            ["Issued (365 days)", s ? `${fmtNumber(s.issued_last_365d, 3)} ${i.uom}` : "—"],
            ["Compatible assets", s?.compatible_assets.length ? s.compatible_assets.map((a) => <Link key={a.id} className="link mr-2" to={`/assets/${a.id}`}>{a.asset_tag}</Link>) : "—"],
            ["Notes", i.compatibility_notes || i.description || "—"]]} />
        </Card>
      </div>
    </div>
  );
}
