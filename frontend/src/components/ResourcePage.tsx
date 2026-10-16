import { useEffect, useState, type ReactNode } from "react";
import type { Option, Paged } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { useApi } from "@/hooks/useApi";
import { useDebounced } from "@/hooks/useDebounced";
import { useUrlState } from "@/hooks/useUrlState";
import { Button, Card, Input, PageHeader, Select, useToast } from "./ui";
import { DataTable, FilterBar, FilterField, Pagination, ResourceFormDialog, type Column, type FormField } from "./data";

export interface FilterDef {
  name: string;
  label: string;
  type: "select" | "text" | "date" | "boolean";
  options?: Option[];
}

export interface ResourcePageProps<T> {
  title: string;
  subtitle?: ReactNode;
  endpoint: string;
  columns: Column<T>[];
  filters?: FilterDef[];
  search?: boolean;
  defaultOrdering?: string;
  paged?: boolean;
  form?: {
    fields: FormField[];
    perm: string;
    noun: string;
    editable?: (row: T) => boolean;
    initial?: Record<string, unknown>;
    transform?: (payload: Record<string, unknown>) => Record<string, unknown>;
  };
  rowActions?: (row: T, reload: () => void) => ReactNode;
  headerActions?: ReactNode;
  pageSize?: number;
  embedded?: boolean;
  fixedParams?: Record<string, string>;
}

export function ResourcePage<T extends { id: number }>(props: ResourcePageProps<T>) {
  const { title, subtitle, endpoint, columns, filters = [], search = true, defaultOrdering = "", paged = true, form,
    rowActions, headerActions, pageSize = 25, embedded, fixedParams } = props;
  const { can } = useAuth();
  const toast = useToast();
  const defaults: Record<string, string> = { page: "1", search: "", ordering: defaultOrdering };
  filters.forEach((f) => (defaults[f.name] = ""));
  const [state, update, reset] = useUrlState(defaults);
  const [searchText, setSearchText] = useState(state.search);
  const debouncedSearch = useDebounced(searchText);
  useEffect(() => {
    if (debouncedSearch !== state.search) update({ search: debouncedSearch });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch]);

  const params: Record<string, unknown> = { ...state, ...fixedParams };
  if (paged) params.page_size = pageSize;
  else delete params.page;
  const { data, loading, error, reload } = useApi<Paged<T> | T[]>(endpoint, params);
  const rows = Array.isArray(data) ? data : data?.results;
  const [editing, setEditing] = useState<T | null | undefined>(undefined);

  const canManage = form ? can(form.perm) : false;
  const allColumns: Column<T>[] = [...columns];
  if (rowActions || (form && canManage)) {
    allColumns.push({
      key: "_actions", header: <span className="sr-only">Actions</span>, align: "right",
      render: (row) => (
        <div className="flex justify-end gap-1">
          {rowActions?.(row, reload)}
          {form && canManage && (!form.editable || form.editable(row)) && (
            <Button size="sm" variant="ghost" onClick={() => setEditing(row)} aria-label={`Edit ${form.noun}`}>Edit</Button>
          )}
        </div>
      ),
    });
  }

  const body = (
    <Card bodyClass="p-0">
      {(search || filters.length > 0) && (
        <FilterBar onReset={() => { setSearchText(""); reset(); }}>
          {search && (
            <FilterField label="Search" width="w-56">
              <Input type="search" value={searchText} onChange={(e) => setSearchText(e.target.value)} placeholder="Search…" />
            </FilterField>
          )}
          {filters.map((f) => (
            <FilterField key={f.name} label={f.label}>
              {f.type === "select" || f.type === "boolean" ? (
                <Select value={state[f.name] ?? ""} onChange={(e) => update({ [f.name]: e.target.value })}>
                  <option value="">All</option>
                  {(f.type === "boolean" ? [{ value: "true", label: "Yes" }, { value: "false", label: "No" }] : f.options ?? [])
                    .map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </Select>
              ) : (
                <Input type={f.type === "date" ? "date" : "text"} value={state[f.name] ?? ""}
                  onChange={(e) => update({ [f.name]: e.target.value })} />
              )}
            </FilterField>
          ))}
        </FilterBar>
      )}
      <DataTable columns={allColumns} rows={rows} loading={loading} error={error} onRetry={reload} rowKey={(r) => r.id}
        ordering={state.ordering} onOrder={(o) => update({ ordering: o })} caption={title} />
      {paged && data && !Array.isArray(data) && (
        <Pagination count={data.count} page={Number(state.page) || 1} pageSize={pageSize}
          onPage={(p) => update({ page: String(p) }, { resetPage: false })} />
      )}
    </Card>
  );

  return (
    <div>
      {!embedded && (
        <PageHeader title={title} subtitle={subtitle} actions={<>
          {headerActions}
          {form && canManage && <Button variant="primary" icon="plus" onClick={() => setEditing(null)}>New {form.noun}</Button>}
        </>} />
      )}
      {embedded && form && canManage && (
        <div className="mb-2 flex justify-end"><Button variant="primary" size="sm" icon="plus" onClick={() => setEditing(null)}>New {form.noun}</Button></div>
      )}
      {body}
      {form && (
        <ResourceFormDialog open={editing !== undefined} onClose={() => setEditing(undefined)}
          title={editing ? `Edit ${form.noun}` : `New ${form.noun}`} endpoint={endpoint} fields={form.fields}
          initial={(editing ?? form.initial ?? {}) as Record<string, unknown>} id={editing?.id ?? null}
          transform={form.transform}
          onSaved={() => { toast.success(`${form.noun[0].toUpperCase()}${form.noun.slice(1)} saved`); reload(); }} />
      )}
    </div>
  );
}
