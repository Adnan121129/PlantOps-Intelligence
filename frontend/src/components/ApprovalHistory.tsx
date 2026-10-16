import { fmtDateTime, humanize } from "@/lib/format";
import { Card, StatusBadge } from "./ui";

export interface Approval { id: number; action: string; from_status: string; to_status: string; actor_name: string; comment: string; revision: number; created_at: string }

const ACTION_STATUS: Record<string, string> = { SUBMIT: "SUBMITTED", APPROVE: "APPROVED", REJECT: "REJECTED", REOPEN: "DRAFT", VERIFY: "COMPLETED", RETURN: "REJECTED" };

export function ApprovalHistory({ records, title = "Approval history" }: { records: Approval[]; title?: string }) {
  return (
    <Card title={title}>
      {records.length === 0 ? <p className="text-sm text-muted">No workflow decisions yet.</p> : (
        <ol className="relative space-y-3 border-l border-border pl-4">
          {records.map((a) => (
            <li key={a.id}>
              <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" aria-hidden="true" />
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={ACTION_STATUS[a.action] ?? a.to_status} label={humanize(a.action)} />
                <span className="text-sm">{a.actor_name}</span>
                <span className="text-xs text-muted">{fmtDateTime(a.created_at)} · rev. {a.revision}</span>
              </div>
              {a.comment && <p className="mt-0.5 text-sm text-ink-2">“{a.comment}”</p>}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
