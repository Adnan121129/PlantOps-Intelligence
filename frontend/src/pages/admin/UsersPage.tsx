import { ResourcePage } from "@/components/ResourcePage";
import { StatusBadge } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";
import { fmtDateTime } from "@/lib/format";

interface U { id: number; username: string; first_name: string; last_name: string; email: string; role: string; role_label: string; job_title: string;
  department: number | null; department_name: string | null; assigned_units: number[]; is_active: boolean; last_login: string | null }

export const ROLE_OPTIONS = [["ADMIN", "Administrator"], ["OPERATIONS", "Operations Officer"], ["MAINTENANCE", "Maintenance Engineer"],
  ["STORE", "Store & Procurement Officer"], ["SUPERVISOR", "Shift Supervisor"], ["MANAGEMENT", "Management / Executive"]].map(([value, label]) => ({ value, label }));

export default function UsersPage() {
  const { departments, units } = useReference();
  return (
    <ResourcePage<U> title="Users & roles" subtitle="Roles grant permissions server-side. Users cannot change their own role; accounts are deactivated, never deleted."
      endpoint="/auth/users/" defaultOrdering="username"
      filters={[{ name: "role", label: "Role", type: "select", options: ROLE_OPTIONS }, { name: "is_active", label: "Active", type: "boolean" }]}
      columns={[{ key: "username", header: "Username", sortKey: "username" }, { key: "name", header: "Name", render: (u) => `${u.first_name} ${u.last_name}`.trim() || "—" },
        { key: "role", header: "Role", sortKey: "role", render: (u) => u.role_label }, { key: "department_name", header: "Department", render: (u) => u.department_name ?? "—" },
        { key: "units", header: "Assigned units", render: (u) => u.assigned_units.map((id) => units.find((x) => x.id === id)?.code).filter(Boolean).join(", ") || "—" },
        { key: "active", header: "Status", render: (u) => <StatusBadge status={u.is_active ? "ACTIVE" : "INACTIVE"} /> },
        { key: "last", header: "Last login", sortKey: "last_login", render: (u) => fmtDateTime(u.last_login) }]}
      form={{ perm: "users.manage", noun: "user", initial: { role: "OPERATIONS", is_active: true }, fields: [
        { name: "username", label: "Username", required: true, readOnlyOnEdit: true },
        { name: "password", label: "Password", type: "password", hint: "Required for new users; leave empty to keep the current password. Min. 10 characters." },
        { name: "first_name", label: "First name" }, { name: "last_name", label: "Last name" }, { name: "email", label: "Email" },
        { name: "role", label: "Role", type: "select", options: ROLE_OPTIONS, required: true },
        { name: "job_title", label: "Job title" },
        { name: "department", label: "Department", type: "select", options: departments.map((d) => ({ value: d.id, label: d.name })) },
        { name: "assigned_units", label: "Assigned units", type: "multiselect", options: units.map((u) => ({ value: u.id, label: `${u.code} · ${u.name}` })),
          hint: "Operations officers report on, and supervisors review, only these units" },
        { name: "is_active", label: "Active", type: "checkbox", hint: "Can sign in" },
      ] }} />
  );
}
