import { Link } from "react-router-dom";
import { PeriodFilter, presetRange } from "@/components/PeriodFilter";
import { Alert, Badge, Card, EmptyState, ErrorState, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { fmtNumber } from "@/lib/format";

interface Insight { id: string; area: string; severity: "critical" | "attention" | "info"; title: string; observation: string;
  evidence: { label: string; value: number | null; unit: string }[]; hypothesis: string | null; recommendation: string | null; link: string }

export default function InsightsPage() {
  const [state, update] = useUrlState({ ...presetRange("30"), unit: "" });
  const { data, error, reload } = useApi<{ engine: string; insights: Insight[] }>("/analytics/insights/", state);
  return (
    <div>
      <PageHeader title="Management insights" subtitle="Rule-based summaries computed from validated KPIs. Observations are facts; hypotheses and recommendations are labelled." />
      <PeriodFilter value={state} onChange={(p) => update(p)} />
      <div className="mb-3"><Alert tone="info">No external AI service is used. Each statement is derived from the same calculations as the dashboard for the selected period and scope.</Alert></div>
      {error ? <ErrorState error={error} onRetry={reload} /> : !data ? <Loading /> : data.insights.length === 0 ? (
        <EmptyState title="Nothing requires attention" message="No insight rules were triggered for this period." icon="bulb" />
      ) : (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          {data.insights.map((i) => (
            <Card key={i.id} title={<span className="flex items-center gap-2">{i.title}</span>}
              actions={<><Badge tone="neutral" icon={null}>{i.area}</Badge>
                <Badge tone={i.severity === "critical" ? "bad" : i.severity === "attention" ? "warn" : "info"}>{i.severity}</Badge></>}>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Observed</p>
              <p className="mb-2 text-sm">{i.observation}</p>
              {i.evidence.length > 0 && (
                <dl className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  {i.evidence.map((e) => <div key={e.label}><dt className="inline text-muted">{e.label}: </dt>
                    <dd className="inline tabular">{e.value === null ? "—" : fmtNumber(e.value, 2)} {e.unit !== "currency" ? e.unit : ""}</dd></div>)}
                </dl>
              )}
              {i.hypothesis && <><p className="text-xs font-semibold uppercase tracking-wide text-muted">Possible explanation (hypothesis)</p><p className="mb-2 text-sm italic text-ink-2">{i.hypothesis}</p></>}
              {i.recommendation && <><p className="text-xs font-semibold uppercase tracking-wide text-muted">Recommendation</p><p className="mb-2 text-sm">{i.recommendation}</p></>}
              <Link className="text-xs link" to={i.link}>View supporting records</Link>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
