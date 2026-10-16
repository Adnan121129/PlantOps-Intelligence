import { expect, test } from "@playwright/test";
import { apiAs, login, plantDate, toast } from "./helpers";

/** Role-based approval flow: an operations officer submits a shift report, a supervisor approves it,
 *  management sees only approved data, and approved reports are locked against silent edits. */
test("shift report approval workflow with segregation of duties", async ({ page, baseURL }) => {
  const code = `E${Date.now().toString().slice(-5)}`;
  const { api: admin, csrf } = await apiAs(baseURL!, "admin");
  const headers = async () => ({ "X-CSRFToken": await csrf(), Referer: baseURL! });
  // Admin configures a new reporting unit and assigns it to the operations officer and the supervisor.
  const plants = await (await admin.get("/api/core/plants/")).json();
  const unit = await (await admin.post("/api/core/units/", { headers: await headers(), data: {
    plant: plants.results[0].id, code, name: `E2E water unit ${code}`, unit_type: "UTILITY", requires_shift_reports: true } })).json();
  const users = (await (await admin.get("/api/auth/users/?page_size=100")).json()).results;
  for (const username of ["operations", "supervisor"]) {
    const u = users.find((x: { username: string }) => x.username === username);
    const r = await admin.patch(`/api/auth/users/${u.id}/`, { headers: await headers(), data: { assigned_units: [...u.assigned_units, unit.id] } });
    expect(r.ok()).toBeTruthy();
  }
  const shifts = await (await admin.get("/api/workforce/shifts/")).json();
  const morning = shifts.find((s: { code: string }) => s.code === "A");

  // Operations officer prepares and submits the report
  await login(page, "operations");
  await page.goto(`/operations/reports/new?unit=${unit.id}&shift=${morning.id}&date=${plantDate(-1)}`);
  await page.getByLabel("Demineralised water produced", { exact: true }).fill("612");
  await page.getByLabel("Unit availability", { exact: true }).fill("98.5");
  // A meter is faulty: record the reason instead of a value (never a zero)
  await page.getByLabel("Demin water conductivity not available").check();
  await page.getByLabel("Reason Demin water conductivity is missing").fill("Analyser under calibration");
  await page.getByRole("button", { name: "Save & submit" }).click();
  await toast(page, /submitted for review/i);
  await expect(page.getByText("Submitted", { exact: true }).first()).toBeVisible();
  const reportId = page.url().split("/").pop();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  // A duplicate report for the same unit, shift and date is refused
  await page.goto(`/operations/reports/new?unit=${unit.id}&shift=${morning.id}&date=${plantDate(-1)}`);
  await page.getByLabel("Demineralised water produced", { exact: true }).fill("1");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("alert").first()).toContainText(/already exists/);

  // Management cannot see the submitted (unapproved) report yet
  const { api: mgr } = await apiAs(baseURL!, "manager");
  expect((await mgr.get(`/api/operations/reports/${reportId}/`)).status()).toBe(404);

  // Supervisor approves
  await login(page, "supervisor");
  await page.goto(`/operations/reports/${reportId}`);
  await expect(page.getByText("Missing: Analyser under calibration")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
  await toast(page, /report approved/i);
  await expect(page.getByText("Approved", { exact: true }).first()).toBeVisible();
  await expect(page.locator("section", { hasText: "Approval history" }).getByText("Approve", { exact: true })).toBeVisible();

  // Approved data is now visible to management; the operations officer can no longer edit it
  expect((await mgr.get(`/api/operations/reports/${reportId}/`)).status()).toBe(200);
  await login(page, "operations");
  await page.goto(`/operations/reports/${reportId}`);
  await expect(page.getByRole("link", { name: "Edit" })).toHaveCount(0);
  const { api: ops, csrf: opsCsrf } = await apiAs(baseURL!, "operations");
  const edit = await ops.patch(`/api/operations/reports/${reportId}/`, { headers: { "X-CSRFToken": await opsCsrf(), Referer: baseURL! }, data: { summary: "changed" } });
  expect(edit.status()).toBe(400);
});

test("theme preference persists across reloads and sessions", async ({ page }) => {
  await login(page, "manager");
  const html = page.locator("html");
  const initial = await html.getAttribute("data-theme");
  const target = initial === "dark" ? "light" : "dark";
  await page.getByRole("button", { name: `Switch to ${target} theme` }).click();
  await expect(html).toHaveAttribute("data-theme", target);
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", target);
  await page.goto("/maintenance/work-orders");
  await expect(html).toHaveAttribute("data-theme", target);
  await page.getByRole("button", { name: `Switch to ${initial ?? "light"} theme` }).click();
});

test("server rejects actions the role does not hold even if the UI is bypassed", async ({ baseURL }) => {
  const { api, csrf } = await apiAs(baseURL!, "store");
  const res = await api.post("/api/maintenance/work-orders/", { headers: { "X-CSRFToken": await csrf(), Referer: baseURL! },
    data: { asset: 1, title: "x", description: "x" } });
  expect(res.status()).toBe(403);
  const me = await (await api.get("/api/auth/me/")).json();
  const escalate = await api.patch("/api/auth/me/", { headers: { "X-CSRFToken": await csrf(), Referer: baseURL! }, data: { role: "ADMIN" } });
  expect((await escalate.json()).role).toBe(me.role);
});
