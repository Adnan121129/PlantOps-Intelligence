import {
  createContext, forwardRef, useCallback, useContext, useEffect, useId, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "./Icon";

export { Icon } from "./Icon";

// ------------------------------------------------------------------ Button
type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:bg-accent/90 border border-transparent",
  secondary: "bg-surface text-ink border border-border-strong hover:bg-sunken",
  ghost: "bg-transparent text-ink-2 border border-transparent hover:bg-sunken hover:text-ink",
  danger: "bg-bad text-white border border-transparent hover:bg-bad/90",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  icon?: IconName;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, loading, className = "", children, disabled, type = "button", ...rest }, ref,
) {
  const sizing = size === "sm" ? "h-7 px-2.5 text-xs gap-1.5" : "h-8 px-3 text-sm gap-2";
  return (
    <button ref={ref} type={type} disabled={disabled || loading} aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center rounded-md font-medium transition-colors whitespace-nowrap
        disabled:opacity-50 disabled:cursor-not-allowed ${sizing} ${VARIANTS[variant]} ${className}`} {...rest}>
      {loading ? <Spinner size={14} /> : icon ? <Icon name={icon} size={size === "sm" ? 14 : 16} /> : null}
      {children}
    </button>
  );
});

export function LinkButton({ to, children, icon, variant = "secondary", size = "md" }:
  { to: string; children: ReactNode; icon?: IconName; variant?: Variant; size?: "sm" | "md" }) {
  const sizing = size === "sm" ? "h-7 px-2.5 text-xs gap-1.5" : "h-8 px-3 text-sm gap-2";
  return (
    <Link to={to} className={`inline-flex items-center rounded-md font-medium ${sizing} ${VARIANTS[variant]}`}>
      {icon && <Icon name={icon} size={size === "sm" ? 14 : 16} />}
      {children}
    </Link>
  );
}

// ------------------------------------------------------------------ Feedback
export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  return (
    <span role={label ? "status" : undefined} className="inline-flex items-center gap-2 text-muted">
      <svg width={size} height={size} viewBox="0 0 24 24" className="animate-spin" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" fill="none" opacity="0.25" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
      </svg>
      {label && <span className="text-sm">{label}</span>}
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="flex items-center justify-center py-12"><Spinner label={label} /></div>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-sunken ${className}`} aria-hidden="true" />;
}

