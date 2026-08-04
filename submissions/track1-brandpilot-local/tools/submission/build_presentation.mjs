import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const shotDir = path.join(root, "evidence", "final-submission", "screenshots");
const outputDir = path.join(root, "submission");
const renderDir = path.join(outputDir, "presentation-render");

const W = 1280;
const H = 720;
const BG = "#08080A";
const CARD = "#141417";
const LINE = "#303036";
const INK = "#F6F3F2";
const MUTED = "#B5AEAC";
const RED = "#EF3340";
const GREEN = "#67D6A5";
const AMBER = "#F4B85A";
const HEAD = "Arial";
const BODY = "Arial";

async function bytes(file) {
  const data = await fs.readFile(file);
  return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
}

function addShape(slide, geometry, position, fill = "none", line = { style: "solid", fill: "none", width: 0 }, name) {
  return slide.shapes.add({ geometry, position, fill, line, ...(name ? { name } : {}) });
}

function addText(slide, text, position, options = {}) {
  const shape = addShape(slide, "textbox", position, "none", { style: "solid", fill: "none", width: 0 }, options.name);
  shape.text = text;
  shape.text.style = {
    fontFamily: options.fontFamily || BODY,
    fontSize: options.fontSize || 22,
    bold: options.bold || false,
    color: options.color || INK,
    alignment: options.alignment || "left",
    verticalAlignment: options.verticalAlignment || "top",
  };
  return shape;
}

function base(slide, number, eyebrow, title, titleWidth = 1100) {
  slide.background.fill = BG;
  addShape(slide, "rect", { left: 64, top: 54, width: 78, height: 7 }, RED, { style: "solid", fill: "none", width: 0 });
  addText(slide, eyebrow.toUpperCase(), { left: 64, top: 84, width: 520, height: 28 }, { fontSize: 18, bold: true, color: RED });
  addText(slide, title, { left: 64, top: 116, width: titleWidth, height: 76 }, { fontSize: 50, bold: true, color: INK });
  addText(slide, String(number).padStart(2, "0"), { left: 1160, top: 60, width: 56, height: 28 }, { fontSize: 18, bold: true, color: "#6F6A6A", alignment: "right" });
}

function footer(slide, label = "AMD AI DevMaster - Track 1") {
  addText(slide, "BrandPilot Local", { left: 64, top: 676, width: 240, height: 20 }, { fontSize: 16, bold: true, color: "#777273" });
  addText(slide, label, { left: 880, top: 676, width: 336, height: 20 }, { fontSize: 16, color: "#777273", alignment: "right" });
}

function note(slide, lines, sources) {
  slide.speakerNotes.textFrame.setText([
    ...lines,
    "",
    "[Sources]",
    ...sources.map((source) => `- ${source}`),
    "[/Sources]",
  ]);
}

async function addImage(slide, file, position, alt, fit = "cover", crop) {
  return slide.images.add({
    blob: await bytes(path.join(shotDir, file)),
    contentType: "image/png",
    alt,
    fit,
    position,
    geometry: "roundRect",
    borderRadius: "rounded-xl",
    ...(crop ? { crop } : {}),
  });
}

function label(slide, text, left, top, color = RED) {
  addShape(slide, "roundRect", { left, top, width: 214, height: 38 }, "#18181B", { style: "solid", fill: LINE, width: 1 });
  addText(slide, text.toUpperCase(), { left: left + 15, top: top + 9, width: 184, height: 20 }, { fontSize: 16, bold: true, color });
}

