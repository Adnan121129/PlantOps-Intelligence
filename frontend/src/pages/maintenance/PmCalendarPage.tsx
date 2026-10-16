import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, ErrorState, Loading, PageHeader, Select } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { useReference } from "@/lib/ReferenceContext";
import { plantToday } from "@/lib/format";

interface Entry { date: string; kind: "work_order" | "projected"; work_order_id?: number; number?: string; title: string; asset_tag: string; status: string; overdue: boolean; technician: string | null }

const iso = (d: Date) => d.toISOString().slice(0, 10);

export default function PmCalendarPage() {
  const { units } = useReference();
  const [state, update] = useUrlState({ month: plantToday().slice(0, 7), unit: "" });
  const first = new Date(`${state.month}-01T00:00:00Z`);
  const gridStart = new Date(first); gridStart.setUTCDate(1 - ((first.getUTCDay() + 6) % 7));
  const gridEnd = new Date(gridStart); gridEnd.setUTCDate(gridStart.getUTCDate() + 41);
  const { data, error, loading, reload } = useApi<{ entries: Entry[] }>("/maintenance/schedules/calendar/",
    { start: iso(gridStart), end: iso(gridEnd), unit: state.unit });
  const byDay = useMemo(() => {
    const m = new Map<string, Entry[]>();
    data?.entries.forEach((e) => m.set(e.date, [...(m.get(e.date) ?? []), e]));
    return m;
  }, [data]);
  const shift = (months: number) => {
    const d = new Date(first); d.setUTCMonth(d.getUTCMonth() + months);
    update({ month: iso(d).slice(0, 7) });
  };
  const today = plantToday();
  const days = Array.from({ length: 42 }, (_, i) => { const d = new Date(gridStart); d.setUTCDate(d.getUTCDate() + i); return iso(d); });
  const label = first.toLocaleString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });

  return (
    <div>
      <PageHeader title="Preventive maintenance calendar" subtitle="Generated work orders and projected (not yet generated) due dates"
        actions={<>
          <Select className="w-40" value={state.unit} onChange={(e) => update({ unit: e.target.value })} aria-label="Unit">
            <option value="">All units</option>{units.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
          </Select>
          <Button icon="chevronLeft" onClick={() => shift(-1)} aria-label="Previous month" />
          <span className="min-w-[9rem] text-center text-sm font-medium">{label}</span>
          <Button onClick={() => shift(1)} aria-label="Next month">›</Button>
        </>} />
      <div className="mb-2 flex flex-wrap gap-3 text-xs text-muted">
        <span className="flex items-center gap-1"><Badge tone="info" icon={null}>WO</Badge> Generated work order</span>
        <span className="flex items-center gap-1"><Badge tone="good">Done</Badge> Completed</span>
        <span className="flex items-center gap-1"><Badge tone="bad">Overdue</Badge> Past due and open</span>
        <span className="flex items-center gap-1"><Badge tone="neutral" icon={null}>Projected</Badge> Future due date</span>
      </div>
      {error ? <ErrorState error={error} onRetry={reload} /> : loading && !data ? <Loading /> : (
        <Card bodyClass="p-0">
          <div className="grid grid-cols-7 border-b border-border bg-raised text-xs font-semibold text-ink-2" aria-hidden="true">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="px-2 py-1.5">{d}</div>)}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-7">
            {days.map((d) => {
              const entries = byDay.get(d) ?? [];
              const outside = d.slice(0, 7) !== state.month;
              return (
                <div key={d} className={`min-h-[6.5rem] border-b border-r border-border p-1.5 ${outside ? "bg-sunken/50 text-muted" : ""} ${d === today ? "ring-2 ring-inset ring-accent" : ""}`}>
                  <p className="mb-1 text-xs font-medium">{Number(d.slice(8))}<span className="sm:hidden"> {d}</span></p>
                  <ul className="space-y-1">
                    {entries.slice(0, 4).map((e, i) => (
                      <li key={i} className="text-2xs leading-tight">
                        {e.kind === "work_order" ? (
                          <Link to={`/maintenance/work-orders/${e.work_order_id}`} className="block rounded border border-border bg-surface px-1 py-0.5 hover:border-accent"
                            title={`${e.number} ${e.title}`}>
                            <span className="font-medium">{e.asset_tag}</span> {e.title.slice(0, 22)}
                            <span className="mt-0.5 block">{e.status === "COMPLETED" ? <Badge tone="good">Done</Badge>
                              : e.overdue ? <Badge tone="bad">Overdue</Badge> : <Badge tone="info" icon={null}>{e.status.replace("_", " ").toLowerCase()}</Badge>}</span>
                          </Link>
                        ) : (
                          <span className="block rounded border border-dashed border-border px-1 py-0.5 text-muted" title={e.title}>
                            {e.asset_tag} {e.title.slice(0, 22)}
                          </span>
                        )}
                      </li>
                    ))}
                    {entries.length > 4 && <li className="text-2xs text-muted">+{entries.length - 4} more</li>}
                  </ul>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
