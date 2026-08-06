import { expect, test } from '@playwright/test';

const LIVE = process.env.E2E_LIVE_BASE_URL;

test.describe('live M1 vertical slice', () => {
  test.skip(!LIVE, 'set E2E_LIVE_BASE_URL to run against the local FastAPI backend');

  test('creates, autosaves, pauses, restores, resumes and exposes an Agent terminal', async ({
    page,
  }) => {
    await page.goto('/?view=m1&source=live');
    await page.getByRole('textbox', { name: '这份资产想帮助你做什么（可选）' }).fill(
      '复盘这次选椅决策',
    );
    await page.getByRole('textbox', { name: '经历内容' }).fill(
      '我试用了一把网椅。坐久后前沿让我不舒服。因为仍在退换期，我换成了软垫人体工学椅。',
    );
    await page.getByTestId('m1-start-submit').click();
    await expect(page.getByTestId('m1-workspace')).toBeVisible();
    await expect(page.getByTestId('m1-question')).toHaveCount(2);

    await page
      .getByRole('textbox', { name: '希望解决的问题 / 用途' })
      .fill('复盘这次选椅决策，并形成可复用检查清单');
    await expect(page.getByTestId('m1-save-state')).toContainText('已自动保存');

    await page.getByTestId('m1-pause').click();
    await expect(page.getByTestId('m1-resume')).toBeVisible();
    await page.reload();
    await expect(page.getByTestId('m1-resume')).toBeVisible();
    await expect(
      page.getByRole('textbox', { name: '希望解决的问题 / 用途' }),
    ).toHaveValue('复盘这次选椅决策，并形成可复用检查清单');
    await page.getByTestId('m1-resume').click();

    await page.getByTestId('m1-agent-permission').check();
    await page.getByTestId('m1-run-agent').click();
    await expect(page.getByTestId('m1-agent-trace')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('m1-agent-terminal')).not.toHaveText('RUNNING');

    await page.screenshot({
      path: 'e2e-results/screenshots/17-m1-live.png',
      fullPage: true,
    });
  });
});
