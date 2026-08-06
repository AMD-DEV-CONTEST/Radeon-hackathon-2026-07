const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  Header,
  HeadingLevel,
  ImageRun,
  LevelFormat,
  Packer,
  PageBreak,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} = require("docx");
const PptxGenJS = require("pptxgenjs");
const { marked } = require("marked");

const root = path.resolve(__dirname, "..");
const submission = path.join(root, "submission");
const screenshot = path.join(submission, "assets", "claimcourt-ui.png");
const docxPath = path.join(submission, "ClaimCourt_Project_Description.docx");
const htmlPath = path.join(submission, "ClaimCourt_Project_Description.html");
const pptxPath = path.join(submission, "ClaimCourt_Presentation.pptx");

const C = {
  ink: "111827",
  muted: "5B6475",
  line: "D7DEE8",
  paper: "FFFFFF",
  soft: "F3F6FA",
  green: "00A878",
  cyan: "008FB3",
  amber: "D98E04",
  red: "D6425D",
  night: "0B0F14",
  panel: "131A24",
  panel2: "1B2432",
  white: "F5F7FA",
  gray: "93A4B8",
  neon: "00E5A8",
  electric: "00C2E0",
  gold: "FFB000",
  danger: "FF4D6D",
};

const thinBorder = { style: BorderStyle.SINGLE, size: 1, color: C.line };
const borders = { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder };

function run(text, options = {}) {
  return new TextRun({ text, font: options.font || "Arial", size: options.size || 21, color: options.color || C.ink, bold: options.bold, italics: options.italics });
}

function para(text, options = {}) {
  return new Paragraph({
    alignment: options.align || AlignmentType.LEFT,
    spacing: { before: options.before || 0, after: options.after === undefined ? 110 : options.after, line: options.line || 300 },
    children: [run(text, options)],
  });
}

function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { after: 70, line: 290 },
    children: [run(text)],
  });
}

function heading(text, level = 1) {
  return new Paragraph({
    heading: level === 1 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2,
    children: [run(text, { bold: true })],
  });
}

function code(lines) {
  return lines.map((line) => new Paragraph({
    spacing: { after: 0, line: 250 },
    shading: { fill: "EEF2F7", type: ShadingType.CLEAR },
    indent: { left: 240, right: 240 },
    children: [run(line || " ", { font: "Consolas", size: 18, color: "273142" })],
  }));
}

function cell(text, width, options = {}) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: options.header ? { fill: "DFF5EF", type: ShadingType.CLEAR } : options.fill ? { fill: options.fill, type: ShadingType.CLEAR } : undefined,
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      alignment: options.align || AlignmentType.LEFT,
      spacing: { before: 50, after: 50 },
      children: [run(text, { bold: options.header, size: options.size || 19, color: options.color || C.ink })],
    })],
  });
}

function table(headers, rows, widths) {
  return new Table({
    columnWidths: widths,
    margins: { top: 100, bottom: 100, left: 140, right: 140 },
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((item, i) => cell(item, widths[i], { header: true })) }),
      ...rows.map((row) => new TableRow({ children: row.map((item, i) => cell(String(item), widths[i])) })),
    ],
  });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

