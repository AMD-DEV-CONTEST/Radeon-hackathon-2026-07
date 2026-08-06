const path = require("path");
const fs = require("fs");
const crypto = require("crypto");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const OUTPUT = path.join(ROOT, "docs", "ProofLaunch_Submission_Deck.pptx");
const UI = path.join(ROOT, "docs", "assets", "prooflaunch-field-journal-v5-desktop-fold.png");
const COVER = path.join(ROOT, "docs", "assets", "prooflaunch-cover-key-visual-v1.png");
const HERO = path.join(ROOT, "evidence", "v10", "local-campaign-pack-v1", "delivery-v6", "prooflaunch-hero-4k.png");
const LANDING = path.join(ROOT, "evidence", "v10", "local-campaign-pack-v1", "delivery-v6", "prooflaunch-landing-1920x1080.png");
const SOCIAL = path.join(ROOT, "evidence", "v10", "local-campaign-pack-v1", "delivery-v6", "prooflaunch-social-1080x1350.png");

function shortSha(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex").slice(0, 10).toUpperCase();
}

const C = {
  ink: "11151E",
  midnight: "070A14",
  violet: "835EFF",
  violetSoft: "DDD4FF",
  paper: "F3F0E8",
  white: "FFFFFF",
  text: "20251F",
  muted: "656A73",
  line: "D3CEC2",
  green: "2F7057",
  greenSoft: "DCEBE3",
  amber: "B66B16",
  amberSoft: "F6E6CB",
  rust: "B45132",
  slate: "303748",
};

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "Banyan";
pptx.company = "Banyan";
pptx.subject = "AMD AI DevMaster Hackathon 2026 — Track 1 submission";
pptx.title = "ProofLaunch: Multimodal GTM Studio";
pptx.lang = "en-US";
pptx.theme = {
  headFontFace: "Arial Black",
  bodyFontFace: "Aptos",
  lang: "en-US",
};

function addText(slide, text, options) {
  slide.addText(text, {
    fontFace: "Aptos",
    color: C.text,
    margin: 0,
    breakLine: false,
    fit: "shrink",
    ...options,
  });
}

function addTitle(slide, eyebrow, title, dark = false) {
  addText(slide, eyebrow.toUpperCase(), {
    x: 0.62, y: 0.42, w: 8.8, h: 0.24,
    fontFace: "Arial Black", fontSize: 9.5, charSpacing: 1.5,
    color: dark ? C.violetSoft : C.rust,
  });
  addText(slide, title, {
    x: 0.62, y: 0.78, w: 11.95, h: 0.68,
    fontFace: "Arial Black", fontSize: 30, bold: true,
    color: dark ? C.white : C.ink,
  });
}

function addFooter(slide, index, dark = false) {
  addText(slide, "TEAM BANYAN · PROOFLAUNCH · AMD RADEON HACKATHON 2026 · TRACK 1", {
    x: 0.62, y: 7.15, w: 10.8, h: 0.15,
    fontFace: "Arial Black", fontSize: 7.2, charSpacing: 0.7,
    color: dark ? "9198A8" : "777B82",
  });
  addText(slide, String(index).padStart(2, "0"), {
    x: 12.08, y: 7.08, w: 0.6, h: 0.22,
    fontFace: "Arial Black", fontSize: 9.5, align: "right",
    color: dark ? C.violetSoft : C.rust,
  });
}

function addPill(slide, text, x, y, w, dark = false) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h: 0.38,
    rectRadius: 0.08,
    fill: { color: dark ? C.violet : C.violetSoft },
    line: { color: dark ? C.violet : C.violetSoft, transparency: 100 },
  });
  addText(slide, text.toUpperCase(), {
    x: x + 0.14, y: y + 0.095, w: w - 0.28, h: 0.16,
    fontFace: "Arial Black", fontSize: 7.5, charSpacing: 0.8,
    color: dark ? C.white : "493294", align: "center",
  });
}

