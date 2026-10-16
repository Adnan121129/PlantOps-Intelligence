import { useReference } from "@/lib/ReferenceContext";
import { plantToday } from "@/lib/format";
import { Input, Select } from "./ui";

export interface PeriodState { date_from: string; date_to: string; unit: string }

const PRESETS = [
  { id: "7", label: "Last 7 days", days: 7 },
  { id: "30", label: "Last 30 days", days: 30 },
  { id: "90", label: "Last 90 days", days: 90 },
  { id: "mtd", label: "Month to date" },
  { id: "ytd", label: "Year to date" },
];

export function presetRange(id: string): { date_from: string; date_to: string } {
  const today = plantToday();
  if (id === "mtd") return { date_from: `${today.slice(0, 8)}01`, date_to: today };
  if (id === "ytd") return { date_from: `${today.slice(0, 4)}-01-01`, date_to: today };
  const days = PRESETS.find((p) => p.id === id)?.days ?? 30;
  return { date_from: plantToday(-(days - 1)), date_to: today };
}

/** Reporting-period and scope controls. Dates are plant-local business dates (inclusive). */
export function PeriodFilter({ value, onChange, showUnit = true, children }: {
  value: PeriodState; onChange: (patch: Partial<PeriodState>) => void; showUnit?: boolean; children?: React.ReactNode;
}) {
  const { units, timeZone } = useReference();
  const active = PRESETS.find((p) => {
    const r = presetRange(p.id);
    return r.date_from === value.date_from && r.date_to === value.date_to;
  })?.id ?? "custom";
  return (
    <div className="card mb-4 flex flex-wrap items-end gap-3 px-4 py-3" role="search" aria-label="Reporting period and scope">
      <label className="flex flex-col gap-1 text-xs text-ink-2">
        <span>Period</span>
        <Select className="w-40" value={active} onChange={(e) => e.target.value !== "custom" && onChange(presetRange(e.target.value))}>
          {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          <option value="custom">Custom range</option>
        </Select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-ink-2">
        <span>From</span>
        <Input type="date" className="w-40" value={value.date_from} max={value.date_to}
          onChange={(e) => e.target.value && onChange({ date_from: e.target.value })} />
      </label>
      <label className="flex flex-col gap-1 text-xs text-ink-2">
        <span>To</span>
        <Input type="date" className="w-40" value={value.date_to} min={value.date_from}
          onChange={(e) => e.target.value && onChange({ date_to: e.target.value })} />
      </label>
      {showUnit && (
        <label className="flex flex-col gap-1 text-xs text-ink-2">
          <span>Plant unit</span>
          <Select className="w-48" value={value.unit} onChange={(e) => onChange({ unit: e.target.value })}>
            <option value="">All units</option>
            {units.map((u) => <option key={u.id} value={u.id}>{u.code} · {u.name}</option>)}
          </Select>
        </label>
      )}
      {children}
      <p className="ml-auto self-center text-2xs text-muted">Dates in plant time ({timeZone})</p>
    </div>
  );
}
