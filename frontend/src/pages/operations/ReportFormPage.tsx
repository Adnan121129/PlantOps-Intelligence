import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { send, type ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Alert, Button, Card, ErrorState, Field, Input, Loading, PageHeader, Select, Textarea, useToast } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useReference } from "@/lib/ReferenceContext";
import { humanize, plantToday } from "@/lib/format";

interface Metric { id: number; code: string; name: string; unit: string; is_required: boolean; valid_min: string | null; valid_max: string | null; target_value: string | null }
interface Template {
  unit: { id: number; code: string; name: string };
  today: string;
  shifts: { id: number; name: string; start_time: string; end_time: string }[];
  metrics: Metric[];
  assets: { id: number; asset_tag: string; name: string; status: string }[];
}
interface Existing {
  id: number; plant_unit: number; shift: number; report_date: string; summary: string; observations: string; status: string;
  measurements: { metric: number; value: string | null; missing_reason: string; note: string }[];
  equipment_statuses: { asset: number; status: string; note: string }[];
  capabilities: { edit: boolean };
}
type MeasureState = Record<number, { value: string; missing: boolean; reason: string }>;

export default function ReportFormPage() {
  const { id } = useParams();
  const [qs] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { user } = useAuth();
  const { units } = useReference();
  const existing = useApi<Existing>(id ? `/operations/reports/${id}/` : null);
  const myUnits = units.filter((u) => user?.assigned_unit_ids.includes(u.id) && u.requires_shift_reports);
  const [unitId, setUnitId] = useState<string>(qs.get("unit") ?? "");
  const template = useApi<Template>(unitId ? "/operations/reports/template/" : null, { unit: unitId });
  const [shift, setShift] = useState(qs.get("shift") ?? "");
  const [date, setDate] = useState(qs.get("date") ?? plantToday());
  const [summary, setSummary] = useState("");
  const [observations, setObservations] = useState("");
  const [measures, setMeasures] = useState<MeasureState>({});
  const [equipment, setEquipment] = useState<Record<number, string>>({});
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "save" | "submit">("");

  useEffect(() => {
    if (!unitId && myUnits.length === 1) setUnitId(String(myUnits[0].id));
  }, [myUnits, unitId]);

  useEffect(() => {
    const r = existing.data;
    if (!r) return;
    setUnitId(String(r.plant_unit)); setShift(String(r.shift)); setDate(r.report_date);
    setSummary(r.summary); setObservations(r.observations);
    setMeasures(Object.fromEntries(r.measurements.map((m) => [m.metric, { value: m.value ?? "", missing: m.value === null, reason: m.missing_reason }])));
    setEquipment(Object.fromEntries(r.equipment_statuses.map((e) => [e.asset, e.status])));
  }, [existing.data]);

  useEffect(() => {
    if (!template.data || id) return;
    setEquipment((prev) => Object.keys(prev).length ? prev : Object.fromEntries(template.data!.assets.map((a) => [a.id, a.status === "RETIRED" ? "OPERATIONAL" : a.status])));
  }, [template.data, id]);

  const metrics = template.data?.metrics ?? [];
  const missingRequired = useMemo(() => metrics.filter((m) => m.is_required && !(measures[m.id]?.missing ? measures[m.id]?.reason : measures[m.id]?.value)), [metrics, measures]);

  const payload = () => ({
    ...(id ? {} : { plant_unit: Number(unitId), shift: Number(shift), report_date: date }),
    summary, observations,
    measurements: metrics.flatMap((m): { metric: number; value: string | null; missing_reason?: string }[] => {
      const s = measures[m.id];
      if (!s) return [];
      if (s.missing) return s.reason.trim() ? [{ metric: m.id, value: null, missing_reason: s.reason.trim() }] : [];
      return s.value.trim() === "" ? [] : [{ metric: m.id, value: s.value.trim() }];
    }),
    equipment_statuses: Object.entries(equipment).map(([asset, status]) => ({ asset: Number(asset), status })),
  });

  const save = async (andSubmit: boolean) => {
    setBusy(andSubmit ? "submit" : "save"); setErrors({}); setMessage(null);
    try {
      const report = id ? await send<{ id: number }>("patch", `/operations/reports/${id}/`, payload())
        : await send<{ id: number }>("post", "/operations/reports/", payload());
      if (andSubmit) await send("post", `/operations/reports/${report.id}/submit/`);
      toast.success(andSubmit ? "Report submitted for review" : "Draft saved");
      navigate(`/operations/reports/${report.id}`);
    } catch (e) {
      const err = e as ApiError;
      setErrors(err.fieldErrors); setMessage(err.message);
    } finally { setBusy(""); }
  };

  if (id && existing.error) return <ErrorState error={existing.error} />;
  if (id && !existing.data) return <Loading />;
  if (existing.data && !existing.data.capabilities.edit) {
    return <Alert tone="warn" title="This report cannot be edited">Only draft or rejected reports for your units can be edited.</Alert>;
  }

  return (
    <div className="max-w-5xl">
      <PageHeader title={id ? "Edit shift report" : "New shift report"} subtitle="Enter values as measured. Leave a value empty only with a reason - missing data is never treated as zero." />
      {message && <div className="mb-3"><Alert tone="bad">{message}</Alert></div>}
      <Card title="Reporting scope" className="mb-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="Plant unit" required htmlFor="unit" error={errors.plant_unit}>
            <Select id="unit" value={unitId} disabled={!!id} onChange={(e) => { setUnitId(e.target.value); setMeasures({}); setEquipment({}); }}>
              <option value="">Select…</option>
              {myUnits.map((u) => <option key={u.id} value={u.id}>{u.code} · {u.name}</option>)}
            </Select>
          </Field>
          <Field label="Shift" required htmlFor="shift" error={errors.shift}>
            <Select id="shift" value={shift} disabled={!!id || !template.data} onChange={(e) => setShift(e.target.value)}>
              <option value="">Select…</option>
              {template.data?.shifts.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)})</option>)}
            </Select>
          </Field>
          <Field label="Report date" required htmlFor="date" error={errors.report_date} hint="Date the shift starts (plant time)">
            <Input id="date" type="date" value={date} max={template.data?.today} disabled={!!id} onChange={(e) => setDate(e.target.value)} />
          </Field>
        </div>
        {!myUnits.length && <p className="mt-2 text-sm text-muted">You are not assigned to any unit that requires shift reports.</p>}
      </Card>

      {template.data && (
        <>
          <Card title="Measurements" subtitle="Targets and valid ranges come from the configured metric definitions" className="mb-4" bodyClass="p-0">
            {errors.measurements && <div className="p-3"><Alert tone="bad">{errors.measurements.join(" ")}</Alert></div>}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border bg-raised"><tr>
                  <th className="th">Metric</th><th className="th">Value</th><th className="th">Valid range</th><th className="th">Target</th><th className="th">Not available</th>
                </tr></thead>
                <tbody>
                  {metrics.map((m) => {
                    const s = measures[m.id] ?? { value: "", missing: false, reason: "" };
                    const set = (patch: Partial<typeof s>) => setMeasures({ ...measures, [m.id]: { ...s, ...patch } });
                    return (
                      <tr key={m.id} className="border-b border-border last:border-0">
                        <td className="td"><label htmlFor={`m-${m.id}`} className="font-medium">{m.name}</label>
                          {m.is_required && <span className="text-bad" aria-hidden="true"> *</span>}
                          <span className="block text-xs text-muted">{m.code}</span></td>
                        <td className="td">
                          {s.missing ? (
                            <Input aria-label={`Reason ${m.name} is missing`} placeholder="Reason (e.g. meter fault)" value={s.reason}
                              onChange={(e) => set({ reason: e.target.value })} />
                          ) : (
                            <div className="flex items-center gap-2">
                              <Input id={`m-${m.id}`} type="number" step="any" className="w-36" value={s.value} onChange={(e) => set({ value: e.target.value })} />
                              <span className="text-xs text-muted">{m.unit}</span>
                            </div>
                          )}
                        </td>
                        <td className="td text-xs text-muted tabular">{m.valid_min ?? "—"} – {m.valid_max ?? "—"}</td>
                        <td className="td text-xs tabular">{m.target_value ?? "—"}</td>
                        <td className="td"><input type="checkbox" aria-label={`${m.name} not available`} checked={s.missing}
                          onChange={(e) => set({ missing: e.target.checked })} className="h-4 w-4" /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Equipment status at time of reporting" className="mb-4">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {template.data.assets.map((a) => (
                <label key={a.id} className="flex items-center justify-between gap-2 rounded border border-border px-3 py-1.5">
                  <span className="text-sm"><span className="font-medium">{a.asset_tag}</span> <span className="text-muted">{a.name}</span></span>
                  <Select className="w-48" value={equipment[a.id] ?? "OPERATIONAL"} onChange={(e) => setEquipment({ ...equipment, [a.id]: e.target.value })}
                    aria-label={`Status of ${a.asset_tag}`}>
                    {["OPERATIONAL", "UNDER_MAINTENANCE", "OUT_OF_SERVICE"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
                  </Select>
                </label>
              ))}
            </div>
          </Card>

          <Card title="Shift notes" className="mb-4">
            <div className="grid grid-cols-1 gap-3">
              <Field label="Summary" htmlFor="summary"><Textarea id="summary" value={summary} onChange={(e) => setSummary(e.target.value)} /></Field>
              <Field label="Unusual observations" htmlFor="obs" hint="Record operational incidents separately under Incidents so they can be tracked.">
                <Textarea id="obs" value={observations} onChange={(e) => setObservations(e.target.value)} />
              </Field>
            </div>
          </Card>

          <div className="flex flex-wrap items-center justify-end gap-2">
            {missingRequired.length > 0 && <p className="mr-auto text-xs text-warn">{missingRequired.length} required value(s) still empty - you can save a draft, but not submit.</p>}
            <Button onClick={() => navigate(-1)}>Cancel</Button>
            <Button onClick={() => save(false)} loading={busy === "save"} disabled={!shift || !unitId}>Save draft</Button>
            <Button variant="primary" onClick={() => save(true)} loading={busy === "submit"} disabled={!shift || !unitId || missingRequired.length > 0}>
              Save &amp; submit
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
