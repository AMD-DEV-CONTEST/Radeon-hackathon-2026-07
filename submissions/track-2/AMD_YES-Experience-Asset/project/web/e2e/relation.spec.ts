import { test, expect } from '@playwright/test';

const SHOTS = 'e2e-results/screenshots';

async function shot(page: import('@playwright/test').Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

test.describe('cross-asset relation discovery states', () => {
  test('locked: no candidates until KnowledgeCardReady', async ({ page }) => {
    await page.goto('/?view=status&source=mock&scenario=healthy');
    await expect(page.getByTestId('relation-panel')).toBeVisible();
    await expect(page.getByTestId('relation-gate')).toHaveText('未就绪（已锁定）');
    await expect(page.getByTestId('relation-candidates')).toHaveCount(0);
    await shot(page, '11-relation-locked');
  });

  test('ready: summary-only candidates, detail denied until confirmed', async ({ page }) => {
    await page.goto('/?view=status&source=mock&scenario=relation-ready');
    await expect(page.getByTestId('relation-gate')).toHaveText('已就绪');
    await expect(page.getByTestId('relation-candidates')).toBeVisible();
    await expect(
      page.getByTestId('relation-00000000-0000-4000-8000-000000000601-confirmation'),
    ).toHaveText('待确认');
    await expect(
      page.getByTestId('relation-00000000-0000-4000-8000-000000000601-detail'),
    ).toContainText('需先确认关系');
    await shot(page, '12-relation-ready');
  });

  test('no-match: a valid empty result', async ({ page }) => {
    await page.goto('/?view=status&source=mock&scenario=relation-no-match');
    await expect(page.getByTestId('relation-no-match')).toBeVisible();
    await shot(page, '13-relation-no-match');
  });

  // The MVP exposes at most one candidate, so "one confirmed alongside one
  // declined" is no longer a representable state. Asserting the confirmed one
  // and the declined one separately keeps both behaviours covered without
  // asserting a shape the frozen contract rules out.
  test('confirmed: detail is unlocked on the confirmed relation', async ({ page }) => {
    await page.goto('/?view=status&source=mock&scenario=relation-confirmed');
    await expect(
      page.getByTestId('relation-00000000-0000-4000-8000-000000000601-detail'),
    ).toContainText('已解锁');
    await expect(
      page.getByTestId('relation-00000000-0000-4000-8000-000000000601-confirmation'),
    ).toHaveText('已确认');
    await shot(page, '14-relation-confirmed');
  });

  test('denied-detail: declined relation closes its detail', async ({ page }) => {
    await page.goto('/?view=status&source=mock&scenario=relation-detail-denied');
    await expect(
      page.getByTestId('relation-00000000-0000-4000-8000-000000000601-detail'),
    ).toContainText('已随拒绝关闭');
    await shot(page, '15-relation-detail-denied');
  });

  test('invalidated: editing M1–M4 invalidates the whole surface', async ({ page }) => {
    await page.goto('/?view=status&source=mock&scenario=relation-invalidated');
    await expect(page.getByTestId('relation-gate')).toHaveText('已失效');
    await expect(page.getByTestId('relation-invalidated')).toBeVisible();
    await shot(page, '16-relation-invalidated');
  });
});