function addCard(slide, x, y, w, h, title, body, options = {}) {
  const fill = options.fill || C.white;
  const line = options.line || C.line;
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h,
    rectRadius: 0.07,
    fill: { color: fill },
    line: { color: line, width: options.lineWidth || 1 },
    shadow: options.shadow ? { type: "outer", color: "000000", blur: 2, offset: 1, angle: 135, opacity: 0.12 } : undefined,
  });
  if (options.number) {
    addText(slide, options.number, {
      x: x + 0.23, y: y + 0.21, w: 0.55, h: 0.32,
      fontFace: "Arial Black", fontSize: 18,
      color: options.accent || C.violet,
    });
  }
  addText(slide, title, {
    x: x + 0.23, y: y + (options.number ? 0.68 : 0.25), w: w - 0.46, h: 0.34,
    fontFace: "Arial Black", fontSize: options.titleSize || 15,
    color: options.titleColor || C.ink,
  });
  addText(slide, body, {
    x: x + 0.23, y: y + (options.number ? 1.09 : 0.72), w: w - 0.46, h: h - (options.number ? 1.3 : 0.93),
    fontSize: options.bodySize || 11.5, breakLine: true,
    color: options.bodyColor || C.muted,
    valign: "top",
  });
}

function addMetric(slide, x, y, w, value, label, accent = C.violet) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h: 1.28,
    rectRadius: 0.06,
    fill: { color: C.white },
    line: { color: C.line, width: 1 },
  });
  addText(slide, value, {
    x: x + 0.22, y: y + 0.18, w: w - 0.44, h: 0.48,
    fontFace: "Arial Black", fontSize: 27, color: accent,
  });
  addText(slide, label, {
    x: x + 0.22, y: y + 0.78, w: w - 0.44, h: 0.25,
    fontFace: "Arial Black", fontSize: 8.4, charSpacing: 0.5, color: C.muted,
  });
}

// 01 — Hero
{
  const slide = pptx.addSlide();
  slide.background = { color: C.midnight };
  slide.addImage({ path: COVER, x: 4.75, y: 0, w: 9.78, h: 5.5, transparency: 3, altText: "ProofLaunch optical evidence engine key visual" });
  slide.addShape(pptx.ShapeType.rect, {
    x: 0, y: 0, w: 6.15, h: 7.5,
    fill: { color: C.midnight, transparency: 2 },
    line: { color: C.midnight, transparency: 100 },
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: 4.7, y: 0, w: 2.35, h: 7.5,
    fill: { color: C.midnight, transparency: 35 },
    line: { color: C.midnight, transparency: 100 },
  });
  addPill(slide, "AMD Track 1 · Team Banyan", 0.68, 0.65, 2.75, true);
  addText(slide, "ProofLaunch", {
    x: 0.68, y: 1.35, w: 5.35, h: 0.72,
    fontFace: "Arial Black", fontSize: 42, bold: true, color: C.white,
  });
  addText(slide, "Multimodal GTM Studio", {
    x: 0.68, y: 2.14, w: 5.55, h: 0.62,
    fontFace: "Arial Black", fontSize: 27, color: C.violetSoft,
  });
  addText(slide, "Turn approved product evidence into an audited campaign pack—strategy, copy, image, audio and video—with a human release boundary.", {
    x: 0.68, y: 3.02, w: 4.75, h: 1.18,
    fontSize: 17, color: "D4D7DF", breakLine: true, valign: "top",
  });
  addText(slide, "Evidence before promise. Release only what earns trust.", {
    x: 0.68, y: 5.72, w: 6.4, h: 0.36,
    fontFace: "Arial Black", fontSize: 13, color: C.white,
  });
  addFooter(slide, 1, true);
}

