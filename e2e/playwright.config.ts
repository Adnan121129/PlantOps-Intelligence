import { defineConfig } from "@playwright/test";

/**
 * End-to-end tests run against a real backend + frontend.
 * `./run-e2e.sh` provisions an isolated database (plantops_e2e), seeds 30 days of demo data,
 * starts Django and Vite on ports 8001/5174 and runs these tests. To reuse already-running
 * servers set E2E_BASE_URL.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
});
