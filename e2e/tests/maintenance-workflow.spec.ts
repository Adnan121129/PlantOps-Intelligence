import { expect, test } from "@playwright/test";
import { apiAs, login, plantLocal, toast } from "./helpers";

/**
 * Corrective-maintenance flow across roles, through the real UI:
 *  maintenance creates an asset -> operations records an incident and raises a work order ->
 *  maintenance assigns, starts, records downtime, issues a spare part, adds labour cost, returns the
 *  equipment to service and completes -> supervisor verifies -> stock, history, KPIs and exports reconcile.
 */
test("corrective maintenance end to end", async ({ page, baseURL }) => {
  const tag = `E2E-${Date.now().toString().slice(-6)}`;
  const assetName = `E2E test pump ${tag}`;
  const { api: mgr } = await apiAs(baseURL!, "manager");
  const kpi = async () => {
    const d = await (await mgr.get("/api/analytics/dashboard/")).json();
    return Object.fromEntries(d.kpis.map((k: { code: string; value: number }) => [k.code, k.value]));
  };
  const before = await kpi();
  const { api: store } = await apiAs(baseURL!, "store");
  const items = await (await store.get("/api/inventory/items/?search=LUBE-GREASE-EP2")).json();
  const grease = items.results[0];
  const stockBefore = Number(grease.current_stock);

  // 1. Maintenance engineer registers a new asset
  await login(page, "maintenance");
  await page.goto("/assets");
  await page.getByRole("button", { name: "New asset" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Asset ID").fill(tag);
  await dialog.getByLabel("Name").fill(assetName);
  await dialog.getByLabel("Category").selectOption({ label: "Pump" });
  await dialog.getByLabel("Plant unit").selectOption({ label: "BOP · Balance of Plant" });
  await dialog.getByLabel("Criticality").selectOption({ label: "High (A)" });
  await dialog.getByRole("button", { name: "Save" }).click();
  await toast(page, /asset saved/i);

  // 2. Operations officer records an incident on that asset and raises a work order from it
  await login(page, "operations");
  await page.goto("/operations/incidents");
  await page.getByRole("button", { name: "New incident" }).click();
  await dialog.getByLabel("Plant unit").selectOption({ label: "BOP · Balance of Plant" });
  await dialog.getByLabel("Asset (if equipment related)").selectOption({ label: `${tag} · ${assetName}` });
  await dialog.getByLabel("Occurred at").fill(plantLocal(-130));
  await dialog.getByLabel("Severity").selectOption("HIGH");
  await dialog.getByLabel("Title").fill(`Seal leak on ${tag}`);
  await dialog.getByLabel("Description").fill("Visible leakage at the mechanical seal; pump stopped.");
  await dialog.getByRole("button", { name: "Save" }).click();
  await toast(page, /incident saved/i);
  const row = page.getByRole("row").filter({ hasText: `Seal leak on ${tag}` });
  await row.getByRole("button", { name: "Raise WO" }).click();
  await expect(dialog.getByLabel("Title")).toHaveValue(`Seal leak on ${tag}`);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(/\/maintenance\/work-orders\/\d+$/);
  const woId = page.url().split("/").pop()!;
  await expect(page.getByText("Reported", { exact: true }).first()).toBeVisible();
  // Fault reporters cannot plan or assign
  await expect(page.getByRole("button", { name: "Assign" })).toHaveCount(0);

  // 3. Maintenance assigns, starts work and records the outage
  await login(page, "maintenance");
  await page.goto(`/maintenance/work-orders/${woId}`);
  await page.getByRole("button", { name: "Assign" }).click();
  await dialog.getByLabel("Technician").selectOption({ index: 1 });
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.locator("li[aria-current=step]")).toHaveText(/Assigned/);
  await page.getByRole("button", { name: "Start work" }).click();
  // default start time is "now" (work cannot start before it was reported)
  await dialog.getByRole("button", { name: "Start" }).click();
  await toast(page, /work started/i);

  await page.getByRole("button", { name: "Record downtime" }).click();
  await dialog.getByLabel("Stopped at").fill(plantLocal(-125));
  await dialog.getByLabel("Cause").fill("Mechanical seal failure");
  await dialog.getByRole("button", { name: "Save" }).click();
  await toast(page, /downtime recorded/i);
  await expect(page.getByText("Ongoing").first()).toBeVisible();

  // 4. Issue a spare part (stock ledger) and record labour cost (cost ledger)
  await page.getByRole("button", { name: "Issue part" }).click();
  const greaseValue = await dialog.getByLabel("Item").locator("option", { hasText: "LUBE-GREASE-EP2" }).first().getAttribute("value");
  await dialog.getByLabel("Item").selectOption(greaseValue!);
  await dialog.getByLabel("Quantity").fill("2");
  await dialog.getByRole("button", { name: "Issue", exact: true }).click();
  await toast(page, /part issued/i);
  await page.getByRole("button", { name: "Add cost" }).click();
  await dialog.getByLabel("Category").selectOption("LABOR");
  await dialog.getByLabel("Amount").fill("250");
  await dialog.getByLabel("Description").fill("Technician labour 6 h");
  await dialog.getByRole("button", { name: "Save" }).click();
  await toast(page, /cost recorded/i);

  // 5. Completion is blocked while the outage is open; return to service, then complete
  await page.getByRole("button", { name: "Complete" }).click();
  await expect(dialog.getByText(/close the linked downtime event/i)).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Return to service" }).click();
  await dialog.getByLabel("Returned to service at").fill(plantLocal(-5));
  await dialog.getByRole("button", { name: "Close downtime" }).click();
  await toast(page, /downtime closed/i);
  await page.getByRole("button", { name: "Complete" }).click();
  await dialog.getByLabel("Failure classification").selectOption("MECHANICAL");
  await dialog.getByLabel("Actions performed").fill("Replaced mechanical seal, flushed and test-ran the pump.");
  await dialog.getByLabel("Labour hours").fill("6");
  await dialog.getByRole("button", { name: "Submit for verification" }).click();
  await toast(page, /submitted for verification/i);
  // The engineer who completed the work cannot verify it
  await expect(page.getByRole("button", { name: "Verify" })).toHaveCount(0);

  // 6. Supervisor verifies
  await login(page, "supervisor");
  await page.goto(`/maintenance/work-orders/${woId}`);
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await dialog.getByRole("button", { name: "Verify & close" }).click();
  await toast(page, /verified and closed/i);
  await expect(page.locator("li[aria-current=step]")).toHaveText(/Completed/);

  // 7. Stock, maintenance history and KPIs reconcile
  const wo = await (await mgr.get(`/api/maintenance/work-orders/${woId}/`)).json();
  expect(wo.status).toBe("COMPLETED");
  expect(wo.downtime_hours).toBeCloseTo(2, 0);
  const partsCost = Number(wo.parts[0].value);
  expect(wo.costs.labor).toBe(250);
  expect(wo.costs.total).toBeCloseTo(250 + partsCost, 2);
  const after = await (await store.get(`/api/inventory/items/${grease.id}/`)).json();
  expect(Number(after.current_stock)).toBe(stockBefore - 2);
  const k = await kpi();
  expect(k.maintenance_cost).toBeCloseTo(before.maintenance_cost + 250 + partsCost, 1);
  expect(k.total_assets).toBe(before.total_assets + 1);
  expect(k.downtime_hours).toBeGreaterThan(before.downtime_hours + 1.9);

  await page.goto(`/assets/${wo.asset}`);
  await expect(page.getByRole("link", { name: wo.number })).toBeVisible();
  await page.getByRole("tab", { name: "Downtime history" }).click();
  await expect(page.getByRole("cell", { name: "Mechanical seal failure" })).toBeVisible();

  // 8. Export a reporting dataset from the report center and verify its contents
  await login(page, "manager");
  await page.goto("/reports?report=maintenance_history");
  await expect(page.getByRole("cell", { name: wo.number })).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "CSV" }).click()]);
  const csv = await (await download.createReadStream()).toArray().then((chunks) => Buffer.concat(chunks).toString("utf-8"));
  const header = csv.replace(/^﻿/, "").split(/\r?\n/)[0];
  expect(header).toContain("Work order");
  const line = csv.split(/\r?\n/).find((l) => l.startsWith(wo.number))!;
  expect(line).toContain(tag);
  expect(line).toContain("MECHANICAL");
});