// 02 — Problem and outcome
{
  const slide = pptx.addSlide();
  slide.background = { color: C.paper };
  addTitle(slide, "Why ProofLaunch", "Creative speed is not enough when product truth breaks");
  addCard(slide, 0.68, 1.72, 2.35, 2.32, "Unsupported claims", "Generated copy can outrun approved source evidence and create release risk.", { number: "01", accent: C.rust, fill: "FAF8F2", bodySize: 10.8 });
  addCard(slide, 3.22, 1.72, 2.35, 2.32, "Identity drift", "Products, logos and typography can change silently across still and video outputs.", { number: "02", accent: C.rust, fill: "FAF8F2", bodySize: 10.8 });
  addCard(slide, 5.76, 1.72, 2.35, 2.32, "No release proof", "A polished asset without provenance, audit history or approval cannot be defended.", { number: "03", accent: C.rust, fill: "FAF8F2", bodySize: 10.8 });
  slide.addImage({ path: UI, x: 8.4, y: 1.72, w: 4.27, h: 2.96, altText: "Finished ProofLaunch product website — Frontier GTM Studio" });
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 0.68, y: 4.87, w: 12.0, h: 1.48,
    rectRadius: 0.06, fill: { color: C.ink }, line: { color: C.ink },
  });
  addText(slide, "PROOFLAUNCH CHANGES THE UNIT OF WORK", {
    x: 0.98, y: 5.16, w: 3.0, h: 0.25,
    fontFace: "Arial Black", fontSize: 10, charSpacing: 1.2, color: C.violetSoft,
  });
  addText(slide, "Evidence", { x: 4.2, y: 5.12, w: 1.2, h: 0.32, fontFace: "Arial Black", fontSize: 14, color: C.white, align: "center" });
  addText(slide, "→", { x: 5.35, y: 5.09, w: 0.45, h: 0.38, fontFace: "Arial Black", fontSize: 20, color: C.violet });
  addText(slide, "Campaign", { x: 5.82, y: 5.12, w: 1.35, h: 0.32, fontFace: "Arial Black", fontSize: 14, color: C.white, align: "center" });
  addText(slide, "→", { x: 7.2, y: 5.09, w: 0.45, h: 0.38, fontFace: "Arial Black", fontSize: 20, color: C.violet });
  addText(slide, "Audit", { x: 7.68, y: 5.12, w: 0.95, h: 0.32, fontFace: "Arial Black", fontSize: 14, color: C.white, align: "center" });
  addText(slide, "→", { x: 8.7, y: 5.09, w: 0.45, h: 0.38, fontFace: "Arial Black", fontSize: 20, color: C.violet });
  addText(slide, "Human release", { x: 9.18, y: 5.12, w: 1.75, h: 0.32, fontFace: "Arial Black", fontSize: 14, color: C.white, align: "center" });
  addText(slide, "→", { x: 10.95, y: 5.09, w: 0.45, h: 0.38, fontFace: "Arial Black", fontSize: 20, color: C.violet });
  addText(slide, "Receipt", { x: 11.38, y: 5.12, w: 0.95, h: 0.32, fontFace: "Arial Black", fontSize: 14, color: C.white, align: "center" });
  addText(slide, "One inspectable workflow replaces disconnected prompts, silent retries and release-by-appearance.", {
    x: 4.2, y: 5.74, w: 7.9, h: 0.26, fontSize: 11.2, color: "E0E3E9", align: "center",
  });
  addFooter(slide, 2, false);
}

// 03 — Workflow
{
  const slide = pptx.addSlide();
  slide.background = { color: C.midnight };
  addTitle(slide, "Product workflow", "One supervisor. Six visible stages. A hard release boundary.", true);
  const stages = [
    ["01", "EVIDENCE", "Hash, rights and located claims"],
    ["02", "PLAN", "Claim-bound briefs and channel intent"],
    ["03", "CREATE", "Image, audio and video candidates"],
    ["04", "AUDIT", "Claim, identity, type and safe zones"],
    ["05", "REPAIR", "Maximum two recorded rounds"],
    ["06", "DELIVER", "Human-approved export and evidence ledger"],
  ];
  stages.forEach((s, i) => {
    const x = 0.68 + i * 2.03;
    slide.addShape(pptx.ShapeType.roundRect, {
      x, y: 2.0, w: 1.72, h: 2.5,
      rectRadius: 0.06, fill: { color: i === 5 ? "1B2440" : "111724" },
      line: { color: i === 5 ? C.violet : "323A4C", width: i === 5 ? 2 : 1 },
    });
    addText(slide, s[0], { x: x + 0.18, y: 2.2, w: 0.55, h: 0.35, fontFace: "Arial Black", fontSize: 20, color: C.violet });
    addText(slide, s[1], { x: x + 0.18, y: 2.82, w: 1.36, h: 0.3, fontFace: "Arial Black", fontSize: 12, color: C.white, align: "center" });
    addText(slide, s[2], { x: x + 0.18, y: 3.35, w: 1.36, h: 0.76, fontSize: 10.2, color: "B6BCC9", align: "center", valign: "mid" });
    if (i < stages.length - 1) addText(slide, "→", { x: x + 1.74, y: 3.0, w: 0.3, h: 0.34, fontFace: "Arial Black", fontSize: 17, color: i === 4 ? C.violetSoft : "9AA2B4", align: "center" });
  });
  slide.addShape(pptx.ShapeType.line, { x: 10.68, y: 1.78, w: 0, h: 2.92, line: { color: C.violet, width: 3.2 } });
  slide.addShape(pptx.ShapeType.roundRect, { x: 9.86, y: 4.65, w: 1.64, h: 0.34, rectRadius: 0.04, fill: { color: C.violet }, line: { color: C.violet } });
  addText(slide, "HUMAN APPROVAL GATE", { x: 9.96, y: 4.765, w: 1.44, h: 0.11, fontFace: "Arial Black", fontSize: 6.6, charSpacing: 0.5, color: C.white, align: "center" });
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 1.72, y: 5.05, w: 9.86, h: 1.2,
    rectRadius: 0.05, fill: { color: "121927" }, line: { color: "394155" },
  });
  addText(slide, "CODE-ENFORCED HARNESS", { x: 2.05, y: 5.48, w: 2.25, h: 0.25, fontFace: "Arial Black", fontSize: 10, charSpacing: 0.9, color: C.violetSoft });
  addText(slide, "Typed inputs · tenant isolation · budget limits · content-bound approvals · immutable audit events · no autonomous publish/send/spend", {
    x: 4.35, y: 5.31, w: 6.82, h: 0.54, fontSize: 10.8, color: "D0D4DD", align: "center", valign: "mid",
  });
  addFooter(slide, 3, true);
}

