import { Link } from "react-router-dom";
import { useOptions } from "@/components/data";
import { ResourcePage } from "@/components/ResourcePage";
import { Badge, StatusBadge } from "@/components/ui";
import { fmtDateTime, fmtMoney, fmtNumber } from "@/lib/format";

export interface Item {
  id: number; item_code: string; name: string; category: number; category_name: string; uom: string; current_stock: string; unit_cost: string;
  stock_value: string; min_stock_level: string; reorder_quantity: string; storage_location: string; supplier_name: string | null;
  criticality: string; stock_status: string; last_movement_at: string | null; is_active: boolean; description: string;
  preferred_supplier: number | null; compatibility_notes: string; compatible_assets: number[];
}

export const UOMS = [["EA", "Each"], ["SET", "Set"], ["KG", "Kilogram"], ["L", "Litre"], ["M", "Metre"], ["BOX", "Box"]].map(([value, label]) => ({ value, label }));

export default function ItemListPage() {
  const categories = useOptions("/inventory/categories/", (c) => String(c.name));
  const suppliers = useOptions("/inventory/suppliers/", (s) => String(s.name));
  const assets = useOptions("/assets/equipment/", (a) => `${a.asset_tag} · ${a.name}`);
  return (
    <ResourcePage<Item> title="Items & stock" subtitle="Stock on hand is maintained by the stock ledger and cannot be edited directly"
      endpoint="/inventory/items/" defaultOrdering="item_code"
      filters={[
        { name: "stock_status", label: "Stock status", type: "select", options: [
          { value: "LOW", label: "At/below reorder point" }, { value: "CRITICAL_LOW", label: "Critical spares low" },
          { value: "OUT_OF_STOCK", label: "Out of stock" }, { value: "OK", label: "Above reorder point" }] },
        { name: "category", label: "Category", type: "select", options: categories },
        { name: "criticality", label: "Criticality", type: "select", options: [{ value: "CRITICAL", label: "Critical spare" }, { value: "STANDARD", label: "Standard" }] },
        { name: "is_active", label: "Active", type: "boolean" },
      ]}
      columns={[
        { key: "item_code", header: "Item", sortKey: "item_code", render: (i) => <Link className="link font-medium" to={`/inventory/items/${i.id}`}>{i.item_code}</Link> },
        { key: "name", header: "Name", sortKey: "name", render: (i) => <>{i.name}{i.criticality === "CRITICAL" && <span className="ml-1"><Badge tone="accent" icon="flag">Critical</Badge></span>}</> },
        { key: "category", header: "Category", render: (i) => i.category_name },
        { key: "stock", header: "Stock", align: "right", sortKey: "current_stock", render: (i) => `${fmtNumber(i.current_stock, 3)} ${i.uom}` },
        { key: "min", header: "Reorder point", align: "right", render: (i) => fmtNumber(i.min_stock_level, 3) },
        { key: "status", header: "Status", render: (i) => <StatusBadge status={i.stock_status} /> },
        { key: "value", header: "Value", align: "right", render: (i) => fmtMoney(i.stock_value) },
        { key: "loc", header: "Location", render: (i) => i.storage_location || "—" },
        { key: "last", header: "Last movement", sortKey: "last_movement_at", render: (i) => fmtDateTime(i.last_movement_at) },
      ]}
      form={{
        perm: "inventory.manage", noun: "item", initial: { uom: "EA", criticality: "STANDARD", is_active: true, min_stock_level: 0, reorder_quantity: 0 },
        fields: [
          { name: "item_code", label: "Item code", required: true, readOnlyOnEdit: true },
          { name: "name", label: "Name", required: true },
          { name: "category", label: "Category", type: "select", options: categories, required: true },
          { name: "uom", label: "Unit of measure", type: "select", options: UOMS, required: true },
          { name: "min_stock_level", label: "Reorder point (minimum stock)", type: "number", step: "any", required: true },
          { name: "reorder_quantity", label: "Reorder quantity", type: "number", step: "any", required: true },
          { name: "criticality", label: "Criticality", type: "select", options: [{ value: "CRITICAL", label: "Critical spare" }, { value: "STANDARD", label: "Standard" }] },
          { name: "preferred_supplier", label: "Preferred supplier", type: "select", options: suppliers },
          { name: "storage_location", label: "Storage location" },
          { name: "is_active", label: "Active", type: "checkbox", hint: "Available for issue" },
          { name: "compatible_assets", label: "Compatible assets", type: "multiselect", options: assets, full: true, hint: "Ctrl/Cmd-click to select several" },
          { name: "compatibility_notes", label: "Compatibility notes", type: "textarea" },
          { name: "description", label: "Description", type: "textarea" },
        ],
      }} />
  );
}
