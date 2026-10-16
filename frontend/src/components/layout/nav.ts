import type { IconName } from "@/components/ui/Icon";

export interface NavItem { to: string; label: string; perm?: string }
export interface NavGroup { label: string; icon: IconName; items: NavItem[] }

/** Navigation is permission-aware for presentation only; every API call is authorised server-side. */
export const NAV: NavGroup[] = [
  { label: "Overview", icon: "dashboard", items: [
    { to: "/", label: "Executive dashboard", perm: "dashboard.view" },
    { to: "/insights", label: "Management insights", perm: "insights.view" },
    { to: "/approvals", label: "Approvals", perm: "dashboard.view" },
    { to: "/alerts", label: "Alerts", perm: "alerts.view" },
  ] },
  { label: "Operations", icon: "factory", items: [
    { to: "/operations/reports", label: "Shift reports", perm: "dashboard.view" },
    { to: "/operations/incidents", label: "Incidents", perm: "dashboard.view" },
    { to: "/operations/analytics", label: "Operations analytics", perm: "dashboard.view" },
  ] },
  { label: "Maintenance", icon: "wrench", items: [
    { to: "/assets", label: "Equipment register", perm: "assets.view" },
    { to: "/maintenance/work-orders", label: "Work orders", perm: "workorders.view" },
    { to: "/maintenance/downtime", label: "Downtime", perm: "assets.view" },
    { to: "/maintenance/schedules", label: "PM schedules", perm: "workorders.view" },
    { to: "/maintenance/calendar", label: "PM calendar", perm: "workorders.view" },
    { to: "/maintenance/analytics", label: "Maintenance analytics", perm: "workorders.view" },
  ] },
  { label: "Inventory", icon: "box", items: [
    { to: "/inventory/items", label: "Items & stock", perm: "inventory.view" },
    { to: "/inventory/transactions", label: "Stock ledger", perm: "inventory.view" },
    { to: "/procurement/requests", label: "Purchase requests", perm: "procurement.view" },
    { to: "/procurement/orders", label: "Purchase orders", perm: "procurement.view" },
    { to: "/inventory/suppliers", label: "Suppliers", perm: "inventory.view" },
    { to: "/inventory/analytics", label: "Inventory analytics", perm: "inventory.view" },
  ] },
  { label: "Workforce", icon: "users", items: [
    { to: "/workforce/employees", label: "Employees", perm: "employees.view" },
    { to: "/workforce/roster", label: "Roster & coverage", perm: "employees.view" },
    { to: "/workforce/handovers", label: "Shift handovers", perm: "employees.view" },
    { to: "/workforce/overtime", label: "Overtime", perm: "overtime.view" },
  ] },
  { label: "Costs", icon: "coins", items: [
    { to: "/costs/expenses", label: "Cost ledger", perm: "costs.view" },
    { to: "/costs/budgets", label: "Budgets", perm: "costs.view" },
    { to: "/costs/analytics", label: "Cost analytics", perm: "costs.view" },
  ] },
  { label: "Reports & BI", icon: "file", items: [
    { to: "/reports", label: "Report center", perm: "reports.view" },
    { to: "/reports/kpis", label: "KPI dictionary", perm: "dashboard.view" },
    { to: "/reports/power-bi", label: "Power BI access", perm: "bi.access" },
  ] },
  { label: "Administration", icon: "settings", items: [
    { to: "/admin/users", label: "Users & roles", perm: "users.manage" },
    { to: "/admin/reference", label: "Reference data", perm: "reference.manage" },
    { to: "/admin/alert-rules", label: "Alert rules", perm: "alerts.view" },
    { to: "/admin/settings", label: "System settings", perm: "reference.manage" },
    { to: "/admin/audit", label: "Audit log", perm: "audit.view" },
  ] },
];

const SEGMENTS: Record<string, string> = {
  operations: "Operations", maintenance: "Maintenance", inventory: "Inventory", procurement: "Procurement",
  workforce: "Workforce", costs: "Costs", reports: "Reports", admin: "Administration", assets: "Equipment",
};

export function breadcrumbsFor(pathname: string): { to: string; label: string }[] {
  if (pathname === "/") return [{ to: "/", label: "Executive dashboard" }];
  const flat = NAV.flatMap((g) => g.items);
  const parts = pathname.split("/").filter(Boolean);
  const crumbs: { to: string; label: string }[] = [];
  let acc = "";
  parts.forEach((p, i) => {
    acc += `/${p}`;
    const match = flat.find((n) => n.to === acc);
    if (match) crumbs.push({ to: acc, label: match.label });
    else if (i === 0 && SEGMENTS[p]) crumbs.push({ to: "", label: SEGMENTS[p] });
    else if (/^\d+$/.test(p)) crumbs.push({ to: acc, label: `#${p}` });
    else if (p === "new") crumbs.push({ to: acc, label: "New" });
  });
  return crumbs;
}
