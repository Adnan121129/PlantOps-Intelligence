import { useNavigate } from "react-router-dom";
import type { Kpi } from "@/api/types";
import { ChartCard, ColumnChart, KpiCard, RankedBars } from "@/components/charts";
import { PeriodFilter, presetRange } from "@/components/PeriodFilter";
import { ErrorState, Loading, PageHeader, Select } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDate, fmtHours, fmtNumber } from "@/lib/format";

interface MA {
  kpis: Kpi[];
  downtime_trend: { bucket: string; unplanned_failure: number; planned_maintenance: number; external: number; operational: number; total: number }[];
  top_downtime_assets: { asset_id: number; asset_tag: string; name: string; hours: number; events: number }[];
  failures_by_category: { category_id: number; category: string; failures: number; hours: number }[];
  repeat_failure_assets: { asset_id: number; asset_tag: string; name: string; repeats: number }[];
}

export default function MaintenanceAnalyticsPage() {
  const navigate = useNavigate();
  const { currency } = useReference();
  const [state, update] = useUrlState({ ...presetRange("90"), unit: "", granularity: "week" });
  const { data, error, reload } = useApi<MA>("/analytics/maintenance/", state);
  return (
    <div>
      <PageHeader title="Maintenance analytics" subtitle="Reliability, compliance and work-order performance. Metrics without sufficient records are shown as insufficient data." />
      <PeriodFilter value={state} onChange={(p) => update(p)}>
        <label className="flex flex-col gap-1 text-xs text-ink-2"><span>Granularity</span>
          <Select className="w-32" value={state.granularity} onChange={(e) => update({ granularity: e.target.value })}>
            <option value="day">Daily</option><option value="week">Weekly</option><option value="month">Monthly</option>
          </Select></label>
      </PeriodFilter>
      {error ? <ErrorState error={error} onRetry={reload} /> : !data ? <Loading /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">{data.kpis.map((k) => <KpiCard key={k.code} kpi={k} currency={currency} compact />)}</div>
          <ChartCard title="Downtime by type" subtitle={`Equipment-hours per ${state.granularity}`} rows={data.downtime_trend.filter((r) => r.total > 0)} height={260}
            columns={[{ key: "bucket", label: "Period", format: (v) => fmtDate(String(v)) }, { key: "total", label: "Hours", align: "right", format: (v) => fmtNumber(Number(v), 1) }]}>
            <ColumnChart data={data.downtime_trend} x="bucket" xFormat={(d) => fmtDate(d).slice(0, 6)} valueFormat={fmtHours}
              series={[{ key: "unplanned_failure", label: "Unplanned failure" }, { key: "planned_maintenance", label: "Planned" }, { key: "external", label: "External" }, { key: "operational", label: "Operational" }]} />
          </ChartCard>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <ChartCard title="Top assets by downtime" rows={data.top_downtime_assets} height={320}
              columns={[{ key: "asset_tag", label: "Asset" }, { key: "hours", label: "Hours", align: "right", format: (v) => fmtNumber(Number(v), 1) }, { key: "events", label: "Events", align: "right" }]}>
              <RankedBars data={data.top_downtime_assets} label="asset_tag" value="hours" valueFormat={fmtHours} onSelect={(r) => navigate(`/assets/${r.asset_id}`)} />
            </ChartCard>
            <ChartCard title="Failures by equipment category" rows={data.failures_by_category} height={320}
              columns={[{ key: "category", label: "Category" }, { key: "failures", label: "Failures", align: "right" }, { key: "hours", label: "Hours", align: "right" }]}>
              <RankedBars data={data.failures_by_category} label="category" value="failures" valueFormat={(v) => fmtNumber(v, 0)} />
            </ChartCard>
            <ChartCard title="Repeat-failure assets" subtitle="Failures within the repeat window of the previous failure" rows={data.repeat_failure_assets} height={320}
              columns={[{ key: "asset_tag", label: "Asset" }, { key: "name", label: "Name" }, { key: "repeats", label: "Repeats", align: "right" }]}
              empty="No repeat failures in this period.">
              <RankedBars data={data.repeat_failure_assets} label="asset_tag" value="repeats" valueFormat={(v) => fmtNumber(v, 0)} onSelect={(r) => navigate(`/assets/${r.asset_id}`)} />
            </ChartCard>
          </div>
        </div>
      )}
    </div>
  );
}
