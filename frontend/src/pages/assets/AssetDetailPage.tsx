import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { send } from "@/api/client";
import type { Paged } from "@/api/types";
import { Can, useAuth } from "@/auth/AuthContext";
import { Attachments } from "@/components/Attachments";
import { ChartCard, ColumnChart } from "@/components/charts";
import { CreateWorkOrderDialog } from "@/components/CreateWorkOrderDialog";
import { DataTable } from "@/components/data";
import { RecordDowntimeDialog } from "@/components/RecordDowntimeDialog";
import { Alert, Button, Card, DescriptionList, ErrorState, Loading, PageHeader, PriorityBadge, ReasonDialog, StatusBadge, Tabs, useToast } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate, fmtDateTime, fmtHours, fmtMoney, humanize } from "@/lib/format";

interface Asset {
  id: number; asset_tag: string; name: string; category_name: string; plant_unit_code: string; plant_unit_name: string; location: string;
  manufacturer: string; model_number: string; serial_number: string; commissioned_on: string | null; status: string; status_label: string;
  criticality_label: string; technical_notes: string; is_archived: boolean; archived_at: string | null;
  last_maintenance_at: string | null; next_maintenance_due: string | null; open_work_orders: number;
}
interface Summary {
  downtime_hours_lifetime: number; downtime_hours_90d: number; downtime_events: number; failures: number; mttr_hours: number | null;
  ongoing_downtime: { id: number; started_at: string; cause: string } | null; maintenance_cost_total: number; maintenance_cost_ytd: number;
  cost_by_category: Record<string, number>; work_orders_by_status: Record<string, number>; monthly_cost: { month: string; total: number }[];
}
interface WO { id: number; number: string; title: string; maintenance_type_label: string; priority: string; status: string; status_label: string; reported_at: string; actual_end: string | null; is_overdue: boolean; downtime_hours: number }
interface Downtime { id: number; downtime_type_label: string; started_at: string; ended_at: string | null; duration_hours: number | null; cause: string; work_order: number | null; work_order_number: string | null }
interface Schedule { id: number; title: string; task_type: string; interval_days: number; next_due_date: string; last_completed_at: string | null; is_active: boolean }

