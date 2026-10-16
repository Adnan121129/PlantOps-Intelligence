import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { send } from "@/api/client";
import { Attachments } from "@/components/Attachments";
import { ApprovalHistory } from "@/components/ApprovalHistory";
import { Alert, Badge, Button, Card, DescriptionList, ErrorState, LinkButton, Loading, PageHeader, ReasonDialog, StatusBadge, useToast } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate, fmtDateTime, fmtNumber, humanize } from "@/lib/format";
import type { Approval } from "@/components/ApprovalHistory";

interface Report {
  id: number; plant_unit_code: string; shift_name: string; report_date: string; status: string; status_label: string; revision: number;
  created_by_name: string; submitted_by_name: string | null; submitted_at: string | null; reviewed_by_name: string | null; reviewed_at: string | null;
  summary: string; observations: string; review_comment: string;
  target_comparison: { metric: string; name: string; unit: string; value: string | null; missing_reason: string; target: string | null; variance: string | null; variance_pct: string | null; status: string | null }[];
  equipment_statuses: { id: number; asset: number; asset_tag: string; asset_name: string; status: string; note: string }[];
  approvals: Approval[];
  incidents: { id: number; incident_number: string; title: string; severity: string; status: string }[];
  capabilities: { edit: boolean; submit: boolean; review: boolean; reopen: boolean };
}

export default function ReportDetailPage() {
  const { id } = useParams();
  const { data: r, error, reload, setData } = useApi<Report>(`/operations/reports/${id}/`);
  const toast = useToast();
  const [dialog, setDialog] = useState<"" | "reject" | "reopen" | "approve">("");
  const [busy, setBusy] = useState(false);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!r) return <Loading />;

  const act = async (path: string, body: object, msg: string) => {
    const updated = await send<Report>("post", `/operations/reports/${r.id}/${path}/`, body);
    setData(updated);
    toast.success(msg);
  };
  const submit = async () => {
    setBusy(true);
    try { await act("submit", {}, "Report submitted for review"); } catch (e) { toast.error((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title={`${r.plant_unit_code} · ${r.shift_name} · ${fmtDate(r.report_date)}`}
        subtitle={<span className="inline-flex items-center gap-2"><StatusBadge status={r.status} label={r.status_label} /> Revision {r.revision}</span>}
        actions={<>
          {r.capabilities.edit && <LinkButton to={`/operations/reports/${r.id}/edit`} icon="file">Edit</LinkButton>}
          {r.capabilities.submit && <Button variant="primary" onClick={submit} loading={busy}>Submit for review</Button>}
          {r.capabilities.review && <>
            <Button variant="danger" onClick={() => setDialog("reject")}>Reject</Button>
            <Button variant="primary" icon="check" onClick={() => setDialog("approve")}>Approve</Button>
          </>}
          {r.capabilities.reopen && <Button onClick={() => setDialog("reopen")}>Reopen for correction</Button>}
        </>} />
      {r.status === "REJECTED" && r.review_comment && <div className="mb-3"><Alert tone="bad" title="Returned by reviewer">{r.review_comment}</Alert></div>}
      {r.status === "DRAFT" && r.revision > 1 && <div className="mb-3"><Alert tone="warn" title="Correction in progress">{r.review_comment}</Alert></div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card title="Results vs targets" bodyClass="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border bg-raised"><tr>
                  <th className="th">Metric</th><th className="th text-right">Value</th><th className="th text-right">Target</th>
                  <th className="th text-right">Variance</th><th className="th">Assessment</th></tr></thead>
                <tbody>
                  {r.target_comparison.map((m) => (
                    <tr key={m.metric} className="border-b border-border last:border-0">
                      <td className="td">{m.name} <span className="text-xs text-muted">({m.unit})</span></td>
                      <td className="td text-right tabular">{m.value === null ? <Badge tone="warn" title={m.missing_reason}>Missing: {m.missing_reason}</Badge> : fmtNumber(m.value, 2)}</td>
                      <td className="td text-right tabular">{fmtNumber(m.target, 2)}</td>
                      <td className="td text-right tabular">{m.variance === null ? "—" : `${fmtNumber(m.variance, 2)} (${m.variance_pct}%)`}</td>
                      <td className="td">{m.status ? <Badge tone={m.status === "ON_TARGET" ? "good" : m.status === "INFO" ? "neutral" : "warn"}>{humanize(m.status)}</Badge> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Shift notes">
            <DescriptionList items={[["Summary", r.summary || "—"], ["Unusual observations", r.observations || "—"]]} />
          </Card>
          <Card title="Equipment status at reporting time" bodyClass="p-0">
            <table className="w-full text-sm"><tbody>
              {r.equipment_statuses.map((e) => (
                <tr key={e.id} className="border-b border-border last:border-0">
                  <td className="td"><Link className="link" to={`/assets/${e.asset}`}>{e.asset_tag}</Link> <span className="text-muted">{e.asset_name}</span></td>
                  <td className="td"><StatusBadge status={e.status} /></td>
                </tr>
              ))}
              {r.equipment_statuses.length === 0 && <tr><td className="td text-muted">Not recorded.</td></tr>}
            </tbody></table>
          </Card>
          {r.incidents.length > 0 && (
            <Card title="Incidents during this shift" bodyClass="p-0">
              <table className="w-full text-sm"><tbody>
                {r.incidents.map((i) => (
                  <tr key={i.id} className="border-b border-border last:border-0">
                    <td className="td"><Link className="link" to={`/operations/incidents?search=${i.incident_number}`}>{i.incident_number}</Link></td>
                    <td className="td">{i.title}</td><td className="td"><StatusBadge status={i.severity} /></td><td className="td"><StatusBadge status={i.status} /></td>
                  </tr>
                ))}
              </tbody></table>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card title="Workflow">
            <DescriptionList cols={2} items={[
              ["Prepared by", r.created_by_name], ["Submitted by", r.submitted_by_name ?? "—"], ["Submitted", fmtDateTime(r.submitted_at)],
              ["Reviewed by", r.reviewed_by_name ?? "—"], ["Reviewed", fmtDateTime(r.reviewed_at)]]} />
          </Card>
          <ApprovalHistory records={r.approvals} />
          <Attachments targetType="operationalreport" objectId={r.id} canAdd={r.capabilities.edit} />
        </div>
      </div>

      <ReasonDialog open={dialog === "approve"} title="Approve report" label="Comment" required={false} confirmLabel="Approve"
        onClose={() => setDialog("")} onConfirm={(c) => act("review", { decision: "approve", comment: c }, "Report approved")} />
      <ReasonDialog open={dialog === "reject"} title="Reject report" label="What must be corrected?" confirmLabel="Reject" tone="danger"
        onClose={() => setDialog("")} onConfirm={(c) => act("review", { decision: "reject", comment: c }, "Report returned to the author")} />
      <ReasonDialog open={dialog === "reopen"} title="Reopen approved report" label="Reason for correction" confirmLabel="Reopen"
        description="The approved values are preserved in the approval history and the report becomes a new draft revision."
        onClose={() => setDialog("")} onConfirm={(c) => act("reopen", { reason: c }, "Report reopened for correction")} />
    </div>
  );
}
