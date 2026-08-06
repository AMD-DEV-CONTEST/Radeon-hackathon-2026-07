const path = require("path");
const { chromium } = require("playwright-core");

async function main() {
  const url = process.argv[2] || "http://127.0.0.1:8521/";
  const output = process.argv[3] || path.resolve(__dirname, "../submission/assets/claimcourt-ui.png");
  const browser = await chromium.launch({
    executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.getByText("RADEON GPU READY", { exact: true }).waitFor({ timeout: 20_000 });
    await page.screenshot({ path: output, fullPage: true });
    console.log(output);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
