import { Link } from "react-router-dom";
import type { Paged } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { Card, EmptyState, PageHeader, StatusBadge } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate, fmtDateTime, fmtRelative } from "@/lib/format";

interface Row { id: number; [k: string]: unknown }

/** One queue of items waiting for a decision, across modules. Each section is shown to roles that can see it. */
export default function ApprovalsPage() {
  const { can } = useAuth();
  const reports = useApi<Paged<Row>>(can("opsreports.view_all") ? "/operations/reports/" : null, { status: "SUBMITTED", page_size: 50, ordering: "report_date" });
  const prs = useApi<Paged<Row>>(can("procurement.view") ? "/inventory/purchase-requests/" : null, { status: "SUBMITTED", page_size: 50 });
  const wos = useApi<Paged<Row>>("/maintenance/work-orders/", { status: "AWAITING_VERIFICATION", page_size: 50 });
  const ot = useApi<Paged<Row>>(can("overtime.view") ? "/workforce/overtime/" : null, { status: "PENDING", page_size: 50 });
  const sections = [
    { title: "Operational reports awaiting review", data: reports.data, decide: can("opsreports.review"),
      render: (r: Row) => <><Link className="link" to={`/operations/reports/${r.id}`}>{String(r.plant_unit_code)} · {String(r.shift_name)} · {fmtDate(String(r.report_date))}</Link>
        <span className="text-xs text-muted">by {String(r.created_by_name)}, submitted {fmtRelative(String(r.submitted_at))}</span></> },
    { title: "Purchase requests awaiting approval", data: prs.data, decide: can("procurement.approve"),
      render: (r: Row) => <><Link className="link" to={`/procurement/requests/${r.id}`}>{String(r.pr_number)}</Link>
        <span className="text-xs text-muted">{String(r.justification).slice(0, 80)} · {String(r.requested_by_name)} · {fmtDateTime(String(r.submitted_at))}</span></> },
    { title: "Work orders awaiting verification", data: wos.data, decide: can("workorders.verify"),
      render: (r: Row) => <><Link className="link" to={`/maintenance/work-orders/${r.id}`}>{String(r.number)} · {String(r.title)}</Link>
        <span className="text-xs text-muted">{String(r.asset_tag)} · completed {fmtDateTime(String(r.actual_end))}</span></> },
    { title: "Overtime pending approval", data: ot.data, decide: can("overtime.manage"),
      render: (r: Row) => <><Link className="link" to="/workforce/overtime?status=PENDING">{String(r.employee_code)} · {String(r.hours)} h on {fmtDate(String(r.date))}</Link>
        <span className="text-xs text-muted">{String(r.reason)}</span></> },
  ].filter((s) => s.data);
  return (
    <div>
      <PageHeader title="Approvals" subtitle="Items waiting for a decision. You cannot approve your own submissions." />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {sections.map((s) => (
          <Card key={s.title} title={s.title} actions={<StatusBadge status={s.data!.count ? "PENDING" : "OK"} label={`${s.data!.count} pending`} />}
            subtitle={s.decide ? "You can decide on these" : "View only for your role"}>
            {s.data!.results.length === 0 ? <EmptyState title="Nothing pending" icon="check" /> : (
              <ul className="divide-y divide-border">
                {s.data!.results.map((r) => <li key={r.id} className="flex flex-col py-2">{s.render(r)}</li>)}
              </ul>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
