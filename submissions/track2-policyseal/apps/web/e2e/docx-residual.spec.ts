import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  artifactPath,
  createHeroTask,
  expectPageIntegrity,
  expectZipPackage,
  REPO_ROOT,
} from "./helpers";

test("DOCX output keeps stable aliases and residual evidence without raw secrets", async ({
  page,
}) => {
  await createHeroTask(
    page,
    "Incident report / Response partner",
    "security-incident-hero.docx",
  );

  await expect(page.getByText("Minimum disclosure ready")).toBeVisible();
  await expect(page.getByText(/residual checks completed/i)).toBeVisible();
  const hostRegion = page.locator("button.document-region", {
    hasText: "section:2:table:1:row:4:cell:2",
  });
  await expect(hostRegion).toBeVisible();
  await hostRegion.click();
  await expect(page.locator(".diff-panel--target").getByText("Stable asset alias", { exact: true })).toBeVisible();
  await expect(page.getByText("PS-DOCX-RESPONDER-ASSET-ALIAS")).toBeVisible();
  await page.locator("summary").filter({ hasText: /EV-DOCX-002 \/ Stable aliases/ }).click();
  await expect(page.getByText(/task-local aliases/i)).toBeVisible();

  const tasksResponse = await page.request.get("/api/tasks");
  const tasks = (await tasksResponse.json()) as Array<{
    id: string;
    file_kind: string;
    revisions: Array<{ id: string }>;
  }>;
  const task = tasks.find((item) => item.file_kind === "docx");
  expect(task).toBeTruthy();
  const revisionId = task?.revisions.at(-1)?.id;
  expect(revisionId).toBeTruthy();
  const events = await page.request.get(`/api/revisions/${revisionId}/events`);
  expect(await events.text()).toContain('"stage":"residual_check"');

  await page.getByLabel("Ask about this revision").fill("Why did the internal hostname become an alias?");
  const sendButton = page.getByRole("button", { name: "Send review message" });
  await sendButton.hover();
  await expect(page.getByRole("tooltip", { name: "Send review message" })).toBeVisible();
  await sendButton.click();
  await expect(page.getByText(/task-local alias/i).last()).toBeVisible();

  await expectPageIntegrity(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: artifactPath("docx-alias-desktop.png"), fullPage: true });

  const businessDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Business output" }).click();
  const businessDownload = await businessDownloadPromise;
  const businessPath = await businessDownload.path();
  await expectZipPackage(businessPath);
  expect(businessPath).not.toBeNull();
  if (businessPath) {
    const python = path.join(REPO_ROOT, ".venv", "bin", "python");
    const documentXml = execFileSync(
      python,
      [
        "-c",
        "import sys, zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read('word/document.xml'))",
        businessPath,
      ],
      { encoding: "utf8" },
    );
    expect(documentXml).toMatch(/Host-[A-F0-9]{4}-\d{2}/);
    expect(documentXml).toMatch(/Person-[A-F0-9]{4}-\d{2}/);
    expect(documentXml).not.toContain("Crimson-Falcon-47!");
    expect(documentXml).not.toContain("ps_demo_token_7f4b2e91");
  }

  const evidenceDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Evidence package" }).click();
  await expectZipPackage(await (await evidenceDownloadPromise).path());
});
