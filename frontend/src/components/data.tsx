import { useEffect, useMemo, useState, type ReactNode } from "react";
import { send, type ApiError } from "@/api/client";
import type { Option } from "@/api/types";
import { useApi } from "@/hooks/useApi";
import { isoToLocalInput, localInputToIso } from "@/lib/format";
import { Alert, Button, Checkbox, EmptyState, ErrorState, Field, Icon, Input, Modal, Select, Skeleton, Textarea } from "./ui";

// ------------------------------------------------------------------ DataTable
export interface Column<T> {
  key: string;
  header: ReactNode;
  render?: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
  sortKey?: string;
  className?: string;
}

export function DataTable<T>({ columns, rows, loading, error, onRetry, rowKey, ordering, onOrder, empty, caption, dense }: {
  columns: Column<T>[];
  rows: T[] | undefined;
  loading?: boolean;
  error?: ApiError | null;
  onRetry?: () => void;
  rowKey: (row: T) => string | number;
  ordering?: string;
  onOrder?: (ordering: string) => void;
  empty?: ReactNode;
  caption?: string;
  dense?: boolean;
}) {
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  const sortState = (key?: string): "ascending" | "descending" | undefined =>
    !key || !ordering ? undefined : ordering === key ? "ascending" : ordering === `-${key}` ? "descending" : undefined;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="border-b border-border bg-raised">
          <tr>
            {columns.map((c) => {
              const state = sortState(c.sortKey);
              return (
                <th key={c.key} scope="col" aria-sort={state ?? (c.sortKey ? "none" : undefined)}
                  className={`th ${c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : ""}`}>
                  {c.sortKey && onOrder ? (
                    <button className="inline-flex items-center gap-1 hover:text-ink"
                      onClick={() => onOrder(state === "ascending" ? `-${c.sortKey}` : c.sortKey!)}>
                      {c.header}
                      <span aria-hidden="true" className="text-muted">{state === "ascending" ? "▲" : state === "descending" ? "▼" : "↕"}</span>
                    </button>
                  ) : c.header}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {loading && !rows?.length
            ? Array.from({ length: 5 }).map((_, i) => (
              <tr key={i} className="border-b border-border">
                {columns.map((c) => <td key={c.key} className="td"><Skeleton className="h-4 w-full max-w-[10rem]" /></td>)}
              </tr>
            ))
            : rows?.map((row) => (
              <tr key={rowKey(row)} className="border-b border-border last:border-0 hover:bg-raised">
                {columns.map((c) => (
                  <td key={c.key} className={`${dense ? "px-3 py-1.5" : "td"} ${c.align === "right" ? "text-right tabular" : ""} ${c.className ?? ""}`}>
                    {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
      {!loading && rows && rows.length === 0 && (empty ?? <EmptyState title="No records found" message="Adjust the filters or the reporting period." />)}
      {loading && !!rows?.length && <div className="h-0.5 animate-pulse bg-accent/40" aria-hidden="true" />}
    </div>
  );
}

export function Pagination({ count, page, pageSize, onPage }: { count: number; page: number; pageSize: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (count <= pageSize) return count ? <p className="px-4 py-2 text-xs text-muted">{count} record{count === 1 ? "" : "s"}</p> : null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(count, page * pageSize);
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-2 border-t border-border px-4 py-2 text-xs text-muted">
      <span className="tabular">{from}–{to} of {count}</span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" icon="chevronLeft" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <span className="tabular px-1">Page {page} of {pages}</span>
        <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next <Icon name="chevronRight" size={14} />
        </Button>
      </div>
    </nav>
  );
}

export function FilterBar({ children, onReset }: { children: ReactNode; onReset?: () => void }) {
  return (
    <div className="flex flex-wrap items-end gap-3 border-b border-border px-4 py-3" role="search">
      {children}
      {onReset && <Button size="sm" variant="ghost" onClick={onReset}>Reset filters</Button>}
    </div>
  );
}

export function FilterField({ label, children, width = "w-40" }: { label: string; children: ReactNode; width?: string }) {
  return <label className={`flex flex-col gap-1 text-xs text-ink-2 ${width}`}><span>{label}</span>{children}</label>;
}

// ------------------------------------------------------------------ Reference options (select boxes fed from the API)
export function useOptions(url: string | null, label: (row: Record<string, unknown>) => string, params?: Record<string, unknown>): Option[] {
  const { data } = useApi<unknown>(url, { page_size: 200, ...params });
  return useMemo(() => {
    const rows = (Array.isArray(data) ? data : (data as { results?: unknown[] })?.results ?? []) as Record<string, unknown>[];
    return rows.map((r) => ({ value: r.id as number, label: label(r) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
}

// ------------------------------------------------------------------ Schema-driven form
export type FieldType = "text" | "number" | "date" | "datetime" | "textarea" | "select" | "checkbox" | "multiselect" | "time" | "password";

export interface FormField {
  name: string;
  label: string;
  type?: FieldType;
  options?: Option[];
  required?: boolean;
  hint?: string;
  step?: string;
  placeholder?: string;
  full?: boolean;
  readOnlyOnEdit?: boolean;
  showIf?: (values: Record<string, unknown>) => boolean;
}

export function toFormValues(fields: FormField[], initial: Record<string, unknown> = {}) {
  const v: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = initial[f.name];
    if (f.type === "checkbox") v[f.name] = raw ?? false;
    else if (f.type === "multiselect") v[f.name] = Array.isArray(raw) ? raw : [];
    else if (f.type === "datetime") v[f.name] = typeof raw === "string" ? isoToLocalInput(raw) : "";
    else v[f.name] = raw ?? "";
  }
  return v;
}

function toPayload(fields: FormField[], values: Record<string, unknown>) {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    if (f.showIf && !f.showIf(values)) continue;
    let v = values[f.name];
    if (f.type === "datetime") v = v ? localInputToIso(String(v)) : null;
    else if ((f.type === "select" || f.type === "number" || f.type === "date") && v === "") v = null;
    else if (f.type === "password" && v === "") continue;
    out[f.name] = v;
  }
  return out;
}

export function FormGrid({ fields, values, setValues, errors, editing }: {
  fields: FormField[]; values: Record<string, unknown>; setValues: (v: Record<string, unknown>) => void;
  errors: Record<string, string[]>; editing?: boolean;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {fields.filter((f) => !f.showIf || f.showIf(values)).map((f) => {
        const id = `f-${f.name}`;
        const err = errors[f.name];
        const disabled = editing && f.readOnlyOnEdit;
        const set = (val: unknown) => setValues({ ...values, [f.name]: val });
        const common = { id, name: f.name, disabled, invalid: !!err, "aria-describedby": err ? `${id}-err` : undefined };
        let control: ReactNode;
        switch (f.type) {
          case "textarea":
            control = <Textarea {...common} value={String(values[f.name] ?? "")} onChange={(e) => set(e.target.value)} />;
            break;
          case "select":
            control = (
              <Select {...common} value={String(values[f.name] ?? "")} onChange={(e) => set(e.target.value)}>
                <option value="">{f.required ? "Select…" : "—"}</option>
                {f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
            );
            break;
          case "multiselect":
            control = (
              <Select {...common} multiple value={(values[f.name] as (string | number)[]).map(String)} className="h-24"
                onChange={(e) => set(Array.from(e.target.selectedOptions).map((o) => (Number.isNaN(Number(o.value)) ? o.value : Number(o.value))))}>
                {f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
            );
            break;
          case "checkbox":
            control = <div className="pt-1"><Checkbox id={id} label={f.hint ?? "Yes"} checked={!!values[f.name]} onChange={set} /></div>;
            break;
          default:
            control = (
              <Input {...common} type={f.type === "datetime" ? "datetime-local" : f.type ?? "text"} step={f.step}
                placeholder={f.placeholder} value={String(values[f.name] ?? "")} onChange={(e) => set(e.target.value)} />
            );
        }
        return (
          <Field key={f.name} label={f.label} required={f.required} htmlFor={id} error={err}
            hint={f.type === "checkbox" ? undefined : f.hint} className={f.full || f.type === "textarea" ? "sm:col-span-2" : ""}>
            {control}
          </Field>
        );
      })}
    </div>
  );
}

/** Create/edit dialog for one REST resource. */
export function ResourceFormDialog({ open, onClose, title, endpoint, fields, initial, id, onSaved, transform }: {
  open: boolean; onClose: () => void; title: string; endpoint: string; fields: FormField[];
  initial?: Record<string, unknown>; id?: number | null; onSaved: (row: unknown) => void;
  transform?: (payload: Record<string, unknown>) => Record<string, unknown>;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(() => toFormValues(fields, initial));
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) { setValues(toFormValues(fields, initial)); setErrors({}); setMessage(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, id]);

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const missing = fields.filter((f) => f.required && (!f.showIf || f.showIf(values)) && (values[f.name] === "" || values[f.name] === null));
    if (missing.length) {
      setErrors(Object.fromEntries(missing.map((f) => [f.name, ["This field is required."]])));
      return;
    }
    setBusy(true);
    try {
      let payload = toPayload(fields, values);
      if (transform) payload = transform(payload);
      const row = id ? await send("patch", `${endpoint}${id}/`, payload) : await send("post", endpoint, payload);
      onSaved(row);
      onClose();
    } catch (err) {
      const apiErr = err as ApiError;
      setErrors(apiErr.fieldErrors ?? {});
      setMessage(apiErr.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title={title} size="lg"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={() => submit()}>Save</Button></>}>
      <form onSubmit={submit} noValidate>
        {message && <div className="mb-3"><Alert tone="bad">{message}</Alert></div>}
        <FormGrid fields={fields} values={values} setValues={setValues} errors={errors} editing={!!id} />
        <button type="submit" className="hidden" aria-hidden="true" tabIndex={-1} />
      </form>
    </Modal>
  );
}
