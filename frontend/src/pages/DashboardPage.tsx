import { useNavigate } from "react-router-dom";
import { exportUrl } from "@/api/client";
import type { Kpi, PeriodInfo } from "@/api/types";
import { ChartCard, ColumnChart, KpiCard, RankedBars, TrendChart } from "@/components/charts";
import { PeriodFilter, presetRange } from "@/components/PeriodFilter";
import { Card, ErrorState, Icon, PageHeader, Select, Skeleton, StatusBadge } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { fmtDate, fmtDateTime, fmtHours, fmtMoney, fmtNumber, fmtRelative, humanize } from "@/lib/format";
import { CHART } from "@/theme/ThemeContext";

interface Dashboard {
  period: PeriodInfo;
  scope: { unit: number | null; unit_code: string | null; plant_name: string | null };
  granularity: string;
  currency: string;
  output_metric: { id: number; name: string; unit: string } | null;
  kpis: Kpi[];
  charts: {
    downtime_trend: { bucket: string; unplanned_failure: number; planned_maintenance: number; external: number; operational: number; total: number }[];
    failures_by_category: { category_id: number; category: string; failures: number; hours: number }[];
    top_downtime_assets: { asset_id: number; asset_tag: string; name: string; hours: number; events: number }[];
    maintenance_mix: { totals: Record<string, number>; planned_pct: number | null; monthly: { month: string; corrective: number; preventive: number; inspection: number }[] };
    work_order_status: { status: string; label: string; count: number }[];
    stock_status: { status: string; count: number }[];
    reorder_watchlist: { item_id: number; item_code: string; name: string; stock: number; min: number; coverage_pct: number; status: string; uom: string }[];
    output_trend: { date: string; value: number | null; target: number | null; reports: number }[];
    output_by_shift: { shift_id: number; shift: string; total: number; per_report: number; reports: number }[];
    incidents_by_shift: { shift: string; incidents: number }[];
    maintenance_cost_by_month?: { month: string; actual: number; budget: number | null; variance: number | null }[];
    cost_by_department?: { department_id: number | null; department: string; total: number }[];
  };
  freshness: Record<string, string | null>;
  restricted: string[];
}

const short = (iso: string) => fmtDate(iso).replace(/ \d{4}$/, "");
const monthLabel = (iso: string) => new Date(`${iso.slice(0, 7)}-15T00:00:00Z`).toLocaleString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });

