import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { get, send } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { useApi } from "@/hooks/useApi";
import { useDebounced } from "@/hooks/useDebounced";
import { fmtRelative } from "@/lib/format";
import { useTheme } from "@/theme/ThemeContext";
import { Badge, Icon, StatusBadge } from "../ui";
import { NAV, breadcrumbsFor } from "./nav";

const SIDEBAR_KEY = "plantops.sidebar";

export function AppShell() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(SIDEBAR_KEY) === "collapsed"; } catch { return false; }
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setMobileOpen(false), [location.pathname]);
  const toggleCollapsed = () => {
    setCollapsed((c) => {
      try { localStorage.setItem(SIDEBAR_KEY, c ? "expanded" : "collapsed"); } catch { /* ignore */ }
      return !c;
    });
  };
  return (
    <div className="flex h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 card px-3 py-2">
        Skip to content
      </a>
      <Sidebar collapsed={collapsed} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setMobileOpen(true)} onCollapse={toggleCollapsed} collapsed={collapsed} />
        <main id="main" className="min-w-0 flex-1 overflow-y-auto px-4 py-4 lg:px-6">
          <DemoBanner />
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function DemoBanner() {
  const { data } = useApi<{ code: string }[] | { results: { code: string }[] }>("/core/plants/");
  const plants = Array.isArray(data) ? data : data?.results ?? [];
  if (!plants.some((p) => p.code === "DEMO-CCPP")) return null;
  return (
    <p className="mb-3 rounded-md border border-warn/30 bg-warn-soft px-3 py-1.5 text-xs text-ink">
      <strong>Demonstration environment.</strong> All plants, people and figures are synthetic demo data.
    </p>
  );
}

