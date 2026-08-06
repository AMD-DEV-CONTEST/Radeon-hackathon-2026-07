import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '/Users/tonalddrump/.claude/skills/gstack/node_modules/playwright/index.mjs';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const APP = 'http://127.0.0.1:8790';
const OUT = path.join(ROOT, 'demo');
const RAW = path.join(OUT, 'raw');
const WIDTH = 1600;
const HEIGHT = 900;

const narration = (await fs.readFile(path.join(ROOT, 'docs/DEMO_NARRATION.txt'), 'utf8'))
  .split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean);
const totalSeconds = 235.92;
const weights = narration.map((part) => part.split(/\s+/).length);
const totalWords = weights.reduce((sum, n) => sum + n, 0);
const segmentSeconds = weights.map((n) => totalSeconds * n / totalWords);

await fs.mkdir(RAW, { recursive: true });
const architecture = (await fs.readFile(path.join(ROOT, 'docs/architecture.png'))).toString('base64');

const slideStyle = `
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; }
  body { background: #0b0f10; color: #edf3f3; font: 600 24px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  .slide { width: 1600px; height: 900px; padding: 86px 112px; position: relative; background: #0b0f10; }
  .slide:after { content: ''; position: absolute; left: 112px; right: 112px; bottom: 58px; height: 3px; background: #e95751; }
  .kicker { color: #65d7cf; font: 800 18px/1.2 ui-monospace, Menlo, monospace; letter-spacing: 2px; }
  h1 { margin: 18px 0 18px; max-width: 1100px; font-size: 64px; line-height: 1.04; letter-spacing: 0; }
  h2 { margin: 0 0 18px; font-size: 42px; line-height: 1.08; }
  p { color: #b4c3c5; font-size: 25px; line-height: 1.45; max-width: 1060px; }
  .muted { color: #7e9194; font: 700 18px/1.4 ui-monospace, Menlo, monospace; }
  .warning { display: inline-block; margin-top: 28px; padding: 12px 16px; border-left: 4px solid #e0b24f; background: #201a10; color: #f0d797; font-size: 20px; }
  .grid { display: grid; grid-template-columns: 1.05fr .95fr; gap: 34px; margin-top: 44px; }
  .panel { border: 1px solid #344044; background: #111719; padding: 28px; }
  .panel h3 { margin: 0 0 20px; color: #65d7cf; font: 800 18px/1.2 ui-monospace, Menlo, monospace; }
  .row { display: flex; justify-content: space-between; gap: 24px; padding: 16px 0; border-bottom: 1px solid #283235; }
  .row:last-child { border-bottom: 0; }
  .row span { color: #91a3a5; }
  .row strong { color: #edf3f3; text-align: right; }
  .big { color: #65d7cf; font-size: 46px; font-weight: 800; }
  .red { color: #ff817a; }
  .arch { position: absolute; right: 100px; bottom: 170px; width: 600px; border: 1px solid #344044; }
  .columns { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 44px; }
  .step { min-height: 160px; border: 1px solid #344044; padding: 22px; background: #111719; }
  .step b { display: block; color: #65d7cf; font: 800 15px/1.2 ui-monospace, Menlo, monospace; }
  .step strong { display: block; margin-top: 16px; font-size: 22px; }
  .footer { position: absolute; left: 112px; bottom: 82px; color: #7e9194; font: 700 16px/1.2 ui-monospace, Menlo, monospace; }
`;

function slide(body) {
  return `<!doctype html><html><head><style>${slideStyle}</style></head><body>${body}</body></html>`;
}

async function showSlide(page, body, seconds) {
  await page.setContent(slide(body), { waitUntil: 'load' });
  await page.waitForTimeout(Math.max(250, Math.round(seconds * 1000)));
}

async function hold(page, seconds) {
  await page.waitForTimeout(Math.max(250, Math.round(seconds * 1000)));
}

