import { useState } from "react";
import { send, type ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Alert, Badge, Button, Card, Checkbox, ErrorState, Field, Input, Loading, Modal, PageHeader, Select, StatusBadge, useToast } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtRelative, humanize } from "@/lib/format";

interface Rule { id: number; code: string; name: string; description: string; is_enabled: boolean; severity: string; params: Record<string, number>;
  default_params: Record<string, number>; audience_roles: string[]; last_evaluated_at: string | null; active_alerts: number }
const ROLES = ["ADMIN", "OPERATIONS", "MAINTENANCE", "STORE", "SUPERVISOR", "MANAGEMENT"];

export default function AlertRulesPage() {
  const { can } = useAuth();
  const { data, error, reload } = useApi<Rule[]>("/alerts/rules/");
  const [editing, setEditing] = useState<Rule | null>(null);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  return (
    <div>
      <PageHeader title="Alert rules" subtitle="Thresholds are configuration, not code. Each rule's logic is documented in its description." />
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {data.map((r) => (
          <Card key={r.id} title={r.name} subtitle={r.code}
            actions={<>{<StatusBadge status={r.is_enabled ? "ACTIVE" : "INACTIVE"} label={r.is_enabled ? "Enabled" : "Disabled"} />}
              {can("alerts.rules.manage") && <Button size="sm" onClick={() => setEditing(r)}>Configure</Button>}</>}>
            <p className="mb-2 text-sm text-ink-2">{r.description}</p>
            <div className="flex flex-wrap gap-1 text-xs">
              <StatusBadge status={r.severity} label={`Default severity: ${humanize(r.severity)}`} />
              {Object.entries(r.params).map(([k, v]) => <Badge key={k} icon={null}>{k} = {v}</Badge>)}
            </div>
            <p className="mt-2 text-xs text-muted">Audience: {r.audience_roles.map(humanize).join(", ")} · {r.active_alerts} active · evaluated {fmtRelative(r.last_evaluated_at)}</p>
          </Card>
        ))}
      </div>
      {editing && <RuleDialog rule={editing} onClose={() => setEditing(null)} onSaved={reload} />}
    </div>
  );
}

function RuleDialog({ rule, onClose, onSaved }: { rule: Rule; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [enabled, setEnabled] = useState(rule.is_enabled);
  const [severity, setSeverity] = useState(rule.severity);
  const [params, setParams] = useState<Record<string, string>>(Object.fromEntries(Object.entries(rule.params).map(([k, v]) => [k, String(v)])));
  const [roles, setRoles] = useState<string[]>(rule.audience_roles);
  const [error, setError] = useState<ApiError | null>(null);
  const save = async () => {
    try {
      await send("patch", `/alerts/rules/${rule.id}/`, { is_enabled: enabled, severity, audience_roles: roles,
        params: Object.fromEntries(Object.entries(params).map(([k, v]) => [k, Number(v)])) });
      toast.success("Rule updated"); onSaved(); onClose();
    } catch (e) { setError(e as ApiError); }
  };
  return (
    <Modal open onClose={onClose} title={`Configure ${rule.name}`} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save}>Save</Button></>}>
      {error && <div className="mb-3"><Alert tone="bad">{error.message}</Alert></div>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Checkbox label="Rule enabled" checked={enabled} onChange={setEnabled} />
        <Field label="Default severity" htmlFor="sev"><Select id="sev" value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {["INFO", "WARNING", "CRITICAL"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}</Select></Field>
        {Object.keys(rule.default_params).map((k) => (
          <Field key={k} label={humanize(k)} htmlFor={`p-${k}`} hint={`Default ${rule.default_params[k]}`}>
            <Input id={`p-${k}`} type="number" step="any" value={params[k] ?? ""} onChange={(e) => setParams({ ...params, [k]: e.target.value })} /></Field>
        ))}
        <fieldset className="sm:col-span-2"><legend className="label">Audience (roles that see these alerts)</legend>
          <div className="flex flex-wrap gap-3">{ROLES.map((r) => <Checkbox key={r} label={humanize(r)} checked={roles.includes(r)}
            onChange={(v) => setRoles(v ? [...roles, r] : roles.filter((x) => x !== r))} />)}</div></fieldset>
      </div>
    </Modal>
  );
}