async function buildDocx() {
  const children = [
    para("CLAIMCOURT", { align: AlignmentType.CENTER, bold: true, size: 54, color: C.green, before: 900, after: 80 }),
    para("A Private Local AI Evidence Court", { align: AlignmentType.CENTER, bold: true, size: 34, after: 220 }),
    para("AMD AI DevMaster Hackathon 2026", { align: AlignmentType.CENTER, size: 24, color: C.muted, after: 50 }),
    para("Track 2 - Development & Local Deployment of Private AI Agents", { align: AlignmentType.CENTER, size: 22, color: C.muted, after: 50 }),
    para("Team Zi Fei Yu", { align: AlignmentType.CENTER, bold: true, size: 24, color: C.cyan, after: 500 }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 260 },
      children: [new ImageRun({
        type: "png",
        data: fs.readFileSync(screenshot),
        transformation: { width: 610, height: 381 },
        altText: { title: "ClaimCourt interface", description: "English ClaimCourt private investigation interface", name: "ClaimCourt UI" },
      })],
    }),
    para("Private documents stay inside the selected deployment boundary. Evidence is retrieved, cited, challenged, and exported only after approval.", { align: AlignmentType.CENTER, italics: true, size: 20, color: C.muted, after: 0 }),
    pageBreak(),

    heading("1. Executive Summary"),
    para("ClaimCourt is a private, evidence-grounded local AI agent for people who remember the meaning of a record but not its filename, and for teams that must resolve disputed commitments across contracts, email, meeting notes, presentations, and internal reports."),
    para("Its Fuzzy Intent Compiler converts incomplete human recollections into a transparent structured search plan. Its Evidence Court then runs controlled prosecution, defense, and judge stages using one local instruction model. Every verdict is constrained to citations from the retrieved packet and includes contradictions, a timeline, missing evidence, and a recommended next action."),
    para("The verified competition stack runs on an AMD Radeon PRO W7900-class GPU with ROCm, Qwen3-14B BF16 through vLLM, a ClaimCourt intent LoRA, BAAI/bge-small-zh-v1.5, and a local BGE cross-encoder. No closed remote model API is required."),

    heading("2. Application Scenarios"),
    heading("2.1 Disputed commitment review", 2),
    para("A customer says sales promised 99.9% uptime. Procurement sees no SLA in the signed agreement. Engineering remembers a conditional Q4 target. ClaimCourt distinguishes marketing, drafts, signed obligations, exceptions, and missing records before producing a cited brief."),
    heading("2.2 Fuzzy private file recovery", 2),
    para("A user asks, \"Find the presentation I wrote about the customer's delayed launch and Q4 risk.\" ClaimCourt compiles the recollection, groups draft and final versions, selects the authoritative file, and creates a cited summary from the complete artifact."),
    heading("2.3 Redacted sensitive-record location", 2),
    para("A deterministic local scanner locates credential-like records but returns only file location, category, fingerprint, and redacted preview. Raw secret values never enter the model, UI history, or exported report."),
    heading("2.4 Approval reconstruction", 2),
    para("ClaimCourt reconstructs who approved a change and under what conditions from dated meeting notes, approval logs, email, and change requests."),
    pageBreak(),

    heading("3. Agent Architecture"),
    para("The three roles are controlled serial stages using one local model. This is auditable orchestration, not a claim of autonomous multi-model collaboration."),
    table(
      ["Stage", "Local component", "Output"],
      [
        ["1. Ingest", "PDF, DOC, DOCX, PPTX, TXT, MD, EML and local OCR parsers", "Parent-child chunks with page or slide locators"],
        ["2. Remember", "SHA-256 evidence ledger, durable SQLite FTS5 and version archive", "Auditable local workspace memory"],
        ["3. Understand", "Qwen3-14B + ClaimCourt intent LoRA", "Structured intent, constraints and clarification policy"],
        ["4. Retrieve", "BM25, FTS5, TF-IDF, BGE, metadata and file-family authority rules", "Ranked evidence and authoritative files"],
        ["5. Challenge", "Prosecutor and defense calls", "Supporting evidence, counter-evidence and exceptions"],
        ["6. Decide", "Judge call with citation allow-list", "Verdict, confidence, contradictions, timeline and missing evidence"],
        ["7. Act", "Explicit permission gate", "Local Markdown decision brief"],
      ],
      [1500, 3900, 3960],
    ),
    heading("3.1 Core Track 2 capabilities", 2),
    bullet("Local RAG with structure-aware chunks, durable indexes, embeddings and reranking."),
    bullet("Tool routing for evidence court, file location, artifact summary and redacted secret scanning."),
    bullet("Multi-step planning across understand, retrieve, prosecute, defend, judge and export."),
    bullet("Persistent local memory for hashes, versions, query plans, feedback and diagnostics."),
    bullet("Permission controls, loopback endpoints, citation validation and fail-closed privacy behavior."),
    pageBreak(),

    heading("4. Retrieval and Fuzzy Intent Innovation"),
    para("ClaimCourt does not treat a vague sentence as an embedding query. The Fuzzy Intent Compiler extracts artifact types, topics, entities, dates, remembered relations, required roles, excluded roles, request mode, and clarification requirements. This plan is visible to the user and drives every retrieval layer."),
    heading("4.1 Hybrid retrieval", 2),
    bullet("BM25 and SQLite FTS5 preserve exact terms, identifiers and Chinese short phrases."),
    bullet("Word TF-IDF and character n-grams handle partial filenames and spelling variation."),
    bullet("BGE embeddings recover semantic similarity and cross-language concepts."),
    bullet("Metadata and filename evidence enforce artifact, time and path constraints."),
    bullet("A local cross-encoder reranks only a bounded shortlist."),
    bullet("File-family authority rules keep Final or Signed above Draft unless Draft is explicitly requested."),
    heading("4.2 Safety against confident retrieval mistakes", 2),
    para("Ranking is not treated as a verdict. ClaimCourt calibrates score and margin, asks for clarification on ambiguous requests, returns no-match for unsupported year or role constraints, and records local owner feedback without exporting private query text into public training data."),
    pageBreak(),

    heading("5. Privacy, Permissions and Audit"),
    table(
      ["Threat", "Control"],
      [
        ["Document text sent to a public model", "Only loopback endpoints are accepted unless the owner explicitly allow-lists a private host."],
        ["Secret exposed in an answer", "Deterministic redaction runs before model, UI, history and export paths."],
        ["Model invents a citation", "Only citation IDs from the retrieved packet are allowed; unknown IDs are removed and logged."],
        ["Report written without consent", "Export is disabled until the user approves the local write."],
        ["Model failure hidden by a demo answer", "Real workspaces fail closed; deterministic fallback is limited to the labeled synthetic demo."],
        ["Stale or changed evidence", "SHA-256 source and evidence hashes plus version history expose changes."],
      ],
      [3100, 6260],
    ),
    heading("5.1 Honest scope", 2),
    para("ClaimCourt is a private alpha and not legal advice. The public benchmark is synthetic. Encryption at rest, authenticated multi-user isolation, and long-term owner dogfood remain post-hackathon production gates."),
    pageBreak(),

    heading("6. Model and Radeon Deployment"),
    table(
      ["Layer", "Verified component"],
      [
        ["GPU", "AMD Radeon PRO W7900 class, gfx1100, 51.52 GB VRAM"],
        ["Runtime", "ROCm + vLLM, OpenAI-compatible loopback endpoints"],
        ["Judge", "Qwen3-14B BF16"],
        ["Intent specialization", "ClaimCourt LoRA trained on synthetic query-to-intent plans"],
        ["Embedding", "BAAI/bge-small-zh-v1.5, 512 dimensions, vLLM pooling runner"],
        ["Reranker", "Local bge-reranker-base cross-encoder"],
        ["Interface", "React/Vite frontend with a local Python API"],
      ],
      [3100, 6260],
    ),
    heading("6.1 Startup", 2),
    ...code([
      "cd /workspace/claimcourt",
      "python -m pip install -r requirements-radeon.txt",
      "bash scripts/start_radeon_stack.sh",
    ]),
    heading("6.2 Radeon optimization", 2),
    bullet("One shared Qwen3-14B service is reused by prosecution, defense and judge."),
    bullet("BF16 fits the verified W7900 stack while preserving model quality."),
    bullet("Judge VRAM allocation is 0.82 and embedding allocation is 0.10; observed peak stack usage was approximately 45.3 GB of 51.52 GB."),
    bullet("Thinking is disabled for schema calls to reduce output overhead and protect JSON contracts."),
    bullet("The judge receives a bounded 8,192-token evidence packet instead of the complete workspace."),
    bullet("The cross-encoder reranks only a shortlist; router concurrency 8 saturated the GPU during live evaluation."),
    pageBreak(),

    heading("7. Measured Results"),
    heading("7.1 Live Radeon court gate", 2),
    table(
      ["Metric", "Measured result"],
      [
        ["First-token latency", "0.27 s"],
        ["Generation throughput", "14.3 tokens/s"],
        ["Completion tokens", "1,778"],
        ["Complete three-role latency", "126.44 s"],
        ["Court mode", "local vLLM"],
        ["Expected verdict", "insufficient_evidence"],
      ],
      [4680, 4680],
    ),
    heading("7.2 Frozen live fuzzy-intent holdout", 2),
    table(
      ["Metric", "Result"],
      [
        ["Queries", "320"],
        ["Overall pass rate", "100%"],
        ["Intent contract accuracy", "100%"],
        ["Single-target Top-1", "100%"],
        ["Multi-target full coverage", "100%"],
        ["No-match and clarification accuracy", "100%"],
        ["Unsafe wrong auto-selections", "0"],
        ["Live Router, embedding and reranker", "all passed"],
      ],
      [4680, 4680],
    ),
    para("The frozen holdout is an engineering regression gate built from synthetic data. It does not claim universal retrieval quality. Private directory evaluation remains outside the public repository and only sanitized aggregate metrics are published.", { italics: true, color: C.muted }),
    pageBreak(),

    heading("8. Demo and Repository Verification"),
    heading("8.1 Four-minute demo", 2),
    bullet("Show rocminfo, rocm-smi, local vLLM endpoints and zero-external-call runtime evidence."),
    bullet("Load the synthetic multi-file SLA workspace and ask whether 99.9% uptime was contractually committed."),
    bullet("Inspect the intent plan, evidence packet, prosecution, defense, cited verdict and timeline."),
    bullet("Approve the local export and show that no report is written before consent."),
    bullet("Close with measured latency, throughput, VRAM and 320/320 live holdout evidence."),
    heading("8.2 Verification commands", 2),
    ...code([
      "python -m unittest discover -s tests -t .",
      "python scripts/championship_check.py --output championship_results.local.json",
      "python scripts/adversarial_holdout_check.py",
      "CLAIMCOURT_RERANKER_MODEL=/workspace/models/bge-reranker-base bash scripts/run_radeon_holdout.sh",
    ]),
    para("Current release status: 78 Python tests passed, frontend TypeScript lint passed, frontend production build passed, and both Radeon live acceptance gates passed.", { bold: true, color: C.green, before: 200 }),
  ];

  const doc = new Document({
    creator: "Zi Fei Yu",
    title: "ClaimCourt: A Private Local AI Evidence Court",
    description: "AMD AI DevMaster Hackathon 2026 Track 2 project description",
    styles: {
      default: { document: { run: { font: "Arial", size: 21, color: C.ink } } },
      paragraphStyles: [
        { id: "Title", name: "Title", basedOn: "Normal", run: { font: "Arial", size: 52, bold: true, color: C.ink }, paragraph: { spacing: { after: 180 }, alignment: AlignmentType.CENTER } },
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: "Arial", size: 32, bold: true, color: C.green }, paragraph: { spacing: { before: 260, after: 130 }, outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: "Arial", size: 25, bold: true, color: C.cyan }, paragraph: { spacing: { before: 190, after: 90 }, outlineLevel: 1 } },
      ],
    },
    numbering: {
      config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 260 } } } }] }],
    },
    sections: [{
      properties: { page: { margin: { top: 900, right: 900, bottom: 900, left: 900 }, pageNumbers: { start: 1, formatType: "decimal" } } },
      headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [run("CLAIMCOURT  /  TEAM ZI FEI YU", { size: 16, color: C.muted, bold: true })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [run("AMD AI DevMaster Hackathon 2026  |  Track 2  |  Page ", { size: 16, color: C.muted }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: C.muted })] })] }) },
      children,
    }],
  });

  fs.writeFileSync(docxPath, await Packer.toBuffer(doc));
}

