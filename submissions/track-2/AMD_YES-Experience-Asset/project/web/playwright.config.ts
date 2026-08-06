import { defineConfig, devices } from '@playwright/test';

// E2E runs against the production preview build so captures reflect the real
// application, not the dev server. The mock provider is the default data source;
// live-backend captures are produced by a separate documented run.
export default defineConfig({
  testDir: './e2e',
  // A real localhost W7900 flow includes bounded model calls.  Keep the fast
  // mock defaults, but do not mistake normal device inference latency for a UI
  // failure when the explicitly enabled live suite is collecting evidence.
  // The M4 live scenario includes an initial map plus an explicit
  // regeneration. Each inference is still bounded by the backend's 120-second
  // per-call cap; the scenario timeout only allows both calls to be observed.
  timeout: process.env.E2E_LIVE_BASE_URL ? 360_000 : 30_000,
  expect: {
    timeout: process.env.E2E_LIVE_BASE_URL ? 120_000 : 5_000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: 'e2e-results/results.json' }]],
  outputDir: 'e2e-results/artifacts',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'off',
    screenshot: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run build && npm run preview',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