export default function AssetDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const toast = useToast();
  const asset = useApi<Asset>(`/assets/equipment/${id}/`);
  const summary = useApi<Summary>(`/assets/equipment/${id}/summary/`);
  const [tab, setTab] = useState("work-orders");
  const wos = useApi<Paged<WO>>(tab === "work-orders" ? "/maintenance/work-orders/" : null, { asset: id, page_size: 50, ordering: "-reported_at" });
  const downtime = useApi<Paged<Downtime>>(tab === "downtime" ? "/maintenance/downtime/" : null, { asset: id, page_size: 50 });
  const schedules = useApi<Paged<Schedule>>(tab === "schedules" ? "/maintenance/schedules/" : null, { asset: id });
  const [dialog, setDialog] = useState<"" | "wo" | "downtime" | "archive">("");

  if (asset.error) return <ErrorState error={asset.error} onRetry={asset.reload} />;
  if (!asset.data) return <Loading />;
  const a = asset.data;
  const s = summary.data;
  const refresh = () => { asset.reload(); summary.reload(); downtime.reload(); wos.reload(); };

  return (
    <div>
      <PageHeader title={`${a.asset_tag} · ${a.name}`}
        subtitle={<span className="inline-flex items-center gap-2"><StatusBadge status={a.status} label={a.status_label} />{a.plant_unit_code} · {a.category_name}</span>}
        actions={!a.is_archived && <>
          <Can perm="downtime.record"><Button onClick={() => setDialog("downtime")} icon="pause">Record downtime</Button></Can>
          <Can perm="workorders.report"><Button variant="primary" icon="wrench" onClick={() => setDialog("wo")}>Raise work order</Button></Can>
          <Can perm="assets.manage"><Button variant="ghost" onClick={() => setDialog("archive")}>Archive</Button></Can>
        </>} />
      {a.is_archived && <div className="mb-3"><Alert tone="warn" title="Archived asset">Retired on {fmtDateTime(a.archived_at)}. History is kept for reporting.</Alert></div>}
      {s?.ongoing_downtime && (
        <div className="mb-3"><Alert tone="bad" title="Ongoing outage">Down since {fmtDateTime(s.ongoing_downtime.started_at)} - {s.ongoing_downtime.cause}</Alert></div>
      )}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {[["Downtime (90 days)", fmtHours(s?.downtime_hours_90d)], ["Downtime (lifetime)", fmtHours(s?.downtime_hours_lifetime)],
          ["Failures", s?.failures ?? "—"], ["MTTR", s?.mttr_hours === null ? "Insufficient data" : fmtHours(s?.mttr_hours)],
          ...(can("costs.view") ? [["Maintenance cost YTD", fmtMoney(s?.maintenance_cost_ytd)], ["Maintenance cost total", fmtMoney(s?.maintenance_cost_total)]] : []),
        ].map(([label, value]) => (
          <div key={String(label)} className="card p-3"><p className="text-xs text-ink-2">{label}</p><p className="mt-1 text-lg font-semibold">{value}</p></div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Tabs active={tab} onChange={setTab} tabs={[{ id: "work-orders", label: "Work orders" }, { id: "downtime", label: "Downtime history" },
            { id: "schedules", label: "Inspection & PM schedule" }]} />
          {tab === "work-orders" && (
            <Card bodyClass="p-0">
              <DataTable rows={wos.data?.results} loading={wos.loading} error={wos.error} rowKey={(w) => w.id} caption="Work orders"
                columns={[
                  { key: "number", header: "Work order", render: (w) => <Link className="link" to={`/maintenance/work-orders/${w.id}`}>{w.number}</Link> },
                  { key: "title", header: "Title" }, { key: "type", header: "Type", render: (w) => w.maintenance_type_label },
                  { key: "priority", header: "Priority", render: (w) => <PriorityBadge priority={w.priority} /> },
                  { key: "status", header: "Status", render: (w) => <span className="flex gap-1"><StatusBadge status={w.status} label={w.status_label} />
                    {w.is_overdue && <StatusBadge status="OPEN" label="Overdue" />}</span> },
                  { key: "reported", header: "Reported", render: (w) => fmtDateTime(w.reported_at) },
                  { key: "dt", header: "Downtime", align: "right", render: (w) => fmtHours(w.downtime_hours) },
                ]} />
            </Card>
          )}
          {tab === "downtime" && (
            <Card bodyClass="p-0">
              <DataTable rows={downtime.data?.results} loading={downtime.loading} error={downtime.error} rowKey={(d) => d.id} caption="Downtime"
                columns={[
                  { key: "type", header: "Type", render: (d) => d.downtime_type_label },
                  { key: "start", header: "Stopped", render: (d) => fmtDateTime(d.started_at) },
                  { key: "end", header: "Returned", render: (d) => d.ended_at ? fmtDateTime(d.ended_at) : <StatusBadge status="OPEN" label="Ongoing" /> },
                  { key: "dur", header: "Duration", align: "right", render: (d) => fmtHours(d.duration_hours) },
                  { key: "cause", header: "Cause" },
                  { key: "wo", header: "Work order", render: (d) => d.work_order ? <Link className="link" to={`/maintenance/work-orders/${d.work_order}`}>{d.work_order_number}</Link> : "—" },
                ]} />
            </Card>
          )}
          {tab === "schedules" && (
            <Card bodyClass="p-0">
              <DataTable rows={schedules.data?.results} loading={schedules.loading} error={schedules.error} rowKey={(x) => x.id} caption="Schedules"
                empty={<p className="p-6 text-center text-sm text-muted">No preventive or inspection schedule is configured for this asset.</p>}
                columns={[
                  { key: "title", header: "Task" }, { key: "type", header: "Type", render: (x) => humanize(x.task_type) },
                  { key: "interval", header: "Interval", render: (x) => `${x.interval_days} days` },
                  { key: "next", header: "Next due", render: (x) => fmtDate(x.next_due_date) },
                  { key: "last", header: "Last completed", render: (x) => fmtDateTime(x.last_completed_at) },
                  { key: "active", header: "Active", render: (x) => <StatusBadge status={x.is_active ? "ACTIVE" : "INACTIVE"} /> },
                ]} />
            </Card>
          )}
          {can("costs.view") && s && (
            <ChartCard title="Maintenance cost by month" subtitle="Actual cost-ledger entries linked to this asset (last 12 months)"
              rows={s.monthly_cost} columns={[{ key: "month", label: "Month", format: (v) => fmtDate(String(v)) },
                { key: "total", label: "Actual", align: "right", format: (v) => fmtMoney(v as number) }]} height={200}>
              <ColumnChart data={s.monthly_cost} x="month" series={[{ key: "total", label: "Actual" }]} valueFormat={(v) => fmtMoney(v)}
                xFormat={(m) => fmtDate(m).slice(3)} />
            </ChartCard>
          )}
        </div>
        <div className="space-y-4">
          <Card title="Asset details">
            <DescriptionList items={[["Unit", `${a.plant_unit_code} · ${a.plant_unit_name}`], ["Location", a.location || "—"],
              ["Criticality", a.criticality_label], ["Manufacturer", a.manufacturer || "—"], ["Model", a.model_number || "—"],
              ["Serial number", a.serial_number || "—"], ["Commissioned", fmtDate(a.commissioned_on)],
              ["Last maintenance", fmtDateTime(a.last_maintenance_at)], ["Next PM due", fmtDate(a.next_maintenance_due)],
              ["Open work orders", a.open_work_orders]]} />
            {a.technical_notes && <p className="mt-3 whitespace-pre-line border-t border-border pt-3 text-sm text-ink-2">{a.technical_notes}</p>}
          </Card>
          <Attachments targetType="equipmentasset" objectId={a.id} canAdd={can("assets.manage")} />
        </div>
      </div>
      <CreateWorkOrderDialog open={dialog === "wo"} onClose={() => setDialog("")} assetId={a.id} />
      <RecordDowntimeDialog open={dialog === "downtime"} onClose={() => setDialog("")} assetId={a.id} onSaved={refresh} />
      <ReasonDialog open={dialog === "archive"} title={`Archive ${a.asset_tag}`} label="Reason" confirmLabel="Archive asset" tone="danger"
        description="Archiving retires the asset and deactivates its PM schedules. Open work orders and ongoing downtime must be closed first."
        onClose={() => setDialog("")}
        onConfirm={async (reason) => { await send("post", `/assets/equipment/${a.id}/archive/`, { reason }); toast.success("Asset archived"); refresh(); }} />
    </div>
  );
}
