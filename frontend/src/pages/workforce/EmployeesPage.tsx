import { useAuth } from "@/auth/AuthContext";
import { ResourcePage } from "@/components/ResourcePage";
import { StatusBadge } from "@/components/ui";
import { useReference } from "@/lib/ReferenceContext";
import { fmtMoney } from "@/lib/format";

interface Employee { id: number; employee_code: string; full_name: string; first_name: string; last_name: string; department: number; department_name: string;
  job_title: string; employment_status: string; email?: string; phone?: string; hourly_rate?: string | null; user_name: string | null }

export default function EmployeesPage() {
  const { departments } = useReference();
  const { can } = useAuth();
  const contact = can("employees.view_contact");
  const depts = departments.map((d) => ({ value: d.id, label: d.name }));
  return (
    <ResourcePage<Employee> title="Employees" subtitle={contact ? "Operational staff profiles" : "Contact details and rates are restricted to supervisors and administrators"}
      endpoint="/workforce/employees/" defaultOrdering="employee_code"
      filters={[{ name: "department", label: "Department", type: "select", options: depts },
        { name: "employment_status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] }]}
      columns={[
        { key: "employee_code", header: "Code", sortKey: "employee_code" },
        { key: "full_name", header: "Name", sortKey: "last_name" },
        { key: "department_name", header: "Department" },
        { key: "job_title", header: "Job role" },
        { key: "status", header: "Status", render: (e) => <StatusBadge status={e.employment_status} /> },
        ...(contact ? [
          { key: "email", header: "Email", render: (e: Employee) => e.email || "—" },
          { key: "phone", header: "Phone", render: (e: Employee) => e.phone || "—" },
          { key: "rate", header: "Hourly rate", align: "right" as const, render: (e: Employee) => fmtMoney(e.hourly_rate) },
        ] : []),
        { key: "user", header: "System user", render: (e) => e.user_name ?? "—" },
      ]}
      form={{ perm: "employees.manage", noun: "employee", initial: { employment_status: "ACTIVE" }, fields: [
        { name: "employee_code", label: "Employee code", required: true, readOnlyOnEdit: true },
        { name: "first_name", label: "First name", required: true }, { name: "last_name", label: "Last name", required: true },
        { name: "department", label: "Department", type: "select", options: depts, required: true },
        { name: "job_title", label: "Job role", required: true },
        { name: "employment_status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] },
        { name: "email", label: "Email" }, { name: "phone", label: "Phone" },
        { name: "hourly_rate", label: "Hourly rate (overtime costing)", type: "number", step: "0.01" },
      ] }} />
  );
}