function addText(slide, text, x, y, w, h, options = {}) {
  slide.addText(text, {
    x, y, w, h,
    fontFace: options.fontFace || "Aptos",
    fontSize: options.fontSize || 18,
    color: options.color || C.white,
    bold: options.bold || false,
    margin: options.margin === undefined ? 0 : options.margin,
    valign: options.valign || "mid",
    align: options.align || "left",
    breakLine: false,
    fit: "shrink",
  });
}

function baseSlide(pptx, section, number) {
  const slide = pptx.addSlide();
  slide.background = { color: C.night };
  slide.addShape(pptx.ShapeType.line, { x: 0.45, y: 0.54, w: 12.42, h: 0, line: { color: "283445", width: 1 } });
  addText(slide, "CC", 0.45, 0.16, 0.38, 0.28, { fontFace: "Consolas", fontSize: 15, bold: true, color: C.neon, align: "center" });
  addText(slide, "CLAIMCOURT", 0.92, 0.14, 1.55, 0.3, { fontFace: "Consolas", fontSize: 15, bold: true });
  addText(slide, section.toUpperCase(), 10.15, 0.14, 2.15, 0.3, { fontFace: "Consolas", fontSize: 11, color: C.gray, align: "right" });
  addText(slide, String(number).padStart(2, "0"), 12.4, 0.14, 0.4, 0.3, { fontFace: "Consolas", fontSize: 11, color: C.neon, align: "right" });
  return slide;
}

