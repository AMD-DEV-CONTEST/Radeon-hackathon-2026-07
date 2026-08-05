import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Presentation, PresentationFile } from "file:///C:/Users/lucianaib/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const outputDir = path.join(root, "tmp/privateops-deck/output");
const finalPath = path.join(root, "submission/PrivateOps-Agent-Competition-Deck.pptx");
const screenshot = new Uint8Array(await fs.readFile(path.join(root, "submission/assets/ui-development.png")));
const architecture = new Uint8Array(await fs.readFile(path.join(root, "submission/assets/architecture.png")));

const C = {
  ink: "#0B1020", muted: "#64748B", line: "#D9E1EC", soft: "#F4F7FB",
  white: "#FFFFFF", blue: "#2563EB", blueSoft: "#EAF1FF", orange: "#ED7D31",
  green: "#15803D", amber: "#B45309", red: "#B91C1C",
};

function box(slide, left, top, width, height, fill = C.white, line = C.line, radius = "rounded-xl") {
  return slide.shapes.add({ geometry: "roundRect", position: { left, top, width, height }, fill,
    line: { style: "solid", fill: line, width: 1 }, borderRadius: radius });
}

function text(slide, value, left, top, width, height, size = 24, color = C.ink, bold = false) {
  const shape = slide.shapes.add({ geometry: "textbox", position: { left, top, width, height }, fill: "none",
    line: { style: "solid", fill: "none", width: 0 } });
  shape.text = value;
  shape.text.style = { fontSize: size, color, bold, fontFamily: "Aptos" };
  return shape;
}

function base(slide, eyebrow, title, number) {
  slide.background.fill = C.soft;
  text(slide, eyebrow.toUpperCase(), 64, 42, 540, 24, 12, C.blue, true);
  text(slide, title, 64, 76, 1110, 66, 34, C.ink, true);
  text(slide, String(number).padStart(2, "0"), 1170, 48, 50, 22, 11, C.muted, true);
  slide.shapes.add({ geometry: "line", position: { left: 64, top: 146, width: 1152, height: 1 },
    fill: "none", line: { style: "solid", fill: C.line, width: 1 } });
}

function footer(slide) {
  text(slide, "PRIVATEOPS AGENT  /  TRACK 2", 64, 676, 320, 18, 10, C.muted, true);
  text(slide, "PERMISSION-FIRST • LOCAL • AUDITABLE", 850, 676, 366, 18, 10, C.muted, true);
}

function notes(slide, body, sources = []) {
  const sourceLines = sources.length ? `\n[Sources]\n${sources.map((s) => `- ${s}`).join("\n")}` : "";
  slide.speakerNotes.textFrame.setText(`${body}${sourceLines}`);
  slide.speakerNotes.setVisible(true);
}

function pill(slide, label, left, top, width, fill = C.blueSoft, color = C.blue) {
  box(slide, left, top, width, 34, fill, fill, "rounded-full");
  text(slide, label, left + 12, top + 8, width - 24, 18, 11, color, true);
}

const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });

// 1 — Minimal cover.
{
  const s = p.slides.add(); s.background.fill = C.ink;
  pill(s, "AMD AI DEVMASTER 2026 • TRACK 2", 72, 62, 290, "#16213D", "#9CC2FF");
  text(s, "Permission before action.", 72, 184, 920, 92, 54, C.white, true);
  text(s, "PrivateOps Agent", 72, 292, 600, 52, 30, "#9CC2FF", true);
  text(s, "A private computer AI with broad supported visibility, deliberate action, exact confirmation, and evidence for every decision.", 72, 370, 900, 130, 22, "#CAD5E7");
  pill(s, "LangChain Core", 72, 548, 150); pill(s, "vLLM", 234, 548, 92); pill(s, "ROCm + Radeon", 338, 548, 150, "#2A1D18", "#FFB277");
  text(s, "BROAD VISIBILITY. DELIBERATE ACTION. EVIDENCE FOR EVERY DECISION.", 72, 646, 720, 22, 11, "#8391A8", true);
  notes(s, "Open with the user's permission insight: useful AI needs access, but access must not become silent control.", ["https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md"]);
}

