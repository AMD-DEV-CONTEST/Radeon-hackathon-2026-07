import { expect, test } from "@playwright/test";

import { artifactPath, createHeroTask, expectPageIntegrity } from "./helpers";

test("XLSX matrix keeps what-if Block non-downloadable until formal confirmation", async ({
  page,
}) => {
  await createHeroTask(
    page,
    "Supplier matrix / Internal procurement",
    "supplier-matrix-hero.xlsx",
  );

  await expect(page.getByText("Minimum disclosure ready")).toBeVisible();
  await expect(page.getByText("Disclosure action matrix")).toBeVisible();
  const personalHeader = page.getByRole("columnheader", { name: /Personal email/ });
  await expect(personalHeader).toContainText("Blocked");
  const actions = await page.locator(".matrix-action span").allTextContents();
  expect(new Set(actions).size).toBeGreaterThan(3);

  await personalHeader.click();
  await expect(page.getByText("Disclosure blocked")).toBeVisible();
  await expect(page.getByText("Simulation only")).toBeVisible();
  await expect(page.getByRole("button", { name: "Business output" })).toHaveCount(0);

  await page.getByRole("button", { name: "Set as formal context" }).click();
  await page.getByRole("button", { name: "Create formal revision" }).click();
  await expect(page.getByText("Disclosure blocked")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByRole("columnheader", { name: /Personal email/ })).toContainText("Formal");
  await expect(page.getByRole("button", { name: "Business output" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Evidence package" })).toBeDisabled();
  await expect(page.getByText("Policy Block cannot enter approval.")).toBeVisible();

  await expectPageIntegrity(page);
  await page.screenshot({ path: artifactPath("xlsx-block-desktop.png"), fullPage: true });
});
