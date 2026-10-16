import { Card, ErrorState, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";

interface Def { code: string; label: string; unit: string; period: string; definition: string; formula: string; source: string; notes?: string }

export default function KpiDictionaryPage() {
  const { data, error, reload } = useApi<Def[]>("/analytics/kpi-dictionary/");
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  return (
    <div>
      <PageHeader title="KPI dictionary" subtitle="The single definition used by the dashboards, reports, API and Power BI documentation" />
      <Card bodyClass="p-0">
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead className="border-b border-border bg-raised"><tr><th className="th">KPI</th><th className="th">Unit</th><th className="th">Period</th>
            <th className="th">Definition</th><th className="th">Formula</th><th className="th">Source &amp; notes</th></tr></thead>
          <tbody>{data.map((k) => (
            <tr key={k.code} id={k.code} className="border-b border-border align-top last:border-0">
              <td className="td"><p className="font-medium">{k.label}</p><p className="font-mono text-2xs text-muted">{k.code}</p></td>
              <td className="td">{k.unit}</td><td className="td">{k.period === "snapshot" ? "Current state" : "Reporting period"}</td>
              <td className="td max-w-sm">{k.definition}</td><td className="td max-w-xs font-mono text-2xs text-ink-2">{k.formula}</td>
              <td className="td max-w-xs text-xs text-ink-2"><p>{k.source}</p>{k.notes && <p className="mt-1 text-muted">{k.notes}</p>}</td></tr>))}</tbody>
        </table></div>
      </Card>
    </div>
  );
}
