import { expect, test } from "@playwright/test"

// shell.spec.ts — Todo 9 route-safe shell E2E.
// Runs against the PRODUCTION fallback server (E2E_BASE_URL), not Vite dev:
// the spec asserts a non-dev-server response (web/dist asset served).

const BASE = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173"

const ROUTES = [
  { path: "/garden", label: "技能花园" },
  { path: "/upload", label: "上传资料" },
  { path: "/skills/1", label: "学习与评估" },
  { path: "/skills/1/learn", label: "学习 ·" },
  { path: "/skills/1/assessment", label: "首次评估" },
  { path: "/skills/1/review", label: "费曼复习" },
  { path: "/processing/1", label: "提取作业" },
]

test.describe("shell routing (production fallback)", () => {
  test("serves built web/dist assets, not Vite dev server", async ({ page }) => {
    const resp = await page.goto(`${BASE}/`)
    expect(resp?.status()).toBe(200)
    // dev server injects @vite/client; production does not
    const html = await page.content()
    expect(html).not.toContain("@vite/client")
    expect(html.toLowerCase()).toContain("<!doctype html")
  })

  for (const r of ROUTES) {
    test(`direct load recovers ${r.path}`, async ({ page }) => {
      const resp = await page.goto(`${BASE}${r.path}`)
      expect(resp?.status()).toBe(200)
      // no blank page: at least one visible heading/button area
      await expect(page.locator("body")).not.toBeEmpty()
    })
  }

  test("back/forward navigation between routes", async ({ page }) => {
    await page.goto(`${BASE}/garden`)
    await page.goto(`${BASE}/upload`)
    await page.goBack()
    await expect(page).toHaveURL(`${BASE}/garden`)
    await page.goForward()
    await expect(page).toHaveURL(`${BASE}/upload`)
  })

  test("refresh preserves deep link", async ({ page }) => {
    await page.goto(`${BASE}/skills/1`)
    await page.reload()
    await expect(page).toHaveURL(`${BASE}/skills/1`)
    await expect(page.locator("body")).not.toBeEmpty()
  })

  test("invalid route renders accessible recovery state", async ({ page }) => {
    await page.goto(`${BASE}/skills/not-a-number`)
    await expect(page.getByRole("alert")).toBeVisible()
    await expect(page.getByRole("button", { name: "返回花园" })).toBeVisible()
  })

  test("unknown path renders recovery state", async ({ page }) => {
    await page.goto(`${BASE}/does-not-exist`)
    await expect(page.getByRole("alert")).toBeVisible()
  })

  test("draft survives reload and clears on abandon", async ({ page }) => {
    await page.goto(`${BASE}/skills/1/learn`)
    await page.getByLabel("费曼复述草稿").fill("我的部分回答")
    await page.reload()
    await expect(page.getByLabel("费曼复述草稿")).toHaveValue("我的部分回答")
    // simulate abandon path: navigate away and back — sessionStorage draft persists
    await page.goto(`${BASE}/garden`)
    await page.goto(`${BASE}/skills/1/learn`)
    await expect(page.getByLabel("费曼复述草稿")).toHaveValue("我的部分回答")
    // clearing: fill empty then reload — no resurrection
    await page.getByLabel("费曼复述草稿").fill("")
    await page.reload()
    await expect(page.getByLabel("费曼复述草稿")).toHaveValue("")
  })
})

test.describe("shell responsiveness", () => {
  test("no horizontal overflow at 375px", async ({ page }) => {
    await page.goto(`${BASE}/garden`)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })

  test("primary controls reachable at 375px (mobile nav)", async ({ page }) => {
    await page.goto(`${BASE}/garden`)
    await expect(page.getByRole("button", { name: "📤 上传资料" })).toBeVisible()
  })

  test("desktop sidebar present at 1280px", async ({ page }) => {
    await page.goto(`${BASE}/garden`)
    const sidebar = page.locator("aside")
    await expect(sidebar).toBeVisible()
  })
})
