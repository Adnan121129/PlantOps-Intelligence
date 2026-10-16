import { ResourceFormDialog, useOptions, type FormField } from "./data";
import { useToast } from "./ui";
import { nowLocalInput } from "@/lib/format";

export const DOWNTIME_TYPES = [
  { value: "UNPLANNED_FAILURE", label: "Unplanned - equipment failure" }, { value: "PLANNED_MAINTENANCE", label: "Planned maintenance" },
  { value: "EXTERNAL", label: "External (grid, fuel, weather)" }, { value: "OPERATIONAL", label: "Operational / process" },
];

/** Downtime is recorded as start/end timestamps (the source of truth); duration is always derived. */
export function RecordDowntimeDialog({ open, onClose, assetId, workOrderId, onSaved }: {
  open: boolean; onClose: () => void; assetId?: number; workOrderId?: number; onSaved: () => void;
}) {
  const toast = useToast();
  const assets = useOptions(open && !assetId ? "/assets/equipment/" : null, (a) => `${a.asset_tag} · ${a.name}`);
  const fields: FormField[] = [
    ...(!assetId ? [{ name: "asset", label: "Asset", type: "select" as const, options: assets, required: true }] : []),
    { name: "downtime_type", label: "Downtime type", type: "select", options: DOWNTIME_TYPES, required: true },
    { name: "started_at", label: "Stopped at", type: "datetime", required: true, hint: "Plant local time" },
    { name: "ended_at", label: "Returned to service", type: "datetime", hint: "Leave empty while the outage is ongoing" },
    { name: "cause", label: "Cause", required: true, full: true },
    { name: "description", label: "Details", type: "textarea" },
  ];
  return (
    <ResourceFormDialog open={open} onClose={onClose} title="Record downtime" endpoint="/maintenance/downtime/" fields={fields}
      initial={{ downtime_type: "UNPLANNED_FAILURE", started_at: undefined }}
      transform={(p) => ({ ...p, asset: assetId ?? p.asset, work_order: workOrderId ?? null, started_at: p.started_at })}
      onSaved={() => { toast.success("Downtime recorded"); onSaved(); }} />
  );
}

export { nowLocalInput };
