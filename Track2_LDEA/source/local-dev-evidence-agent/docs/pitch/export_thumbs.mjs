import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const slidesDir = path.join(__dirname, 'slides');
const thumbsDir = path.join(__dirname, 'thumbs');
fs.mkdirSync(thumbsDir, { recursive: true });

const files = fs.readdirSync(slidesDir).filter((f) => f.endsWith('.html')).sort();
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

let i = 1;
for (const f of files) {
  const page = await ctx.newPage();
  const url = 'file:///' + path.join(slidesDir, f).replace(/\\/g, '/');
  await page.goto(url, { waitUntil: 'networkidle' }).catch(() => page.goto(url));
  await page.waitForTimeout(1500);
  const out = path.join(thumbsDir, String(i).padStart(2, '0') + '.jpg');
  await page.screenshot({ path: out, type: 'jpeg', quality: 82 });
  console.log('thumb', path.basename(out));
  await page.close();
  i++;
}
await browser.close();
console.log('done', files.length);