function title(slide, kicker, headline, subhead = "") {
  addText(slide, kicker.toUpperCase(), 0.65, 0.82, 4.6, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.neon });
  addText(slide, headline, 0.65, 1.15, 12.0, 0.92, { fontSize: 32, bold: true, valign: "top" });
  if (subhead) addText(slide, subhead, 0.65, 2.16, 11.8, 0.38, { fontSize: 15, color: C.gray, valign: "top" });
}

function panel(slide, pptx, x, y, w, h, accent = C.neon) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.04, fill: { color: C.panel }, line: { color: "2A3748", width: 1 } });
  slide.addShape(pptx.ShapeType.rect, { x, y, w: 0.05, h, fill: { color: accent }, line: { color: accent, transparency: 100 } });
}

function metric(slide, pptx, x, y, w, value, label, accent) {
  panel(slide, pptx, x, y, w, 1.12, accent);
  addText(slide, value, x + 0.22, y + 0.16, w - 0.35, 0.45, { fontFace: "Consolas", fontSize: 26, bold: true, color: accent });
  addText(slide, label, x + 0.22, y + 0.68, w - 0.35, 0.24, { fontSize: 11, color: C.gray });
}

function arrow(slide, pptx, x, y, w) {
  slide.addShape(pptx.ShapeType.chevron, { x, y, w, h: 0.33, fill: { color: "344154" }, line: { color: "344154" } });
}

