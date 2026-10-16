import { useState } from "react";
import { ResourcePage } from "@/components/ResourcePage";
import { Badge, Modal } from "@/components/ui";
import { fmtDateTime, humanize } from "@/lib/format";

interface Log { id: number; timestamp: string; actor_name: string | null; action: string; entity_type: string; entity_id: string; entity_repr: string;
  changes: Record<string, unknown>; message: string; ip_address: string | null }

export default function AuditLogPage() {
  const [open, setOpen] = useState<Log | null>(null);
  return (
    <>
      <ResourcePage<Log> title="Audit log" subtitle="Immutable record of approvals, stock movements, record changes and security events" endpoint="/auth/audit-log/"
        defaultOrdering="-timestamp" pageSize={50}
        filters={[{ name: "action", label: "Action", type: "select", options: ["CREATE", "UPDATE", "DELETE", "STATUS", "APPROVE", "REJECT", "STOCK", "LOGIN", "LOGOUT", "LOGIN_FAILED", "SECURITY"].map((a) => ({ value: a, label: humanize(a) })) },
          { name: "entity_type", label: "Entity type", type: "text" }]}
        columns={[{ key: "timestamp", header: "Time", sortKey: "timestamp", render: (l) => fmtDateTime(l.timestamp) }, { key: "actor", header: "User", render: (l) => l.actor_name ?? "System" },
          { key: "action", header: "Action", render: (l) => <Badge icon={null} tone={l.action.includes("FAIL") || l.action === "DELETE" ? "bad" : l.action === "SECURITY" ? "warn" : "neutral"}>{humanize(l.action)}</Badge> },
          { key: "entity", header: "Record", render: (l) => <span><span className="text-xs text-muted">{l.entity_type}</span> {l.entity_repr}</span> },
          { key: "message", header: "Message", render: (l) => <span className="line-clamp-1">{l.message || "—"}</span> },
          { key: "ip", header: "IP", render: (l) => l.ip_address ?? "—" }]}
        rowActions={(l) => Object.keys(l.changes).length > 0 && <button className="text-xs link" onClick={() => setOpen(l)}>Changes</button>} />
      <Modal open={!!open} onClose={() => setOpen(null)} title={`Changes · ${open?.entity_repr ?? ""}`} size="lg">
        <pre className="max-h-[60vh] overflow-auto rounded bg-sunken p-3 text-xs">{JSON.stringify(open?.changes, null, 2)}</pre>
      </Modal>
    </>
  );
}
