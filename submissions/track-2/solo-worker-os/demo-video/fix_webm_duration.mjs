import { chromium } from "playwright";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const input = path.resolve(process.argv[2]);
const durationMs = Number(process.argv[3]);
const temporary = `${input}.duration-fix.tmp`;
const fixer = path.resolve(
  "demo-video/vendor/fix-webm-duration/fix-webm-duration.js",
);
const size = fs.statSync(input).size;

const server = http.createServer((req, res) => {
  if (req.url === "/") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end("<!doctype html><title>WebM duration repair</title>");
    return;
  }
  if (req.url === "/media.webm") {
    res.writeHead(200, {
      "Content-Length": size,
      "Content-Type": "video/webm",
      "Cache-Control": "no-store",
    });
    fs.createReadStream(input).pipe(res);
    return;
  }
  res.writeHead(404).end();
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const port = server.address().port;
const browser = await chromium.launch({
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  headless: true,
});

try {
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.addScriptTag({ path: fixer });

  const downloadPromise = page.waitForEvent("download", { timeout: 60_000 });
  await page.evaluate(async ({ durationMs }) => {
    const response = await fetch("/media.webm");
    const source = await response.blob();
    const fixed = await window.ysFixWebmDuration(source, durationMs, { logger: false });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(fixed);
    link.download = "duration-fixed.webm";
    link.click();
  }, { durationMs });

  const download = await downloadPromise;
  await download.saveAs(temporary);
  await context.close();
} finally {
  await browser.close();
  server.close();
}

fs.rmSync(input);
fs.renameSync(temporary, input);
console.log(input);
