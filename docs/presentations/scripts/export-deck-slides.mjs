#!/usr/bin/env node
/**
 * Export investor-seed-2026.html slides to PNG for PPT assembly.
 * Usage: node export-deck-slides.mjs [--deck path] [--out dir] [--width 1920] [--height 1080] [--scale 2]
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import puppeteer from 'puppeteer';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const presentationsDir = path.resolve(__dirname, '..');

function parseArgs(argv) {
  const opts = {
    deck: path.join(presentationsDir, 'investor-seed-2026.html'),
    out: path.join(presentationsDir, 'slides-png', 'investor-seed-2026'),
    width: 1920,
    height: 1080,
    scale: 2,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--deck' && argv[i + 1]) opts.deck = path.resolve(argv[++i]);
    else if (a === '--out' && argv[i + 1]) opts.out = path.resolve(argv[++i]);
    else if (a === '--width' && argv[i + 1]) opts.width = Number(argv[++i]);
    else if (a === '--height' && argv[i + 1]) opts.height = Number(argv[++i]);
    else if (a === '--scale' && argv[i + 1]) opts.scale = Number(argv[++i]);
  }
  return opts;
}

const opts = parseArgs(process.argv);
if (!fs.existsSync(opts.deck)) {
  console.error('Deck not found:', opts.deck);
  process.exit(1);
}
fs.mkdirSync(opts.out, { recursive: true });

const deckUrl = `file://${opts.deck}?export=1&slide=0`;

const browser = await puppeteer.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--font-render-hinting=medium'],
});
const page = await browser.newPage();
await page.setViewport({
  width: opts.width,
  height: opts.height,
  deviceScaleFactor: opts.scale,
});

await page.goto(deckUrl, { waitUntil: 'networkidle0', timeout: 120000 });
const slideCount = await page.evaluate(() => document.querySelectorAll('#deck .slide').length);
console.log(`Exporting ${slideCount} slides → ${opts.out}`);
console.log(`Viewport ${opts.width}×${opts.height} @${opts.scale}x (${opts.width * opts.scale}×${opts.height * opts.scale}px output)`);

for (let i = 0; i < slideCount; i++) {
  const url = `file://${opts.deck}?export=1&slide=${i}`;
  await page.goto(url, { waitUntil: 'networkidle0', timeout: 120000 });
  await page.evaluate(() => document.fonts?.ready);
  await new Promise((r) => setTimeout(r, 350));
  const name = `slide-${String(i + 1).padStart(2, '0')}.png`;
  await page.screenshot({ path: path.join(opts.out, name), type: 'png' });
  console.log(`  ${name}`);
}

await browser.close();

const manifest = {
  deck: path.basename(opts.deck),
  slides: slideCount,
  size: `${opts.width}x${opts.height}`,
  deviceScaleFactor: opts.scale,
  pptHint: 'Insert 16:9 slide; fit image to slide. Recommended: one PNG per slide in order.',
};
fs.writeFileSync(path.join(opts.out, 'MANIFEST.json'), JSON.stringify(manifest, null, 2));
console.log('Done.');
