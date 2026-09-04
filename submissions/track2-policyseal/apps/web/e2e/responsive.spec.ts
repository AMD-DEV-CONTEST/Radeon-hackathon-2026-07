import { expect, test } from "@playwright/test";

import { artifactPath, createHeroTask, expectPageIntegrity } from "./helpers";

test("review workspace remains stable at desktop and mobile widths", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await createHeroTask(
    page,
    "Supplier matrix / External audit",
    "supplier-matrix-hero.xlsx",
  );
  await expect(page.getByText("Disclosure action matrix")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: /Personal email/ })).toContainText("Blocked");
  const firstBox = await page.locator(".review-tabs").boundingBox();
  await page.waitForTimeout(350);
  const stableBox = await page.locator(".review-tabs").boundingBox();
  expect(stableBox).toEqual(firstBox);
  await expectPageIntegrity(page);
  await page.screenshot({ path: artifactPath("matrix-desktop-1440.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "Disclosure tasks" })).toBeVisible();
  await expect(page.getByText("Disclosure action matrix")).toBeVisible();
  await expect(page.getByRole("button", { name: "New task" })).toBeVisible();
  await expectPageIntegrity(page);
  await page.screenshot({ path: artifactPath("matrix-mobile-390.png"), fullPage: true });
});
