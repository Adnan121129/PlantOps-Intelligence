/**
 * Chart building blocks. Conventions (from the data-viz method used for this project):
 *  - colours come from the validated palette in ThemeContext (CHART), switched per theme;
 *  - thin marks: bars <= 24px with 4px rounded ends, 2px lines, hairline solid grids;
 *  - one y-axis per chart (never dual-axis); a legend for >= 2 series;
 *  - every chart has a table view (light-mode palette has sub-3:1 slots, so the table is the relief);
 *  - hover tooltips on every mark; clicking a mark drills through when a handler is provided.
 */
import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Kpi } from "@/api/types";
import { fmtCompact, fmtMoney, fmtNumber } from "@/lib/format";
import { useChartColors } from "@/theme/ThemeContext";
import { Badge, EmptyState, Icon } from "../ui";

export interface TableCol<T> { key: keyof T & string; label: string; format?: (v: unknown, row: T) => ReactNode; align?: "right" }

export function ChartCard<T extends object>({ title, subtitle, rows, columns, children, empty, height = 240, actions, summary }: {
  title: string; subtitle?: ReactNode; rows: T[]; columns: TableCol<T>[]; children: ReactNode; empty?: string;
  height?: number; actions?: ReactNode; summary?: string;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const titleId = useId();
  const hasData = rows.length > 0;
  return (
    <section className="card flex min-w-0 flex-col" aria-labelledby={titleId}>
      <header className="flex items-start justify-between gap-2 px-4 pb-1 pt-3">
        <div className="min-w-0">
          <h2 id={titleId} className="text-sm font-semibold">{title}</h2>
          {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {actions}
          {hasData && (
            <div className="flex rounded-md border border-border p-0.5" role="group" aria-label="View">
              <button aria-pressed={view === "chart"} onClick={() => setView("chart")} title="Chart view"
                className={`rounded px-1.5 py-0.5 ${view === "chart" ? "bg-sunken text-ink" : "text-muted"}`}>
                <Icon name="bars" size={14} /><span className="sr-only">Chart</span>
              </button>
              <button aria-pressed={view === "table"} onClick={() => setView("table")} title="Table view"
                className={`rounded px-1.5 py-0.5 ${view === "table" ? "bg-sunken text-ink" : "text-muted"}`}>
                <Icon name="table" size={14} /><span className="sr-only">Table</span>
              </button>
            </div>
          )}
        </div>
      </header>
      <div className="px-2 pb-3">
        {!hasData ? (
          <EmptyState title="No data for this period" message={empty ?? "No records match the selected period and scope."} icon="bars" />
        ) : view === "chart" ? (
          <div style={{ height }} role="img" aria-label={summary ?? `${title} chart. Switch to table view for values.`}>{children}</div>
        ) : (
          <div className="max-h-72 overflow-auto px-2">
            <table className="w-full text-sm">
              <caption className="sr-only">{title}</caption>
              <thead><tr className="border-b border-border">{columns.map((c) => (
                <th key={c.key} scope="col" className={`th ${c.align === "right" ? "text-right" : ""}`}>{c.label}</th>))}</tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-border last:border-0">
                    {columns.map((c) => (
                      <td key={c.key} className={`px-3 py-1.5 ${c.align === "right" ? "text-right tabular" : ""}`}>
                        {c.format ? c.format((r as Record<string, unknown>)[c.key], r) : String((r as Record<string, unknown>)[c.key] ?? "—")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function TooltipBox({ active, payload, label, valueFormat, labelFormat }: {
  active?: boolean; payload?: { name?: string; value?: number | string | null; color?: string; dataKey?: string }[];
  label?: string | number; valueFormat?: (v: number) => string; labelFormat?: (l: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="card px-3 py-2 text-xs shadow-pop">
      {label !== undefined && <p className="mb-1 font-medium text-ink">{labelFormat ? labelFormat(String(label)) : label}</p>}
      {payload.filter((p) => p.value !== null && p.value !== undefined).map((p) => (
        <p key={String(p.dataKey)} className="flex items-center gap-2 text-ink-2">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color }} aria-hidden="true" />
          <span>{p.name}</span>
          <span className="ml-auto tabular text-ink">{valueFormat ? valueFormat(Number(p.value)) : fmtNumber(Number(p.value), 2)}</span>
        </p>
      ))}
    </div>
  );
}

const axisProps = (c: ReturnType<typeof useChartColors>) => ({
  tick: { fill: c.tick, fontSize: 11 }, tickLine: false, axisLine: { stroke: c.axis }, stroke: c.axis,
});

export interface Series { key: string; label: string }
type Row = Record<string, unknown>;

/** Vertical stacked/grouped columns over a category axis (e.g. time buckets). */
export function ColumnChart<T extends object>({ data, x, series, stacked = true, valueFormat, xFormat, onSelect }: {
  data: T[]; x: keyof T & string; series: Series[]; stacked?: boolean; valueFormat?: (v: number) => string;
  xFormat?: (v: string) => string; onSelect?: (row: T) => void;
}) {
  const c = useChartColors();
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data as Row[]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="25%">
        <CartesianGrid vertical={false} stroke={c.grid} />
        <XAxis dataKey={x as string} {...axisProps(c)} tickFormatter={xFormat} minTickGap={16} />
        <YAxis {...axisProps(c)} axisLine={false} width={48} tickFormatter={(v) => fmtCompact(Number(v))} />
        <Tooltip cursor={{ fill: c.grid, opacity: 0.4 }} content={<TooltipBox valueFormat={valueFormat} labelFormat={xFormat} />} />
        {series.length > 1 && <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 11, color: c.tick }} />}
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} stackId={stacked ? "a" : undefined} fill={c.series[i % c.series.length]}
            maxBarSize={24} animationDuration={400} stroke={c.surface} strokeWidth={stacked ? 1 : 0}
            radius={stacked ? (i === series.length - 1 ? [4, 4, 0, 0] : 0) : [4, 4, 0, 0]}
            cursor={onSelect ? "pointer" : undefined}
            onClick={onSelect ? (d: { payload?: unknown }) => d?.payload && onSelect(d.payload as T) : undefined} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Horizontal ranked bars, one series (e.g. top assets by downtime). Label column on the left. */
export function RankedBars<T extends object>({ data, label, value, valueFormat, onSelect, colorFor, height }: {
  data: T[]; label: keyof T & string; value: keyof T & string; valueFormat?: (v: number) => string; onSelect?: (row: T) => void;
  colorFor?: (row: T) => string | undefined; height?: number;
}) {
  const c = useChartColors();
  return (
    <ResponsiveContainer width="100%" height={height ?? "100%"}>
      <BarChart data={data as Row[]} layout="vertical" margin={{ top: 4, right: 48, bottom: 0, left: 8 }} barCategoryGap="22%">
        <CartesianGrid horizontal={false} stroke={c.grid} />
        <XAxis type="number" {...axisProps(c)} tickFormatter={(v) => fmtCompact(Number(v))} />
        <YAxis type="category" dataKey={label as string} {...axisProps(c)} axisLine={false} width={110} interval={0} />
        <Tooltip cursor={{ fill: c.grid, opacity: 0.4 }} content={<TooltipBox valueFormat={valueFormat} />} />
        <Bar dataKey={value as string} name="Value" maxBarSize={18} animationDuration={400} radius={[0, 4, 4, 0]} fill={c.series[0]}
          cursor={onSelect ? "pointer" : undefined}
          onClick={onSelect ? (d: { payload?: unknown }) => d?.payload && onSelect(d.payload as T) : undefined}
          label={{ position: "right", fill: c.tick, fontSize: 11, formatter: (v: unknown) => (valueFormat ? valueFormat(Number(v)) : fmtCompact(Number(v))) }}>
          {colorFor && data.map((row, i) => <Cell key={i} fill={colorFor(row) ?? c.series[0]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Lines over time on ONE axis, with an optional target series drawn as a thin dashed threshold. */
export function TrendChart<T extends object>({ data, x, series, target, valueFormat, xFormat, referenceY }: {
  data: T[]; x: keyof T & string; series: Series[]; target?: Series; valueFormat?: (v: number) => string;
  xFormat?: (v: string) => string; referenceY?: { value: number; label: string };
}) {
  const c = useChartColors();
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data as Row[]} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke={c.grid} />
        <XAxis dataKey={x as string} {...axisProps(c)} tickFormatter={xFormat} minTickGap={24} />
        <YAxis {...axisProps(c)} axisLine={false} width={48} tickFormatter={(v) => fmtCompact(Number(v))} />
        <Tooltip cursor={{ stroke: c.axis }} content={<TooltipBox valueFormat={valueFormat} labelFormat={xFormat} />} />
        {(series.length > 1 || target) && <Legend iconType="plainline" iconSize={12} wrapperStyle={{ fontSize: 11, color: c.tick }} />}
        {referenceY && <ReferenceLine y={referenceY.value} stroke={c.target} strokeDasharray="4 4"
          label={{ value: referenceY.label, fill: c.tick, fontSize: 10, position: "insideTopRight" }} />}
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={c.series[i % c.series.length]} strokeWidth={2} animationDuration={400}
            dot={false} activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2 }} connectNulls={false} />
        ))}
        {target && <Line type="monotone" dataKey={target.key} name={target.label} stroke={c.target} strokeWidth={1.5}
          strokeDasharray="5 4" animationDuration={400} dot={false} activeDot={false} connectNulls={false} />}
      </LineChart>
    </ResponsiveContainer>
  );
}

// ------------------------------------------------------------------ KPI stat tile
export function KpiCard({ kpi, currency, compact }: { kpi: Kpi; currency?: string; compact?: boolean }) {
  const [showDef, setShowDef] = useState(false);
  const defId = useId();
  const insufficient = kpi.status === "insufficient_data" || kpi.value === null;
  const isMoney = kpi.unit === currency || kpi.unit === "currency";
  const value = insufficient ? null
    : isMoney ? fmtMoney(kpi.value, { compact: Math.abs(kpi.value ?? 0) >= 100000 })
      : kpi.unit === "%" ? `${fmtNumber(kpi.value, 1)}%`
        : fmtNumber(kpi.value, Math.abs(kpi.value ?? 0) >= 100 ? 0 : Math.abs(kpi.value ?? 0) < 10 ? 2 : 1);
  const unitLabel = !isMoney && kpi.unit !== "%" ? kpi.unit : null;
  const content = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-ink-2">{kpi.label}</p>
        <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowDef((s) => !s); }}
          aria-expanded={showDef} aria-controls={defId} aria-label={`Definition of ${kpi.label}`}
          className="rounded p-0.5 text-muted hover:bg-sunken hover:text-ink">
          <Icon name="info" size={13} />
        </button>
      </div>
      {insufficient ? (
        <p className="mt-1.5 text-sm font-medium text-muted">Insufficient data</p>
      ) : (
        <p className={`mt-1 font-semibold text-ink ${compact ? "text-xl" : "text-2xl"}`}>
          {value}{unitLabel && <span className="ml-1 text-xs font-normal text-muted">{unitLabel}</span>}
        </p>
      )}
      <div className="mt-1 flex flex-wrap items-center gap-1 text-2xs text-muted">
        <span>{kpi.period_type === "snapshot" ? "Current" : "Selected period"}</span>
        {kpi.status === "low_confidence" && <Badge tone="warn">Low sample</Badge>}
        {kpi.link && (
          <Link to={kpi.link} className="ml-auto inline-flex items-center gap-0.5 text-accent hover:underline"
            aria-label={`View records behind ${kpi.label}`}>
            View records <Icon name="chevronRight" size={11} />
          </Link>
        )}
      </div>
      {showDef && (
        <div id={defId} className="mt-2 rounded border border-border bg-raised p-2 text-2xs text-ink-2">
          <p>{kpi.definition}</p>
          <p className="mt-1 font-mono text-[10px] text-muted">{kpi.formula}</p>
          {kpi.notes && <p className="mt-1 text-muted">{kpi.notes}</p>}
        </div>
      )}
    </>
  );
  return <div className="card p-3" data-testid={`kpi-${kpi.code}`}>{content}</div>;
}