async function build() {
  await fs.mkdir(outputDir, { recursive: true });
  await fs.mkdir(renderDir, { recursive: true });
  const deck = Presentation.create({ slideSize: { width: W, height: H } });

  // 1 - Title
  {
    const slide = deck.slides.add();
    slide.background.fill = BG;
    await addImage(slide, "home-desktop.png", { left: 650, top: 0, width: 630, height: 720 }, "BrandPilot Local homepage", "cover", { left: 0.28, top: 0, right: 0, bottom: 0 });
    addShape(slide, "rect", { left: 0, top: 0, width: 780, height: 720 }, { color: BG, transparency: 0 }, { style: "solid", fill: "none", width: 0 });
    addShape(slide, "rect", { left: 620, top: 0, width: 200, height: 720 }, { color: BG, transparency: 30000 }, { style: "solid", fill: "none", width: 0 });
    addText(slide, "AMD AI DEVMASTER - TRACK 1", { left: 64, top: 86, width: 480, height: 28 }, { fontSize: 18, bold: true, color: RED });
    addText(slide, "BrandPilot\nLocal", { left: 64, top: 130, width: 520, height: 170 }, { fontSize: 76, bold: true, color: INK });
    addText(slide, "One product image. One campaign system. One accountable human decision.", { left: 64, top: 330, width: 520, height: 92 }, { fontSize: 30, color: MUTED });
    label(slide, "Mock-first product", 64, 470, GREEN);
    addText(slide, "Talal Khawaja  |  Aqeela Urooj", { left: 64, top: 550, width: 520, height: 34 }, { fontSize: 24, bold: true, color: INK });
    addText(slide, "AMD Radeon + ROCm evidence, without overstating the public edge", { left: 64, top: 592, width: 540, height: 52 }, { fontSize: 20, color: MUTED });
    note(slide, ["Open with the customer problem and the product's honest verification boundary."], ["README.md", "docs/final-claim-audit.md"]);
  }

  // 2 - Problem
  {
    const slide = deck.slides.add();
    base(slide, 2, "Problem", "Campaign creation is fragmented by default.");
    const steps = [
      ["PROMPT", "A visual idea without brand context"],
      ["DESIGN", "Formats and composition split elsewhere"],
      ["COPY", "Claims and calls-to-action drift"],
      ["REVIEW", "Decisions disappear into chat"],
    ];
    steps.forEach(([head, copy], i) => {
      const top = 236 + i * 88;
      addText(slide, head, { left: 76, top, width: 150, height: 30 }, { fontSize: 18, bold: true, color: RED });
      addText(slide, copy, { left: 230, top, width: 470, height: 48 }, { fontSize: 24, color: INK });
      if (i < steps.length - 1) addShape(slide, "rect", { left: 76, top: top + 59, width: 624, height: 1 }, LINE, { style: "solid", fill: "none", width: 0 });
    });
    addShape(slide, "roundRect", { left: 760, top: 226, width: 456, height: 344 }, CARD, { style: "solid", fill: LINE, width: 1 });
    addText(slide, "The cost", { left: 800, top: 264, width: 220, height: 34 }, { fontSize: 32, bold: true, color: INK });
    addText(slide, "Slow iteration\nWeak traceability\nUnnecessary asset exposure\nReview without accountability", { left: 800, top: 324, width: 350, height: 185 }, { fontSize: 28, color: MUTED });
    footer(slide);
    note(slide, ["Describe the fragmented workflow and why a campaign system is more valuable than another prompt box."], ["README.md#the-problem", "submission/project-profile.md#problem"]);
  }

  // 3 - Workflow
  {
    const slide = deck.slides.add();
    base(slide, 3, "Solution", "One asset becomes an accountable campaign.");
    const items = [
      ["01", "Upload", "Validated product image"],
      ["02", "Direct", "Audience, brand, formats"],
      ["03", "Create", "Four labelled concepts"],
      ["04", "Review", "Persisted human decision"],
    ];
    items.forEach(([num, head, copy], i) => {
      const left = 64 + i * 288;
      addText(slide, num, { left, top: 224, width: 58, height: 34 }, { fontSize: 24, bold: true, color: RED });
      addText(slide, head, { left, top: 270, width: 240, height: 38 }, { fontSize: 32, bold: true, color: INK });
      addText(slide, copy, { left, top: 318, width: 230, height: 58 }, { fontSize: 22, color: MUTED });
      if (i < 3) addShape(slide, "rect", { left: left + 230, top: 289, width: 42, height: 2 }, RED, { style: "solid", fill: "none", width: 0 });
    });
    await addImage(slide, "studio-desktop.png", { left: 64, top: 418, width: 1152, height: 220 }, "Creative Studio screenshot", "cover", { left: 0, top: 0, right: 0, bottom: 0.48 });
    label(slide, "Local UI demonstration", 88, 440, GREEN);
    footer(slide);
    note(slide, ["Walk through the four product stages. Clarify that the screenshot shows the local mock-first product."], ["frontend/app/studio/page.tsx", "evidence/final-submission/screenshots/studio-desktop.png"]);
  }

  // 4 - Product experience
  {
    const slide = deck.slides.add();
    base(slide, 4, "Product experience", "The review board makes provenance visible.");
    await addImage(slide, "results-desktop.png", { left: 64, top: 220, width: 716, height: 390 }, "Mock campaign results", "cover", { left: 0.08, top: 0.02, right: 0, bottom: 0.18 });
    await addImage(slide, "review-approved.png", { left: 808, top: 220, width: 408, height: 255 }, "Approved mock campaign review", "cover", { left: 0.03, top: 0, right: 0.03, bottom: 0 });
    label(slide, "Mock campaign concept", 88, 242, AMBER);
    addText(slide, "Mock stays labelled.", { left: 818, top: 508, width: 390, height: 34 }, { fontSize: 30, bold: true, color: INK });
    addText(slide, "Approve, reject, request changes, edit copy, regenerate, and refresh without losing the decision.", { left: 818, top: 552, width: 370, height: 78 }, { fontSize: 22, color: MUTED });
    footer(slide);
    note(slide, ["Point out the mock disclosure and the Approved state. The local browser refresh reloaded the stored decision."], ["evidence/final-submission/screenshots/results-desktop.png", "evidence/final-submission/screenshots/review-approved.png", "backend/tests/test_api.py"]);
  }

  // 5 - Architecture
  {
    const slide = deck.slides.add();
    base(slide, 5, "Architecture", "Mock remains default. Radeon remains explicit.");
    const nodes = [
      ["PRODUCT + BRIEF", "Validated input", 64, RED],
      ["NEXT.JS", "Responsive studio", 304, INK],
      ["FASTAPI", "Persistence + review", 544, INK],
      ["ROCM WORKER", "Single lazy GPU job", 784, AMBER],
      ["AMD RADEON", "SDXL via PyTorch/HIP", 1024, GREEN],
    ];
    nodes.forEach(([head, copy, left, color], i) => {
      addShape(slide, "roundRect", { left, top: 258, width: 194, height: 154 }, CARD, { style: "solid", fill: LINE, width: 1 });
      addText(slide, head, { left: left + 18, top: 282, width: 158, height: 28 }, { fontSize: 18, bold: true, color });
      addText(slide, copy, { left: left + 18, top: 330, width: 158, height: 60 }, { fontSize: 22, color: MUTED });
      if (i < nodes.length - 1) addShape(slide, "rect", { left: left + 194, top: 334, width: 46, height: 2 }, RED, { style: "solid", fill: "none", width: 0 });
    });
    addShape(slide, "roundRect", { left: 540, top: 478, width: 676, height: 120 }, "#101013", { style: "solid", fill: "#3A2A18", width: 1 });
    addText(slide, "EXPERIMENTAL OPT-IN", { left: 568, top: 500, width: 240, height: 26 }, { fontSize: 18, bold: true, color: AMBER });
    addText(slide, "Bearer auth · explicit CORS · loopback bind · one job · no CPU/mock fallback", { left: 568, top: 538, width: 620, height: 42 }, { fontSize: 22, color: INK });
    addText(slide, "Mock path", { left: 64, top: 486, width: 190, height: 34 }, { fontSize: 32, bold: true, color: GREEN });
    addText(slide, "Always available\nNo GPU dependency", { left: 64, top: 535, width: 220, height: 62 }, { fontSize: 22, color: MUTED });
    footer(slide);
    note(slide, ["Explain the architecture left to right. The Radeon branch is explicit and temporary; the mock product remains useful without it."], ["docs/architecture.md", "backend/app/core/config.py", "frontend/lib/experimental.ts"]);
  }

  // 6 - Radeon
  {
    const slide = deck.slides.add();
    base(slide, 6, "AMD Radeon + ROCm", "Real SDXL image-to-image completed on Radeon.");
    await addImage(slide, "verified-radeon-environment.png", { left: 64, top: 220, width: 582, height: 250 }, "Sanitized Radeon environment evidence", "contain");
    await addImage(slide, "verified-radeon-output.png", { left: 740, top: 210, width: 310, height: 310 }, "Verified Radeon generated output", "contain");
    label(slide, "Recorded Radeon evidence", 80, 236, GREEN);
    addText(slide, "gfx1100", { left: 64, top: 520, width: 170, height: 44 }, { fontSize: 38, bold: true, color: INK });
    addText(slide, "48 GiB reported", { left: 250, top: 520, width: 240, height: 44 }, { fontSize: 30, bold: true, color: INK });
    addText(slide, "HIP 7.2", { left: 510, top: 520, width: 170, height: 44 }, { fontSize: 30, bold: true, color: INK });
    addText(slide, "SDXL base 1.0\nexact revision pinned", { left: 1050, top: 280, width: 166, height: 90 }, { fontSize: 24, bold: true, color: INK });
    addText(slide, "768 × 768\n15 steps\nfp16", { left: 1050, top: 390, width: 150, height: 110 }, { fontSize: 24, color: MUTED });
    addText(slide, "The real image shown here was generated during the verified cloud session.", { left: 64, top: 598, width: 920, height: 34 }, { fontSize: 22, color: MUTED });
    footer(slide);
    note(slide, ["State explicitly that the output is recorded evidence, not a live generation in this presentation."], ["docs/radeon-session-1-results.md", "evidence/radeon-session-1/generation-metadata.json", "evidence/radeon-session-1/generated-output.png"]);
  }

  // 7 - Performance
  {
    const slide = deck.slides.add();
    base(slide, 7, "Measured performance", "The evidence records time, memory, and integrity.");
    const metrics = [
      ["132.295 s", "cold model load"],
      ["222.111 s", "generation"],
      ["13.41 GiB", "peak allocated"],
      ["14.31 GiB", "peak reserved"],
    ];
    metrics.forEach(([value, copy], i) => {
      const left = 64 + (i % 2) * 360;
      const top = 230 + Math.floor(i / 2) * 146;
      addText(slide, value, { left, top, width: 320, height: 58 }, { fontSize: 42, bold: true, color: i < 2 ? INK : GREEN });
      addText(slide, copy, { left, top: top + 64, width: 280, height: 30 }, { fontSize: 22, color: MUTED });
    });
    addShape(slide, "roundRect", { left: 828, top: 226, width: 388, height: 306 }, CARD, { style: "solid", fill: LINE, width: 1 });
    addText(slide, "Pinned run", { left: 864, top: 260, width: 250, height: 38 }, { fontSize: 32, bold: true, color: INK });
    addText(slide, "768 × 768\n15 steps\nstrength 0.35\nguidance 6.5\nseed 20260725", { left: 864, top: 320, width: 280, height: 170 }, { fontSize: 28, color: MUTED });
    addText(slide, "Output SHA-256", { left: 64, top: 535, width: 220, height: 26 }, { fontSize: 18, bold: true, color: RED });
    addText(slide, "bce21d016a8179ac4ddabcbf5869a71eacf03565948d0d1f97d24e279b125452", { left: 64, top: 574, width: 1050, height: 32 }, { fontSize: 20, color: INK });
    footer(slide, "Session 1 measured values");
    note(slide, ["These are one controlled Session 1 run's measured values. Do not describe them as a benchmark comparison."], ["evidence/radeon-session-1/generation-metadata.json", "docs/radeon-session-1-results.md"]);
  }

  // 8 - Honest validation
  {
    const slide = deck.slides.add();
    base(slide, 8, "Honest validation", "Public browser edge stopped at DNS.");
    await addImage(slide, "final-dns-blocker.png", { left: 64, top: 216, width: 716, height: 402 }, "Sanitized DNS blocker summary", "contain");
    const rows = [
      ["Standalone SDXL", "VERIFIED", GREEN],
      ["FastAPI loopback", "VERIFIED", GREEN],
      ["rc-tunnel 0.3.0", "VERIFIED", GREEN],
      ["Chrome TLS/auth/CORS/upload", "VERIFIED", GREEN],
      ["Protected output through edge", "BLOCKED - DNS", RED],
    ];
    rows.forEach(([name, status, color], i) => {
      const top = 226 + i * 72;
      addText(slide, name, { left: 820, top, width: 252, height: 46 }, { fontSize: 21, color: MUTED });
      addText(slide, status, { left: 1074, top, width: 142, height: 46 }, { fontSize: 20, bold: true, color, alignment: "right" });
      if (i < rows.length - 1) addShape(slide, "rect", { left: 820, top: top + 54, width: 396, height: 1 }, LINE, { style: "solid", fill: "none", width: 0 });
    });
    addText(slide, "No unofficial tunnel. No TLS bypass. No fabricated success.", { left: 820, top: 594, width: 390, height: 50 }, { fontSize: 19, bold: true, color: INK });
    footer(slide);
    note(slide, ["Session 2b reached project upload through the official edge. The final retry ended earlier at DNS and loaded no model. Every instance was destroyed."], ["docs/radeon-session-2b-results.md", "docs/radeon-session-3-results.md", "evidence/radeon-session-3/dns-python-final.json"]);
  }

  // 9 - Value
  {
    const slide = deck.slides.add();
    base(slide, 9, "Practical value", "Generation becomes a reviewable brand workflow.");
    const uses = [
      ["Independent brands", "Launch concepts without a fragmented toolchain"],
      ["In-house teams", "Adapt one campaign across formats"],
      ["Creative studios", "Explore directions before production"],
      ["Privacy-conscious teams", "Keep the default workflow controlled"],
    ];
    uses.forEach(([head, copy], i) => {
      const top = 226 + i * 90;
      addText(slide, head, { left: 64, top, width: 300, height: 32 }, { fontSize: 28, bold: true, color: INK });
      addText(slide, copy, { left: 372, top, width: 406, height: 50 }, { fontSize: 22, color: MUTED });
    });
    await addImage(slide, "home-mobile.png", { left: 844, top: 216, width: 170, height: 370 }, "BrandPilot mobile homepage", "cover", { left: 0, top: 0, right: 0, bottom: 0.18 });
    await addImage(slide, "studio-mobile.png", { left: 1030, top: 216, width: 170, height: 370 }, "BrandPilot mobile studio", "cover", { left: 0, top: 0, right: 0, bottom: 0.18 });
    addText(slide, "Responsive by design", { left: 844, top: 612, width: 356, height: 34 }, { fontSize: 30, bold: true, color: GREEN, alignment: "center" });
    footer(slide);
    note(slide, ["Connect the product to the 80-point value/innovation criteria: complete workflow, practical scenarios, and human accountability."], ["README.md#the-solution", "docs/judging-evidence-map.md", "evidence/final-submission/screenshots/home-mobile.png"]);
  }

  // 10 - Close
  {
    const slide = deck.slides.add();
    slide.background.fill = BG;
    addShape(slide, "rect", { left: 64, top: 58, width: 78, height: 7 }, RED, { style: "solid", fill: "none", width: 0 });
    addText(slide, "BRANDPILOT LOCAL", { left: 64, top: 92, width: 420, height: 32 }, { fontSize: 20, bold: true, color: RED });
    addText(slide, "Practical today.\nDisciplined about tomorrow.", { left: 64, top: 150, width: 760, height: 150 }, { fontSize: 62, bold: true, color: INK });
    addText(slide, "Verified", { left: 64, top: 356, width: 180, height: 34 }, { fontSize: 30, bold: true, color: GREEN });
    addText(slide, "Real SDXL on Radeon + ROCm\nAuthenticated FastAPI loopback generation\nHuman review and responsive product workflow", { left: 64, top: 406, width: 560, height: 124 }, { fontSize: 24, color: MUTED });
    addText(slide, "Next measured phase", { left: 700, top: 356, width: 320, height: 34 }, { fontSize: 30, bold: true, color: AMBER });
    addText(slide, "Compare base SDXL with IP-Adapter plus masking/compositing for product preservation - only after submission.", { left: 700, top: 406, width: 450, height: 112 }, { fontSize: 24, color: MUTED });
    addShape(slide, "rect", { left: 64, top: 574, width: 1088, height: 1 }, LINE, { style: "solid", fill: "none", width: 0 });
    addText(slide, "Talal Khawaja  |  Aqeela Urooj", { left: 64, top: 610, width: 520, height: 36 }, { fontSize: 26, bold: true, color: INK });
    addText(slide, "github.com/kmt9967/brandpilot-local", { left: 700, top: 610, width: 452, height: 36 }, { fontSize: 22, color: MUTED, alignment: "right" });
    note(slide, ["Close on what is verified, the honest limitation, and the next measurable research question."], ["docs/final-claim-audit.md", "docs/roadmap.md"]);
  }

  for (const [index, slide] of deck.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const png = await deck.export({ slide, format: "png", scale: 1 });
    await fs.writeFile(path.join(renderDir, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(renderDir, `${stem}.layout.json`), await layout.text());
  }
  const montage = await deck.export({ format: "webp", montage: true, scale: 1 });
  await fs.writeFile(path.join(renderDir, "deck-montage.webp"), new Uint8Array(await montage.arrayBuffer()));
  const inspect = await deck.inspect({ kind: "slide,textbox,shape,image,notes", maxChars: 20000 });
  await fs.writeFile(path.join(renderDir, "deck-inspect.ndjson"), inspect.ndjson);
  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(path.join(outputDir, "BrandPilot-Local-Presentation.pptx"));
}

await build();
