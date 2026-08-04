import { expect, test } from "@playwright/test";

import { artifactPath, createHeroTask, expectPageIntegrity, expectZipPackage } from "./helpers";

test("PDF reference output requires an independent exact-binding approval", async ({ page }) => {
  await createHeroTask(
    page,
    "Reference contract / Candidate supplier",
    "reference-contract-hero.pdf",
  );

  await expect(page.getByText("Approval required")).toBeVisible();
  await expect(page.locator(".reference-preview__title")).toContainText(
    "Reference Draft - Not for Signature",
  );
  const sourcePages = page.getByRole("img", { name: /Source PDF page/ });
  await expect(sourcePages).toHaveCount(3);
  for (const image of await sourcePages.all()) {
    await expect.poll(() => image.evaluate((node) => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  }

  await page.getByRole("button", { name: "Request approval" }).click();
  await expect(page.getByText("Self-approval unavailable.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Reviewer" }).click();
  await expect(page.getByRole("button", { name: "Approve exact revision" })).toBeVisible();
  await page.getByRole("button", { name: "Approve exact revision" }).click();
  await expect(page.getByText("Approved", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Business output" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Evidence package" })).toBeEnabled();

  await expectPageIntegrity(page);
  await page.screenshot({ path: artifactPath("pdf-approved-desktop.png"), fullPage: true });

  const businessDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Business output" }).click();
  const businessDownload = await businessDownloadPromise;
  await expectZipPackage(await businessDownload.path());
  expect(businessDownload.suggestedFilename()).toMatch(/\.docx$/);

  await expect(page.getByRole("button", { name: "Business output" })).toBeDisabled();
  const evidenceDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Evidence package" }).click();
  const evidenceDownload = await evidenceDownloadPromise;
  await expectZipPackage(await evidenceDownload.path());
  expect(evidenceDownload.suggestedFilename()).toMatch(/\.zip$/);
});