// 04 — Radeon architecture
{
  const slide = pptx.addSlide();
  slide.background = { color: C.paper };
  addTitle(slide, "AMD Radeon / ROCm architecture", "Radeon-targeted inference, explicit residency and observable evidence");
  addText(slide, "SEQUENCED BY THE PROOFLAUNCH SUPERVISOR", {
    x: 0.72, y: 1.48, w: 5.4, h: 0.2,
    fontFace: "Arial Black", fontSize: 8.3, charSpacing: 1.0, color: C.rust,
  });
  const nodes = ["Qwen3-VL\nunderstand", "SDXL\ncreate", "SigLIP2\naudit", "LTX-Video\nmotion", "SAM2 + CLAP\nverify"];
  nodes.forEach((label, i) => {
    const x = 0.72 + i * 2.42;
    slide.addShape(pptx.ShapeType.roundRect, {
      x, y: 1.78, w: 1.98, h: 0.92,
      rectRadius: 0.05, fill: { color: i === 1 ? C.violetSoft : C.white },
      line: { color: i === 1 ? C.violet : C.line, width: i === 1 ? 1.7 : 1 },
    });
    addText(slide, String(i + 1).padStart(2, "0"), { x: x + 0.12, y: 1.91, w: 0.36, h: 0.2, fontFace: "Arial Black", fontSize: 7.7, color: C.rust });
    addText(slide, label, { x: x + 0.24, y: 2.03, w: 1.5, h: 0.43, fontFace: "Arial Black", fontSize: 10.7, color: C.ink, align: "center", valign: "mid" });
    slide.addShape(pptx.ShapeType.line, { x: x + 0.99, y: 2.7, w: 0, h: 0.3, line: { color: C.rust, width: 1.1 } });
  });
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 0.72, y: 2.98, w: 11.86, h: 0.52,
    rectRadius: 0.04, fill: { color: C.ink }, line: { color: C.ink },
  });
  addText(slide, "AMD RADEON GPU · ROCm / HIP LOCAL INFERENCE FOUNDATION", { x: 1.05, y: 3.145, w: 11.2, h: 0.17, fontFace: "Arial Black", fontSize: 9.4, charSpacing: 1.0, color: C.white, align: "center" });
  addCard(slide, 0.72, 3.83, 3.7, 2.12, "Single-model residency", "Only one heavy model is resident at a time. Explicit unload, garbage collection and cache controls keep the pipeline inside the available VRAM envelope.", { number: "A", accent: C.violet, fill: C.white, titleSize: 15, bodySize: 10.7 });
  addCard(slide, 4.67, 3.83, 3.7, 2.12, "Reproducible evidence", "Every real run retains hardware identity, ROCm/HIP version, model revision, input hash, seed, latency, peak VRAM and output SHA-256.", { number: "B", accent: C.violet, fill: C.white, titleSize: 15, bodySize: 10.7 });
  addCard(slide, 8.62, 3.83, 4.0, 2.12, "Fail-closed truth boundary", "The 190.9-second product Demo Video is included; the live Radeon receipt remains pending. No Mac, mock or provider output is substituted for hardware evidence.", { number: "C", accent: C.amber, fill: C.amberSoft, line: "E0B777", titleSize: 15, bodySize: 10.3 });
  addFooter(slide, 4, false);
}

