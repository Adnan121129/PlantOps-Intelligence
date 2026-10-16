import { useState } from "react";
import { Link } from "react-router-dom";
import { exportUrl, send } from "@/api/client";
import { Can } from "@/auth/AuthContext";
import { useOptions } from "@/components/data";
import { DOWNTIME_TYPES, RecordDowntimeDialog } from "@/components/RecordDowntimeDialog";
import { ResourcePage } from "@/components/ResourcePage";
import { Badge, Button, useToast } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDateTime, fmtHours } from "@/lib/format";

interface Downtime {
  id: number; asset: number; asset_tag: string; asset_name: string; plant_unit_code: string; category_name: string; work_order: number | null;
  work_order_number: string | null; downtime_type: string; downtime_type_label: string; started_at: string; ended_at: string | null;
  duration_hours: number | null; is_ongoing: boolean; cause: string; recorded_by_name: string;
}

export default function DowntimePage() {
  const { units } = useReference();
  const categories = useOptions("/assets/categories/", (c) => String(c.name));
  const assets = useOptions("/assets/equipment/", (a) => String(a.asset_tag));
  const [recording, setRecording] = useState(false);
  const [key, setKey] = useState(0);
  const toast = useToast();
  return (
    <>
      <ResourcePage<Downtime> key={key} title="Downtime events"
        subtitle="Source of truth for downtime: start/end timestamps per asset. Date filters select events overlapping the range."
        endpoint="/maintenance/downtime/" defaultOrdering="-started_at"
        headerActions={<>
          <a className="inline-flex h-8 items-center rounded-md border border-border-strong bg-surface px-3 text-sm font-medium hover:bg-sunken"
            href={exportUrl("/analytics/reports/downtime_analysis/", { export: "csv" })}>Export analysis (CSV)</a>
          <Can perm="downtime.record"><Button variant="primary" icon="plus" onClick={() => setRecording(true)}>Record downtime</Button></Can>
        </>}
        filters={[
          { name: "date_from", label: "From", type: "date" }, { name: "date_to", label: "To", type: "date" },
          { name: "downtime_type", label: "Type", type: "select", options: DOWNTIME_TYPES },
          { name: "unit", label: "Unit", type: "select", options: units.map((u) => ({ value: u.id, label: u.code })) },
          { name: "category", label: "Category", type: "select", options: categories },
          { name: "asset", label: "Asset", type: "select", options: assets },
          { name: "ongoing", label: "Ongoing", type: "boolean" },
        ]}
        columns={[
          { key: "asset", header: "Asset", render: (d) => <Link className="link" to={`/assets/${d.asset}`}>{d.asset_tag}</Link> },
          { key: "name", header: "Name", render: (d) => d.asset_name },
          { key: "unit", header: "Unit", render: (d) => d.plant_unit_code },
          { key: "type", header: "Type", render: (d) => d.downtime_type_label },
          { key: "start", header: "Stopped", sortKey: "started_at", render: (d) => fmtDateTime(d.started_at) },
          { key: "end", header: "Returned", sortKey: "ended_at", render: (d) => d.ended_at ? fmtDateTime(d.ended_at) : <Badge tone="bad">Ongoing</Badge> },
          { key: "dur", header: "Duration", align: "right", render: (d) => fmtHours(d.duration_hours) },
          { key: "cause", header: "Cause" },
          { key: "wo", header: "Work order", render: (d) => d.work_order ? <Link className="link" to={`/maintenance/work-orders/${d.work_order}`}>{d.work_order_number}</Link> : "—" },
        ]}
        rowActions={(d, reload) => d.is_ongoing && (
          <Can perm="downtime.record">
            <Button size="sm" variant="ghost" onClick={async () => {
              try { await send("post", `/maintenance/downtime/${d.id}/close/`, {}); toast.success("Returned to service now"); reload(); }
              catch (e) { toast.error((e as Error).message); }
            }}>Return to service now</Button>
          </Can>
        )} />
      <RecordDowntimeDialog open={recording} onClose={() => setRecording(false)} onSaved={() => setKey((k) => k + 1)} />
    </>
  );
}
