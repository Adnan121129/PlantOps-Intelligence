import { useRef, useState } from "react";
import { api, toApiError } from "@/api/client";
import type { Paged } from "@/api/types";
import { useApi } from "@/hooks/useApi";
import { fmtDateTime } from "@/lib/format";
import { Button, Card, Icon, useToast } from "./ui";

interface Attachment { id: number; original_name: string; size_bytes: number; uploaded_by_name: string; uploaded_at: string; download_url: string }

export function Attachments({ targetType, objectId, canAdd }: { targetType: string; objectId: number; canAdd: boolean }) {
  const { data, reload, error } = useApi<Paged<Attachment>>("/core/attachments/", { target_type: targetType, object_id: objectId });
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  if (error?.status === 403) return null;
  const upload = async (file: File) => {
    const form = new FormData();
    form.append("target_type", targetType);
    form.append("object_id", String(objectId));
    form.append("file", file);
    setBusy(true);
    try {
      await api.post("/core/attachments/", form);
      toast.success("File attached");
      reload();
    } catch (e) {
      toast.error(toApiError(e).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <Card title="Attachments" actions={canAdd && (
      <>
        <input ref={input} type="file" className="hidden" accept=".pdf,.png,.jpg,.jpeg,.txt,.csv,.xlsx"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} aria-label="Choose file to attach" />
        <Button size="sm" icon="plus" loading={busy} onClick={() => input.current?.click()}>Attach</Button>
      </>
    )}>
      {!data?.results.length ? <p className="text-sm text-muted">No documents attached. PDF, images, text, CSV or XLSX up to 5 MB.</p> : (
        <ul className="space-y-1.5">
          {data.results.map((a) => (
            <li key={a.id} className="flex items-center gap-2 text-sm">
              <Icon name="file" className="text-muted" />
              <a className="link truncate" href={a.download_url}>{a.original_name}</a>
              <span className="ml-auto shrink-0 text-xs text-muted">{(a.size_bytes / 1024).toFixed(0)} KB · {fmtDateTime(a.uploaded_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
