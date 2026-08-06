import { expect, test } from '@playwright/test';

const LIVE = process.env.E2E_LIVE_BASE_URL;

test.describe('live M1 to M3 decision-ledger journey', () => {
  test.skip(!LIVE, 'set E2E_LIVE_BASE_URL to run against the local FastAPI backend');

  test('resolves upstream IDs, reviews M3, invalidates and regenerates', async ({
    page,
    request,
  }) => {
    const ingestedResponse = await request.post('/api/v1/m1/assets', {
      data: {
        source_kind: 'PASTED_TEXT',
        display_label: 'M3 live public fixture',
        text: '我试坐后发现支撑不足，于是更换了椅子，之后久坐更舒服。',
        goal_hint: '复盘选择',
      },
    });
    expect(ingestedResponse.ok()).toBeTruthy();
    const ingested = await ingestedResponse.json();
    const assetId = ingested.asset.asset_id as string;

    const m1Response = await request.post(`/api/v1/m1/assets/${assetId}/confirm`, {
      data: {
        expected_version_id: ingested.asset.version_id,
        complete_with_gaps: true,
      },
    });
    expect(m1Response.ok()).toBeTruthy();
    const m1 = await m1Response.json();

    const m2ProposedResponse = await request.post(`/api/v1/m2/assets/${assetId}`, {
      data: {expected_m1_version_id: m1.asset.version_id},
    });
    expect(m2ProposedResponse.ok()).toBeTruthy();
    const m2Proposed = await m2ProposedResponse.json();
    const m2EditedResponse = await request.patch(`/api/v1/m2/assets/${assetId}`, {
      data: {
        expected_artifact_id: m2Proposed.artifact.artifact_id,
        moments: m2Proposed.artifact.moments.map(
          (moment: {moment_id: string; title: string}) => ({
            moment_id: moment.moment_id,
            title: moment.title,
            criticality_status: 'USER_CONFIRMED',
          }),
        ),
      },
    });
    expect(m2EditedResponse.ok()).toBeTruthy();
    const m2Edited = await m2EditedResponse.json();
    const m2ConfirmedResponse = await request.post(
      `/api/v1/m2/assets/${assetId}/confirm`,
      {
        data: {
          expected_artifact_id: m2Edited.artifact.artifact_id,
          complete_with_gaps: true,
        },
      },
    );
    expect(m2ConfirmedResponse.ok()).toBeTruthy();

    await page.goto(`/?view=m3&source=live&asset=${assetId}`);
    await expect(page.getByTestId('m3-current-upstream')).toContainText('CONFIRMED');
    await expect(page.getByLabel('M2 Artifact ID')).toHaveCount(0);
    await expect(page.getByLabel('Canonical Version ID')).toHaveCount(0);
    await page.getByRole('button', {name: '从当前 M2 生成'}).click();
    await expect(page.getByTestId('m3-decision-evidence-ledger')).toBeVisible();

    const confirmations = page.getByRole('button', {name: 'CONFIRM'});
    await expect(confirmations).toHaveCount(5);
    for (let index = 0; index < 5; index += 1) {
      const response = page.waitForResponse(
        item => item.url().includes(`/api/v1/m3/assets/${assetId}`)
          && item.request().method() === 'PATCH',
      );
      await confirmations.nth(index).click();
      expect((await response).ok()).toBeTruthy();
    }
    await page.getByRole('button', {name: '确认账本'}).click();
    await expect(page.getByTestId('m3-decision-evidence-ledger')).toContainText('CONFIRMED');

    const currentM2Response = await request.get(`/api/v1/m2/assets/${assetId}`);
    const currentM2 = await currentM2Response.json();
    const correctedResponse = await request.patch(`/api/v1/m2/assets/${assetId}`, {
      data: {
        expected_artifact_id: currentM2.artifact.artifact_id,
        moments: currentM2.artifact.moments.map(
          (moment: {moment_id: string; title: string}) => ({
            moment_id: moment.moment_id,
            title: `${moment.title}（修正）`,
            criticality_status: 'USER_CONFIRMED',
          }),
        ),
      },
    });
    expect(correctedResponse.ok()).toBeTruthy();
    const corrected = await correctedResponse.json();
    const reacceptedResponse = await request.post(
      `/api/v1/m2/assets/${assetId}/confirm`,
      {
        data: {
          expected_artifact_id: corrected.artifact.artifact_id,
          complete_with_gaps: true,
        },
      },
    );
    expect(reacceptedResponse.ok()).toBeTruthy();

    await page.getByRole('button', {name: '重新载入'}).click();
    await expect(page.getByTestId('m3-invalidated')).toBeVisible();
    await page.getByRole('button', {name: '重新生成'}).click();
    await expect(page.getByTestId('m3-invalidated')).toHaveCount(0);
    await expect(page.getByTestId('m3-decision-evidence-ledger')).toBeVisible();
    await page.screenshot({
      path: 'e2e-results/screenshots/18-m3-live.png',
      fullPage: true,
    });
  });
});
