import { useMemo, useState } from "react";
import { send } from "@/api/client";
import { Can } from "@/auth/AuthContext";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { Badge, Button, Card, ErrorState, Input, Loading, PageHeader, Tabs } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDate, humanize, plantToday } from "@/lib/format";

interface Coverage { summary: Record<string, number>; rows: { date: string; shift: number; shift_name: string; assigned: number; min_staff: number; status: string }[] }
interface Assignment { id: number; employee_name: string; employee_code: string; shift_name: string; date: string; plant_unit_code: string | null; duty: string }

export default function RosterPage() {
  const [state, update] = useUrlState({ tab: "coverage", date_from: plantToday(), date_to: plantToday(13) });
  const { units } = useReference();
  const employees = useOptions("/workforce/directory/", (e) => `${e.employee_code} · ${e.full_name}`);
  const shifts = useOptions("/workforce/shifts/", (s) => String(s.name));
  return (
    <div>
      <PageHeader title="Roster & coverage" subtitle="Shift assignments against minimum staffing" />
      <Tabs active={state.tab} onChange={(t) => update({ tab: t })} tabs={[{ id: "coverage", label: "Coverage" }, { id: "assignments", label: "Assignments" }]} />
      {state.tab === "coverage" ? <CoverageGrid from={state.date_from} to={state.date_to} onRange={(p) => update(p)} /> : (
        <ResourcePage<Assignment> title="Assignments" embedded endpoint="/workforce/assignments/" defaultOrdering="-date"
          filters={[{ name: "date_from", label: "From", type: "date" }, { name: "date_to", label: "To", type: "date" },
            { name: "shift", label: "Shift", type: "select", options: shifts }]}
          columns={[{ key: "date", header: "Date", render: (a) => fmtDate(a.date) }, { key: "shift_name", header: "Shift" },
            { key: "employee", header: "Employee", render: (a) => `${a.employee_code} · ${a.employee_name}` },
            { key: "duty", header: "Duty", render: (a) => humanize(a.duty) }, { key: "unit", header: "Unit", render: (a) => a.plant_unit_code ?? "—" }]}
          rowActions={(a, reload) => <Can perm="shifts.assign"><Button size="sm" variant="ghost" onClick={async () => {
            await send("delete", `/workforce/assignments/${a.id}/`); reload(); }}>Remove</Button></Can>}
          form={{ perm: "shifts.assign", noun: "assignment", initial: { duty: "OPERATIONS", date: plantToday() }, fields: [
            { name: "employee", label: "Employee", type: "select", options: employees, required: true },
            { name: "date", label: "Date", type: "date", required: true },
            { name: "shift", label: "Shift", type: "select", options: shifts, required: true },
            { name: "duty", label: "Duty", type: "select", options: ["OPERATIONS", "MAINTENANCE", "SUPERVISION"].map((d) => ({ value: d, label: humanize(d) })) },
            { name: "plant_unit", label: "Unit", type: "select", options: units.map((u) => ({ value: u.id, label: u.code })) },
            { name: "notes", label: "Notes", full: true },
          ] }} />
      )}
    </div>
  );
}

function CoverageGrid({ from, to, onRange }: { from: string; to: string; onRange: (p: { date_from?: string; date_to?: string }) => void }) {
  const { data, error, loading, reload } = useApi<Coverage>("/workforce/assignments/coverage/", { date_from: from, date_to: to });
  const grid = useMemo(() => {
    const dates = Array.from(new Set(data?.rows.map((r) => r.date)));
    const shiftNames = Array.from(new Set(data?.rows.map((r) => r.shift_name)));
    const lookup = new Map(data?.rows.map((r) => [`${r.date}|${r.shift_name}`, r]));
    return { dates, shiftNames, lookup };
  }, [data]);
  const [hover, setHover] = useState<string | null>(null);
  return (
    <Card bodyClass="p-0">
      <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3">
        <label className="flex flex-col gap-1 text-xs text-ink-2">From<Input type="date" value={from} onChange={(e) => onRange({ date_from: e.target.value })} /></label>
        <label className="flex flex-col gap-1 text-xs text-ink-2">To<Input type="date" value={to} onChange={(e) => onRange({ date_to: e.target.value })} /></label>
        {data && <div className="ml-auto flex gap-2 text-xs">
          <Badge tone="good">Covered {data.summary.COVERED}</Badge><Badge tone="warn">Understaffed {data.summary.UNDERSTAFFED}</Badge>
          <Badge tone="bad">Unassigned {data.summary.UNASSIGNED}</Badge></div>}
      </div>
      {error ? <ErrorState error={error} onRetry={reload} /> : loading && !data ? <Loading /> : (
        <div className="overflow-x-auto p-3">
          <table className="text-xs">
            <thead><tr><th className="th">Shift</th>{grid.dates.map((d) => <th key={d} className="th text-center">{fmtDate(d).slice(0, 6)}</th>)}</tr></thead>
            <tbody>{grid.shiftNames.map((s) => (
              <tr key={s}><th scope="row" className="th">{s}</th>
                {grid.dates.map((d) => {
                  const r = grid.lookup.get(`${d}|${s}`)!;
                  const tone = r.status === "COVERED" ? "bg-good-soft text-good" : r.status === "UNDERSTAFFED" ? "bg-warn-soft text-warn" : "bg-bad-soft text-bad";
                  const key = `${d}|${s}`;
                  return (
                    <td key={d} className="p-0.5">
                      <div className={`relative min-w-[3.25rem] rounded px-1 py-1 text-center font-medium ${tone}`} tabIndex={0}
                        onMouseEnter={() => setHover(key)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(key)} onBlur={() => setHover(null)}
                        aria-label={`${s} ${d}: ${r.assigned} of ${r.min_staff} - ${humanize(r.status)}`}>
                        {r.assigned}/{r.min_staff}{r.status !== "COVERED" && <span aria-hidden="true"> !</span>}
                        {hover === key && <span className="card absolute left-1/2 top-full z-10 mt-1 -translate-x-1/2 whitespace-nowrap px-2 py-1 text-ink shadow-pop">
                          {humanize(r.status)} · {r.assigned} assigned, min {r.min_staff}</span>}
                      </div>
                    </td>
                  );
                })}</tr>))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
