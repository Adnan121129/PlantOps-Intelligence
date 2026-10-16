import { ChartCard, RankedBars, TrendChart } from "@/components/charts";
import { PeriodFilter, presetRange } from "@/components/PeriodFilter";
import { Card, ErrorState, Loading, PageHeader, Select, StatusBadge } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { fmtDate, fmtNumber, fmtPct, humanize } from "@/lib/format";

interface OpsAnalytics {
  metrics: { metric_id: number; code: string; name: string; aggregation: string; direction: string; value: number | null; unit: string;
    reports: number; missing: number; target: number | null; vs_target_pct: number | null; status: string }[];
  selected_metric: { id: number; name: string; unit: string } | null;
  trend: { date: string; value: number | null; target: number | null; reports: number }[];
  by_shift: { shift: string; total: number; per_report: number; reports: number }[];
  report_status: Record<string, number>;
  missing_reports: number;
  incidents_by_shift: { shift: string; incidents: number }[];
}

export default function OperationsAnalyticsPage() {
  const [state, update] = useUrlState({ ...presetRange("30"), unit: "", metric: "" });
  const { data, error, reload } = useApi<OpsAnalytics>("/analytics/operations/", state);
  return (
    <div>
      <PageHeader title="Operations analytics" subtitle="Approved operational data only. Missing values are excluded and counted, never zero-filled." />
      <PeriodFilter value={state} onChange={(p) => update(p)}>
        {data && (
          <label className="flex flex-col gap-1 text-xs text-ink-2">
            <span>Metric</span>
            <Select className="w-56" value={state.metric || String(data.selected_metric?.id ?? "")} onChange={(e) => update({ metric: e.target.value })}>
              {data.metrics.map((m) => <option key={m.metric_id} value={m.metric_id}>{m.name}</option>)}
            </Select>
          </label>
        )}
      </PeriodFilter>
      {error ? <ErrorState error={error} onRetry={reload} /> : !data ? <Loading /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Object.entries({ APPROVED: 0, SUBMITTED: 0, REJECTED: 0, DRAFT: 0, ...data.report_status }).map(([k, v]) => (
              <div key={k} className="card p-3"><StatusBadge status={k} /><p className="mt-1 text-xl font-semibold">{v}</p>
                <p className="text-2xs text-muted">reports in period</p></div>
            ))}
          </div>
          <Card title="Metric summary" subtitle={`${data.missing_reports} expected report(s) missing or not submitted in the period`} bodyClass="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border bg-raised"><tr>
                  <th className="th">Metric</th><th className="th">Aggregation</th><th className="th text-right">Value</th><th className="th text-right">Target</th>
                  <th className="th text-right">vs target</th><th className="th text-right">Reports</th><th className="th text-right">Missing values</th></tr></thead>
                <tbody>
                  {data.metrics.map((m) => (
                    <tr key={m.metric_id} className="border-b border-border last:border-0">
                      <td className="td">{m.name}</td><td className="td text-xs text-muted">{humanize(m.aggregation)}</td>
                      <td className="td text-right tabular">{m.value === null ? <span className="text-muted">Insufficient data</span> : `${fmtNumber(m.value, 1)} ${m.unit}`}</td>
                      <td className="td text-right tabular">{fmtNumber(m.target, 1)}</td>
                      <td className="td text-right tabular">{fmtPct(m.vs_target_pct)}</td>
                      <td className="td text-right tabular">{m.reports}</td><td className="td text-right tabular">{m.missing}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <div className="xl:col-span-2">
              <ChartCard title={`${data.selected_metric?.name ?? "Metric"} per day`} subtitle="Approved reports; gaps mean no approved data that day"
                rows={data.trend.filter((r) => r.value !== null)} height={280}
                columns={[{ key: "date", label: "Date", format: (v) => fmtDate(String(v)) },
                  { key: "value", label: "Actual", align: "right", format: (v) => fmtNumber(v as number, 1) },
                  { key: "target", label: "Target", align: "right", format: (v) => fmtNumber(v as number, 1) },
                  { key: "reports", label: "Reports", align: "right" }]}>
                <TrendChart data={data.trend} x="date" xFormat={(d) => fmtDate(d).slice(0, 6)}
                  series={[{ key: "value", label: `Actual (${data.selected_metric?.unit ?? ""})` }]} target={{ key: "target", label: "Target" }} />
              </ChartCard>
            </div>
            <ChartCard title="By shift" subtitle="Average per approved report" rows={data.by_shift} height={280}
              columns={[{ key: "shift", label: "Shift" }, { key: "per_report", label: "Per report", align: "right", format: (v) => fmtNumber(Number(v), 1) },
                { key: "reports", label: "Reports", align: "right" }]}>
              <RankedBars data={data.by_shift} label="shift" value="per_report" />
            </ChartCard>
          </div>
          <ChartCard title="Incidents by shift" subtitle="Incidents linked to shift reports in the period" rows={data.incidents_by_shift}
            columns={[{ key: "shift", label: "Shift" }, { key: "incidents", label: "Incidents", align: "right" }]} height={180}>
            <RankedBars data={data.incidents_by_shift} label="shift" value="incidents" />
          </ChartCard>
        </div>
      )}
    </div>
  );
}