// 2 — Problem + product evidence.
{
  const s = p.slides.add(); base(s, "The permission gap", "Giving AI access must not mean giving up control.", 2);
  text(s, "If AI is going to take work away from people, it needs permission. PrivateOps makes that permission bounded, visible, and reviewable before action.", 64, 178, 430, 150, 23, C.ink);
  box(s, 64, 374, 430, 176, C.white);
  text(s, "See broadly. Act deliberately.", 88, 398, 360, 30, 18, C.ink, true);
  text(s, "Read-only by default • exact confirmation • blocked exfiltration • local audit", 88, 444, 360, 72, 18, C.muted);
  box(s, 534, 178, 682, 410, C.white);
  s.images.add({ blob: screenshot, contentType: "image/png", alt: "PrivateOps inference panel with Remote model and Local ROCm modes", fit: "contain", position: { left: 550, top: 194, width: 650, height: 378 }, geometry: "roundRect", borderRadius: "rounded-lg" });
  footer(s); notes(s, "Show the real dual-mode UI. Local ROCm restores the loopback Qwen defaults without requiring a key; Remote model retains a separate development profile.");
}

// 3 — Scenario.
{
  const s = p.slides.add(); base(s, "Focused scenario", "One permission kernel, two truthful observation surfaces.", 3);
  const items = [
    ["01", "Windows computer", "Seven fixed read-only collectors inspect startup, processes, services, tasks, ports, hardware, and security."],
    ["02", "Radeon project", "Same-instance tools inspect private knowledge, files, tests, submission readiness, GPU, and ROCm state."],
    ["03", "Permission proof", "Return evidence, plan, tool results, memory, confirmation state, and a redacted audit export."],
  ];
  items.forEach((it, i) => { const x = 64 + i * 386; box(s, x, 194, 354, 350, C.white); text(s, it[0], x + 24, 220, 52, 30, 15, i === 2 ? C.orange : C.blue, true); text(s, it[1], x + 24, 276, 306, 58, 25, C.ink, true); text(s, it[2], x + 24, 360, 306, 130, 18, C.muted); });
  pill(s, "Whole-computer permission means broad supported observation—not arbitrary admin access", 220, 590, 840);
  footer(s); notes(s, "The official video uses the Radeon project surface. Windows inspection is a separate genuine extension.");
}

// 4 — Workflow.
{
  const s = p.slides.add(); base(s, "Agent workflow", "One request becomes an inspectable execution trace.", 4);
  const stages = [
    ["1", "Observe + retrieve", "Fixed tools and 14 bilingual RAG sources return bounded evidence with stable IDs."],
    ["2", "Plan + guard", "Every request is classified safe, exact-confirmation, or blocked before tool execution."],
    ["3", "Synthesize + audit", "The local Radeon model explains observed results; memory and audit remain inspectable."],
  ];
  stages.forEach((it, i) => { const x = 64 + i * 392; box(s, x, 210, 350, 300, i === 1 ? C.blueSoft : C.white, i === 1 ? "#B7CDFB" : C.line); pill(s, it[0], x + 24, 236, 46, i === 2 ? "#FFF1E8" : "#EAF1FF", i === 2 ? C.orange : C.blue); text(s, it[1], x + 24, 298, 300, 38, 25, C.ink, true); text(s, it[2], x + 24, 360, 300, 102, 18, C.muted); if (i < 2) text(s, "→", x + 357, 330, 30, 30, 24, C.blue, true); });
  box(s, 260, 556, 760, 58, "#101A31", "#101A31"); text(s, "REQUEST  →  EVIDENCE  →  PLAN  →  PERMISSION  →  TOOL  →  AUDIT ID", 296, 574, 688, 22, 14, C.white, true);
  footer(s); notes(s, "Walk left to right. The differentiator is not another chat UI; it is an observable execution trace.");
}

