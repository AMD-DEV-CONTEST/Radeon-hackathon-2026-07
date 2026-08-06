# Xenix Radeon Edition poster source

`index.html` is an editable, single-page A3 landscape poster. Its print geometry is fixed by CSS to `420mm × 297mm` with zero page margin. It uses only system fonts and local repository assets; no network connection is required.

## Assets and provenance

- `../../../src/xenix/resources/logo.png` is the Xenix product mark.
- `../assets/architecture.svg` is the editable architecture and trust-boundary diagram. It can also be opened independently in a browser or vector editor.
- `../assets/hero-keyart.png` is a generative-assisted decorative visual. It is deliberately darkened and cropped behind the title, carries no factual text or measured data, and is not technical evidence.

The poster intentionally contains no AMD logo and makes no comparative performance claim. Its evidence boundary is printed directly on the page.

## Chrome print export

1. Open `index.html` in Chrome from this repository checkout.
2. Choose **Print** → **Save to PDF**.
3. Select **A3**, **Landscape**, **Margins: None**, **Scale: 100**, and enable **Background graphics**.
4. Disable browser headers and footers. The preview should show exactly one `420mm × 297mm` page with no clipped edge content.

Chrome's print dialog can occasionally retain a previous paper choice. If the preview is not exactly one A3 landscape page, reselect A3 and 100% scale; do not use “Fit to page.”

## Playwright print export

From the repository root, with Playwright and its Chromium browser available, run this PowerShell command. Replace only the output path if desired:

```powershell
$posterUri = [System.Uri]::new((Resolve-Path 'submission/track2/poster/index.html')).AbsoluteUri
node -e "const { chromium } = require('playwright'); (async()=>{ const b=await chromium.launch(); const p=await b.newPage(); await p.goto(process.argv[1], {waitUntil:'load'}); await p.pdf({path:'xenix-radeon-track2-a3.pdf', printBackground:true, preferCSSPageSize:true, margin:{top:'0',right:'0',bottom:'0',left:'0'}}); await b.close(); })();" $posterUri
```

`preferCSSPageSize: true` is required so Chromium honors the poster's `@page` dimensions instead of substituting a default paper size. The resulting PDF should contain one page. Keep the HTML and SVG as the editable sources; the exported PDF is a delivery artifact, not an authority for poster content.
