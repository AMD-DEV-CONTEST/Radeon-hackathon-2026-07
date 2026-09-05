import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const EXPORTED_HTML = readFileSync(
  new URL('../../tests/fixtures/e7_complete_preview.html', import.meta.url),
  'utf8',
);

test('self-contained E7 preview exposes exact identity and interactive sections', async ({ page }) => {
  const externalRequests: string[] = [];
  page.on('request', request => {
    if (/^https?:/.test(request.url())) externalRequests.push(request.url());
  });

  await page.setContent(EXPORTED_HTML);

  await expect(page.getByRole('heading', {name: 'What two chair trials clarified'})).toBeVisible();
  await expect(page.getByLabel('Delivery status')).toContainText('not approved for external');
  const body = page.locator('body');
  const routeDraftHash = await body.getAttribute('data-route-draft-hash');
  const rendererInputIdentity = await body.getAttribute('data-renderer-input-identity');
  expect(routeDraftHash).not.toBe(rendererInputIdentity);
  expect(await body.getAttribute('data-draft-state')).toBe('CURRENT');

  const identity = JSON.parse(
    (await page.locator('#e7-delivery-identity').textContent()) ?? '{}',
  );
  expect(identity.route_draft_hash).toBe(routeDraftHash);
  expect(identity.renderer_input_identity).toBe(rendererInputIdentity);
  expect(identity.relation_projection_hash).toBe(
    await body.getAttribute('data-relation-projection-hash'),
  );
  expect(identity.version_id).toBe(await body.getAttribute('data-version-id'));

  const firstSection = page.locator('details').first();
  await expect(firstSection).toHaveJSProperty('open', true);
  await firstSection.locator('summary').click();
  await expect(firstSection).toHaveJSProperty('open', false);
  expect(externalRequests).toEqual([]);
});