// 5 — Capability coverage.
{
  const s = p.slides.add(); base(s, "Track 2 coverage", "All five minimum-capability categories are implemented.", 5);
  const caps = [
    ["✓", "Local RAG", "14 bilingual sources + stable IDs"], ["✓", "Tool calling", "Project + Windows StructuredTool"],
    ["✓", "Multi-step planning", "Visible retrieve / inspect / synthesize"], ["✓", "Local memory", "Atomic JSON persistence"],
    ["✓", "Permission + privacy", "Path confinement, tokens, redaction"],
  ];
  caps.forEach((it, i) => { const row = i < 3 ? 0 : 1; const col = row === 0 ? i : i - 3; const width = row === 0 ? 354 : 548; const x = row === 0 ? 64 + col * 386 : 163 + col * 580; const y = row === 0 ? 190 : 406; box(s, x, y, width, 168, C.white); pill(s, it[0], x + 20, y + 20, 42, "#E9F8EF", C.green); text(s, it[1], x + 78, y + 24, width - 98, 32, 20, C.ink, true); text(s, it[2], x + 24, y + 92, width - 48, 42, 16, C.muted); });
  footer(s); notes(s, "The rules require at least two capabilities. PrivateOps deliberately implements all five so functionality and trust reinforce each other.", ["https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md"]);
}

// 6 — Architecture.
{
  const s = p.slides.add(); base(s, "Architecture", "The model proposes; the local control plane decides and records.", 6);
  box(s, 64, 178, 804, 438, C.white);
  s.images.add({ blob: architecture, contentType: "image/png", alt: "PrivateOps local architecture diagram", fit: "contain", position: { left: 84, top: 200, width: 764, height: 392 } });
  box(s, 900, 178, 316, 438, "#101A31", "#101A31");
  text(s, "Non-negotiable boundaries", 928, 210, 260, 58, 22, C.white, true);
  [["LOOPBACK", "Core inference never needs a remote API."], ["WORKSPACE", "Tools resolve paths inside one configured root."], ["NO FALLBACK", "ROCm mode fails visibly if local inference fails."], ["REDACTION", "Secrets are removed from audit exports."]].forEach((it, i) => { pill(s, it[0], 928, 296 + i * 72, 108, i === 0 ? "#2A1D18" : "#16213D", i === 0 ? "#FFB277" : "#9CC2FF"); text(s, it[1], 1048, 298 + i * 72, 144, 52, 13, "#D5DEED"); });
  footer(s); notes(s, "The LLM is only one component. Retrieval, planning, permissions, tools, memory, audit, and evidence recording remain local and inspectable.");
}

// 7 — Radeon deployment.
{
  const s = p.slides.add(); base(s, "Radeon deployment", "Local ROCm keeps PrivateOps and vLLM on one loopback boundary.", 7);
  const y = 238; const stages = [
    ["Radeon GPU", "ROCm image", C.orange], ["vLLM", "OpenAI-compatible", C.blue], ["Qwen2.5 7B", "8,192 context", C.blue], ["PrivateOps", "127.0.0.1 only", C.green],
  ];
  stages.forEach((it, i) => { const x = 64 + i * 294; box(s, x, y, 252, 178, C.white); pill(s, String(i + 1), x + 20, y + 18, 42, i === 0 ? "#FFF1E8" : "#EAF1FF", it[2]); text(s, it[0], x + 20, y + 76, 212, 32, 21, C.ink, true); text(s, it[1], x + 20, y + 124, 212, 24, 15, C.muted); if (i < 3) text(s, "→", x + 258, y + 74, 28, 30, 24, C.blue, true); });
  box(s, 166, 474, 948, 104, C.blueSoft, "#B7CDFB");
  text(s, "Verified capture", 192, 496, 190, 26, 15, C.blue, true);
  text(s, "gfx1100  •  ROCm 7.2.1  •  Qwen2.5-7B  •  127.0.0.1 only", 192, 534, 884, 26, 19, C.ink, true);
  footer(s); notes(s, "The captured instance ran PrivateOps and vLLM together. The UI can switch to a separate Remote model profile, but only Local ROCm uses this same-instance loopback path.", ["https://docs.vllm.ai/en/latest/getting_started/quickstart/", "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct", "https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/Radeon-Cloud-User%20Guide/README.md"]);
}

