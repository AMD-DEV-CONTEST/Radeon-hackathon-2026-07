import { test, expect } from '@playwright/test';

/**
 * Live-contract capture against the real localhost FastAPI backend.
 *
 * Skipped unless E2E_LIVE_BASE_URL is set (e.g. http://127.0.0.1:8080), because
 * it needs Lane A's E1-A app running. It proves the mock->live switch works with
 * no UI contract change: the same shell reads real health and truthfully reports
 * that asset/run state is not yet served.
 */
const LIVE = process.env.E2E_LIVE_BASE_URL;

test.describe('live health', () => {
  test.skip(!LIVE, 'set E2E_LIVE_BASE_URL to run against a running FastAPI backend');

  test('reads real health and reports asset state as not-served', async ({ page }) => {
    // Same-origin: the preview server proxies /api to the backend (VITE_PROXY_TARGET),
    // so the browser makes no cross-origin request and needs no CORS.
    await page.goto('/?source=live');
    await expect(page.getByTestId('health-panel')).toBeVisible();
    await expect(page.getByTestId('health-status')).toHaveText('正常');
    await expect(page.getByTestId('health-database')).toContainText('ok');
    await expect(page.getByTestId('active-source')).toContainText('Live');
    await expect(page.getByTestId('empty-message')).toContainText('后端');
    await page.screenshot({ path: 'e2e-results/screenshots/10-live-health.png', fullPage: true });
  });
});
