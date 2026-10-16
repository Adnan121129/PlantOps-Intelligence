import { Link, useNavigate } from "react-router-dom";
import type { Kpi } from "@/api/types";
import { ChartCard, ColumnChart, KpiCard, RankedBars } from "@/components/charts";
import { PeriodFilter, presetRange } from "@/components/PeriodFilter";
import { Alert, Card, ErrorState, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { fmtDate, fmtMoney, fmtPct } from "@/lib/format";

interface CA {
  currency: string; kpis: Kpi[];
  by_month: { month: string; actual: number; budget: number | null; variance: number | null }[];
  by_category: { category: string; label: string; actual: number; budget: number | null; variance: number | null; variance_pct: number | null }[];
  by_asset: { asset_id: number; asset_tag: string; name: string; total: number; work_orders: number }[];
  by_department: { department_id: number | null; department: string; total: number }[];
  by_unit: { plant_unit_id: number | null; unit: string; total: number }[];
  anomalies: { key: string; title: string; message: string; link: string }[];
}
const month = (iso: string) => fmtDate(iso).slice(3);

export default function CostAnalyticsPage() {
  const navigate = useNavigate();
  const [state, update] = useUrlState({ ...presetRange("ytd"), unit: "" });
  const { data, error, reload } = useApi<CA>("/analytics/costs/", state);
  const range = `date_from=${state.date_from}&date_to=${state.date_to}`;
  return (
    <div>
      <PageHeader title="Cost analytics" subtitle="Actual spend from the cost ledger against prorated budgets. Estimates and commitments are excluded from actuals." />
      <PeriodFilter value={state} onChange={(p) => update(p)} />
      {error ? <ErrorState error={error} onRetry={reload} /> : !data ? <Loading /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{data.kpis.map((k) => <KpiCard key={k.code} kpi={k} currency={data.currency} />)}</div>
          {data.anomalies.length > 0 && (
            <Card title="Unusual or rapidly increasing expenses" subtitle="Detected by the expense-anomaly rule (thresholds configurable under Alert rules)">
              <div className="space-y-2">{data.anomalies.map((a) => <Alert key={a.key} tone="warn" title={a.title}>{a.message} <Link className="link" to={a.link}>View</Link></Alert>)}</div>
            </Card>
          )}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <ChartCard title="Actual vs budget by month" rows={data.by_month} height={260}
              columns={[{ key: "month", label: "Month", format: (v) => month(String(v)) }, { key: "actual", label: "Actual", align: "right", format: (v) => fmtMoney(v as number) },
                { key: "budget", label: "Budget", align: "right", format: (v) => fmtMoney(v as number) }, { key: "variance", label: "Variance", align: "right", format: (v) => fmtMoney(v as number) }]}>
              <ColumnChart data={data.by_month} x="month" stacked={false} xFormat={month} valueFormat={(v) => fmtMoney(v)}
                series={[{ key: "actual", label: "Actual" }, { key: "budget", label: "Budget" }]} />
            </ChartCard>
            <ChartCard title="Cost by category" subtitle="Click a bar to open the entries" rows={data.by_category} height={260}
              columns={[{ key: "label", label: "Category" }, { key: "actual", label: "Actual", align: "right", format: (v) => fmtMoney(v as number) },
                { key: "budget", label: "Budget", align: "right", format: (v) => fmtMoney(v as number) }, { key: "variance_pct", label: "Variance %", align: "right", format: (v) => fmtPct(v as number) }]}>
              <RankedBars data={data.by_category} label="label" value="actual" valueFormat={(v) => fmtMoney(v, { compact: true })}
                onSelect={(r) => navigate(`/costs/expenses?category=${r.category}&cost_type=ACTUAL&${range}`)} />
            </ChartCard>
            <ChartCard title="Maintenance expenditure by equipment" subtitle="Top 10 assets" rows={data.by_asset} height={300}
              columns={[{ key: "asset_tag", label: "Asset" }, { key: "name", label: "Name" }, { key: "total", label: "Actual", align: "right", format: (v) => fmtMoney(v as number) },
                { key: "work_orders", label: "Work orders", align: "right" }]}>
              <RankedBars data={data.by_asset} label="asset_tag" value="total" valueFormat={(v) => fmtMoney(v, { compact: true })} onSelect={(r) => navigate(`/assets/${r.asset_id}`)} />
            </ChartCard>
            <ChartCard title="Departmental comparison" rows={data.by_department} height={300}
              columns={[{ key: "department", label: "Department" }, { key: "total", label: "Actual", align: "right", format: (v) => fmtMoney(v as number) }]}>
              <RankedBars data={data.by_department} label="department" value="total" valueFormat={(v) => fmtMoney(v, { compact: true })}
                onSelect={(r) => r.department_id && navigate(`/costs/expenses?department=${r.department_id}&${range}`)} />
            </ChartCard>
          </div>
        </div>
      )}
    </div>
  );
}
