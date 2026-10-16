import { Link } from "react-router-dom";
import type { Kpi } from "@/api/types";
import { ChartCard, ColumnChart, KpiCard } from "@/components/charts";
import { PeriodFilter, presetRange } from "@/components/PeriodFilter";
import { Card, ErrorState, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDate, fmtDateTime, fmtMoney, fmtNumber, fmtPct } from "@/lib/format";

interface IA {
  kpis: Kpi[];
  consumption_by_month: { month: string; value: number }[];
  slow_moving: { item_id: number; item_code: string; name: string; stock: number; value: number; last_issue_at: string | null; uom: string }[];
  slow_moving_days: number;
  suppliers: { supplier_id: number; supplier: string; orders: number; avg_days: number; on_time_pct: number | null; quoted: number | null }[];
}

export default function InventoryAnalyticsPage() {
  const { currency } = useReference();
  const [state, update] = useUrlState({ ...presetRange("90"), unit: "" });
  const { data, error, reload } = useApi<IA>("/analytics/inventory/", state);
  return (
    <div>
      <PageHeader title="Inventory analytics" subtitle="Valuation at weighted-average cost. Inventory is shared across units, so no unit filter applies." />
      <PeriodFilter value={state} onChange={(p) => update(p)} showUnit={false} />
      {error ? <ErrorState error={error} onRetry={reload} /> : !data ? <Loading /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">{data.kpis.map((k) => <KpiCard key={k.code} kpi={k} currency={currency} compact />)}</div>
          <ChartCard title="Consumption by month" subtitle="Net value issued (issues minus returns)" rows={data.consumption_by_month} height={240}
            columns={[{ key: "month", label: "Month", format: (v) => fmtDate(String(v)) }, { key: "value", label: "Value", align: "right", format: (v) => fmtMoney(v as number) }]}>
            <ColumnChart data={data.consumption_by_month} x="month" series={[{ key: "value", label: "Net issued value" }]} valueFormat={(v) => fmtMoney(v)}
              xFormat={(m) => fmtDate(m).slice(3)} />
          </ChartCard>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Slow-moving stock" subtitle={`Stock on hand with no issue in the last ${data.slow_moving_days} days, by value`} bodyClass="p-0">
              <table className="w-full text-sm"><thead className="border-b border-border bg-raised"><tr><th className="th">Item</th>
                <th className="th text-right">Stock</th><th className="th text-right">Value</th><th className="th">Last issue</th></tr></thead>
                <tbody>{data.slow_moving.slice(0, 15).map((r) => (
                  <tr key={r.item_id} className="border-b border-border last:border-0"><td className="td"><Link className="link" to={`/inventory/items/${r.item_id}`}>{r.item_code}</Link> {r.name}</td>
                    <td className="td text-right tabular">{fmtNumber(r.stock, 1)} {r.uom}</td><td className="td text-right tabular">{fmtMoney(r.value)}</td>
                    <td className="td">{r.last_issue_at ? fmtDateTime(r.last_issue_at) : "Never issued"}</td></tr>))}
                {!data.slow_moving.length && <tr><td className="td text-muted" colSpan={4}>No slow-moving items.</td></tr>}</tbody></table>
            </Card>
            <Card title="Supplier lead time" subtitle="Orders fully received in the period: order date to final receipt" bodyClass="p-0">
              <table className="w-full text-sm"><thead className="border-b border-border bg-raised"><tr><th className="th">Supplier</th>
                <th className="th text-right">Orders</th><th className="th text-right">Avg days</th><th className="th text-right">Quoted</th><th className="th text-right">On time</th></tr></thead>
                <tbody>{data.suppliers.map((s) => (
                  <tr key={s.supplier_id} className="border-b border-border last:border-0"><td className="td">{s.supplier}</td><td className="td text-right tabular">{s.orders}</td>
                    <td className="td text-right tabular">{fmtNumber(s.avg_days, 1)}</td><td className="td text-right tabular">{s.quoted ?? "—"}</td>
                    <td className="td text-right tabular">{fmtPct(s.on_time_pct, 0)}</td></tr>))}
                {!data.suppliers.length && <tr><td className="td text-muted" colSpan={5}>No orders were fully received in this period.</td></tr>}</tbody></table>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
