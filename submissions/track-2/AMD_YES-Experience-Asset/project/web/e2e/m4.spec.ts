import { expect, test } from '@playwright/test';

const LIVE = process.env.E2E_LIVE_BASE_URL;

async function acceptedLedger(request: import('@playwright/test').APIRequestContext) {
  const ingestedResponse = await request.post('/api/v1/m1/assets', {
    data: {
      source_kind: 'PASTED_TEXT',
      display_label: 'M4 live public fixture',
      text: '我试坐后发现支撑不足，于是更换了椅子，之后久坐更舒服。',
      goal_hint: '复盘选择',
    },
  });
  expect(ingestedResponse.ok()).toBeTruthy();
  const ingested = await ingestedResponse.json();
  const assetId = ingested.asset.asset_id as string;

  const m1Response = await request.post(`/api/v1/m1/assets/${assetId}/confirm`, {
    data: {expected_version_id: ingested.asset.version_id, complete_with_gaps: true},
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
  const m2Confirmed = await m2ConfirmedResponse.json();

  const m3CreatedResponse = await request.post(`/api/v1/m3/assets/${assetId}`, {
    data: {
      expected_m2_artifact_id: m2Confirmed.artifact.artifact_id,
      expected_canonical_version_id: (
        await (await request.get(`/api/v1/m1/assets/${assetId}`)).json()
      ).asset.version_id,
    },
  });
  expect(m3CreatedResponse.ok()).toBeTruthy();
  const m3Created = await m3CreatedResponse.json();
  const statements = m3Created.artifact.entries.flatMap(
    (entry: {statements: Array<{statement_id: string; text: string}>}) => entry.statements,
  );
  const m3EditedResponse = await request.patch(`/api/v1/m3/assets/${assetId}`, {
    data: {
      expected_artifact_id: m3Created.artifact.artifact_id,
      statements: statements.map((statement: {statement_id: string; text: string}) => ({
        statement_id: statement.statement_id,
        text: statement.text,
        user_action: 'CONFIRM',
      })),
    },
  });
  expect(m3EditedResponse.ok()).toBeTruthy();
  const m3Edited = await m3EditedResponse.json();
  const m3ConfirmedResponse = await request.post(`/api/v1/m3/assets/${assetId}/confirm`, {
    data: {expected_artifact_id: m3Edited.artifact.artifact_id, complete_with_gaps: false},
  });
  expect(m3ConfirmedResponse.ok()).toBeTruthy();
  return assetId;
}

test.describe('live M4 insight and boundary map journey', () => {
  test.skip(!LIVE, 'set E2E_LIVE_BASE_URL to run against the local FastAPI backend');

  test('generates the map, opens its evidence, invalidates and regenerates', async ({
    page,
    request,
  }) => {
    const assetId = await acceptedLedger(request);

    await page.goto(`/?view=m4&source=live&asset=${assetId}`);
    await expect(page.getByTestId('m4-current-upstream')).toContainText('CONFIRMED');
    // The workspace resolves the upstream identities itself; asking the user to
    // paste UUIDs would make the screen unusable for the person it is for.
    await expect(page.getByLabel('M3 Artifact ID')).toHaveCount(0);

    await page.getByRole('button', {name: '从当前 M3 生成'}).click();
    await expect(page.getByTestId('m4-insight-boundary-map')).toBeVisible();

    // Every role including the three boundary roles, or the lesson is not
    // safe to reuse.
    for (const role of [
      'lesson',
      'support',
      'counterfactual',
      'limitation',
      'counterexample',
      'applicability',
    ]) {
      await expect(page.getByTestId(`m4-statement-${role}`)).toBeVisible();
    }

    const lessonEvidence = page
      .getByTestId('m4-statement-lesson')
      .getByTestId('m4-evidence-details');
    await lessonEvidence.getByText('查看这条依据的原始证据').click();
    await expect(lessonEvidence.locator('li').first()).toBeVisible();

    // Correct the ledger the map was drawn from; the map must say so rather
    // than keep presenting conclusions from evidence the user has replaced.
    const currentM3 = await (await request.get(`/api/v1/m3/assets/${assetId}`)).json();
    const target = currentM3.artifact.entries[0].statements[0];
    const correctedResponse = await request.patch(`/api/v1/m3/assets/${assetId}`, {
      data: {
        expected_artifact_id: currentM3.artifact.artifact_id,
        statements: [
          {
            statement_id: target.statement_id,
            text: '其实支撑没问题，是坐姿的问题。',
            user_action: 'CONFIRM',
          },
        ],
      },
    });
    expect(correctedResponse.ok()).toBeTruthy();

    await page.getByRole('button', {name: '重新载入'}).click();
    await expect(page.getByTestId('m4-invalidated')).toBeVisible();
    await expect(page.getByTestId('m4-state-badge')).toContainText('已失效');

    // Rebuilding waits for the ledger to be accepted again; drawing new
    // lessons from a ledger mid-correction is the failure this gate prevents.
    const reaccept = await (await request.get(`/api/v1/m3/assets/${assetId}`)).json();
    expect(
      (
        await request.post(`/api/v1/m3/assets/${assetId}/confirm`, {
          data: {
            expected_artifact_id: reaccept.artifact.artifact_id,
            complete_with_gaps: false,
          },
        })
      ).ok(),
    ).toBeTruthy();

    await page.getByRole('button', {name: '重新载入'}).click();
    await page.getByRole('button', {name: '重新生成'}).click();
    await expect(page.getByTestId('m4-invalidated')).toHaveCount(0);
    await expect(page.getByTestId('m4-insight-boundary-map')).toBeVisible();
    await page.screenshot({
      path: 'e2e-results/screenshots/19-m4-live.png',
      fullPage: true,
    });
  });
});