async function buildPptx() {
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "Zi Fei Yu";
  pptx.company = "Zi Fei Yu";
  pptx.subject = "AMD AI DevMaster Hackathon 2026 Track 2";
  pptx.title = "ClaimCourt: A Private Local AI Evidence Court";
  pptx.lang = "en-US";
  pptx.theme = { headFontFace: "Aptos Display", bodyFontFace: "Aptos", lang: "en-US" };
  pptx.defineSlideMaster({ title: "CLAIMCOURT", background: { color: C.night }, objects: [] });

  let slide = baseSlide(pptx, "Track 2 submission", 1);
  addText(slide, "PRIVATE / LOCAL / EVIDENCE-GROUNDED", 0.7, 1.12, 5.4, 0.32, { fontFace: "Consolas", fontSize: 13, bold: true, color: C.neon });
  addText(slide, "ClaimCourt", 0.7, 1.58, 7.4, 0.95, { fontSize: 48, bold: true });
  addText(slide, "A Private Local AI Evidence Court", 0.72, 2.5, 8.0, 0.55, { fontSize: 24, color: C.electric });
  addText(slide, "Turns fuzzy human recollections and disputed commitments into cited local evidence, contradiction timelines, and approval-gated briefs.", 0.72, 3.25, 7.5, 1.1, { fontSize: 19, color: C.gray, valign: "top" });
  panel(slide, pptx, 8.75, 1.25, 3.85, 3.35, C.gold);
  addText(slide, "TEAM", 9.05, 1.58, 1.0, 0.25, { fontFace: "Consolas", fontSize: 11, color: C.gray });
  addText(slide, "ZI FEI YU", 9.05, 1.92, 2.9, 0.45, { fontFace: "Consolas", fontSize: 25, bold: true, color: C.gold });
  addText(slide, "AMD AI DevMaster Hackathon 2026", 9.05, 2.63, 3.0, 0.6, { fontSize: 16, bold: true });
  addText(slide, "Track 2\nDevelopment & Local Deployment\nof Private AI Agents", 9.05, 3.28, 3.0, 0.92, { fontSize: 14, color: C.gray, valign: "top" });
  addText(slide, "0 CLOSED MODEL APIs", 0.72, 6.72, 2.4, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.neon });
  addText(slide, "RADEON + ROCm + vLLM", 3.3, 6.72, 2.7, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.electric });

  slide = baseSlide(pptx, "The product", 2);
  title(slide, "A real workspace problem", "People remember meaning, not filenames", "ClaimCourt combines fuzzy private memory retrieval with an evidence-grounded decision workflow.");
  slide.addImage({ path: screenshot, x: 0.65, y: 2.58, w: 8.3, h: 5.19 });
  panel(slide, pptx, 9.25, 2.58, 3.4, 1.24, C.neon);
  addText(slide, "01", 9.52, 2.78, 0.52, 0.35, { fontFace: "Consolas", fontSize: 20, bold: true, color: C.neon });
  addText(slide, "Find the right private file from an incomplete recollection.", 10.15, 2.72, 2.15, 0.65, { fontSize: 15, bold: true, valign: "top" });
  panel(slide, pptx, 9.25, 4.02, 3.4, 1.24, C.electric);
  addText(slide, "02", 9.52, 4.22, 0.52, 0.35, { fontFace: "Consolas", fontSize: 20, bold: true, color: C.electric });
  addText(slide, "Challenge disputed claims with cited supporting and opposing evidence.", 10.15, 4.16, 2.15, 0.65, { fontSize: 15, bold: true, valign: "top" });
  panel(slide, pptx, 9.25, 5.46, 3.4, 1.24, C.danger);
  addText(slide, "03", 9.52, 5.66, 0.52, 0.35, { fontFace: "Consolas", fontSize: 20, bold: true, color: C.danger });
  addText(slide, "Locate sensitive records without revealing the secret value.", 10.15, 5.6, 2.15, 0.65, { fontSize: 15, bold: true, valign: "top" });

  slide = baseSlide(pptx, "Core innovation", 3);
  title(slide, "Fuzzy Intent Compiler", "Do not send vague language directly to a vector store", "Compile human memory into explicit constraints, relations, exclusions, and clarification policy first.");
  panel(slide, pptx, 0.65, 2.75, 3.35, 2.55, C.gold);
  addText(slide, "HUMAN RECOLLECTION", 0.92, 3.0, 2.7, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.gold });
  addText(slide, "\"Find the deck I wrote after the customer launch slipped - it mentioned Q4 risk.\"", 0.92, 3.46, 2.72, 1.28, { fontSize: 18, bold: true, valign: "top" });
  arrow(slide, pptx, 4.2, 3.78, 0.48);
  panel(slide, pptx, 4.9, 2.75, 3.6, 2.55, C.neon);
  addText(slide, "LOCAL INTENT PLAN", 5.18, 3.0, 2.9, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.neon });
  addText(slide, "artifact: PPTX\ntopics: customer delay, delivery risk\ntime: Q4\nrelation: causal_after\nmode: single\nclarify: false", 5.18, 3.43, 2.75, 1.5, { fontFace: "Consolas", fontSize: 14, color: C.white, valign: "top" });
  arrow(slide, pptx, 8.72, 3.78, 0.48);
  panel(slide, pptx, 9.42, 2.75, 3.22, 2.55, C.electric);
  addText(slide, "RETRIEVAL DECISION", 9.7, 3.0, 2.6, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.electric });
  addText(slide, "Final version selected\nDraft grouped as alternate\nPage / slide evidence retained\nLow confidence -> clarify", 9.7, 3.46, 2.55, 1.4, { fontSize: 16, bold: true, valign: "top" });
  metric(slide, pptx, 0.65, 5.77, 2.72, "320 / 320", "frozen live queries passed", C.neon);
  metric(slide, pptx, 3.58, 5.77, 2.72, "100%", "single-target Top-1", C.electric);
  metric(slide, pptx, 6.51, 5.77, 2.72, "100%", "clarification accuracy", C.gold);
  metric(slide, pptx, 9.44, 5.77, 3.2, "0", "unsafe wrong auto-selections", C.danger);

  slide = baseSlide(pptx, "Controlled agents", 4);
  title(slide, "Evidence Court", "One local model. Three constrained roles. One citation boundary.", "The workflow is auditable orchestration, not performative multi-agent autonomy.");
  const roles = [
    ["PROSECUTOR", "Strongest supporting evidence", C.neon],
    ["DEFENSE", "Counter-evidence, exceptions and contradictions", C.electric],
    ["JUDGE", "Schema-valid verdict using allowed citation IDs only", C.gold],
  ];
  roles.forEach((role, i) => {
    const x = 0.65 + i * 4.18;
    panel(slide, pptx, x, 2.78, 3.62, 2.18, role[2]);
    addText(slide, `STAGE ${i + 1}`, x + 0.28, 3.02, 1.2, 0.25, { fontFace: "Consolas", fontSize: 11, color: C.gray });
    addText(slide, role[0], x + 0.28, 3.38, 2.8, 0.45, { fontFace: "Consolas", fontSize: 23, bold: true, color: role[2] });
    addText(slide, role[1], x + 0.28, 4.05, 2.94, 0.55, { fontSize: 15, bold: true, valign: "top" });
    if (i < 2) arrow(slide, pptx, x + 3.77, 3.65, 0.28);
  });
  panel(slide, pptx, 0.65, 5.38, 11.98, 1.14, C.danger);
  addText(slide, "HARD OUTPUT CONTRACT", 0.95, 5.62, 2.2, 0.26, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.danger });
  addText(slide, "claim  /  supported | contradicted | insufficient_evidence  /  confidence  /  citations  /  contradictions  /  timeline  /  missing evidence  /  next action", 0.95, 5.98, 11.1, 0.3, { fontFace: "Consolas", fontSize: 12, color: C.white });

  slide = baseSlide(pptx, "System architecture", 5);
  title(slide, "Private local architecture", "Every sensitive component stays inside the selected host", "Evidence is retrieved before inference, and every downstream action is permission- and citation-gated.");
  const stages = [
    ["PRIVATE\nFILES", "PDF / DOCX / PPTX / EML / OCR", C.gray],
    ["LOCAL\nMEMORY", "chunks / SHA-256 / FTS5 / versions", C.electric],
    ["INTENT\nCOMPILER", "Qwen3-14B + ClaimCourt LoRA", C.neon],
    ["HYBRID\nRETRIEVAL", "BM25 / BGE / metadata / reranker", C.electric],
    ["EVIDENCE\nCOURT", "prosecutor / defense / judge", C.gold],
    ["APPROVED\nBRIEF", "local write only after consent", C.danger],
  ];
  stages.forEach((stage, i) => {
    const x = 0.45 + i * 2.13;
    panel(slide, pptx, x, 3.0, 1.78, 2.25, stage[2]);
    addText(slide, stage[0], x + 0.18, 3.28, 1.42, 0.66, { fontFace: "Consolas", fontSize: 17, bold: true, color: stage[2], align: "center" });
    addText(slide, stage[1], x + 0.18, 4.2, 1.42, 0.62, { fontSize: 11, color: C.gray, align: "center", valign: "top" });
    if (i < stages.length - 1) arrow(slide, pptx, x + 1.82, 3.92, 0.23);
  });
  addText(slide, "LOOPBACK MODEL ENDPOINTS", 0.65, 5.78, 2.55, 0.28, { fontFace: "Consolas", fontSize: 11, bold: true, color: C.neon });
  addText(slide, "127.0.0.1:8000/v1  judge + LoRA router", 0.65, 6.12, 3.65, 0.28, { fontFace: "Consolas", fontSize: 12, color: C.white });
  addText(slide, "127.0.0.1:8001/v1  BGE embeddings", 4.48, 6.12, 3.4, 0.28, { fontFace: "Consolas", fontSize: 12, color: C.white });
  addText(slide, "0 external model calls", 9.58, 6.12, 2.7, 0.28, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.danger, align: "right" });

  slide = baseSlide(pptx, "Privacy", 6);
  title(slide, "Privacy is a control plane", "ClaimCourt does not rely on a privacy promise alone", "The architecture blocks unsafe endpoints, raw-secret disclosure, invented citations, silent fallback and unapproved writes.");
  const controls = [
    ["LOCAL ENDPOINT POLICY", "Loopback-only by default; private hosts require explicit owner allow-listing.", C.neon],
    ["SECRET REDACTION", "Raw credentials are removed before model, UI, history and export paths.", C.danger],
    ["CITATION ALLOW-LIST", "The judge may cite only evidence IDs from the current retrieved packet.", C.electric],
    ["FAIL CLOSED", "Real workspaces never receive a fabricated deterministic answer when vLLM fails.", C.gold],
    ["APPROVAL GATE", "No local decision brief is written until the user approves the operation.", C.neon],
    ["AUDIT LEDGER", "Source, evidence and report identities use SHA-256 for later verification.", C.electric],
  ];
  controls.forEach((item, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.65 + col * 6.05;
    const y = 2.72 + row * 1.42;
    panel(slide, pptx, x, y, 5.62, 1.15, item[2]);
    addText(slide, item[0], x + 0.25, y + 0.18, 2.1, 0.25, { fontFace: "Consolas", fontSize: 11, bold: true, color: item[2] });
    addText(slide, item[1], x + 2.28, y + 0.16, 3.02, 0.68, { fontSize: 13, color: C.white, valign: "top" });
  });

  slide = baseSlide(pptx, "AMD Radeon", 7);
  title(slide, "Verified Radeon stack", "Qwen3-14B + LoRA + BGE + reranker on one W7900-class GPU", "The complete local stack peaked at approximately 45.3 GB of 51.52 GB VRAM.");
  metric(slide, pptx, 0.65, 2.68, 2.9, "Qwen3-14B", "BF16 judge and controlled roles", C.gold);
  metric(slide, pptx, 3.75, 2.68, 2.9, "gfx1100", "AMD Radeon PRO W7900 class", C.neon);
  metric(slide, pptx, 6.85, 2.68, 2.9, "45.3 GB", "observed peak stack VRAM", C.electric);
  metric(slide, pptx, 9.95, 2.68, 2.68, "8,192", "judge context tokens", C.danger);
  panel(slide, pptx, 0.65, 4.22, 5.74, 2.05, C.neon);
  addText(slide, "WHY THIS FITS", 0.95, 4.48, 2.0, 0.28, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.neon });
  addText(slide, "• One shared judge service for all three roles\n• Small dedicated BGE pooling runner\n• Shortlist-only cross-encoder reranking\n• Evidence packet instead of full-workspace context", 0.95, 4.93, 4.85, 1.08, { fontSize: 15, color: C.white, valign: "top" });
  panel(slide, pptx, 6.65, 4.22, 5.98, 2.05, C.electric);
  addText(slide, "VERIFIED LOCAL ENDPOINTS", 6.95, 4.48, 2.8, 0.28, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.electric });
  addText(slide, "8000 / Qwen3-14B + ClaimCourt LoRA\n8001 / BGE-small pooling runner\n8503 / local ClaimCourt API\n8502 / private browser interface", 6.95, 4.93, 4.9, 1.08, { fontFace: "Consolas", fontSize: 14, color: C.white, valign: "top" });

  slide = baseSlide(pptx, "Measured evidence", 8);
  title(slide, "Live, no-fallback results", "The quality gate requires the complete local stack", "A component that fails or silently falls back causes the Radeon holdout to fail.");
  metric(slide, pptx, 0.65, 2.72, 2.85, "0.27 s", "first-token latency", C.neon);
  metric(slide, pptx, 3.7, 2.72, 2.85, "14.3", "generation tokens / second", C.electric);
  metric(slide, pptx, 6.75, 2.72, 2.85, "126.44 s", "complete three-role latency", C.gold);
  metric(slide, pptx, 9.8, 2.72, 2.83, "1,778", "completion tokens", C.danger);
  panel(slide, pptx, 0.65, 4.28, 11.98, 1.85, C.neon);
  addText(slide, "320 / 320", 1.0, 4.66, 2.45, 0.6, { fontFace: "Consolas", fontSize: 34, bold: true, color: C.neon });
  addText(slide, "frozen fuzzy-intent holdout", 1.0, 5.35, 2.65, 0.25, { fontSize: 12, color: C.gray });
  addText(slide, "100%", 4.25, 4.66, 1.55, 0.6, { fontFace: "Consolas", fontSize: 34, bold: true, color: C.electric });
  addText(slide, "Top-1 / coverage / no-match / clarification", 4.25, 5.35, 3.2, 0.25, { fontSize: 12, color: C.gray });
  addText(slide, "0", 8.25, 4.66, 0.8, 0.6, { fontFace: "Consolas", fontSize: 34, bold: true, color: C.danger });
  addText(slide, "unsafe wrong auto-selections", 8.25, 5.35, 2.35, 0.25, { fontSize: 12, color: C.gray });
  addText(slide, "LIVE", 11.0, 4.75, 1.0, 0.42, { fontFace: "Consolas", fontSize: 21, bold: true, color: C.gold, align: "center" });
  addText(slide, "Router + BGE + reranker", 10.35, 5.35, 1.95, 0.25, { fontSize: 11, color: C.gray, align: "center" });

  slide = baseSlide(pptx, "Demo", 9);
  title(slide, "Four-minute judge journey", "Show the dispute, the evidence, the permission gate and the GPU proof", "Use only the synthetic championship workspace during public recording.");
  const timeline = [
    ["0:00", "DISPUTE", "Sales promise vs signed contract", C.danger],
    ["0:20", "RADEON", "rocminfo / vLLM / local endpoints", C.neon],
    ["0:45", "INTENT", "Compile the vague claim", C.electric],
    ["1:10", "EVIDENCE", "Retrieve signed, draft and contradictory records", C.neon],
    ["1:45", "COURT", "Prosecute, defend and judge", C.gold],
    ["3:05", "APPROVE", "Permission-gated local brief", C.danger],
    ["3:30", "PROOF", "Latency, throughput, VRAM and 320/320", C.electric],
  ];
  timeline.forEach((item, i) => {
    const y = 2.7 + i * 0.56;
    addText(slide, item[0], 0.75, y, 0.68, 0.28, { fontFace: "Consolas", fontSize: 12, bold: true, color: item[3] });
    slide.addShape(pptx.ShapeType.line, { x: 1.52, y: y + 0.14, w: 0.52, h: 0, line: { color: item[3], width: 2 } });
    addText(slide, item[1], 2.22, y - 0.02, 1.15, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: item[3] });
    addText(slide, item[2], 3.55, y - 0.02, 4.65, 0.3, { fontSize: 14, bold: true });
  });
  panel(slide, pptx, 8.65, 2.7, 3.98, 3.88, C.neon);
  addText(slide, "RECORDING RULES", 8.98, 3.02, 2.5, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.neon });
  addText(slide, "Use synthetic files only\nWarm the model once\nShow local vLLM, never fallback\nHide keys, tokens and shell history\nDo not expose a real workspace publicly\nEnd on the measured evidence", 8.98, 3.52, 3.02, 2.3, { fontSize: 16, color: C.white, valign: "top" });

  slide = baseSlide(pptx, "Closing", 10);
  addText(slide, "CLAIMCOURT", 0.7, 1.18, 4.8, 0.38, { fontFace: "Consolas", fontSize: 15, bold: true, color: C.neon });
  addText(slide, "Private evidence\nbefore confident answers.", 0.7, 1.72, 9.3, 1.45, { fontSize: 42, bold: true, valign: "top" });
  addText(slide, "ClaimCourt understands fuzzy human memory, retrieves the right private records, exposes contradictions, and asks permission before it acts.", 0.72, 3.52, 8.6, 0.92, { fontSize: 21, color: C.gray, valign: "top" });
  panel(slide, pptx, 9.55, 1.45, 3.05, 3.78, C.gold);
  addText(slide, "WHY IT MATTERS", 9.85, 1.78, 2.25, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.gold });
  addText(slide, "LOCAL\nAUDITABLE\nCITED\nPRIVACY-GATED\nRADEON-OPTIMIZED", 9.85, 2.35, 2.2, 2.15, { fontFace: "Consolas", fontSize: 20, bold: true, color: C.white, valign: "top" });
  addText(slide, "TEAM ZI FEI YU  /  TRACK 2", 0.72, 6.65, 3.6, 0.3, { fontFace: "Consolas", fontSize: 12, bold: true, color: C.electric });

  await pptx.writeFile({ fileName: pptxPath });
}

