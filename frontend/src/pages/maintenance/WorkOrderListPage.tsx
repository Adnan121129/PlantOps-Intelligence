import { useState } from "react";
import { Link } from "react-router-dom";
import { exportUrl } from "@/api/client";
import type { Paged } from "@/api/types";
import { Can } from "@/auth/AuthContext";
import { CreateWorkOrderDialog } from "@/components/CreateWorkOrderDialog";
import { DataTable, FilterBar, FilterField, Pagination } from "@/components/data";
import { Badge, Button, Card, Input, PageHeader, PriorityBadge, Select, StatusBadge } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useDebounced } from "@/hooks/useDebounced";
import { useUrlState } from "@/hooks/useUrlState";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDate, fmtDateTime, fmtHours, humanize } from "@/lib/format";

interface WO {
  id: number; number: string; asset: number; asset_tag: string; asset_name: string; plant_unit_code: string; maintenance_type_label: string;
  title: string; priority: string; status: string; status_label: string; is_overdue: boolean; is_blocked: boolean; blocked_reason: string;
  technician_name: string | null; assigned_team: string; due_date: string | null; planned_end: string | null; reported_at: string; downtime_hours: number;
}

const STATUSES = ["REPORTED", "ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION", "COMPLETED", "CANCELLED"];

export default function WorkOrderListPage() {
  const { units } = useReference();
  const [state, update, reset] = useUrlState({ page: "1", ordering: "-reported_at", search: "", status: "", open: "", overdue: "",
    maintenance_type: "", priority: "", unit: "", preventive: "", reported_from: "", reported_to: "", due_from: "", due_to: "", asset: "", is_blocked: "" });
  const [search, setSearch] = useState(state.search);
  const term = useDebounced(search);
  const params = { ...state, search: term, page_size: 25 };
  const { data, loading, error, reload } = useApi<Paged<WO>>("/maintenance/work-orders/", params);
  const [creating, setCreating] = useState(false);
  const activeChips = Object.entries(state).filter(([k, v]) => v && !["page", "ordering", "search"].includes(k));

  return (
    <div>
      <PageHeader title="Work orders" subtitle="Corrective, preventive and inspection work"
        actions={<>
          <a className="inline-flex h-8 items-center rounded-md border border-border-strong bg-surface px-3 text-sm font-medium hover:bg-sunken"
            href={exportUrl("/analytics/reports/work_order_performance/", { export: "csv", date_from: state.reported_from, date_to: state.reported_to, unit: state.unit })}>
            Export CSV
          </a>
          <Can perm="workorders.report"><Button variant="primary" icon="plus" onClick={() => setCreating(true)}>Raise work order</Button></Can>
        </>} />
      <Card bodyClass="p-0">
        <FilterBar onReset={() => { setSearch(""); reset(); }}>
          <FilterField label="Search" width="w-56"><Input type="search" value={search} onChange={(e) => { setSearch(e.target.value); update({ search: e.target.value }); }} placeholder="Number, title, asset…" /></FilterField>
          <FilterField label="Status">
            <Select value={state.status} onChange={(e) => update({ status: e.target.value })}>
              <option value="">All</option>{STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </Select>
          </FilterField>
          <FilterField label="Open / closed">
            <Select value={state.open} onChange={(e) => update({ open: e.target.value })}>
              <option value="">All</option><option value="true">Open</option><option value="false">Closed</option>
            </Select>
          </FilterField>
          <FilterField label="Type">
            <Select value={state.maintenance_type} onChange={(e) => update({ maintenance_type: e.target.value })}>
              <option value="">All</option>{["CORRECTIVE", "PREVENTIVE", "INSPECTION"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
            </Select>
          </FilterField>
          <FilterField label="Priority">
            <Select value={state.priority} onChange={(e) => update({ priority: e.target.value })}>
              <option value="">All</option>{["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
            </Select>
          </FilterField>
          <FilterField label="Unit">
            <Select value={state.unit} onChange={(e) => update({ unit: e.target.value })}>
              <option value="">All units</option>{units.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
            </Select>
          </FilterField>
          <FilterField label="Indicator">
            <Select value={state.overdue ? "overdue" : state.is_blocked ? "blocked" : ""} onChange={(e) =>
              update({ overdue: e.target.value === "overdue" ? "true" : undefined, is_blocked: e.target.value === "blocked" ? "true" : undefined })}>
              <option value="">Any</option><option value="overdue">Overdue</option><option value="blocked">Blocked</option>
            </Select>
          </FilterField>
        </FilterBar>
        {activeChips.length > 0 && (
          <div className="flex flex-wrap gap-1 px-4 pt-2" aria-label="Active filters">
            {activeChips.map(([k, v]) => <Badge key={k} tone="accent" icon={null}>{humanize(k)}: {v}</Badge>)}
          </div>
        )}
        <DataTable rows={data?.results} loading={loading} error={error} onRetry={reload} rowKey={(w) => w.id} caption="Work orders"
          ordering={state.ordering} onOrder={(o) => update({ ordering: o })}
          columns={[
            { key: "number", header: "Work order", sortKey: "number", className: "whitespace-nowrap", render: (w) => <Link className="link font-medium" to={`/maintenance/work-orders/${w.id}`}>{w.number}</Link> },
            { key: "title", header: "Title", render: (w) => <span className="line-clamp-2">{w.title}</span> },
            { key: "asset", header: "Asset", className: "whitespace-nowrap", render: (w) => <Link className="link" to={`/assets/${w.asset}`}>{w.asset_tag}</Link> },
            { key: "type", header: "Type", render: (w) => w.maintenance_type_label },
            { key: "priority", header: "Priority", sortKey: "priority", render: (w) => <PriorityBadge priority={w.priority} /> },
            { key: "status", header: "Status", sortKey: "status", render: (w) => (
              <span className="flex flex-wrap gap-1"><StatusBadge status={w.status} label={w.status_label} />
                {w.is_overdue && <Badge tone="bad">Overdue</Badge>}
                {w.is_blocked && <Badge tone="warn" icon="pause" title={w.blocked_reason}>Blocked</Badge>}</span>) },
            { key: "tech", header: "Assigned", render: (w) => w.technician_name ?? (w.assigned_team || "—") },
            { key: "due", header: "Due / planned", sortKey: "planned_end", render: (w) => w.due_date ? fmtDate(w.due_date) : fmtDateTime(w.planned_end) },
            { key: "reported", header: "Reported", sortKey: "reported_at", render: (w) => fmtDateTime(w.reported_at) },
            { key: "dt", header: "Downtime", align: "right", render: (w) => fmtHours(w.downtime_hours) },
          ]} />
        {data && <Pagination count={data.count} page={Number(state.page)} pageSize={25} onPage={(p) => update({ page: String(p) }, { resetPage: false })} />}
      </Card>
      <CreateWorkOrderDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}