export default function DashboardPage() {
  const navigate = useNavigate();
  const [state, update] = useUrlState({ ...presetRange("30"), unit: "", granularity: "day" });
  const { data, error, loading, reload } = useApi<Dashboard>("/analytics/dashboard/", state);
  const unitQ = state.unit ? `&unit=${state.unit}` : "";
  const range = `date_from=${state.date_from}&date_to=${state.date_to}`;

  return (
    <div>
      <PageHeader title="Executive dashboard"
        subtitle={data ? `${fmtDate(data.period.date_from)} – ${fmtDate(data.period.date_to)} · ${data.scope.unit_code ?? data.scope.plant_name ?? "All units"}` : "Plant performance overview"}
        actions={
          <a className="inline-flex h-8 items-center gap-2 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium hover:bg-sunken"
            href={exportUrl("/analytics/reports/executive_kpi_summary/", { ...state, export: "xlsx" })}>
            <Icon name="download" /> Export KPI summary
          </a>
        } />
      <PeriodFilter value={state} onChange={(p) => update(p)}>
        <label className="flex flex-col gap-1 text-xs text-ink-2">
          <span>Trend granularity</span>
          <Select className="w-32" value={state.granularity} onChange={(e) => update({ granularity: e.target.value })}>
            <option value="day">Daily</option><option value="week">Weekly</option><option value="month">Monthly</option>
          </Select>
        </label>
      </PeriodFilter>

      {error ? <Card><ErrorState error={error} onRetry={reload} /></Card> : !data ? <DashboardSkeleton /> : (
        <div className={loading ? "opacity-70 transition-opacity" : ""} aria-busy={loading}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">
            {data.kpis.map((k) => <KpiCard key={k.code} kpi={k} currency={data.currency} />)}
          </div>
          {data.restricted.includes("costs") && (
            <p className="mt-2 text-xs text-muted">Cost KPIs are not shown for your role.</p>
          )}

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <ChartCard title="Downtime trend" subtitle={`Equipment-hours per ${data.granularity}, by downtime type · click a column to open events`}
              rows={data.charts.downtime_trend.filter((r) => r.total > 0)}
              columns={[{ key: "bucket", label: "Period", format: (v) => fmtDate(String(v)) },
                { key: "unplanned_failure", label: "Unplanned", align: "right", format: (v) => fmtNumber(Number(v), 1) },
                { key: "planned_maintenance", label: "Planned", align: "right", format: (v) => fmtNumber(Number(v), 1) },
                { key: "external", label: "External", align: "right", format: (v) => fmtNumber(Number(v), 1) },
                { key: "total", label: "Total h", align: "right", format: (v) => fmtNumber(Number(v), 1) }]}>
              <ColumnChart data={data.charts.downtime_trend} x="bucket" xFormat={data.granularity === "month" ? monthLabel : short}
                valueFormat={(v) => fmtHours(v)}
                series={[{ key: "unplanned_failure", label: "Unplanned failure" }, { key: "planned_maintenance", label: "Planned maintenance" },
                  { key: "external", label: "External" }, { key: "operational", label: "Operational" }]}
                onSelect={(r) => navigate(`/maintenance/downtime?date_from=${r.bucket}&date_to=${endOfBucket(r.bucket, data.granularity)}${unitQ}`)} />
            </ChartCard>

            <ChartCard title={data.output_metric ? `${data.output_metric.name} vs target` : "Operational performance"}
              subtitle={data.output_metric ? `Approved shift reports, ${data.output_metric.unit} per day. Gaps = no approved data.` : "No primary output metric configured"}
              rows={data.charts.output_trend.filter((r) => r.value !== null)}
              columns={[{ key: "date", label: "Date", format: (v) => fmtDate(String(v)) },
                { key: "value", label: "Actual", align: "right", format: (v) => fmtNumber(v as number, 0) },
                { key: "target", label: "Target", align: "right", format: (v) => fmtNumber(v as number, 0) },
                { key: "reports", label: "Reports", align: "right" }]}>
              <TrendChart data={data.charts.output_trend} x="date" xFormat={short}
                series={[{ key: "value", label: `Actual (${data.output_metric?.unit ?? ""})` }]}
                target={{ key: "target", label: "Target" }} valueFormat={(v) => fmtNumber(v, 0)} />
            </ChartCard>

            {data.charts.maintenance_cost_by_month && (
              <ChartCard title="Maintenance expenditure by month" subtitle="Actual cost-ledger entries vs prorated maintenance budget · click to open entries"
                rows={data.charts.maintenance_cost_by_month}
                columns={[{ key: "month", label: "Month", format: (v) => monthLabel(String(v)) },
                  { key: "actual", label: "Actual", align: "right", format: (v) => fmtMoney(v as number) },
                  { key: "budget", label: "Budget", align: "right", format: (v) => fmtMoney(v as number) },
                  { key: "variance", label: "Variance", align: "right", format: (v) => fmtMoney(v as number) }]}>
                <ColumnChart data={data.charts.maintenance_cost_by_month} x="month" xFormat={monthLabel} stacked={false}
                  valueFormat={(v) => fmtMoney(v)} series={[{ key: "actual", label: "Actual" }, { key: "budget", label: "Budget" }]}
                  onSelect={(r) => navigate(`/costs/expenses?maintenance=true&date_from=${r.month}&date_to=${endOfBucket(r.month, "month")}${unitQ}`)} />
              </ChartCard>
            )}

            <ChartCard title="Top equipment by downtime" subtitle="Hours in period · click a bar to open the asset"
              rows={data.charts.top_downtime_assets}
              columns={[{ key: "asset_tag", label: "Asset" }, { key: "name", label: "Name" },
                { key: "hours", label: "Hours", align: "right", format: (v) => fmtNumber(Number(v), 1) },
                { key: "events", label: "Events", align: "right" }]}>
              <RankedBars data={data.charts.top_downtime_assets} label="asset_tag" value="hours" valueFormat={(v) => fmtHours(v)}
                onSelect={(r) => navigate(`/assets/${r.asset_id}`)} />
            </ChartCard>

            <ChartCard title="Equipment failures by category" subtitle="Unplanned failures started in the period · click to open events"
              rows={data.charts.failures_by_category}
              columns={[{ key: "category", label: "Category" }, { key: "failures", label: "Failures", align: "right" },
                { key: "hours", label: "Downtime h", align: "right", format: (v) => fmtNumber(Number(v), 1) }]}>
              <RankedBars data={data.charts.failures_by_category} label="category" value="failures" valueFormat={(v) => fmtNumber(v, 0)}
                onSelect={(r) => navigate(`/maintenance/downtime?category=${r.category_id}&downtime_type=UNPLANNED_FAILURE&${range}${unitQ}`)} />
            </ChartCard>

            <ChartCard title="Preventive vs corrective maintenance"
              subtitle={`Work orders reported per month · planned share ${data.charts.maintenance_mix.planned_pct ?? "—"}%`}
              rows={data.charts.maintenance_mix.monthly}
              columns={[{ key: "month", label: "Month", format: (v) => monthLabel(String(v)) },
                { key: "corrective", label: "Corrective", align: "right" }, { key: "preventive", label: "Preventive", align: "right" },
                { key: "inspection", label: "Inspection", align: "right" }]}>
              <ColumnChart data={data.charts.maintenance_mix.monthly} x="month" xFormat={monthLabel} valueFormat={(v) => fmtNumber(v, 0)}
                series={[{ key: "corrective", label: "Corrective" }, { key: "preventive", label: "Preventive" }, { key: "inspection", label: "Inspection" }]}
                onSelect={(r) => navigate(`/maintenance/work-orders?reported_from=${r.month}&reported_to=${endOfBucket(r.month, "month")}${unitQ}`)} />
            </ChartCard>

            <ChartCard title="Work-order status" subtitle="Work orders reported in the period, by current status · click to filter"
              rows={data.charts.work_order_status}
              columns={[{ key: "label", label: "Status" }, { key: "count", label: "Work orders", align: "right" }]}>
              <RankedBars data={data.charts.work_order_status} label="label" value="count" valueFormat={(v) => fmtNumber(v, 0)}
                onSelect={(r) => navigate(`/maintenance/work-orders?status=${r.status}&reported_from=${state.date_from}&reported_to=${state.date_to}${unitQ}`)} />
            </ChartCard>

            <ChartCard title="Inventory stock & reorder status" subtitle="Active items by stock status (current) · click to filter"
              rows={data.charts.stock_status}
              columns={[{ key: "status", label: "Status", format: (v) => <StatusBadge status={String(v)} /> },
                { key: "count", label: "Items", align: "right" }]}>
              <RankedBars data={data.charts.stock_status.map((r) => ({ ...r, label: humanize(r.status) }))} label="label" value="count"
                valueFormat={(v) => fmtNumber(v, 0)}
                colorFor={(r) => ({ OK: CHART.status.good, LOW: CHART.status.warning, CRITICAL_LOW: CHART.status.serious, OUT_OF_STOCK: CHART.status.critical } as Record<string, string>)[r.status]}
                onSelect={(r) => navigate(`/inventory/items?stock_status=${r.status}`)} />
            </ChartCard>

            <ChartCard title="Shift comparison" subtitle={data.output_metric ? `Average ${data.output_metric.name.toLowerCase()} per approved report, by shift` : "Output per shift"}
              rows={data.charts.output_by_shift}
              columns={[{ key: "shift", label: "Shift" }, { key: "per_report", label: "Per report", align: "right", format: (v) => fmtNumber(Number(v), 0) },
                { key: "total", label: "Total", align: "right", format: (v) => fmtNumber(Number(v), 0) }, { key: "reports", label: "Reports", align: "right" }]}>
              <RankedBars data={data.charts.output_by_shift} label="shift" value="per_report" valueFormat={(v) => fmtNumber(v, 0)} />
            </ChartCard>

            {data.charts.cost_by_department && (
              <ChartCard title="Departmental cost comparison" subtitle="Actual costs in the period by department"
                rows={data.charts.cost_by_department}
                columns={[{ key: "department", label: "Department" }, { key: "total", label: "Actual", align: "right", format: (v) => fmtMoney(v as number) }]}>
                <RankedBars data={data.charts.cost_by_department} label="department" value="total" valueFormat={(v) => fmtMoney(v, { compact: true })}
                  onSelect={(r) => r.department_id && navigate(`/costs/expenses?department=${r.department_id}&${range}`)} />
              </ChartCard>
            )}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card title="Reorder watchlist" subtitle="Lowest stock cover against reorder point" className="xl:col-span-2" bodyClass="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-border bg-raised"><tr>
                    <th className="th">Item</th><th className="th">Status</th><th className="th text-right">Stock</th>
                    <th className="th text-right">Reorder point</th><th className="th text-right">Cover</th></tr></thead>
                  <tbody>
                    {data.charts.reorder_watchlist.map((r) => (
                      <tr key={r.item_id} className="border-b border-border last:border-0">
                        <td className="td"><a className="link" href={`/inventory/items/${r.item_id}`}
                          onClick={(e) => { e.preventDefault(); navigate(`/inventory/items/${r.item_id}`); }}>{r.item_code}</a>
                          <span className="ml-2 text-muted">{r.name}</span></td>
                        <td className="td"><StatusBadge status={r.status} /></td>
                        <td className="td text-right tabular">{fmtNumber(r.stock, 1)} {r.uom}</td>
                        <td className="td text-right tabular">{fmtNumber(r.min, 1)}</td>
                        <td className="td text-right tabular">{fmtNumber(r.coverage_pct, 0)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Data freshness" subtitle="Latest record times feeding this dashboard">
              <dl className="space-y-1.5 text-sm">
                {Object.entries(data.freshness).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3">
                    <dt className="text-muted">{humanize(k.replace(/_at$/, ""))}</dt>
                    <dd className="text-right tabular" title={v ? fmtDateTime(v) : undefined}>{k === "generated_at" ? fmtDateTime(v) : fmtRelative(v)}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function endOfBucket(start: string, granularity: string): string {
  const d = new Date(`${start}T00:00:00Z`);
  if (granularity === "week") d.setUTCDate(d.getUTCDate() + 6);
  else if (granularity === "month") { d.setUTCMonth(d.getUTCMonth() + 1); d.setUTCDate(0); }
  return d.toISOString().slice(0, 10);
}

function DashboardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading dashboard">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">
        {Array.from({ length: 12 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-72" />)}
      </div>
    </div>
  );
}