export function EmptyState({ title, message, icon = "info", action }: { title: string; message?: string; icon?: IconName; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <span className="rounded-full bg-sunken p-2.5 text-muted"><Icon name={icon} size={20} /></span>
      <p className="font-medium text-ink">{title}</p>
      {message && <p className="max-w-md text-sm text-muted">{message}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: { message: string; status?: number } | null; onRetry?: () => void }) {
  if (!error) return null;
  const forbidden = error.status === 403;
  return (
    <div role="alert" className="flex flex-col items-center gap-2 py-10 text-center">
      <span className="rounded-full bg-bad-soft p-2.5 text-bad"><Icon name={forbidden ? "shield" : "alert"} size={20} /></span>
      <p className="font-medium">{forbidden ? "Access restricted" : "Something went wrong"}</p>
      <p className="max-w-md text-sm text-muted">{error.message}</p>
      {onRetry && !forbidden && <Button size="sm" icon="refresh" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Alert({ tone = "info", title, children }: { tone?: "info" | "warn" | "bad" | "good"; title?: string; children?: ReactNode }) {
  const styles = { info: "bg-info-soft text-info", warn: "bg-warn-soft text-warn", bad: "bg-bad-soft text-bad", good: "bg-good-soft text-good" };
  const icon: Record<string, IconName> = { info: "info", warn: "alert", bad: "alert", good: "check" };
  return (
    <div role={tone === "bad" ? "alert" : "note"} className={`flex gap-2 rounded-md px-3 py-2 text-sm ${styles[tone]}`}>
      <Icon name={icon[tone]} className="mt-0.5" />
      <div className="text-ink">{title && <p className="font-medium">{title}</p>}{children}</div>
    </div>
  );
}

// ------------------------------------------------------------------ Badges (never colour-only: icon/label always present)
export type Tone = "neutral" | "info" | "good" | "warn" | "bad" | "accent";
const TONES: Record<Tone, string> = {
  neutral: "bg-sunken text-ink-2 border-border",
  info: "bg-info-soft text-info border-info/30",
  good: "bg-good-soft text-good border-good/30",
  warn: "bg-warn-soft text-warn border-warn/30",
  bad: "bg-bad-soft text-bad border-bad/30",
  accent: "bg-accent-soft text-accent border-accent/30",
};
const TONE_ICON: Partial<Record<Tone, IconName>> = { good: "check", warn: "clock", bad: "alert", info: "info" };

export function Badge({ tone = "neutral", children, icon, title }: { tone?: Tone; children: ReactNode; icon?: IconName | null; title?: string }) {
  const glyph = icon === null ? null : icon ?? TONE_ICON[tone];
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium whitespace-nowrap ${TONES[tone]}`}>
      {glyph && <Icon name={glyph} size={11} />}
      {children}
    </span>
  );
}

const STATUS_TONES: Record<string, Tone> = {
  // work orders
  REPORTED: "info", ASSIGNED: "info", IN_PROGRESS: "accent", AWAITING_VERIFICATION: "warn", COMPLETED: "good", CANCELLED: "neutral",
  // reports & approvals
  DRAFT: "neutral", SUBMITTED: "warn", APPROVED: "good", REJECTED: "bad", ORDERED: "good", PENDING: "warn",
  // assets
  OPERATIONAL: "good", UNDER_MAINTENANCE: "warn", OUT_OF_SERVICE: "bad", RETIRED: "neutral",
  // stock
  OK: "good", LOW: "warn", CRITICAL_LOW: "bad", OUT_OF_STOCK: "bad",
  // procurement
  ISSUED: "info", PARTIALLY_RECEIVED: "warn", RECEIVED: "good", CLOSED: "neutral",
  // alerts & incidents
  OPEN: "bad", ACKNOWLEDGED: "warn", RESOLVED: "good", DISMISSED: "neutral", INVESTIGATING: "warn",
  CRITICAL: "bad", WARNING: "warn", INFO: "info", HIGH: "bad", MEDIUM: "warn", LOW_PRIORITY: "neutral",
  // coverage
  COVERED: "good", UNDERSTAFFED: "warn", UNASSIGNED: "bad", MISSING: "bad", DRAFT_NOT_SUBMITTED: "warn",
  ON_TIME: "good", LATE: "warn", MISSED: "bad", NOT_YET_DUE: "neutral", PROJECTED: "neutral", ACTIVE: "good", INACTIVE: "neutral",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const tone = STATUS_TONES[status] ?? "neutral";
  return <Badge tone={tone}>{label ?? humanizeStatus(status)}</Badge>;
}

export function PriorityBadge({ priority }: { priority: string }) {
  const tone: Tone = priority === "CRITICAL" ? "bad" : priority === "HIGH" ? "warn" : priority === "MEDIUM" ? "info" : "neutral";
  return <Badge tone={tone} icon={priority === "CRITICAL" ? "flag" : null}>{humanizeStatus(priority)}</Badge>;
}

function humanizeStatus(s: string) {
  return s.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

// ------------------------------------------------------------------ Layout pieces
export function Card({ title, actions, children, className = "", bodyClass = "p-4", subtitle }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; subtitle?: ReactNode }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-2.5">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · PlantOps Intelligence`;
  }, [title]);
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold text-ink">{title}</h1>
        {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function DescriptionList({ items, cols = 2 }: { items: [string, ReactNode][]; cols?: 2 | 3 | 4 }) {
  const grid = { 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-2 lg:grid-cols-4" }[cols];
  return (
    <dl className={`grid grid-cols-1 gap-x-6 gap-y-3 ${grid}`}>
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-muted">{k}</dt>
          <dd className="mt-0.5 break-words text-sm text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: ReactNode }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div role="tablist" className="mb-3 flex gap-1 overflow-x-auto border-b border-border">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={active === t.id} onClick={() => onChange(t.id)}
          className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
            active === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ Form controls
export function Field({ label, error, hint, children, required, htmlFor, className = "" }:
  { label: string; error?: string[] | string; hint?: string; children: ReactNode; required?: boolean; htmlFor?: string; className?: string }) {
  const message = Array.isArray(error) ? error.join(" ") : error;
  return (
    <div className={className}>
      <label className="label" htmlFor={htmlFor}>{label}{required && <span className="text-bad" aria-hidden="true"> *</span>}</label>
      {children}
      {message ? <p className="mt-1 text-xs text-bad" role="alert">{message}</p>
        : hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ invalid, className = "", ...rest }, ref) {
    return <input ref={ref} aria-invalid={invalid || undefined} className={`input ${className}`} {...rest} />;
  });

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }>(
  function Select({ invalid, className = "", children, ...rest }, ref) {
    return <select ref={ref} aria-invalid={invalid || undefined} className={`input pr-7 ${className}`} {...rest}>{children}</select>;
  });

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function Textarea({ invalid, className = "", ...rest }, ref) {
    return <textarea ref={ref} aria-invalid={invalid || undefined} rows={3} className={`input ${className}`} {...rest} />;
  });

export function Checkbox({ label, checked, onChange, id }: { label: string; checked: boolean; onChange: (v: boolean) => void; id?: string }) {
  const autoId = useId();
  const cid = id ?? autoId;
  return (
    <label htmlFor={cid} className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input id={cid} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-border-strong accent-[rgb(var(--accent))]" />
      {label}
    </label>
  );
}

// ------------------------------------------------------------------ Modal dialog
export function Modal({ open, onClose, title, children, footer, size = "md" }:
  { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; size?: "sm" | "md" | "lg" | "xl" }) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && panel.current) {
        const focusables = panel.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    const t = setTimeout(() => {
      panel.current?.querySelector<HTMLElement>("input, select, textarea, button:not([data-close])")?.focus();
    }, 0);
    return () => { document.removeEventListener("keydown", onKey); clearTimeout(t); previous?.focus?.(); };
  }, [open, onClose]);
  if (!open) return null;
  const width = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl", xl: "max-w-5xl" }[size];
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:p-8"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className={`card w-full ${width} shadow-pop`}>
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 id={titleId} className="text-base font-semibold">{title}</h2>
          <button data-close aria-label="Close dialog" onClick={onClose} className="rounded p-1 text-muted hover:bg-sunken hover:text-ink">
            <Icon name="x" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-4 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-border px-4 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** Dialog that asks for a reason/comment before running an action (approve/reject/cancel...). */
export function ReasonDialog({ open, title, label = "Reason", required = true, confirmLabel = "Confirm", tone = "primary",
  onClose, onConfirm, description }: {
  open: boolean; title: string; label?: string; required?: boolean; confirmLabel?: string; tone?: Variant;
  onClose: () => void; onConfirm: (text: string) => Promise<void>; description?: ReactNode;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setText(""); setError(null); } }, [open]);
  const submit = async () => {
    if (required && !text.trim()) { setError(`${label} is required.`); return; }
    setBusy(true);
    try { await onConfirm(text.trim()); onClose(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant={tone} loading={busy} onClick={submit}>{confirmLabel}</Button></>}>
      {description && <div className="mb-3 text-sm text-ink-2">{description}</div>}
      <Field label={label} required={required} error={error ?? undefined}>
        <Textarea value={text} onChange={(e) => setText(e.target.value)} invalid={!!error} />
      </Field>
    </Modal>
  );
}

// ------------------------------------------------------------------ Toasts
interface Toast { id: number; tone: "good" | "bad" | "info"; message: string }
const ToastCtx = createContext<(tone: Toast["tone"], message: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "bad" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role={t.tone === "bad" ? "alert" : "status"}
            className="pointer-events-auto card flex items-start gap-2 px-3 py-2.5 shadow-pop">
            <span className={t.tone === "good" ? "text-good" : t.tone === "bad" ? "text-bad" : "text-info"}>
              <Icon name={t.tone === "good" ? "check" : t.tone === "bad" ? "alert" : "info"} />
            </span>
            <p className="text-sm">{t.message}</p>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastCtx);
  return { success: (m: string) => push("good", m), error: (m: string) => push("bad", m), info: (m: string) => push("info", m) };
}