// 8 — Optimization and measurement.
{
  const s = p.slides.add(); base(s, "Optimization + evidence", "Performance claims are measured on Radeon—not typed into the deck.", 8);
  const rows = [
    ["Direct latency", "1,511.072 ms", "Measured through the same-instance loopback model endpoint."],
    ["Throughput", "32.427 tokens/s", "Measured from 49 completion tokens; not manually entered."],
    ["Complete Agent", "18,384.639 ms", "Includes RAG, plan, tool, generation, audit, and response assembly."],
    ["Context optimization", "8,192 / 0.85 / 25", "Bounds context, preserves memory headroom, and removes environment noise."],
  ];
  text(s, "TECHNIQUE", 76, 184, 230, 22, 11, C.muted, true); text(s, "SETTING", 374, 184, 220, 22, 11, C.muted, true); text(s, "WHY IT MATTERS", 648, 184, 480, 22, 11, C.muted, true);
  rows.forEach((it, i) => { const y = 216 + i * 92; box(s, 64, y, 1152, 76, i % 2 ? C.soft : C.white); text(s, it[0], 82, y + 20, 254, 30, 17, C.ink, true); text(s, it[1], 374, y + 20, 230, 30, 16, i === 1 ? C.orange : C.blue, true); text(s, it[2], 648, y + 14, 530, 48, 15, C.muted); });
  footer(s); notes(s, "These values are already captured in immutable machine evidence. No unmeasured speedup, P95, VRAM peak, or concurrency result is claimed.", ["https://docs.vllm.ai/en/latest/getting_started/quickstart/"]);
}

// 9 — Proof posture.
{
  const s = p.slides.add(); base(s, "Reviewer-ready proof", "The submission package is engineered to be checked, not trusted blindly.", 9);
  const metrics = [["5 / 5", "Track capability categories"], ["102", "Local finalization tests"], ["14", "Real bilingual RAG sources"]];
  metrics.forEach((it, i) => { const x = 64 + i * 386; box(s, x, 198, 354, 216, C.white); text(s, it[0], x + 24, 232, 306, 82, 48, i === 2 ? C.orange : C.blue, true); text(s, it[1], x + 24, 334, 306, 46, 16, C.muted, true); });
  box(s, 162, 466, 956, 116, "#101A31", "#101A31");
  text(s, "Included evidence", 188, 490, 180, 28, 15, "#9CC2FF", true);
  text(s, "Source + tests  •  PDF/PPT/poster  •  verified GPU/runtime/model logs  •  benchmark JSON/CSV  •  Agent response + audit", 188, 532, 890, 34, 16, C.white, true);
  footer(s); notes(s, "The Radeon evidence and public demonstration video are complete. Only the official account-bound Fork/PR remains.");
}

// 10 — Close.
{
  const s = p.slides.add(); s.background.fill = C.ink;
  pill(s, "PRIVATEOPS AGENT", 72, 66, 164, "#16213D", "#9CC2FF");
  text(s, "Broad visibility.\nDeliberate action.", 72, 190, 1000, 150, 48, C.white, true);
  text(s, "A permission-first private computer AI that gives useful access without surrendering control, provenance, or reviewability.", 72, 390, 890, 82, 22, "#CAD5E7");
  box(s, 72, 540, 1136, 64, "#16213D", "#263859");
  text(s, "LOCAL RAG  •  LANGCHAIN TOOLS  •  VISIBLE PLANS  •  LOCAL MEMORY  •  PERMISSION + AUDIT", 104, 560, 1072, 24, 15, C.white, true);
  text(s, "TRACK 2  /  VERIFIED AMD RADEON + ROCm  /  EVIDENCE FOR EVERY DECISION", 72, 650, 760, 20, 11, "#8391A8", true);
  notes(s, "Close on the differentiator and move directly into the live demonstration.");
}

await fs.mkdir(outputDir, { recursive: true });
for (const [index, slide] of p.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await p.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(path.join(outputDir, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(path.join(outputDir, `${stem}.layout.json`), await layout.text());
}
const montage = await p.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(path.join(outputDir, "deck-montage.webp"), new Uint8Array(await montage.arrayBuffer()));
const pptx = await PresentationFile.exportPptx(p);
await pptx.save(finalPath);
console.log(finalPath);
