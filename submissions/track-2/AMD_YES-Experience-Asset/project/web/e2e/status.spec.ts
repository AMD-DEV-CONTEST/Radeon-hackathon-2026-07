import { test, expect } from '@playwright/test';

const SHOTS = 'e2e-results/screenshots';

async function shot(page: import('@playwright/test').Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

test.describe('mock status states', () => {
  test('healthy: shows health, version, milestones, counts, routes, progress', async ({ page }) => {
    await page.goto('/?source=mock&scenario=healthy');
    await expect(page.getByTestId('status-dashboard')).toBeVisible();
    await expect(page.getByTestId('health-status')).toHaveText('正常');
    await expect(page.getByTestId('version-current')).toBeVisible();
    await expect(page.getByTestId('milestone-M1-state')).toHaveText('已确认');
    await expect(page.getByTestId('milestone-M2')).toHaveAttribute('data-state', 'IN_PROGRESS');
    await expect(page.getByTestId('count-confirmed')).toContainText('2');
    // Progress carries the final public milestone basis and no fabricated ETA.
    await expect(page.getByTestId('run-progress-label')).toContainText('40%（2/5 公开里程碑');
    await expect(page.getByTestId('run-progress-label')).toContainText('milestones_done/milestones_total');
    await expect(page.getByTestId('run-eta')).toContainText('后端尚无有依据的估算');
    await expect(page.getByTestId('active-source')).toContainText('Mock');
    await shot(page, '01-healthy');
  });

  test('loading: spinner shows while a slow fetch is pending', async ({ page }) => {
    await page.goto('/?source=mock&scenario=loading&delay=60000');
    await expect(page.getByTestId('loading-screen')).toBeVisible();
    await shot(page, '02-loading');
  });

  test('empty: no-instance state without fabricating an asset', async ({ page }) => {
    await page.goto('/?source=mock&scenario=empty');
    await expect(page.getByTestId('empty-screen')).toBeVisible();
    await expect(page.getByTestId('version-panel')).toHaveCount(0);
    await shot(page, '03-empty');
  });

  test('failure: recoverable error with a working retry', async ({ page }) => {
    await page.goto('/?source=mock&scenario=failure');
    await expect(page.getByTestId('error-screen')).toBeVisible();
    const retry = page.getByTestId('error-retry');
    await expect(retry).toBeVisible();
    await shot(page, '04-failure');
    // Retry re-runs the same failing scenario; it must not fabricate success.
    await retry.click();
    await expect(page.getByTestId('error-screen')).toBeVisible();
  });

  test('safe-stop: paused terminal state keeps the last durable version', async ({ page }) => {
    await page.goto('/?source=mock&scenario=safe-stop');
    await expect(page.getByTestId('run-terminal-state')).toHaveText('PAUSED');
    await expect(page.getByTestId('run-safe-stop')).toBeVisible();
    await expect(page.getByTestId('run-recovery')).toContainText('继续');
    await shot(page, '05-safe-stop');
  });

  test('stale: invalidation notice after a correction', async ({ page }) => {
    await page.goto('/?source=mock&scenario=stale');
    await expect(page.getByTestId('stale-notice')).toBeVisible();
    await expect(page.getByTestId('milestone-M2-state')).toHaveText('已失效');
    await shot(page, '06-stale');
  });

  test('terminal-failure: model unavailable with safe message and retry flag', async ({ page }) => {
    await page.goto('/?source=mock&scenario=terminal-failure');
    await expect(page.getByTestId('run-terminal-state')).toHaveText('MODEL_UNAVAILABLE');
    await expect(page.getByTestId('run-safe-message')).toBeVisible();
    await expect(page.getByTestId('run-retryable')).toBeVisible();
    await expect(page.getByTestId('health-status')).toHaveText('降级');
    await shot(page, '07-terminal-failure');
  });

  test('refresh: healthy state re-fetches and stays truthful', async ({ page }) => {
    await page.goto('/?source=mock&scenario=healthy');
    await expect(page.getByTestId('status-dashboard')).toBeVisible();
    await page.getByTestId('refresh').click();
    await expect(page.getByTestId('status-dashboard')).toBeVisible();
    await expect(page.getByTestId('run-progress-label')).toContainText('40%（2/5 公开里程碑');
    await shot(page, '08-refresh');
  });

  test('source switch: live mode is reachable from the toolbar', async ({ page }) => {
    await page.goto('/?source=mock&scenario=healthy');
    await page.getByTestId('source-live').click();
    // Live backend is not running in the default E2E env, so the UI shows a
    // truthful error/empty state — never a fabricated dashboard.
    await expect(page.getByTestId('active-source')).toContainText('Live');
    await expect(
      page.getByTestId('error-screen').or(page.getByTestId('empty-screen')),
    ).toBeVisible();
    await shot(page, '09-live-switch');
  });
});
