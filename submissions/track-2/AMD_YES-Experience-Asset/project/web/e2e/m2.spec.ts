import { expect, test } from '@playwright/test';

const LIVE = process.env.E2E_LIVE_BASE_URL;

test.describe('live M1 to M2 handoff', () => {
  test.skip(!LIVE, 'set E2E_LIVE_BASE_URL to run against the local FastAPI backend');

  test('creates and regenerates M2 from the latest M1 without UUID entry', async ({
    page,
    request,
  }) => {
    const ingestedResponse = await request.post('/api/v1/m1/assets', {
      data: {
        source_kind: 'PASTED_TEXT',
        display_label: 'M2 live role fixture',
        text: [
          '因为第一次试坐时腿麻，我发现支撑不足。',
          '没想到软垫更不舒服。',
          '于是我决定更换椅子。',
        ].join(''),
        goal_hint: '复盘选择',
      },
    });
    expect(ingestedResponse.ok()).toBeTruthy();
    const ingested = await ingestedResponse.json();
    const assetId = ingested.asset.asset_id as string;

    const preparedResponse = await request.patch(`/api/v1/m1/assets/${assetId}/brief`, {
      data: {
        expected_version_id: ingested.asset.version_id,
        context: '先用于个人复盘。',
      },
    });
    expect(preparedResponse.ok()).toBeTruthy();
    const prepared = await preparedResponse.json();
    const acceptedResponse = await request.post(`/api/v1/m1/assets/${assetId}/confirm`, {
      data: {
        expected_version_id: prepared.asset.version_id,
        complete_with_gaps: true,
      },
    });
    expect(acceptedResponse.ok()).toBeTruthy();

    await page.goto(`/?view=m2&source=live&asset=${assetId}`);
    await expect(page.getByTestId('m2-current-m1-version')).toContainText('COMPLETE_WITH_GAPS');
    await expect(page.getByText('已接受的 M1 Version ID')).toHaveCount(0);
    await page.getByRole('button', {name: '从 M1 生成'}).click();
    await expect(page.getByTestId('m2-critical-moment-map')).toBeVisible();
    await expect(page.getByText('线索 1')).toBeVisible();
    await expect(page.getByText('意外 1')).toBeVisible();
    await expect(page.getByText('变化/转折 1')).toBeVisible();

    const currentResponse = await request.get(`/api/v1/m1/assets/${assetId}`);
    expect(currentResponse.ok()).toBeTruthy();
    const current = await currentResponse.json();
    const correctedResponse = await request.patch(`/api/v1/m1/assets/${assetId}/brief`, {
      data: {
        expected_version_id: current.asset.version_id,
        context: '改为形成可复用检查清单。',
      },
    });
    expect(correctedResponse.ok()).toBeTruthy();
    const corrected = await correctedResponse.json();
    const reacceptedResponse = await request.post(
      `/api/v1/m1/assets/${assetId}/confirm`,
      {
        data: {
          expected_version_id: corrected.asset.version_id,
          complete_with_gaps: true,
        },
      },
    );
    expect(reacceptedResponse.ok()).toBeTruthy();

    await page.getByRole('button', {name: '重新载入'}).click();
    await expect(page.getByText(/依赖的 M1 更正而失效/)).toBeVisible();
    await page.getByRole('button', {name: '按最新 M1 重新生成'}).click();
    await expect(page.getByText(/依赖的 M1 更正而失效/)).toHaveCount(0);
    await expect(page.getByTestId('m2-critical-moment-map')).toBeVisible();
  });
});