// 05 — Deliverables
{
  const slide = pptx.addSlide();
  slide.background = { color: C.midnight };
  addTitle(slide, "Campaign pack", "One governed run binds ten GTM deliverables", true);
  slide.addImage({ path: LANDING, x: 0.68, y: 1.72, w: 6.25, h: 3.52, altText: "ProofLaunch landscape campaign example" });
  slide.addImage({ path: SOCIAL, x: 7.18, y: 1.72, w: 2.14, h: 2.68, altText: "ProofLaunch portrait campaign example" });
  slide.addShape(pptx.ShapeType.roundRect, { x: 0.88, y: 4.84, w: 2.45, h: 0.28, rectRadius: 0.03, fill: { color: C.midnight, transparency: 8 }, line: { color: "535B70" } });
  addText(slide, `LANDING · sha256:${shortSha(LANDING)}…`, { x: 1.0, y: 4.93, w: 2.22, h: 0.1, fontFace: "Arial Black", fontSize: 6.7, charSpacing: 0.35, color: C.white, align: "center" });
  slide.addShape(pptx.ShapeType.roundRect, { x: 7.32, y: 4.47, w: 1.86, h: 0.28, rectRadius: 0.03, fill: { color: C.midnight, transparency: 8 }, line: { color: "535B70" } });
  addText(slide, `SOCIAL · ${shortSha(SOCIAL)}…`, { x: 7.42, y: 4.56, w: 1.66, h: 0.1, fontFace: "Arial Black", fontSize: 6.7, charSpacing: 0.35, color: C.white, align: "center" });
  slide.addShape(pptx.ShapeType.roundRect, { x: 9.6, y: 1.72, w: 3.0, h: 3.52, rectRadius: 0.05, fill: { color: "111724" }, line: { color: "343C4E" } });
  addText(slide, "10", { x: 9.95, y: 2.0, w: 2.3, h: 0.72, fontFace: "Arial Black", fontSize: 44, color: C.violetSoft, align: "center" });
  addText(slide, "BOUND DELIVERABLES", { x: 9.95, y: 2.75, w: 2.3, h: 0.25, fontFace: "Arial Black", fontSize: 9, charSpacing: 0.8, color: C.white, align: "center" });
  addText(slide, "Strategy · calendar · copy · analytics · GEO · SEO · execution contract · channel portfolio · audio · 4K film", {
    x: 9.95, y: 3.3, w: 2.3, h: 1.15, fontSize: 11.2, color: "C4C9D3", align: "center", valign: "mid", breakLine: true,
  });
  slide.addShape(pptx.ShapeType.roundRect, { x: 0.68, y: 5.52, w: 11.92, h: 0.82, rectRadius: 0.04, fill: { color: "111724" }, line: { color: "343C4E" } });
  addText(slide, "SEALED · NOT FINAL RADEON EVIDENCE", { x: 0.95, y: 5.78, w: 2.65, h: 0.2, fontFace: "Arial Black", fontSize: 8.0, charSpacing: 0.6, color: "F4B45F" });
  addText(slide, "These assets demonstrate the product package and hash-bound delivery. Their provider-managed source is disclosed and is not claimed as final Radeon evidence.", {
    x: 3.65, y: 5.7, w: 8.45, h: 0.31, fontSize: 10.0, color: "D0D4DD", align: "center",
  });
  addFooter(slide, 5, true);
}

