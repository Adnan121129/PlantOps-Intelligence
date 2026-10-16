import { exportUrl } from "@/api/client";
import { DataTable, Pagination } from "@/components/data";
import { PeriodFilter, presetRange } from "@/components/PeriodFilter";
import { Card, Icon, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { fmtDate, fmtDateTime, fmtMoney, fmtNumber } from "@/lib/format";

interface ReportMeta { code: string; title: string; description: string }
interface ReportData { report: ReportMeta; generated_at: string; count: number; columns: { key: string; label: string; kind: string }[]; results: Record<string, unknown>[] }

function cell(v: unknown, kind: string) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (kind === "money") return fmtMoney(v as number);
  if (kind === "number") return fmtNumber(v as number, 2);
  if (kind === "date") return fmtDate(String(v));
  return String(v);
}

export default function ReportCenterPage() {
  const reports = useApi<ReportMeta[]>("/analytics/reports/");
  const [state, update] = useUrlState({ ...presetRange("30"), unit: "", report: "", page: "1" });
  const current = state.report || reports.data?.[0]?.code || "";
  const params = { date_from: state.date_from, date_to: state.date_to, unit: state.unit };
  const data = useApi<ReportData>(current ? `/analytics/reports/${current}/` : null, { ...params, page: state.page, page_size: 50 });
  return (
    <div>
      <PageHeader title="Report center" subtitle="Operational and management reports from the same calculations as the dashboards. Exports include generation metadata." />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[16rem_1fr]">
        <Card title="Reports" bodyClass="p-1">
          <nav aria-label="Reports"><ul>{reports.data?.map((r) => (
            <li key={r.code}><button onClick={() => update({ report: r.code })} aria-current={current === r.code ? "page" : undefined}
              className={`w-full rounded px-3 py-1.5 text-left text-sm ${current === r.code ? "bg-accent-soft font-medium text-accent" : "hover:bg-sunken"}`}>{r.title}</button></li>))}</ul></nav>
        </Card>
        <div className="min-w-0">
          <PeriodFilter value={state} onChange={(p) => update(p)}>
            <div className="flex gap-2">
              {(["csv", "xlsx"] as const).map((f) => (
                <a key={f} href={exportUrl(`/analytics/reports/${current}/`, { ...params, export: f })}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium hover:bg-sunken">
                  <Icon name="download" /> {f.toUpperCase()}</a>))}
            </div>
          </PeriodFilter>
          <Card title={data.data?.report.title ?? "Report"} subtitle={data.data ? `${data.data.report.description} · ${data.data.count} rows · generated ${fmtDateTime(data.data.generated_at)}` : undefined} bodyClass="p-0">
            <DataTable rows={data.data?.results} loading={data.loading} error={data.error} onRetry={data.reload} rowKey={(r) => JSON.stringify(r).slice(0, 200)} dense
              caption={data.data?.report.title}
              columns={(data.data?.columns ?? []).map((c) => ({ key: c.key, header: c.label, align: c.kind === "number" || c.kind === "money" ? "right" as const : undefined,
                render: (r: Record<string, unknown>) => cell(r[c.key], c.kind) }))} />
            {data.data && <Pagination count={data.data.count} page={Number(state.page)} pageSize={50} onPage={(p) => update({ page: String(p) }, { resetPage: false })} />}
          </Card>
        </div>
      </div>
    </div>
  );
}
