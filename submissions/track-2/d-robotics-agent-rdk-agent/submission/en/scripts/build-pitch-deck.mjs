import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Presentation, PresentationFile } from "@oai/artifact-tool";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../..");
const LOCALE = process.env.RDK_LOCALE === "zh" ? "zh" : "en";
const LOCALIZATION = LOCALE === "zh"
  ? JSON.parse(await fs.readFile(path.join(ROOT, "submission", "zh", "scripts", "localization-map.json"), "utf8"))
  : {};
const ASSETS = path.join(ROOT, "submission", LOCALE, "assets");
const OUT = path.join(ROOT, "submission", LOCALE, "deliverables", "RDK_Agent_Track2_Pitch_Deck.pptx");
const RENDER = path.join(ROOT, "submission", LOCALE, "tmp", "pptx", "rendered");

const W = 1280;
const H = 720;
const M = 48;
const FONT = "Helvetica Neue";
const C = {
  white: "#FFFFFF",
  ink: "#111318",
  muted: "#626B78",
  panel: "#F0F2F4",
  rule: "#B8BCC4",
  blue: "#2F7DF6",
  paleBlue: "#E7F0FF",
  cyan: "#55D5E5",
  coral: "#FF675B",
  green: "#16A36A",
  paleGreen: "#E3F6EF",
  paleCoral: "#FFF0EE",
};

const noLine = { style: "solid", fill: "none", width: 0 };
const tr = (text) => LOCALIZATION[text] ?? text;

function rect(slide, x, y, width, height, fill, options = {}) {
  return slide.shapes.add({
    geometry: options.geometry ?? "rect",
    name: options.name,
    position: { left: x, top: y, width, height },
    fill,
    line: options.line ?? noLine,
    borderRadius: options.borderRadius,
  });
}