const browser = await chromium.launch({
  headless: true,
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
const context = await browser.newContext({
  viewport: { width: WIDTH, height: HEIGHT },
  recordVideo: { dir: RAW, size: { width: WIDTH, height: HEIGHT } },
  deviceScaleFactor: 1,
});
const page = await context.newPage();
page.on('console', (message) => {
  if (message.type() === 'error') console.error(`[browser] ${message.text()}`);
});

// 1. Real operator console: load the synthetic checkout incident.
await page.goto(APP, { waitUntil: 'networkidle' });
await page.click('#sample-button');
await page.screenshot({ path: path.join(OUT, 'stills', '01-sample.png') }).catch(() => {});
await hold(page, segmentSeconds[0]);

// 2. Create the server-owned, bounded four-step investigation.
await page.click('#create-button');
await page.waitForSelector('#next-button:not([disabled])');
await page.screenshot({ path: path.join(OUT, 'stills', '02-plan.png') }).catch(() => {});
await hold(page, segmentSeconds[1]);

// 3. Historical Radeon evidence, explicitly separated from this offline-safe capture.
await showSlide(page, `
  <main class="slide">
    <div class="kicker">RUNTIME EVIDENCE / PROVENANCE</div>
    <h2>Radeon deployment evidence</h2>
    <p>The competition runtime served Qwen3-8B through vLLM on Radeon PRO W7900 with ROCm.</p>
    <div class="grid">
      <section class="panel"><h3>CAPTURED RUNTIME EVIDENCE</h3>
        <div class="row"><span>Captured</span><strong>2026-07-30 · Global Radeon Cloud</strong></div>
        <div class="row"><span>GPU</span><strong>AMD Radeon PRO W7900 · 48 GB</strong></div>
        <div class="row"><span>ROCm / vLLM</span><strong>7.2.1 / 0.16.1.dev</strong></div>
        <div class="row"><span>Model</span><strong>Qwen3-8B-AWQ</strong></div>
      </section>
      <section class="panel"><h3>TRUST BOUNDARY</h3>
        <div class="big">0</div><div>remote core requests in the workflow gate</div>
        <div class="warning">This is captured evidence, not a live GPU check in this recording.</div>
      </section>
    </div>
  </main>
`, segmentSeconds[2]);

// Return to the real UI. The persisted session is restored from local storage.
await page.goto(APP, { waitUntil: 'networkidle' });
await page.waitForSelector('#next-button:not([disabled])');

// 4-7. Execute every real UI step and hold the resulting evidence.
await page.click('#next-button');
await page.waitForSelector('.trace-event');
await page.screenshot({ path: path.join(OUT, 'stills', '03-deployments.png') }).catch(() => {});
await hold(page, segmentSeconds[3]);
await page.click('#next-button');
await page.waitForFunction(() => document.querySelectorAll('.trace-event').length >= 2);
await page.screenshot({ path: path.join(OUT, 'stills', '04-metrics.png') }).catch(() => {});
await hold(page, segmentSeconds[4]);
await page.click('#next-button');
await page.waitForFunction(() => document.querySelectorAll('.trace-event').length >= 3);
await page.screenshot({ path: path.join(OUT, 'stills', '05-logs.png') }).catch(() => {});
await hold(page, segmentSeconds[5]);
await page.click('#next-button');
await page.waitForSelector('.action-item');
await page.screenshot({ path: path.join(OUT, 'stills', '06-synthesis.png') }).catch(() => {});
await hold(page, segmentSeconds[6]);

// 8. Human-controlled simulation queue: approve rollback, reject pool expansion.
const firstAction = page.locator('.action-item').nth(0);
await firstAction.locator('[data-decision="approved"]').click();
await page.waitForSelector('.action-item.approved');
const secondAction = page.locator('.action-item').nth(1);
await secondAction.locator('[data-decision="rejected"]').click();
await page.waitForSelector('.action-item.rejected');
await page.screenshot({ path: path.join(OUT, 'stills', '07-decisions.png') }).catch(() => {});
await hold(page, segmentSeconds[7]);

// 9. Session-scoped cited follow-up.
await page.fill('#message-input', 'Why should we reject the connection-pool increase?');
await page.click('#message-button');
await page.waitForFunction(() => document.querySelectorAll('#messages .message').length >= 2);
await page.screenshot({ path: path.join(OUT, 'stills', '08-followup.png') }).catch(() => {});
await hold(page, segmentSeconds[8]);
await hold(page, segmentSeconds[9]);

// 10. The actual local capture is offline-safe/degraded; preserve that visible state.
await page.evaluate(() => window.scrollTo(0, 0));
await page.screenshot({ path: path.join(OUT, 'stills', '09-fallback.png') }).catch(() => {});
await hold(page, segmentSeconds[10]);

// 11. Model-level benchmark card from committed Radeon JSON evidence.
await showSlide(page, `
  <main class="slide">
    <div class="kicker">MODEL-LEVEL MICROBENCHMARK / SAME PROMPT</div>
    <h2>Radeon vLLM execution mode</h2>
    <p>Five iterations · 459-token prompt · 160 generated tokens · Qwen3-8B-AWQ.</p>
    <div class="grid">
      <section class="panel"><h3>OUTPUT RATE</h3>
        <div class="row"><span>Default compiled</span><strong class="red">15.64 tok/s</strong></div>
        <div class="row"><span>--enforce-eager</span><strong class="big">39.35 tok/s</strong></div>
        <div class="row"><span>Relative throughput</span><strong>2.5×</strong></div>
      </section>
      <section class="panel"><h3>LATENCY P50</h3>
        <div class="row"><span>TTFT</span><strong>76.54 ms → 56.50 ms</strong></div>
        <div class="row"><span>End to end</span><strong>10.31 s → 4.13 s</strong></div>
        <div class="warning">Captured Radeon benchmark evidence; not an end-to-end workflow claim.</div>
      </section>
    </div>
  </main>
`, segmentSeconds[11]);

// 12-13. Close with the editable architecture and submission message.
await showSlide(page, `
  <main class="slide">
    <div class="kicker">LOCAL INCIDENT COMMANDER / AMD AI DEVMASTER TRACK 2</div>
    <h1>Private inference.<br>Bounded tools.<br>Auditable recovery.</h1>
    <p>Native tool calls become a trusted evidence ledger, a cited root cause, a human decision, and a recoverable audit trail.</p>
    <img class="arch" src="data:image/png;base64,${architecture}" alt="Architecture diagram">
  </main>
`, segmentSeconds[12]);

await context.close();
await browser.close();
const videos = (await fs.readdir(RAW)).filter((name) => name.endsWith('.webm'));
if (videos.length !== 1) throw new Error(`Expected exactly one WebM capture, found ${videos.length}`);
await fs.rename(path.join(RAW, videos[0]), path.join(OUT, 'ui-capture.webm'));
console.log(`Captured ${path.join(OUT, 'ui-capture.webm')}`);
console.log(`Segments ${segmentSeconds.map((n) => n.toFixed(2)).join(', ')}`);
