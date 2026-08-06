import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: 'e7-export-preview.spec.ts',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  outputDir: '../e2e-results/e7-artifacts',
  use: {
    ...devices['Desktop Chrome'],
    trace: 'off',
    screenshot: 'off',
  },
});
