import { ResourcePage } from "@/components/ResourcePage";
import { useReference } from "@/lib/ReferenceContext";
import { fmtMoney } from "@/lib/format";
import { COST_CATEGORIES } from "./common";

interface Budget { id: number; year: number; month: number; department: number | null; department_name: string | null; category: string; category_label: string; amount: string; currency: string; notes: string }

const MONTHS = Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: new Date(Date.UTC(2000, i, 1)).toLocaleString("en-GB", { month: "long", timeZone: "UTC" }) }));

export default function BudgetsPage() {
  const { departments } = useReference();
  const depts = departments.map((d) => ({ value: d.id, label: d.name }));
  const year = new Date().getFullYear();
  return (
    <ResourcePage<Budget> title="Budgets" subtitle="Monthly budget lines by department and category. Analytics prorate them to the selected period."
      endpoint="/costs/budgets/" search={false} pageSize={50}
      filters={[{ name: "year", label: "Year", type: "select", options: [year - 1, year, year + 1].map((y) => ({ value: y, label: String(y) })) },
        { name: "month", label: "Month", type: "select", options: MONTHS }, { name: "department", label: "Department", type: "select", options: depts },
        { name: "category", label: "Category", type: "select", options: COST_CATEGORIES }]}
      columns={[{ key: "period", header: "Month", render: (b) => `${MONTHS[b.month - 1].label} ${b.year}` },
        { key: "dept", header: "Department", render: (b) => b.department_name ?? "All" }, { key: "category_label", header: "Category" },
        { key: "amount", header: "Budget", align: "right", render: (b) => fmtMoney(b.amount, { currency: b.currency }) }, { key: "notes", header: "Notes" }]}
      form={{ perm: "budgets.manage", noun: "budget line", initial: { year, month: new Date().getMonth() + 1 }, fields: [
        { name: "year", label: "Year", type: "number", required: true }, { name: "month", label: "Month", type: "select", options: MONTHS, required: true },
        { name: "department", label: "Department", type: "select", options: depts }, { name: "category", label: "Category", type: "select", options: COST_CATEGORIES, required: true },
        { name: "amount", label: "Amount", type: "number", step: "0.01", required: true }, { name: "notes", label: "Notes", full: true },
      ] }} />
  );
}
