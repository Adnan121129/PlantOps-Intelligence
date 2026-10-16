import { ResourcePage } from "@/components/ResourcePage";
import { StatusBadge } from "@/components/ui";

interface Supplier { id: number; code: string; name: string; contact_name: string; email: string; phone: string; quoted_lead_time_days: number | null; is_active: boolean }

export default function SuppliersPage() {
  return (
    <ResourcePage<Supplier> title="Suppliers" endpoint="/inventory/suppliers/" defaultOrdering="name"
      filters={[{ name: "is_active", label: "Active", type: "boolean" }]}
      columns={[
        { key: "code", header: "Code" }, { key: "name", header: "Name" }, { key: "contact_name", header: "Contact" },
        { key: "email", header: "Email" }, { key: "phone", header: "Phone" },
        { key: "lead", header: "Quoted lead time", align: "right", render: (s) => s.quoted_lead_time_days === null ? "—" : `${s.quoted_lead_time_days} d` },
        { key: "active", header: "Status", render: (s) => <StatusBadge status={s.is_active ? "ACTIVE" : "INACTIVE"} /> },
      ]}
      form={{ perm: "inventory.manage", noun: "supplier", initial: { is_active: true }, fields: [
        { name: "code", label: "Code", required: true, readOnlyOnEdit: true }, { name: "name", label: "Name", required: true },
        { name: "contact_name", label: "Contact name" }, { name: "email", label: "Email" }, { name: "phone", label: "Phone" },
        { name: "quoted_lead_time_days", label: "Quoted lead time (days)", type: "number" },
        { name: "is_active", label: "Active", type: "checkbox", hint: "Available for new orders" }, { name: "address", label: "Address", type: "textarea" },
      ] }} />
  );
}
