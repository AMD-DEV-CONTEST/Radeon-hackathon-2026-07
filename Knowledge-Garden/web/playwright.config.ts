import { defineConfig, devices } from "@playwright/test"

// Three viewport projects (375 / 768 / 1280) per Todo 9.
// E2E_BASE_URL must point at the disposable PRODUCTION web port (not Vite dev),
// e.g. set by scripts/bootstrap_disposable_env.sh or the FastAPI SPA fallback.
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173"

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium-375", use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 720 } } },
    { name: "chromium-768", use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 800 } } },
    { name: "chromium-1280", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } } },
  ],
})
