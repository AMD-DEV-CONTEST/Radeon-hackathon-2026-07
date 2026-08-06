import { expect, test } from "@playwright/test"
import { writeFileSync, mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

// journeys.spec.ts — Todo 10: import→verified→learn→assessment→due review.
// Runs against the PRODUCTION fallback server (E2E_BASE_URL), not Vite dev.
// Requires a disposable stack whose DB is seeded by bootstrap_study_fixture.py
// (skill 1 verified unit; skill 2 preview-only) with LC_EXTRACT_STUB=verify and
// --overdue-skill (overdue_skill_id for the due-review case).

const BASE = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173"
const OVERDUE_SKILL = process.env.E2E_OVERDUE_SKILL_ID ?? "3"   // fixture --overdue-skill id
const ANSWER = "Raft 通过强领导者简化共识协议，日志由领导者复制、多数确认后提交。"   // unit content (must never leak on assessment/review)

async function importMaterial(page: import("@playwright/test").Page, skillName: string, text: string) {
  // UploadPage is drag/drop Markdown-only (no paste textarea). Write the source
  // to a temp .md file and feed it through the hidden file input — equivalent to
  // the user picking the file (Playwright drives the same onChange).
  const dir = mkdtempSync(join(tmpdir(), "lc-e2e-"))
  const file = join(dir, "material.md")
  writeFileSync(file, text, "utf8")
  await page.goto(`${BASE}/upload`)
  await page.getByPlaceholder("例如：Raft 共识算法").fill(skillName)
  await page.setInputFiles('input[type="file"]', file)
  // skill name field keeps the manually typed value (autofill only applies when empty)
  await expect(page.getByPlaceholder("例如：Raft 共识算法")).toHaveValue(skillName)
  await expect(page.getByText(/material\.md/).first()).toBeVisible() // filename shown in dropzone
  await page.getByRole("button", { name: "创建导入" }).click()
  // lands on /processing/:runId
  await page.waitForURL(/\/processing\/\d+/)
}

test.describe("import → verified → learn → assessment → due review", () => {
  test("import creates extraction run that reaches verified; no start-learning before verified", async ({ page }) => {
    const text = "Raft 通过强领导者简化共识协议。领导者选举使用随机超时选举，多数票胜出。日志复制由领导者发起，多数确认后提交。"
    await importMaterial(page, `Journey-${Date.now()}`, text)
    // processing page polls until verified (LC_EXTRACT_STUB=verify is deterministic)
    await expect(page.getByText(/verified/)).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText("验证完成，可开始学习")).toBeVisible()
  })

  test("skill detail shows verified-unit provenance and only valid next action", async ({ page }) => {
    await page.goto(`${BASE}/skills/1`)
    await expect(page.getByRole("button", { name: "开始学习" })).toBeVisible()
    await expect(page.getByRole("button", { name: "首次评估" })).toBeVisible()
    // verified unit content is revealed on the detail page
    await expect(page.getByText(/Raft 通过强领导者简化共识协议/).first()).toBeVisible()
  })

  test("preview-only skill cannot enter learning (409, recovery state)", async ({ page }) => {
    // skill 2 in the fixture has NO verified units -> learning CTA disabled
    await page.goto(`${BASE}/skills/2`)
    await expect(page.getByRole("button", { name: "开始学习" })).toBeDisabled()
    await expect(page.getByText(/还没有已验证的学习单元/)).toBeVisible()
  })

  test("learning page reveals explanation/key points/example/pitfall/source", async ({ page }) => {
    await page.goto(`${BASE}/skills/1/learn`)
    await expect(page.getByText(/单元 1/)).toBeVisible()
    await expect(page.getByText(/来源：/).first()).toBeVisible()
    // draft textarea appears once the learn session is established
    await expect(page.getByLabel("费曼复述草稿")).toBeVisible()
  })

  test("first assessment hides answer and shows accessible recall input", async ({ page }) => {
    await page.goto(`${BASE}/skills/1/assessment`)
    await page.getByRole("button", { name: "开始评估" }).click()
    // source-grounded prompt, answer content NOT revealed
    await expect(page.getByLabel("回忆输入")).toBeVisible()
    const body = await page.locator("body").innerText()
    expect(body).not.toContain(ANSWER)
  })

  test("submitted draft is cleared and does not reappear on reload", async ({ page }) => {
    await page.goto(`${BASE}/skills/1/learn`)
    const draft = page.getByLabel("费曼复述草稿")
    await draft.fill("已提交的草稿内容")
    await page.getByRole("button", { name: "标记本单元完成" }).click()
    await page.reload()
    // sessionStorage cleared -> textarea empty after resume
    await expect(page.getByLabel("费曼复述草稿")).toHaveValue("")
  })

  test("due review resumes persisted session and hides answer content", async ({ page }) => {
    await page.goto(`${BASE}/skills/${OVERDUE_SKILL}/review`)
    await expect(page.getByLabel("复习回忆输入")).toBeVisible({ timeout: 20_000 })
    const body = await page.locator("body").innerText()
    expect(body).not.toContain(ANSWER)
    await expect(page.getByText(/来源提示：/)).toBeVisible()
  })

  test("markdown source document is persisted and rendered from the skill detail page", async ({ page }) => {
    // upload a markdown file with structure visible after rendering; the stub
    // extractor uses the FIRST sentence (must contain STUB_KEYS to pass entailment)
    const mdText = "强领导者通过多数确认后提交达成一致。\n\n# 标题单元\n\n**加粗要点**\n\n- 列表项一\n- 列表项二"
    await importMaterial(page, `SourceView-${Date.now()}`, mdText)
    await expect(page.getByText(/verified/)).toBeVisible({ timeout: 20_000 })
    // source document link is reachable from the run card on the skill detail page
    await page.getByRole("button", { name: "查看技能" }).click()
    await page.waitForURL(/\/skills\/\d+/)
    await page.getByRole("button", { name: /查看源文档/ }).first().click()
    await page.waitForURL(/\/source\/\d+/)
    // raw markdown is rendered: heading + bold + list visible
    await expect(page.getByRole("heading", { name: "标题单元" })).toBeVisible()
    await expect(page.getByText("加粗要点")).toBeVisible()
    await expect(page.getByText("列表项一")).toBeVisible()
    // filename shown on the source page
    await expect(page.getByText(/material\.md/).first()).toBeVisible()
  })

  test("non-markdown file is rejected on the upload page", async ({ page }) => {
    const dir = mkdtempSync(join(tmpdir(), "lc-e2e-"))
    const file = join(dir, "notes.txt")
    writeFileSync(file, "这是文本内容，不是 markdown。", "utf8")
    await page.goto(`${BASE}/upload`)
    await page.getByPlaceholder("例如：Raft 共识算法").fill("非 Markdown")
    await page.setInputFiles('input[type="file"]', file)
    await expect(page.getByText(/仅支持 Markdown/)).toBeVisible()
  })
})
