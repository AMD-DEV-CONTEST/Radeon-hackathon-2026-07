const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { marked } = require('marked');

const root = path.resolve(__dirname, '..');
const docsDir = path.join(root, 'docs');
const out = path.join(root, 'submission', 'NuclidePath_Project_Specification.pdf');
const sections = [
  'SPECIFICATION.md',
];

const body = sections.map((name, index) => {
  const markdown = fs.readFileSync(path.join(docsDir, name), 'utf8');
  return `<section class="document ${index ? 'new-page' : ''}">${marked.parse(markdown)}</section>`;
}).join('\n');
const docsUrl = `file://${docsDir.replaceAll(' ', '%20')}/`;
const dashboardUrl = `file://${path.join(docsDir, 'assets', 'dashboard.png').replaceAll(' ', '%20')}`;
const html = `<!doctype html><html><head><meta charset="utf-8"><base href="${docsUrl}"><style>
@page { size: A4; margin: 17mm 16mm 18mm; }
* { box-sizing: border-box; }
body { margin: 0; color: #17191c; font: 10.5pt/1.48 Arial, sans-serif; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }
.kicker { color: #e85d00; font: 700 10pt Arial; letter-spacing: 1.7px; text-transform: uppercase; }
.cover h1 { margin: 12mm 0 2mm; font-size: 36pt; line-height: 1; }
.cover h2 { margin: 0 0 8mm; font-size: 20pt; font-weight: 400; color: #4c5157; }
.cover img { width: 100%; border: 1px solid #d9dde1; margin: 8mm 0; }
.stats { display: grid; grid-template-columns: repeat(4,1fr); gap: 4mm; }
.stat { border-top: 3px solid #ff6b00; padding-top: 2mm; }
.stat b { display: block; font: 700 20pt monospace; }
h1 { font-size: 24pt; line-height: 1.12; margin: 0 0 7mm; color: #101114; }
h2 { font-size: 16pt; margin: 8mm 0 3mm; color: #202327; page-break-after: avoid; }
h3 { font-size: 12.5pt; margin: 6mm 0 2mm; page-break-after: avoid; }
p { margin: 0 0 3mm; }
ul, ol { margin: 0 0 4mm 5mm; padding-left: 5mm; }
li { margin-bottom: 1mm; }
blockquote { margin: 4mm 0; border-left: 4px solid #ff6b00; padding: 3mm 5mm; background: #f5f6f7; }
code { font-family: 'DejaVu Sans Mono', monospace; background: #f0f1f2; padding: 0.2mm 1mm; }
pre { background: #111316; color: #f1f3f5; padding: 4mm; overflow-wrap: anywhere; white-space: pre-wrap; page-break-inside: avoid; }
pre code { background: transparent; padding: 0; }
table { width: 100%; border-collapse: collapse; margin: 3mm 0 5mm; font-size: 9pt; page-break-inside: avoid; }
th { background: #17191c; color: white; text-align: left; }
th, td { border: 1px solid #cfd3d7; padding: 2mm; vertical-align: top; }
a { color: #b54700; text-decoration: none; }
img { max-width: 100%; page-break-inside: avoid; }
hr { border: 0; border-top: 1px solid #cfd3d7; margin: 7mm 0; }
.new-page { page-break-before: always; }
.document > h1:first-child::before { content: 'NUCLIDEPATH  /  TECHNICAL DOSSIER'; display: block; color: #e85d00; font: 700 8pt Arial; letter-spacing: 1.2px; margin-bottom: 4mm; }
</style></head><body>
<section class="cover"><div class="kicker">AMD AI DEVMASTER HACKATHON 2026 · TRACK 2</div><h1>NuclidePath</h1><h2>Private agents. Deterministic physics.</h2><p>A fully local, physics-first AI workflow for traceable Cs-137 groundwater screening.</p><img src="${dashboardUrl}"><div class="stats"><div class="stat"><b>5/5</b>Track 2 capabilities</div><div class="stat"><b>231</b>AMD core snapshot</div><div class="stat"><b>377/15</b>latest CI gate</div><div class="stat"><b>0</b>cloud calls</div></div><p style="margin-top:12mm"><b>Team:</b> Physics-First AI · <b>Author:</b> Stefano Rigante</p><p style="margin-top:2mm;font-size:9pt;color:#4c5157;border-top:1px solid #d9dde1;padding-top:3mm">The Cs–K GCS core covers K competition and NH₄ on frayed-edge sites; the opt-in PHREEQC bridge extends to K/Na/Ca/Mg multicomponent chemistry (schema 2, PROCESS-QUALIFIED ONLY) while the canonical transport path remains authoritative.</p></section>
${body}
</body></html>`;

(async () => {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const temporaryHtml = path.join(path.dirname(out), '.NuclidePath_Project_Specification.html');
  fs.writeFileSync(temporaryHtml, html);
  await page.goto(`file://${temporaryHtml}`, { waitUntil: 'load' });
  await page.waitForFunction(() => Array.from(document.images).every(img => img.complete && img.naturalWidth > 0), null, { timeout: 60000 });
  await page.pdf({ path: out, format: 'A4', printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: '<div style="width:100%;font:8px Arial;color:#777;text-align:center"><span class="title"></span> · <span class="pageNumber"></span>/<span class="totalPages"></span></div>',
    margin: { top: '17mm', bottom: '18mm', left: '16mm', right: '16mm' }
  });
  await browser.close();
  fs.rmSync(temporaryHtml, { force: true });
  console.log(out);
})().catch(error => { console.error(error); process.exit(1); });
