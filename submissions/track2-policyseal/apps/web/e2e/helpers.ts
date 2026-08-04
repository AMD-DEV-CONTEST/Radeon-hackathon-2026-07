import { expect, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

export function sourcePath(filename: string): string {
  return path.join(REPO_ROOT, "demo_data", "sources", filename);
}

export function artifactPath(filename: string): string {
  return path.join(REPO_ROOT, "artifacts", "e2e", filename);
}

export async function createHeroTask(
  page: Page,
  presetLabel: string,
  filename: string,
): Promise<void> {
  await page.goto("/");
  await expect(page.getByText("Local API ready")).toBeVisible();
  await page.getByRole("button", { name: "New task" }).click();
  await page.getByLabel("Scenario template").selectOption({ label: presetLabel });
  await page.getByLabel("Source document").setInputFiles(sourcePath(filename));
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create and analyze" }).click();
  await expect(page.getByRole("dialog", { name: "New disclosure task" })).toBeHidden();
  await expect(page.getByRole("heading", { name: "Local analysis" })).toBeVisible();
  await expect(page.getByLabel("Disclosure review workspace")).toBeVisible({ timeout: 45_000 });
}

export async function expectZipPackage(downloadPath: string | null): Promise<void> {
  expect(downloadPath).not.toBeNull();
  if (!downloadPath) return;
  const { readFile } = await import("node:fs/promises");
  const header = await readFile(downloadPath);
  expect(header.subarray(0, 2).toString("ascii")).toBe("PK");
  expect(header.byteLength).toBeGreaterThan(500);
}

export async function expectPageIntegrity(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const horizontal = document.documentElement.scrollWidth - window.innerWidth;
    const offenders = Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          selector: `${element.tagName.toLowerCase()}.${element.className}`,
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        };
      })
      .filter((item) => item.right > window.innerWidth + 1 || item.left < -1)
      .sort((left, right) => right.right - left.right)
      .slice(0, 8);
    return {
      horizontal,
      vertical: document.documentElement.scrollHeight - document.documentElement.clientHeight,
      offenders,
    };
  });
  expect(
    overflow.horizontal,
    `Horizontal overflow: ${JSON.stringify(overflow.offenders)}`,
  ).toBeLessThanOrEqual(1);
  expect(overflow.vertical).toBeGreaterThanOrEqual(0);

  const clippedButtons = await page.locator("button.button:visible").evaluateAll((buttons) =>
    buttons
      .filter(
        (button) =>
          button.scrollWidth > button.clientWidth + 1 ||
          button.scrollHeight > button.clientHeight + 1,
      )
      .map((button) => button.textContent?.trim() ?? button.getAttribute("aria-label")),
  );
  expect(clippedButtons).toEqual([]);

  const overlaps = await page.evaluate(() => {
    const selectors = [
      ".risk-conclusion",
      ".review-context-bar",
      ".review-tabs",
      ".decision-inspector",
      ".review-operations",
      ".copilot-panel",
    ];
    const boxes = selectors
      .map((selector) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) return undefined;
        const rect = element.getBoundingClientRect();
        return { selector, top: rect.top, bottom: rect.bottom };
      })
      .filter((item): item is { selector: string; top: number; bottom: number } => Boolean(item))
      .sort((left, right) => left.top - right.top);
    const found: string[] = [];
    for (let index = 1; index < boxes.length; index += 1) {
      if (boxes[index].top < boxes[index - 1].bottom - 1) {
        found.push(`${boxes[index - 1].selector}/${boxes[index].selector}`);
      }
    }
    return found;
  });
  expect(overlaps).toEqual([]);
}