function Sidebar({ collapsed, mobileOpen, onClose }: { collapsed: boolean; mobileOpen: boolean; onClose: () => void }) {
  const { can } = useAuth();
  const groups = NAV.map((g) => ({ ...g, items: g.items.filter((i) => !i.perm || can(i.perm)) })).filter((g) => g.items.length);
  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={onClose} aria-hidden="true" />}
      <nav aria-label="Main navigation"
        className={`fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-surface transition-[width,transform] lg:static
          ${mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"} ${collapsed ? "lg:w-14" : "w-64"} w-64`}>
        <div className="flex h-12 items-center gap-2 border-b border-border px-3">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-ink"><Icon name="factory" /></span>
          {!collapsed && <span className="truncate text-sm font-semibold">PlantOps Intelligence</span>}
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {groups.map((g) => (
            <div key={g.label} className="mb-2">
              <p className={`flex items-center gap-2 px-3 py-1 text-2xs font-semibold uppercase tracking-wide text-muted ${collapsed ? "lg:justify-center" : ""}`}
                title={collapsed ? g.label : undefined}>
                <Icon name={g.icon} size={14} />
                <span className={collapsed ? "lg:sr-only" : ""}>{g.label}</span>
              </p>
              <ul className={collapsed ? "lg:hidden" : ""}>
                {g.items.map((i) => (
                  <li key={i.to}>
                    <NavLink to={i.to} end={i.to === "/"}
                      className={({ isActive }) => `mx-2 block rounded-md px-3 py-1.5 text-sm ${
                        isActive ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-sunken hover:text-ink"}`}>
                      {i.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </nav>
    </>
  );
}

function Topbar({ onMenu, onCollapse, collapsed }: { onMenu: () => void; onCollapse: () => void; collapsed: boolean }) {
  const location = useLocation();
  const crumbs = breadcrumbsFor(location.pathname);
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
      <button className="rounded p-1.5 text-ink-2 hover:bg-sunken lg:hidden" onClick={onMenu} aria-label="Open navigation">
        <Icon name="menu" />
      </button>
      <button className="hidden rounded p-1.5 text-ink-2 hover:bg-sunken lg:block" onClick={onCollapse}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-pressed={collapsed}>
        <Icon name="menu" />
      </button>
      <nav aria-label="Breadcrumb" className="hidden min-w-0 md:block">
        <ol className="flex items-center gap-1 text-sm text-muted">
          {crumbs.map((c, i) => (
            <li key={`${c.label}-${i}`} className="flex items-center gap-1 truncate">
              {i > 0 && <Icon name="chevronRight" size={12} />}
              {i === crumbs.length - 1 || !c.to ? (
                <span aria-current={i === crumbs.length - 1 ? "page" : undefined} className={i === crumbs.length - 1 ? "text-ink" : ""}>{c.label}</span>
              ) : <Link to={c.to} className="hover:text-ink">{c.label}</Link>}
            </li>
          ))}
        </ol>
      </nav>
      <div className="ml-auto flex items-center gap-1">
        <GlobalSearch />
        <NotificationCenter />
        <ThemeToggle />
        <UserMenu />
      </div>
    </header>
  );
}

export function ThemeToggle() {
  const { resolved, toggle } = useTheme();
  const next = resolved === "dark" ? "light" : "dark";
  return (
    <button onClick={toggle} className="rounded p-1.5 text-ink-2 hover:bg-sunken hover:text-ink"
      aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
      <Icon name={resolved === "dark" ? "sun" : "moon"} />
    </button>
  );
}

function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && close();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, close]);
  return ref;
}

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<{ type: string; label: string; link: string }[]>([]);
  const term = useDebounced(q, 250);
  const navigate = useNavigate();
  const ref = useDismiss(open, () => setOpen(false));
  useEffect(() => {
    if (term.trim().length < 2) { setResults([]); return; }
    get<{ results: typeof results }>("/analytics/search/", { q: term }).then((r) => setResults(r.results)).catch(() => setResults([]));
  }, [term]);
  return (
    <div ref={ref} className="relative hidden sm:block">
      <label className="sr-only" htmlFor="global-search">Search assets, work orders, items</label>
      <div className="flex items-center gap-1.5 rounded-md border border-border bg-raised px-2">
        <Icon name="search" size={14} className="text-muted" />
        <input id="global-search" value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
          placeholder="Search…" className="h-7 w-44 bg-transparent text-sm outline-none placeholder:text-muted lg:w-64"
          role="combobox" aria-expanded={open && results.length > 0} aria-controls="global-search-results" autoComplete="off" />
      </div>
      {open && term.length >= 2 && (
        <ul id="global-search-results" role="listbox" className="card absolute right-0 z-40 mt-1 max-h-80 w-80 overflow-y-auto py-1 shadow-pop">
          {results.length === 0 && <li className="px-3 py-2 text-sm text-muted">No matches</li>}
          {results.map((r) => (
            <li key={r.link + r.label} role="option" aria-selected="false">
              <button className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-sunken"
                onClick={() => { navigate(r.link); setOpen(false); setQ(""); }}>
                <Badge>{r.type}</Badge><span className="truncate">{r.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface AlertSummary {
  active: number;
  by_severity: Record<string, number>;
  latest: { id: number; title: string; severity: string; link: string; last_detected_at: string }[];
  unread_notifications: number;
}
interface Notification { id: number; title: string; message: string; link: string; created_at: string; read_at: string | null }

function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const summary = useApi<AlertSummary>("/alerts/alerts/summary/");
  const notes = useApi<{ results: Notification[] }>(open ? "/alerts/notifications/" : null, { page_size: 8 });
  const navigate = useNavigate();
  useEffect(() => {
    const t = setInterval(summary.reload, 60_000);
    return () => clearInterval(t);
  }, [summary.reload]);
  const count = (summary.data?.unread_notifications ?? 0) + (summary.data?.by_severity.CRITICAL ?? 0);
  const go = async (n?: Notification, link?: string) => {
    if (n && !n.read_at) await send("post", `/alerts/notifications/${n.id}/read/`).catch(() => undefined);
    setOpen(false);
    summary.reload();
    if (link) navigate(link);
  };
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} className="relative rounded p-1.5 text-ink-2 hover:bg-sunken hover:text-ink"
        aria-label={`Notifications${count ? ` (${count} need attention)` : ""}`} aria-expanded={open}>
        <Icon name="bell" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 min-w-[1rem] rounded-full bg-bad px-1 text-center text-[10px] font-semibold leading-4 text-white">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>
      {open && (
        <div className="card absolute right-0 z-40 mt-1 w-[22rem] shadow-pop">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <p className="text-sm font-semibold">Notifications</p>
            <button className="text-xs link" onClick={async () => { await send("post", "/alerts/notifications/read-all/"); notes.reload(); summary.reload(); }}>
              Mark all read
            </button>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {summary.data && summary.data.active > 0 && (
              <div className="border-b border-border px-3 py-2">
                <p className="mb-1 text-xs font-medium text-ink-2">Active alerts ({summary.data.active})</p>
                {summary.data.latest.map((a) => (
                  <button key={a.id} onClick={() => go(undefined, a.link || "/alerts")} className="flex w-full items-start gap-2 rounded px-1 py-1 text-left hover:bg-sunken">
                    <StatusBadge status={a.severity} /><span className="text-sm">{a.title}</span>
                  </button>
                ))}
                <Link to="/alerts" onClick={() => setOpen(false)} className="mt-1 inline-block text-xs link">Open alert centre</Link>
              </div>
            )}
            {notes.data?.results.length === 0 && <p className="px-3 py-4 text-sm text-muted">No notifications.</p>}
            {notes.data?.results.map((n) => (
              <button key={n.id} onClick={() => go(n, n.link)} className="block w-full border-b border-border px-3 py-2 text-left last:border-0 hover:bg-sunken">
                <p className={`text-sm ${n.read_at ? "text-ink-2" : "font-medium"}`}>
                  {!n.read_at && <span className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" aria-label="Unread" />}
                  {n.title}
                </p>
                {n.message && <p className="line-clamp-2 text-xs text-muted">{n.message}</p>}
                <p className="text-2xs text-muted">{fmtRelative(n.created_at)}</p>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const { preference, setPreference } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const navigate = useNavigate();
  if (!user) return null;
  const initials = (user.display_name || user.username).split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label="User menu"
        className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-sunken">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent">{initials}</span>
        <span className="hidden text-left leading-tight xl:block">
          <span className="block text-sm">{user.display_name}</span>
          <span className="block text-2xs text-muted">{user.role_label}</span>
        </span>
      </button>
      {open && (
        <div className="card absolute right-0 z-40 mt-1 w-60 py-1 shadow-pop" role="menu">
          <div className="border-b border-border px-3 py-2">
            <p className="text-sm font-medium">{user.display_name}</p>
            <p className="text-xs text-muted">{user.role_label}</p>
          </div>
          <div className="px-3 py-2">
            <p className="mb-1 text-xs text-ink-2">Theme</p>
            <div className="flex gap-1" role="radiogroup" aria-label="Theme preference">
              {(["light", "dark", "system"] as const).map((t) => (
                <button key={t} role="radio" aria-checked={preference === t} onClick={() => setPreference(t)}
                  className={`flex-1 rounded border px-2 py-1 text-xs capitalize ${preference === t ? "border-accent bg-accent-soft text-accent" : "border-border hover:bg-sunken"}`}>
                  {t}
                </button>
              ))}
            </div>
          </div>
          <button role="menuitem" onClick={async () => { await logout(); navigate("/login"); }}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-sunken">
            <Icon name="logout" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