// 06 — Verification
{
  const slide = pptx.addSlide();
  slide.background = { color: C.paper };
  addTitle(slide, "Verified product state", "Measured mechanics. Unobserved claims kept separate.");
  addMetric(slide, 0.68, 1.73, 2.2, "827/827", "PRODUCT-CRITICAL TESTS", C.green);
  addMetric(slide, 3.08, 1.73, 2.2, "17/17", "UI TESTS", C.green);
  addMetric(slide, 5.48, 1.73, 2.2, "10/10", "ROUTE VALIDATION", C.green);
  addMetric(slide, 7.88, 1.73, 2.2, "46 · 60", "ROUTES · API CONTRACTS", C.violet);
  addMetric(slide, 10.28, 1.73, 2.32, "4/4", "FINAL INTEGRITY LOCKS", C.green);
  addCard(slide, 0.68, 3.42, 3.75, 2.2, "Observed", "Hash-bound replay, typed approvals, bounded repair, deterministic export and zero automatic publish / send / spend. Desktop and mobile checks report no horizontal overflow.", { fill: C.greenSoft, line: "A9CEB8", titleColor: C.green, bodyColor: "355A47" });
  addCard(slide, 4.78, 3.42, 3.75, 2.2, "Not claimed", "Named-human preference, 4A quality, Top-1 standing, production effect, causal revenue or autonomous business action.", { fill: "FAF8F2", line: C.line, titleColor: C.ink });
  addCard(slide, 8.88, 3.42, 3.72, 2.2, "Still pending", "Live Radeon model inference and the final latency/VRAM receipt. The 190.9-second product Demo Video and official PR #308 are present.", { fill: C.amberSoft, line: "E0B777", titleColor: C.amber, bodyColor: "70470D" });
  addFooter(slide, 6, false);
}

// 07 — Readiness
{
  const slide = pptx.addSlide();
  slide.background = { color: C.midnight };
  addTitle(slide, "Track 1 submission", "The package is organized. Live Radeon evidence closes the final gate.", true);
  const rows = [
    ["Project Profile PDF", "READY", C.green],
    ["Complete source + English README", "READY", C.green],
    ["English supplementary deck", "READY", C.green],
    ["Product Demo Video · 190.9 seconds", "READY", C.green],
    ["Official fork + English PR #308", "READY", C.green],
  ];
  rows.forEach((r, i) => {
    const y = 1.78 + i * 0.77;
    slide.addShape(pptx.ShapeType.roundRect, { x: 0.72, y, w: 7.1, h: 0.57, rectRadius: 0.04, fill: { color: "111724" }, line: { color: "343C4E" } });
    addText(slide, r[0], { x: 0.98, y: y + 0.18, w: 4.55, h: 0.19, fontFace: "Arial Black", fontSize: 10.5, color: C.white });
    const pending = r[1].startsWith("PENDING");
    slide.addShape(pptx.ShapeType.roundRect, { x: 5.55, y: y + 0.115, w: 1.95, h: 0.34, rectRadius: 0.04, fill: { color: pending ? "3A2917" : "173329" }, line: { color: r[2], width: 0.8 } });
    addText(slide, r[1], { x: 5.67, y: y + 0.225, w: 1.71, h: 0.11, fontFace: "Arial Black", fontSize: 7.3, color: r[2], align: "center" });
  });
  slide.addShape(pptx.ShapeType.roundRect, { x: 8.25, y: 1.78, w: 4.35, h: 3.65, rectRadius: 0.06, fill: { color: "111724" }, line: { color: C.violet, width: 1.5 } });
  addText(slide, "OFFICIAL PR TITLE", { x: 8.62, y: 2.15, w: 3.6, h: 0.22, fontFace: "Arial Black", fontSize: 9, charSpacing: 1.0, color: C.violetSoft, align: "center" });
  addText(slide, "Track 1, Banyan,\nProofLaunch: Multimodal GTM Studio", { x: 8.62, y: 2.62, w: 3.6, h: 1.0, fontFace: "Arial Black", fontSize: 19, color: C.white, align: "center", valign: "mid", breakLine: true });
  addText(slide, "GitHub submitter: sylvanccc\nOfficial destination: prooflaunch/\nSubmission language: English", { x: 8.62, y: 4.05, w: 3.6, h: 0.76, fontSize: 10.5, color: "B8BECA", align: "center", breakLine: true });
  slide.addShape(pptx.ShapeType.roundRect, { x: 0.72, y: 6.05, w: 11.88, h: 0.63, rectRadius: 0.04, fill: { color: C.violet }, line: { color: C.violet } });
  addText(slide, "FINAL HARDWARE STEP · Record one truthful live Radeon workflow and bind its latency, VRAM and output receipt.", { x: 1.03, y: 6.25, w: 11.25, h: 0.19, fontFace: "Arial Black", fontSize: 10.4, color: C.white, align: "center" });
  addFooter(slide, 7, true);
}

pptx.writeFile({ fileName: OUTPUT });
console.log(`created ${OUTPUT}`);