function textBox(slide, text, x, y, width, height, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name: options.name,
    position: { left: x, top: y, width, height },
    fill: options.fill ?? "none",
    line: options.line ?? noLine,
    borderRadius: options.borderRadius,
  });
  shape.text = tr(text);
  shape.text.style = {
    fontSize: options.fontSize ?? 22,
    typeface: options.typeface ?? FONT,
    color: options.color ?? C.ink,
    bold: options.bold ?? false,
    alignment: options.alignment ?? "left",
    verticalAlignment: options.verticalAlignment ?? "top",
    autoFit: options.autoFit ?? "none",
    wrap: options.wrap ?? "square",
    lineSpacing: options.lineSpacing,
    insets: options.insets ?? { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function line(slide, x, y, width, color = C.rule, thickness = 1) {
  return rect(slide, x, y, width, thickness, color);
}

function pill(slide, label, x, y, width, fill = C.blue, color = C.white) {
  rect(slide, x, y, width, 28, fill, { geometry: "roundRect", borderRadius: 14 });
  textBox(slide, label, x, y + 1, width, 26, {
    fontSize: 13,
    bold: true,
    color,
    alignment: "center",
    verticalAlignment: "middle",
  });
}

function addTitle(slide, number, kicker, title, subtitle) {
  line(slide, M, 40, 42, C.blue, 4);
  textBox(slide, kicker.toUpperCase(), 100, 32, 420, 28, {
    fontSize: 14,
    bold: true,
    color: C.muted,
    verticalAlignment: "middle",
  });
  textBox(slide, title, M, 74, W - M * 2, 68, {
    fontSize: 46,
    bold: true,
    color: C.ink,
    autoFit: "shrinkText",
    verticalAlignment: "middle",
  });
  if (subtitle) {
    textBox(slide, subtitle, M, 144, W - M * 2 - 90, 46, {
      fontSize: 20,
      color: C.muted,
      autoFit: "shrinkText",
      verticalAlignment: "top",
    });
  }
  textBox(slide, String(number).padStart(2, "0"), W - 88, 650, 40, 24, {
    fontSize: 13,
    color: C.muted,
    alignment: "right",
    verticalAlignment: "bottom",
  });
}

function addFooter(slide, text = "RDK Agent | AMD Radeon AI Agent Hackathon | Track 2") {
  line(slide, M, 680, W - M * 2, C.rule, 1);
  textBox(slide, text, M, 686, 620, 18, { fontSize: 11, color: C.muted });
}

async function addImage(slide, filename, x, y, width, height, options = {}) {
  const bytes = await fs.readFile(path.join(ASSETS, filename));
  if (options.frame !== false) {
    rect(slide, x - 1, y - 1, width + 2, height + 2, C.white, {
      geometry: options.geometry ?? "rect",
      line: { style: "solid", fill: options.stroke ?? C.rule, width: 1 },
      borderRadius: options.borderRadius,
    });
  }
  return slide.images.add({
    blob: bytes,
    contentType: "image/png",
    alt: options.alt ?? filename,
    fit: options.fit ?? "cover",
    position: { left: x, top: y, width, height },
    geometry: options.geometry ?? "rect",
    borderRadius: options.borderRadius,
    ...(options.prompt ? { prompt: options.prompt } : {}),
  });
}

function notes(slide, body, sources) {
  const sourceBlock = ["[Sources]", ...sources.map((s) => `- ${s}`), "[/Sources]"].join("\n");
  slide.speakerNotes.textFrame.setText(`${tr(body)}\n\n${sourceBlock}`);
  slide.speakerNotes.setVisible(true);
}

function smallLabel(slide, label, x, y, color = C.blue) {
  line(slide, x, y, 38, color, 3);
  textBox(slide, label.toUpperCase(), x, y + 12, 180, 22, { fontSize: 13, bold: true, color });
}

async function build() {
  await fs.mkdir(path.dirname(OUT), { recursive: true });
  await fs.mkdir(RENDER, { recursive: true });

  const deck = Presentation.create({ slideSize: { width: W, height: H } });

  // Slide 1 - Codex Grid cover / image split.
  {
    const s = deck.slides.add();
    s.background.fill = C.ink;
    rect(s, 0, 0, 592, H, C.ink);
    await addImage(s, "rdk-agent-hero.png", 592, 0, W - 592, H, {
      frame: false,
      fit: "cover",
      alt: "Original RDK Agent concept image showing governed paths from a developer to local compute and a robot",
      prompt: "Original cinematic technology concept: developer intent flows through verified agent controls into local compute and an RDK-class robot; no logos or embedded text.",
    });
    rect(s, 572, 0, 20, H, C.blue);
    pill(s, "TRACK 2 | AI AGENT APPLICATION", 56, 48, 270, C.blue);
    textBox(s, "RDK\nAgent", 56, 148, 460, 190, {
      fontSize: 80,
      bold: true,
      color: C.white,
      lineSpacing: 0.88,
    });
    textBox(s, "Natural-language intent becomes a verified action on an RDK board.", 56, 378, 455, 92, {
      fontSize: 28,
      color: C.white,
      lineSpacing: 1.05,
    });
    line(s, 56, 503, 78, C.cyan, 4);
    textBox(s, "PRIVATE RADEON TARGET  /  TOOL CALLING  /  MULTI-STEP PLANNING  /  BOUNDED AUTHORITY", 56, 525, 460, 62, {
      fontSize: 15,
      bold: true,
      color: "#D4DAE3",
      lineSpacing: 1.05,
    });
    textBox(s, "d-robotics agent", 56, 656, 320, 20, { fontSize: 13, color: "#AEB6C2" });
    notes(s, "Open with the product promise: one governed path from intent to a board action. The visual is conceptual, not hardware evidence.", [
      "Project repository: README.md and submission/en/PROJECT_SPECIFICATION.md.",
      "Project-created AI-generated asset: submission/en/assets/rdk-agent-hero.png.",
      "Official Track 2 requirements: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07",
    ]);
  }

  // Slide 2 - Codex Grid slide-08 half text / half image.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 2, "Naming story", "Sophon becomes a transparent device bridge", "A memorable literary idea maps to an owner-controlled board-side subsystem.");
    smallLabel(s, "Fictional metaphor", M, 224, C.coral);
    textBox(s, "A messenger is sent toward Earth to observe and communicate.", M, 265, 500, 68, { fontSize: 24, bold: true });
    smallLabel(s, "rdk-sophon", M, 360, C.blue);
    textBox(s, "probe-daemon lives on the board, observes telemetry and exposes governed actions to rdk-agent.", M, 401, 500, 94, { fontSize: 24, bold: true });
    rect(s, M, 532, 500, 100, C.paleBlue, { geometry: "roundRect", borderRadius: 8 });
    textBox(s, "The crucial difference", 68, 550, 210, 24, { fontSize: 18, bold: true, color: C.blue });
    textBox(s, "Transparent, auditable, reversible and deployed by the device owner - never covert surveillance.", 68, 582, 450, 38, { fontSize: 17, color: C.ink });
    await addImage(s, "sophon-three-body-concept.png", 610, 198, 622, 435, {
      fit: "cover",
      geometry: "roundRect",
      borderRadius: 8,
      alt: "Original Three-Body-inspired naming metaphor: three stars send a geometric messenger to an RDK-class board",
      prompt: "Original science-fiction concept: three-star system sends a geometric micro-messenger through a data lattice toward a generic development board and AI node; no text, logos, actors, book covers or adaptation motifs.",
    });
    textBox(s, "Project-created AI image; no official novel or adaptation assets are used. rdk-sophon is a board-side subsystem name, not an AI accelerator brand.", 610, 642, 622, 30, { fontSize: 12, color: C.muted, autoFit: "shrinkText" });
    notes(s, "Keep this as a naming explanation, then return immediately to the Track 2 product and evidence story.", [
      "User-provided naming rationale in this task.",
      "Project-created AI-generated asset: submission/en/assets/sophon-three-body-concept.png.",
      "Project disclaimer: submission/en/PROJECT_SPECIFICATION.md, section 2.",
    ]);
  }

  // Slide 3 - Codex Grid slide-06 three-column problem layout.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 3, "Problem", "One request crosses five fragile handoffs", "A small behavior must survive intent, code, evidence, deployment and physical acceptance.");
    const cols = [
      { x: 48, n: "01", t: "Intent drifts", b: "Natural language can lose left/right direction, scope or the expected device contract." },
      { x: 444, n: "02", t: "Code can overclaim", b: "A model can say 'passed' without running an executable check or preserving the requested behavior." },
      { x: 840, n: "03", t: "Deployment breaks trust", b: "A valid file is not yet a deterministic package, atomic release, installed Skill or verified board result." },
    ];
    for (const col of cols) {
      textBox(s, col.n, col.x, 242, 90, 58, { fontSize: 48, bold: true, color: C.blue });
      line(s, col.x, 314, 330, C.rule, 1);
      textBox(s, col.t, col.x, 345, 330, 48, { fontSize: 28, bold: true });
      textBox(s, col.b, col.x, 407, 330, 125, { fontSize: 21, color: C.muted, lineSpacing: 1.08 });
    }
    rect(s, M, 570, W - 2 * M, 74, C.ink, { geometry: "roundRect", borderRadius: 6 });
    textBox(s, "RDK Agent turns those handoffs into one governed path with bounded retries and executable evidence.", 74, 588, W - 148, 38, { fontSize: 24, bold: true, color: C.white, alignment: "center" });
    addFooter(s);
    notes(s, "Frame the problem as reproducibility and authority, not simply code generation.", [
      "Project specification: submission/en/PROJECT_SPECIFICATION.md, sections 1 and 3.",
      "Workflow implementation: rdk-agent/config/agents.yaml.",
    ]);
  }

  // Slide 4 - dominant architecture evidence image.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 4, "Architecture", "Reasoning stays private; board authority stays local", "The host orchestrates, the target Radeon endpoint serves the model, and rdk-sophon owns the device contract.");
    await addImage(s, "architecture.png", 78, 204, 1124, 474, {
      fit: "contain",
      frame: false,
      alt: "RDK Agent architecture and trust-boundary diagram",
    });
    notes(s, "Call out the separation between model reasoning, deterministic delivery, the device contract and physical acceptance.", [
      "Project architecture source: submission/en/assets/architecture.svg.",
      "Detailed specification: submission/en/PROJECT_SPECIFICATION.md, section 4.",
    ]);
  }

  // Slide 5 - dominant workflow image.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 5, "Workflow", "Five nodes make delivery repeatable", "One bounded Action Package TDD loop is followed by four deterministic delivery and acceptance nodes.");
    await addImage(s, "workflow.png", 72, 208, 1136, 474, {
      fit: "contain",
      frame: false,
      alt: "Five-node RDK Agent delivery workflow",
    });
    notes(s, "The red loop is the only revision loop and is capped at three iterations. Every downstream node requires a successful predecessor.", [
      "Project workflow source: submission/en/assets/workflow.svg.",
      "Workflow configuration: rdk-agent/config/agents.yaml.",
    ]);
  }

  // Slide 6 - Codex Grid checklist / control rows.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 6, "Safety model", "Controls below the prompt keep authority bounded", "The model can propose; software-enforced scope, policy and evidence decide what can progress.");
    const rows = [
      ["SCOPE", "Agent-specific tool, Skill and write-path allowlists", C.blue],
      ["SANDBOX", "Offline, read-only Podman verification", C.ink],
      ["DIRECTION", "ACTION-DIRECTION-001 blocks opposite-side actions", C.coral],
      ["EVIDENCE", "Executable checks gate package progression", C.green],
      ["DEVICE", "probe-daemon exposes only registered plugins and actions", C.cyan],
    ];
    let y = 214;
    for (const [tag, body, color] of rows) {
      rect(s, M, y, 170, 66, color);
      textBox(s, tag, M, y + 1, 170, 64, { fontSize: 17, bold: true, color: color === C.cyan ? C.ink : C.white, alignment: "center", verticalAlignment: "middle" });
      rect(s, M + 170, y, W - M * 2 - 170, 66, C.panel);
      textBox(s, body, M + 194, y + 1, W - M * 2 - 218, 64, { fontSize: 22, bold: true, verticalAlignment: "middle" });
      y += 78;
    }
    rect(s, M, 616, W - M * 2, 50, C.paleCoral, { geometry: "roundRect", borderRadius: 5 });
    textBox(s, "Boundary: transport authentication and routine per-action human approval remain roadmap items.", 68, 618, W - 136, 46, { fontSize: 16, bold: true, color: C.coral, verticalAlignment: "middle" });
    addFooter(s);
    notes(s, "Describe this as agent/tool-layer permission control. Do not imply end-to-end transport security is complete.", [
      "Safety design: submission/en/PROJECT_SPECIFICATION.md, sections 6-7 and 12.",
      "Verification tests: rdk-agent/test/security-hardening.test.ts and related suites.",
    ]);
  }

  // Slide 7 - repository evidence.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 7, "Repository evidence", "196 tests pass across both workspaces", "Fresh verification: 134 TypeScript tests and 62 Rust tests, plus Clippy and a release build.");
    await addImage(s, "test-evidence.png", 180, 200, 920, 518, {
      fit: "contain",
      frame: false,
      alt: "Repository verification snapshot showing 134 TypeScript and 62 Rust tests passing",
    });
    notes(s, "Mention the disclosed formatting follow-up: cargo fmt --all -- --check reports existing differences, so the deck does not call the full formatting state green.", [
      "Evidence log: submission/en/evidence/verification-2026-08-05.md.",
      "Evidence visual source: submission/en/assets/test-evidence.svg.",
    ]);
  }

  // Slide 8 - live board evidence.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 8, "Device evidence", "A live RDK X5 answers through the board contract", "Read-only ping, state and plugin discovery succeeded; sensitive identifiers were removed.");
    await addImage(s, "board-evidence.png", 180, 200, 920, 518, {
      fit: "contain",
      frame: false,
      alt: "Sanitized live RDK X5 ping, telemetry state and plugin evidence",
    });
    notes(s, "This proves board reachability, live collectors and dynamic plugin discovery. It does not prove physical motion or AMD inference hardware.", [
      "Evidence log: submission/en/evidence/verification-2026-08-05.md.",
      "Evidence visual source: submission/en/assets/board-evidence.svg.",
    ]);
  }

  // Slide 9 - private AMD target path.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 9, "AMD Radeon + ROCm", "Both Qwen3 model paths ran successfully", "80B single-GPU serving and the trained 32B SFT live Agent workflow are evidenced separately.");
    rect(s, M, 218, 492, 350, C.ink, { geometry: "roundRect", borderRadius: 8 });
    pill(s, "BOTH MODELS RUN", 76, 246, 166, C.green);
    textBox(s, "Qwen3-Next-80B-\nA3B-Instruct", 76, 302, 430, 92, { fontSize: 34, bold: true, color: C.white, lineSpacing: 0.95 });
    textBox(s, "Provider  amd\nAPI       OpenAI-compatible\nContext   131,072\nMax out   8,192", 76, 422, 420, 112, { fontSize: 20, color: "#D8DEE8", lineSpacing: 1.2 });
    const bx = [610, 830, 1050];
    const labels = ["RDK Agent", "OpenAI API", "vLLM + ROCm"];
    for (let i = 0; i < bx.length; i++) {
      rect(s, bx[i], 282, 170, 86, i === 2 ? C.paleGreen : C.paleBlue, { geometry: "roundRect", borderRadius: 6 });
      textBox(s, labels[i], bx[i], 284, 170, 82, { fontSize: 20, bold: true, alignment: "center", verticalAlignment: "middle" });
      if (i < bx.length - 1) {
        rect(s, bx[i] + 178, 318, 34, 4, C.blue);
        rect(s, bx[i] + 202, 310, 16, 20, C.blue, { geometry: "rightArrow" });
      }
    }
    rect(s, 610, 414, 610, 154, C.paleCoral, { geometry: "roundRect", borderRadius: 8 });
    textBox(s, "Archived evidence", 638, 438, 480, 32, { fontSize: 23, bold: true, color: C.green });
    textBox(s, "80B: single-Radeon llama.cpp metrics\n32B SFT: 5/5 live Agent nodes\nPrivate vLLM provenance remains separate", 638, 486, 540, 72, { fontSize: 19, color: C.ink, lineSpacing: 1.2 });
    addFooter(s);
    notes(s, "Both models ran. Keep the evidence scopes distinct: the 80B figures come from the archived llama.cpp case; the 32B SFT screenshot proves the live Agent path.", [
      "Sanitized config: submission/en/config/pi-models.amd-rocm.example.json.",
      "AMD evidence plan: submission/en/AMD_RADEON_ROCM.md.",
      "Current evidence boundary: submission/en/evidence/verification-2026-08-05.md.",
    ]);
  }

  // Slide 10 - metric-led view of the two archived Radeon paths.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 10, "Optimization", "Measured gains on two Radeon paths", "32B SFT improves user-visible TTFT; 80B single-GPU serving improves decode throughput.");
    const cards = [
      { x: 48, key: "32B TTFT", title: "17.41 -> 8.26 s", body: "p50, 88 trials per arm" },
      { x: 444, key: "80B TOK/S", title: "37.19 -> 49.82", body: "decode, five measured runs per arm" },
      { x: 840, key: "AGENT 5/5", title: "4:04 total", body: "32B SFT workflow on RDK X5" },
    ];
    for (const card of cards) {
      rect(s, card.x, 244, 344, 260, C.panel, { geometry: "roundRect", borderRadius: 6 });
      textBox(s, card.key, card.x + 28, 276, 288, 68, { fontSize: 52, bold: true, color: C.blue });
      textBox(s, card.title, card.x + 28, 370, 288, 34, { fontSize: 23, bold: true });
      textBox(s, card.body, card.x + 28, 425, 288, 50, { fontSize: 18, color: C.muted });
    }
    rect(s, M, 546, W - M * 2, 92, C.ink, { geometry: "roundRect", borderRadius: 6 });
    textBox(s, "Evidence scope", 72, 566, 205, 26, { fontSize: 19, bold: true, color: C.cyan });
    textBox(s, "32B and 80B runs keep separate runtimes, protocols and archived measurements", 290, 563, 880, 36, { fontSize: 20, bold: true, color: C.white, verticalAlignment: "middle" });
    textBox(s, "NO CROSS-RUNTIME SPEED CLAIM; PRIVATE VLLM PROVENANCE REMAINS SEPARATE", 290, 604, 880, 18, { fontSize: 13, bold: true, color: "#FF9B92" });
    addFooter(s);
    notes(s, "Both paths have measured baseline-versus-optimized results. Do not compare their absolute speeds because model sizes, servers and protocols differ.", [
      "Benchmark script: submission/en/scripts/benchmark-openai-compatible.mjs.",
      "Optimization plan: submission/en/AMD_RADEON_ROCM.md.",
    ]);
  }

  // Slide 11 - Codex Grid slide-17 timeline plus video placeholder.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    addTitle(s, 11, "Demo", "The video proves the entire closed loop", "The 3:07 public recording is available from two independent links.");
    rect(s, M, 208, W - M * 2, 78, C.ink, { geometry: "roundRect", borderRadius: 6 });
    textBox(s, "PUBLIC VIDEO", 72, 226, 180, 20, { fontSize: 14, bold: true, color: C.cyan });
    textBox(s, "Bilibili BV1t3up6iEhy  |  Baidu Cloud backup", 266, 220, 850, 34, { fontSize: 28, bold: true, color: C.white });
    line(s, 86, 382, 1108, C.ink, 2);
    const marks = [200, 640, 1080];
    const chapters = [
      ["0:00", "Intent + graph", "Show the request, semantic gate and bounded TDD progress."],
      ["1:15", "Build + deploy", "Show executable checks, package validation, release and Skill installation."],
      ["2:45", "Accept + prove", "Show CLI/NL acceptance, the board result and redacted Radeon/ROCm evidence."],
    ];
    for (let i = 0; i < marks.length; i++) {
      rect(s, marks[i] - 8, 374, 16, 16, C.blue, { geometry: "ellipse" });
      textBox(s, chapters[i][0], marks[i] - 50, 330, 100, 24, { fontSize: 18, bold: true, color: C.blue, alignment: "center" });
      textBox(s, chapters[i][1], marks[i] - 112, 414, 224, 34, { fontSize: 25, bold: true, alignment: "center" });
      textBox(s, chapters[i][2], marks[i] - 150, 462, 300, 102, { fontSize: 19, color: C.muted, alignment: "center", lineSpacing: 1.08 });
    }
    rect(s, M, 594, W - M * 2, 56, C.paleBlue, { geometry: "roundRect", borderRadius: 5 });
    textBox(s, "Privacy check: blur keys, private URLs, emails, MAC addresses and unnecessary internal IPs.", 72, 595, W - 144, 54, { fontSize: 17, bold: true, color: C.blue, alignment: "center", verticalAlignment: "middle" });
    addFooter(s);
    notes(s, "Keep the total duration between three and five minutes. The AMD segment should show the participant-controlled Radeon/ROCm/vLLM runtime, not only the RDK board.", [
      "Video shot list: submission/en/VIDEO.md.",
      "Official Track 2 requirement: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07",
    ]);
  }

  // Slide 12 - Codex Grid slide-26 sparse close.
  {
    const s = deck.slides.add();
    s.background.fill = C.white;
    pill(s, "TRACK 2 | SUBMISSION READY", M, 46, 230, C.blue);
    textBox(s, "One governed path\nfrom intent to a board action.", M, 154, 1020, 176, { fontSize: 66, bold: true, lineSpacing: 0.92 });
    line(s, M, 370, 88, C.cyan, 5);
    textBox(s, "Private reasoning. Deterministic delivery. Live board evidence.", M, 400, 920, 44, { fontSize: 29, bold: true, color: C.muted });
    const items = [
      ["01", "Team: d-robotics agent"],
      ["02", "Public video: primary + backup"],
      ["03", "32B SFT + 80B Radeon evidence"],
    ];
    let y = 500;
    for (const [n, label] of items) {
      textBox(s, n, M, y, 44, 28, { fontSize: 18, bold: true, color: C.coral });
      textBox(s, label, 104, y - 1, 570, 30, { fontSize: 21, bold: true });
      y += 45;
    }
    rect(s, 784, 490, 448, 142, C.ink, { geometry: "roundRect", borderRadius: 8 });
    textBox(s, "Next action", 816, 514, 160, 22, { fontSize: 17, bold: true, color: C.cyan });
    textBox(s, "Run the final integrity review, then open the official Track 2 pull request.", 816, 552, 372, 60, { fontSize: 22, bold: true, color: C.white, lineSpacing: 1.03 });
    addFooter(s);
    notes(s, "Close by resolving the opening promise and naming the only remaining owner actions. Do not end with a generic thank-you slide.", [
      "Submission checklist: submission/en/SUBMISSION_CHECKLIST.md.",
      "PR draft: submission/en/PR_DESCRIPTION.md.",
    ]);
  }

  const snapshot = await deck.inspect({ kind: "slide,textbox,shape,image,notes", maxChars: 50000 });
  await fs.writeFile(path.join(RENDER, "deck-inspect.ndjson"), snapshot.ndjson);

  for (const [index, slide] of deck.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const png = await deck.export({ slide, format: "png", scale: 1 });
    await fs.writeFile(path.join(RENDER, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(RENDER, `${stem}.layout.json`), await layout.text());
  }

  const montage = await deck.export({ format: "webp", montage: true, scale: 1 });
  await fs.writeFile(path.join(RENDER, "deck-montage.webp"), new Uint8Array(await montage.arrayBuffer()));

  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(OUT);
  console.log(OUT);
}

build().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
