import { useState } from "react";
import { send } from "@/api/client";
import { Button, Card, ErrorState, Input, Loading, PageHeader, useToast } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDateTime, humanize } from "@/lib/format";

interface Setting { key: string; value: unknown; default: unknown; description: string; updated_at: string | null }

export default function SettingsPage() {
  const { data, error, reload } = useApi<Setting[]>("/core/settings/");
  const ref = useReference();
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  return (
    <div className="max-w-3xl">
      <PageHeader title="System settings" subtitle="Validated configuration used by KPIs, alerts and reporting periods. Changes are audited." />
      <div className="space-y-3">{data.map((s) => <SettingRow key={s.key} setting={s} onSaved={() => { reload(); ref.reload(); }} />)}</div>
    </div>
  );
}

function SettingRow({ setting, onSaved }: { setting: Setting; onSaved: () => void }) {
  const [value, setValue] = useState(String(setting.value ?? ""));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();
  const numeric = typeof setting.default === "number";
  const save = async () => {
    setBusy(true); setErr(null);
    try { await send("put", `/core/settings/${setting.key}/`, { value: numeric ? Number(value) : value }); toast.success("Setting saved"); onSaved(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <label htmlFor={setting.key} className="font-medium">{humanize(setting.key)}</label>
          <p className="text-xs text-muted">{setting.description} Default: {String(setting.default) || "—"}.{setting.updated_at && ` Last changed ${fmtDateTime(setting.updated_at)}.`}</p>
          {err && <p className="mt-1 text-xs text-bad" role="alert">{err}</p>}
        </div>
        <Input id={setting.key} className="w-40" type={numeric ? "number" : "text"} value={value} onChange={(e) => setValue(e.target.value)} invalid={!!err} />
        <Button onClick={save} loading={busy} disabled={value === String(setting.value ?? "")}>Save</Button>
      </div>
    </Card>
  );
}
