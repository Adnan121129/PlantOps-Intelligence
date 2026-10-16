import { expect, type APIRequestContext, type Page, request } from "@playwright/test";

export const PASSWORD = process.env.PLANTOPS_DEMO_PASSWORD ?? "PlantOps-Demo-2026";
export const TZ = "Asia/Dubai";

export async function login(page: Page, username: string) {
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
}

/** Authenticated API client (session + CSRF) for setup and verification. */
export async function apiAs(baseURL: string, username: string): Promise<{ api: APIRequestContext; csrf: () => Promise<string> }> {
  const api = await request.newContext({ baseURL });
  await api.get("/api/auth/csrf/");
  const csrf = async () => (await api.storageState()).cookies.find((c) => c.name === "csrftoken")!.value;
  const res = await api.post("/api/auth/login/", { data: { username, password: PASSWORD }, headers: { "X-CSRFToken": await csrf(), Referer: baseURL } });
  expect(res.ok()).toBeTruthy();
  return { api, csrf };
}

/** "YYYY-MM-DDTHH:mm" in the plant time zone, offset by minutes from now (for datetime-local inputs). */
export function plantLocal(offsetMinutes = 0): string {
  const d = new Date(Date.now() + offsetMinutes * 60_000);
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit" }).formatToParts(d);
  const g = (t: string) => p.find((x) => x.type === t)!.value;
  return `${g("year")}-${g("month")}-${g("day")}T${g("hour")}:${g("minute")}`;
}

export function plantDate(offsetDays = 0): string {
  return plantLocal(offsetDays * 24 * 60).slice(0, 10);
}

export async function toast(page: Page, text: RegExp | string) {
  await expect(page.getByRole("status").filter({ hasText: text }).first()).toBeVisible();
}
