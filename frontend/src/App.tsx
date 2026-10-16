import { lazy, Suspense, useCallback, useEffect, useRef, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { send } from "@/api/client";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { AppShell } from "@/components/layout/AppShell";
import { EmptyState, Loading, ToastProvider } from "@/components/ui";
import { ReferenceProvider } from "@/lib/ReferenceContext";
import { THEME_KEY, ThemeProvider, useTheme, type ThemePreference } from "@/theme/ThemeContext";
import LoginPage from "@/pages/LoginPage";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const InsightsPage = lazy(() => import("@/pages/InsightsPage"));
const ApprovalsPage = lazy(() => import("@/pages/ApprovalsPage"));
const AlertsPage = lazy(() => import("@/pages/alerts/AlertsPage"));
const AlertRulesPage = lazy(() => import("@/pages/alerts/AlertRulesPage"));
const ReportListPage = lazy(() => import("@/pages/operations/ReportListPage"));
const ReportFormPage = lazy(() => import("@/pages/operations/ReportFormPage"));
const ReportDetailPage = lazy(() => import("@/pages/operations/ReportDetailPage"));
const IncidentsPage = lazy(() => import("@/pages/operations/IncidentsPage"));
const OperationsAnalyticsPage = lazy(() => import("@/pages/operations/OperationsAnalyticsPage"));
const AssetListPage = lazy(() => import("@/pages/assets/AssetListPage"));
const AssetDetailPage = lazy(() => import("@/pages/assets/AssetDetailPage"));
const WorkOrderListPage = lazy(() => import("@/pages/maintenance/WorkOrderListPage"));
const WorkOrderDetailPage = lazy(() => import("@/pages/maintenance/WorkOrderDetailPage"));
const DowntimePage = lazy(() => import("@/pages/maintenance/DowntimePage"));
const SchedulesPage = lazy(() => import("@/pages/maintenance/SchedulesPage"));
const PmCalendarPage = lazy(() => import("@/pages/maintenance/PmCalendarPage"));
const MaintenanceAnalyticsPage = lazy(() => import("@/pages/maintenance/MaintenanceAnalyticsPage"));
const ItemListPage = lazy(() => import("@/pages/inventory/ItemListPage"));
const ItemDetailPage = lazy(() => import("@/pages/inventory/ItemDetailPage"));
const TransactionsPage = lazy(() => import("@/pages/inventory/TransactionsPage"));
const SuppliersPage = lazy(() => import("@/pages/inventory/SuppliersPage"));
const InventoryAnalyticsPage = lazy(() => import("@/pages/inventory/InventoryAnalyticsPage"));
const PurchaseRequestsPage = lazy(() => import("@/pages/procurement/PurchaseRequestsPage"));
const PurchaseRequestDetailPage = lazy(() => import("@/pages/procurement/PurchaseRequestDetailPage"));
const PurchaseOrdersPage = lazy(() => import("@/pages/procurement/PurchaseOrdersPage"));
const PurchaseOrderDetailPage = lazy(() => import("@/pages/procurement/PurchaseOrderDetailPage"));
const EmployeesPage = lazy(() => import("@/pages/workforce/EmployeesPage"));
const RosterPage = lazy(() => import("@/pages/workforce/RosterPage"));
const HandoversPage = lazy(() => import("@/pages/workforce/HandoversPage"));
const OvertimePage = lazy(() => import("@/pages/workforce/OvertimePage"));
const ExpensesPage = lazy(() => import("@/pages/costs/ExpensesPage"));
const BudgetsPage = lazy(() => import("@/pages/costs/BudgetsPage"));
const CostAnalyticsPage = lazy(() => import("@/pages/costs/CostAnalyticsPage"));
const ReportCenterPage = lazy(() => import("@/pages/reports/ReportCenterPage"));
const KpiDictionaryPage = lazy(() => import("@/pages/reports/KpiDictionaryPage"));
const PowerBiPage = lazy(() => import("@/pages/reports/PowerBiPage"));
const UsersPage = lazy(() => import("@/pages/admin/UsersPage"));
const ReferenceDataPage = lazy(() => import("@/pages/admin/ReferenceDataPage"));
const SettingsPage = lazy(() => import("@/pages/admin/SettingsPage"));
const AuditLogPage = lazy(() => import("@/pages/admin/AuditLogPage"));

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading label="Checking session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}

/** Route-level guard for presentation; the API independently rejects unauthorised requests. */
export function RequirePerm({ perm, children }: { perm: string; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(perm)) {
    return <EmptyState icon="shield" title="Access restricted" message="Your role does not include access to this page." />;
  }
  return <>{children}</>;
}

const P = (perm: string, el: ReactNode) => <RequirePerm perm={perm}>{el}</RequirePerm>;

/** On sign-in, adopt the theme saved on the user's profile unless this browser already has an explicit choice. */
function SyncThemeFromProfile() {
  const { user } = useAuth();
  const { setPreference } = useTheme();
  const synced = useRef<number | null>(null);
  useEffect(() => {
    if (!user || synced.current === user.id) return;
    synced.current = user.id;
    let local: string | null = null;
    try { local = localStorage.getItem(THEME_KEY); } catch { /* ignore */ }
    if (!local && user.theme_preference !== "system") setPreference(user.theme_preference);
  }, [user, setPreference]);
  return null;
}

function ThemedApp() {
  const { user } = useAuth();
  // Persist the theme on the user profile as well, so it follows the user across devices.
  const persist = useCallback((p: ThemePreference) => {
    if (user) send("patch", "/auth/me/", { theme_preference: p }).catch(() => undefined);
  }, [user]);
  return (
    <ThemeProvider onChange={persist}>
      <SyncThemeFromProfile />
      <ToastProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth><ReferenceProvider><AppShell /></ReferenceProvider></RequireAuth>}>
            <Route index element={<Suspense fallback={<Loading />}>{P("dashboard.view", <DashboardPage />)}</Suspense>} />
            {[
              ["insights", "insights.view", <InsightsPage />],
              ["approvals", "dashboard.view", <ApprovalsPage />],
              ["alerts", "alerts.view", <AlertsPage />],
              ["operations/reports", "dashboard.view", <ReportListPage />],
              ["operations/reports/new", "opsreports.edit", <ReportFormPage />],
              ["operations/reports/:id", "dashboard.view", <ReportDetailPage />],
              ["operations/reports/:id/edit", "opsreports.edit", <ReportFormPage />],
              ["operations/incidents", "dashboard.view", <IncidentsPage />],
              ["operations/analytics", "dashboard.view", <OperationsAnalyticsPage />],
              ["assets", "assets.view", <AssetListPage />],
              ["assets/:id", "assets.view", <AssetDetailPage />],
              ["maintenance/work-orders", "workorders.view", <WorkOrderListPage />],
              ["maintenance/work-orders/:id", "workorders.view", <WorkOrderDetailPage />],
              ["maintenance/downtime", "assets.view", <DowntimePage />],
              ["maintenance/schedules", "workorders.view", <SchedulesPage />],
              ["maintenance/calendar", "workorders.view", <PmCalendarPage />],
              ["maintenance/analytics", "workorders.view", <MaintenanceAnalyticsPage />],
              ["inventory/items", "inventory.view", <ItemListPage />],
              ["inventory/items/:id", "inventory.view", <ItemDetailPage />],
              ["inventory/transactions", "inventory.view", <TransactionsPage />],
              ["inventory/suppliers", "inventory.view", <SuppliersPage />],
              ["inventory/analytics", "inventory.view", <InventoryAnalyticsPage />],
              ["procurement/requests", "procurement.view", <PurchaseRequestsPage />],
              ["procurement/requests/:id", "procurement.view", <PurchaseRequestDetailPage />],
              ["procurement/orders", "procurement.view", <PurchaseOrdersPage />],
              ["procurement/orders/:id", "procurement.view", <PurchaseOrderDetailPage />],
              ["workforce/employees", "employees.view", <EmployeesPage />],
              ["workforce/roster", "employees.view", <RosterPage />],
              ["workforce/handovers", "employees.view", <HandoversPage />],
              ["workforce/overtime", "overtime.view", <OvertimePage />],
              ["costs/expenses", "costs.view", <ExpensesPage />],
              ["costs/budgets", "costs.view", <BudgetsPage />],
              ["costs/analytics", "costs.view", <CostAnalyticsPage />],
              ["reports", "reports.view", <ReportCenterPage />],
              ["reports/kpis", "dashboard.view", <KpiDictionaryPage />],
              ["reports/power-bi", "bi.access", <PowerBiPage />],
              ["admin/users", "users.manage", <UsersPage />],
              ["admin/reference", "reference.manage", <ReferenceDataPage />],
              ["admin/alert-rules", "alerts.view", <AlertRulesPage />],
              ["admin/settings", "reference.manage", <SettingsPage />],
              ["admin/audit", "audit.view", <AuditLogPage />],
            ].map(([path, perm, el]) => (
              <Route key={path as string} path={path as string}
                element={<Suspense fallback={<Loading />}>{P(perm as string, el as ReactNode)}</Suspense>} />
            ))}
            <Route path="*" element={<EmptyState icon="search" title="Page not found" message="The page you requested does not exist." />} />
          </Route>
        </Routes>
      </ToastProvider>
    </ThemeProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ThemedApp />
    </AuthProvider>
  );
}
