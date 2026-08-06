import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const ROOT = "E:/gitproject/hackathon/solo";
const BASE = process.env.DEMO_BASE || "http://127.0.0.1:3000";
const OUTPUT_DIR = path.join(ROOT, "demo-video", "final");
const CAPTURE_DIR = path.join(OUTPUT_DIR, ".live-capture");
const OUTPUT = path.join(
  OUTPUT_DIR,
  "solo-worker-os-live-radeon-demo-2026-08-06.webm",
);
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function typeAndSend(page, textbox, text) {
  await textbox.click();
  await textbox.fill("");
  await textbox.pressSequentially(text, { delay: 45 });
  await page.waitForTimeout(800);
  await textbox.press("Enter");
  const stopButton = page.getByRole("button", { name: /停止|Stop/ });
  await stopButton.waitFor({ state: "visible", timeout: 10_000 });
  await stopButton.waitFor({ state: "hidden", timeout: 150_000 });
}

async function main() {
  fs.rmSync(CAPTURE_DIR, { recursive: true, force: true });
  fs.mkdirSync(CAPTURE_DIR, { recursive: true });

  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
  });
  const context = await browser.newContext({
    locale: "zh-CN",
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: CAPTURE_DIR, size: { width: 1920, height: 1080 } },
  });
  const page = await context.newPage();
  const video = page.video();

  // Product overview.
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await pause(5_000);
  await page.mouse.move(520, 280);
  await pause(1_000);
  await page.mouse.move(1250, 280);
  await pause(2_000);
  await page.evaluate(() => window.scrollTo({ top: 460, behavior: "smooth" }));
  await pause(4_000);

  // Show the real health response while excluding the temporary tunnel URL.
  await page.goto(`${BASE}/api/local-llm/status`, { waitUntil: "networkidle" });
  const status = JSON.parse(await page.locator("pre").innerText());
  const sanitizedStatus = {
    provider: status.provider,
    isLocal: status.isLocal,
    configuredModel: status.configuredModel,
    reachable: status.reachable,
    servedModels: status.servedModels,
    latencyMs: status.latencyMs,
    error: status.error,
  };
  await page.evaluate((value) => {
    document.body.innerHTML = `
      <main style="font: 28px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace;
        background:#0b0d10;color:#e7ecf2;min-height:100vh;padding:72px 100px;box-sizing:border-box">
        <div style="color:#f5a623;font:700 24px/1.2 system-ui;margin-bottom:20px">LIVE GPU INFERENCE STATUS</div>
        <div style="font:700 48px/1.2 system-ui;margin-bottom:30px">Solo Worker OS + AMD Radeon</div>
        <pre style="white-space:pre-wrap;background:#12161b;border:1px solid #343a42;border-radius:8px;
          padding:34px;color:#dce6ef">${JSON.stringify(value, null, 2)}</pre>
        <p style="font:22px/1.4 system-ui;color:#9da8b4">Temporary network endpoint omitted from the recording.</p>
      </main>`;
  }, sanitizedStatus);
  await pause(8_000);

  // Clear yesterday's messages so this recording contains only live requests.
  await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" });
  const clearButton = page.getByRole("button", { name: /清空|Clear/ });
  if (await clearButton.count()) {
    page.once("dialog", (dialog) => dialog.accept());
    await clearButton.click();
    await pause(2_000);
  }

  const textbox = page.getByRole("textbox", { name: /告诉我你想做什么|Message your agent/i });
  await typeAndSend(
    page,
    textbox,
    "新客户林悦，需要品牌官网设计，预算12800元，截止日期2026年9月15日，请直接创建项目。",
  );
  if (!(await page.getByText("create_project", { exact: false }).count())) {
    console.warn("Live response did not include create_project.");
  }
  await pause(4_000);

  await typeAndSend(page, textbox, "为林悦的项目生成一份合同。");
  if (!(await page.getByText("generate_contract", { exact: false }).count())) {
    console.warn("Live response did not include generate_contract.");
  }
  await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }));
  await pause(7_000);

  // Observability and persisted business result.
  await page.goto(`${BASE}/trace`, { waitUntil: "networkidle" });
  await pause(7_000);
  await page.goto(`${BASE}/projects`, { waitUntil: "networkidle" });
  await pause(6_000);
  await page.getByText("林悦", { exact: true }).first().scrollIntoViewIfNeeded().catch(() => {});
  await pause(5_000);

  await context.close();
  await browser.close();

  const captured = await video.path();
  if (fs.existsSync(OUTPUT)) fs.rmSync(OUTPUT);
  fs.renameSync(captured, OUTPUT);
  if (fs.existsSync(CAPTURE_DIR) && fs.readdirSync(CAPTURE_DIR).length === 0) {
    fs.rmdirSync(CAPTURE_DIR);
  }
  console.log(OUTPUT);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