function buildHtml() {
  const source = fs.readFileSync(path.join(submission, "PROJECT_DESCRIPTION.md"), "utf8");
  const imageData = fs.readFileSync(screenshot).toString("base64");
  const body = marked.parse(source);
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ClaimCourt Project Description</title>
<style>
  @page { size: A4; margin: 14mm 15mm 15mm; }
  * { box-sizing: border-box; }
  body { margin: 0; color: #111827; background: white; font-family: Arial, sans-serif; font-size: 10pt; line-height: 1.42; }
  main { max-width: 100%; }
  .cover { min-height: 255mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }
  .brand { color: #00a878; font: 700 12pt Consolas, monospace; letter-spacing: 1.5px; }
  .cover h1 { margin: 12px 0 6px; color: #111827; font-size: 30pt; line-height: 1.08; }
  .cover h2 { margin: 0 0 18px; color: #008fb3; font-size: 18pt; }
  .meta { color: #5b6475; font-weight: 600; margin-bottom: 18px; }
  .hero { width: 100%; border: 1px solid #d7dee8; border-radius: 6px; margin: 8px 0 14px; }
  .tagline { color: #5b6475; font-style: italic; text-align: center; }
  h1 { color: #00a878; font-size: 21pt; margin: 16px 0 7px; page-break-after: avoid; }
  h2 { color: #008fb3; font-size: 14.5pt; margin: 14px 0 6px; page-break-after: avoid; }
  h3 { color: #111827; font-size: 11.5pt; margin: 11px 0 4px; page-break-after: avoid; }
  p { margin: 0 0 7px; }
  ul, ol { margin: 3px 0 8px 20px; padding: 0; }
  li { margin: 0 0 4px; }
  table { width: 100%; border-collapse: collapse; margin: 10px 0 14px; page-break-inside: avoid; }
  th, td { border: 1px solid #d7dee8; padding: 7px 8px; vertical-align: top; }
  th { background: #dff5ef; text-align: left; }
  pre { white-space: pre-wrap; background: #111827; color: #f5f7fa; border-left: 4px solid #00a878; padding: 10px 12px; font: 8.5pt Consolas, monospace; page-break-inside: avoid; }
  code { font-family: Consolas, monospace; }
  blockquote { margin: 10px 0; padding: 8px 12px; border-left: 4px solid #ffb000; background: #f3f6fa; }
  h2 + table, h3 + table { page-break-before: avoid; }
  .footer-note { margin-top: 18px; color: #5b6475; font-size: 8.5pt; }
</style>
</head>
<body>
<main>
  <section class="cover">
    <div class="brand">CLAIMCOURT / TEAM ZI FEI YU</div>
    <h1>ClaimCourt</h1>
    <h2>A Private Local AI Evidence Court</h2>
    <div class="meta">AMD AI DevMaster Hackathon 2026<br>Track 2 - Development & Local Deployment of Private AI Agents</div>
    <img class="hero" src="data:image/png;base64,${imageData}" alt="ClaimCourt English interface">
    <div class="tagline">Private documents stay local. Evidence is retrieved, challenged, cited, and exported only after approval.</div>
  </section>
  ${body.replace(/^<h1[^>]*>.*?<\/h1>/s, "")}
  <div class="footer-note">ClaimCourt / Team Zi Fei Yu / AMD AI DevMaster Hackathon 2026 / Track 2</div>
</main>
</body>
</html>`;
  fs.writeFileSync(htmlPath, html, "utf8");
}

(async () => {
  fs.mkdirSync(submission, { recursive: true });
  await buildDocx();
  await buildPptx();
  buildHtml();
  console.log(docxPath);
  console.log(pptxPath);
  console.log(htmlPath);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
