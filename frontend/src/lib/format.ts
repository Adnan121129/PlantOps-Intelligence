/** Formatting helpers. Timestamps are rendered in the plant's time zone (set once by ReferenceProvider). */
let plantTimeZone = "UTC";
let baseCurrency = "USD";

export function configureFormatting(opts: { timeZone?: string; currency?: string }) {
  if (opts.timeZone) plantTimeZone = opts.timeZone;
  if (opts.currency) baseCurrency = opts.currency;
}
export const getPlantTimeZone = () => plantTimeZone;
export const getCurrency = () => baseCurrency;

const nf = (opts: Intl.NumberFormatOptions) => new Intl.NumberFormat("en-US", opts);

export function fmtNumber(value: number | string | null | undefined, digits = 1): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return nf({ maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(n);
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return nf({ notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function fmtMoney(value: number | string | null | undefined, opts: { compact?: boolean; currency?: string } = {}): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return nf({
    style: "currency", currency: opts.currency ?? baseCurrency,
    notation: opts.compact ? "compact" : "standard", maximumFractionDigits: opts.compact ? 1 : 2,
  }).format(n);
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "—" : `${fmtNumber(value, digits)}%`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: plantTimeZone, year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(d);
}

/** Business dates (YYYY-MM-DD) are already local dates; format without time-zone shifting. */
export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return value;
  return new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", year: "numeric", month: "short", day: "2-digit" })
    .format(new Date(Date.UTC(y, m - 1, d)));
}

export function fmtHours(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${fmtNumber(value, 1)} h`;
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / 86400)} d ago`;
}

/** Today's date in the plant time zone (YYYY-MM-DD). */
export function plantToday(offsetDays = 0): string {
  const d = new Date(Date.now() + offsetDays * 86400000);
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: plantTimeZone, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(d);
  return parts;
}

/** Convert a <input type="datetime-local"> value (plant local wall time) to an ISO string with offset. */
export function localInputToIso(value: string): string {
  if (!value) return "";
  const [date, time] = value.split("T");
  const [y, mo, d] = date.split("-").map(Number);
  const [h, mi] = time.split(":").map(Number);
  const guess = Date.UTC(y, mo - 1, d, h, mi);
  // Offset of the plant zone at that instant (two passes handle DST edges).
  const offsetAt = (ms: number) => {
    const p = new Intl.DateTimeFormat("en-US", {
      timeZone: plantTimeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(new Date(ms));
    const get = (t: string) => Number(p.find((x) => x.type === t)?.value);
    return Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute")) - ms;
  };
  let ms = guess - offsetAt(guess);
  ms = guess - offsetAt(ms);
  return new Date(ms).toISOString();
}

/** ISO instant -> value for <input type="datetime-local"> in plant time. */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const p = new Intl.DateTimeFormat("en-CA", {
    timeZone: plantTimeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(new Date(iso));
  const g = (t: string) => p.find((x) => x.type === t)?.value ?? "00";
  return `${g("year")}-${g("month")}-${g("day")}T${g("hour")}:${g("minute")}`;
}

export function nowLocalInput(): string {
  return isoToLocalInput(new Date().toISOString());
}

export function humanize(code: string | null | undefined): string {
  if (!code) return "—";
  return code.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
