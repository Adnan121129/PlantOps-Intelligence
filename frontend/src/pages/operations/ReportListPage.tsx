import { Link } from "react-router-dom";
import type { Paged } from "@/api/types";
import { Can } from "@/auth/AuthContext";
import { DataTable, FilterBar, FilterField, Pagination } from "@/components/data";
import { Card, Input, LinkButton, PageHeader, Select, StatusBadge, Tabs } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { useUrlState } from "@/hooks/useUrlState";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDate, fmtDateTime, plantToday } from "@/lib/format";

interface ReportRow {
  id: number; plant_unit_code: string; shift_name: string; report_date: string; status: string; status_label: string;
  revision: number; created_by_name: string; submitted_at: string | null; reviewed_by_name: string | null; updated_at: string;
}
interface Gap { date: string; plant_unit: number; plant_unit_code: string; shift: number; shift_name: string; deadline: string; state: string; report_id: number | null }

export default function ReportListPage() {
  const { units } = useReference();
  const [state, update, reset] = useUrlState({ tab: "reports", page: "1", status: "", unit: "", date_from: "", date_to: "", ordering: "" });
  const list = useApi<Paged<ReportRow>>(state.tab === "reports" ? "/operations/reports/" : null,
    { ...state, tab: undefined, page_size: 25 });
  const gaps = useApi<{ count: number; results: Gap[] }>(state.tab === "missing" ? "/operations/reports/missing/" : null,
    { unit: state.unit, date_from: state.date_from || plantToday(-6), date_to: state.date_to || plantToday() });

  return (
    <div>
      <PageHeader title="Shift reports" subtitle="Daily and shift-wise operational reports with approval workflow"
        actions={<Can perm="opsreports.edit"><LinkButton to="/operations/reports/new" variant="primary" icon="plus">New report</LinkButton></Can>} />
      <Tabs active={state.tab} onChange={(t) => update({ tab: t })}
        tabs={[{ id: "reports", label: "Reports" }, { id: "missing", label: "Missing / incomplete" }]} />
      <Card bodyClass="p-0">
        <FilterBar onReset={reset}>
          {state.tab === "reports" && (
            <FilterField label="Status">
              <Select value={state.status} onChange={(e) => update({ status: e.target.value })}>
                <option value="">All</option>
                {["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"].map((s) => <option key={s} value={s}>{s[0] + s.slice(1).toLowerCase()}</option>)}
              </Select>
            </FilterField>
          )}
          <FilterField label="Unit">
            <Select value={state.unit} onChange={(e) => update({ unit: e.target.value })}>
              <option value="">All units</option>
              {units.filter((u) => u.requires_shift_reports).map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}
            </Select>
          </FilterField>
          <FilterField label="From"><Input type="date" value={state.date_from} onChange={(e) => update({ date_from: e.target.value })} /></FilterField>
          <FilterField label="To"><Input type="date" value={state.date_to} onChange={(e) => update({ date_to: e.target.value })} /></FilterField>
        </FilterBar>
        {state.tab === "reports" ? (
          <>
            <DataTable rows={list.data?.results} loading={list.loading} error={list.error} onRetry={list.reload} rowKey={(r) => r.id}
              ordering={state.ordering} onOrder={(o) => update({ ordering: o })} caption="Shift reports"
              columns={[
                { key: "report_date", header: "Date", sortKey: "report_date",
                  render: (r) => <Link className="link" to={`/operations/reports/${r.id}`}>{fmtDate(r.report_date)}</Link> },
                { key: "unit", header: "Unit", render: (r) => r.plant_unit_code },
                { key: "shift", header: "Shift", render: (r) => r.shift_name },
                { key: "status", header: "Status", sortKey: "status", render: (r) => <StatusBadge status={r.status} label={r.status_label} /> },
                { key: "rev", header: "Rev.", align: "right", render: (r) => r.revision },
                { key: "by", header: "Prepared by", render: (r) => r.created_by_name },
                { key: "submitted", header: "Submitted", render: (r) => fmtDateTime(r.submitted_at) },
                { key: "reviewer", header: "Reviewed by", render: (r) => r.reviewed_by_name ?? "—" },
              ]} />
            {list.data && <Pagination count={list.data.count} page={Number(state.page)} pageSize={25}
              onPage={(p) => update({ page: String(p) }, { resetPage: false })} />}
          </>
        ) : (
          <>
            <p className="px-4 pt-3 text-xs text-muted">
              Expected reports (every active unit requiring shift reports x every shift) whose submission deadline has passed
              without a submitted report. Defaults to the last 7 days.
            </p>
            <DataTable rows={gaps.data?.results} loading={gaps.loading} error={gaps.error} rowKey={(g) => `${g.plant_unit}-${g.shift}-${g.date}`}
              caption="Missing reports"
              empty={<p className="px-4 py-8 text-center text-sm text-muted">All expected reports for the period have been submitted.</p>}
              columns={[
                { key: "date", header: "Date", render: (g) => fmtDate(g.date) },
                { key: "unit", header: "Unit", render: (g) => g.plant_unit_code },
                { key: "shift", header: "Shift", render: (g) => g.shift_name },
                { key: "state", header: "State", render: (g) => <StatusBadge status={g.state} /> },
                { key: "deadline", header: "Deadline", render: (g) => fmtDateTime(g.deadline) },
                { key: "go", header: "", align: "right", render: (g) => g.report_id
                  ? <Link className="link" to={`/operations/reports/${g.report_id}`}>Open draft</Link>
                  : <Can perm="opsreports.edit"><Link className="link" to={`/operations/reports/new?unit=${g.plant_unit}&shift=${g.shift}&date=${g.date}`}>Create</Link></Can> },
              ]} />
          </>
        )}
      </Card>
    </div>
  );
}
