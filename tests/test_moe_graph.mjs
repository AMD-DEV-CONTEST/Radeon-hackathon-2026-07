// ───────────────────────────────────────────────────────────────────────
// MKOGraph tests — pure layout + inline-SVG renderer for the Agent DAG
// canvas that injects inside the chat bubble on MoE responses.
//
// Run:   node --test tests/test_moe_graph.mjs
//
// Pure-Node: NO jsdom. We require() the UMD file the same way the
// browser loads it (window.MKOGraph), so the same source is exercised.
// ───────────────────────────────────────────────────────────────────────

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const __dirname = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const MKOGraph = require("../mko/webui/static/js/moe-graph.js");

// ─── Helpers ─────────────────────────────────────────────────────────

function makeDetails(n, opts) {
  opts = opts || {};
  const names = ["groq", "ollama", "openai", "anthropic", "huggingface"];
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push({
      provider: opts.provider ? opts.provider(i) : names[i % names.length],
      weight: opts.weight ? opts.weight(i) : 1.0,
      time_ms: opts.timeMs ? opts.timeMs(i) : 200 + i * 80,
      tokens: 100 + i * 50,
      response: "expert " + i + " says hi",
    });
  }
  return out;
}

// ─── Public surface ──────────────────────────────────────────────────

test("MKOGraph exports the public surface used by app.js", () => {
  assert.equal(typeof MKOGraph.computeMoEGraphLayout, "function");
  assert.equal(typeof MKOGraph.renderMoEGraphSVG, "function");
  assert.equal(typeof MKOGraph.colorForProvider, "function");
  assert.equal(typeof MKOGraph.formatWeight, "function");
});

// ─── Empty / null / malformed input ──────────────────────────────────

test("computeMoEGraphLayout: null / undefined / {} / 0 experts → null", () => {
  assert.equal(MKOGraph.computeMoEGraphLayout(null), null);
  assert.equal(MKOGraph.computeMoEGraphLayout(undefined), null);
  assert.equal(MKOGraph.computeMoEGraphLayout({}), null);
  assert.equal(MKOGraph.computeMoEGraphLayout({ details: [] }), null);
  // Non-array details → null. Defensive against backend shape drift.
  assert.equal(
    MKOGraph.computeMoEGraphLayout({ details: "not-an-array" }),
    null
  );
  assert.equal(
    MKOGraph.computeMoEGraphLayout({ details: { 0: "weird" } }),
    null
  );
});

test("renderMoEGraphSVG: invalid layout returns empty string", () => {
  assert.equal(MKOGraph.renderMoEGraphSVG(null), "");
  assert.equal(MKOGraph.renderMoEGraphSVG(undefined), "");
  assert.equal(MKOGraph.renderMoEGraphSVG({}), "");
  assert.equal(MKOGraph.renderMoEGraphSVG({ nodes: [] }), "");
  // At least 2 nodes required (gate + 1 expert).
  assert.equal(MKOGraph.renderMoEGraphSVG({ nodes: [{}], edges: [] }), "");
  assert.equal(
    MKOGraph.renderMoEGraphSVG({ nodes: [{}, {}], edges: [] }),
    ""
  );
});

// ─── Geometry: N=1 ──────────────────────────────────────────────────

test("computeMoEGraphLayout: N=1 → 2 nodes 1 edge, single vertical line", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "groq", weight: 1.0, time_ms: 220 }],
    weights: { groq: 1.0 },
  });
  assert.ok(layout, "non-null");
  assert.equal(layout.expertCount, 1);
  assert.equal(layout.nodes.length, 2);
  assert.equal(layout.edges.length, 1);
  assert.equal(layout.nodes[0].id, "gate");
  assert.equal(layout.nodes[0].kind, "gate");
  assert.equal(layout.nodes[1].kind, "expert");
  assert.equal(layout.nodes[1].provider, "groq");
  // Single expert: shares the gate X column → straight vertical edge.
  assert.equal(layout.nodes[0].x, layout.nodes[1].x);
  // Y separation: gate above, expert below.
  assert.ok(layout.nodes[0].y < layout.nodes[1].y);
});

test("computeMoEGraphLayout: N=1 reads weight from weights map first, detail second", () => {
  // detail.weight = 2.0, weights override = 3.5
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "groq", weight: 2.0 }],
    weights: { groq: 3.5 },
  });
  assert.equal(layout.nodes[1].weight, 3.5);
  assert.equal(layout.edges[0].weight, 3.5);

  // detail.weight set, weights map missing → uses detail
  const layout2 = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "groq", weight: 4.25 }],
  });
  assert.equal(layout2.nodes[1].weight, 4.25);
});

// ─── Geometry: N=4 ──────────────────────────────────────────────────

test("computeMoEGraphLayout: N=4 → 5 nodes 4 edges, ordered", () => {
  const details = makeDetails(4);
  const layout = MKOGraph.computeMoEGraphLayout({ details });
  assert.equal(layout.expertCount, 4);
  assert.equal(layout.nodes.length, 5);
  assert.equal(layout.edges.length, 4);
  layout.edges.forEach((e, i) => {
    assert.equal(e.from, "gate");
    assert.equal(e.to, "expert-" + i);
  });
  // Input order preserved in nodes.
  layout.nodes.slice(1).forEach((n, i) => {
    assert.equal(n.provider, details[i].provider);
  });
});

test("computeMoEGraphLayout: expert X-positions evenly distributed", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: makeDetails(5),
  });
  const xs = layout.nodes.slice(1).map((n) => n.x);
  // Monotonic.
  for (let i = 1; i < xs.length; i++) {
    assert.ok(xs[i - 1] < xs[i]);
  }
  // Equal intervals between adjacent experts.
  for (let i = 2; i < xs.length; i++) {
    const d1 = xs[i - 1] - xs[i - 2];
    const d2 = xs[i] - xs[i - 1];
    assert.ok(
      Math.abs(d1 - d2) < 1e-6,
      "even spacing between experts i-2, i-1, i (d1=" + d1 + " d2=" + d2 + ")"
    );
  }
});

test("computeMoEGraphLayout: width scales with N and floors at MIN_WIDTH", () => {
  const lay1 = MKOGraph.computeMoEGraphLayout({ details: makeDetails(1) });
  const lay5 = MKOGraph.computeMoEGraphLayout({ details: makeDetails(5) });
  assert.ok(lay5.width > lay1.width, "5-expert wider than 1-expert");
  assert.ok(lay1.width >= 380, "min-width floor");
  assert.ok(
    lay5.width >= 380 &&
      lay5.width >= 5 * 110 + 2 * 40,
    "5-expert width respects padding+spacing formula"
  );
});

// ─── colorForProvider ────────────────────────────────────────────────

test("colorForProvider is deterministic for same input", () => {
  assert.equal(MKOGraph.colorForProvider("groq"), MKOGraph.colorForProvider("groq"));
  assert.equal(
    MKOGraph.colorForProvider("Anthropic"),
    MKOGraph.colorForProvider("anthropic")
  );
  // Hashes to one of the 6 palette entries (always 6-digit hex).
  const c = MKOGraph.colorForProvider("groq");
  assert.match(c, /^#[0-9a-fA-F]{6}$/);
  assert.ok(MKOGraph.constants.PALETTE.includes(c));
});

test("colorForProvider falls back to a hex for empty / null input", () => {
  // The hash of "" is deterministic (5381), so still maps cleanly.
  const c1 = MKOGraph.colorForProvider("");
  const c2 = MKOGraph.colorForProvider(null);
  const c3 = MKOGraph.colorForProvider(undefined);
  assert.match(c1, /^#[0-9a-fA-F]{6}$/);
  assert.match(c2, /^#[0-9a-fA-F]{6}$/);
  assert.match(c3, /^#[0-9a-fA-F]{6}$/);
});

// ─── formatWeight ────────────────────────────────────────────────────

test("formatWeight: compact 'Nx' labels for common inputs", () => {
  assert.equal(MKOGraph.formatWeight(1), "1x");
  assert.equal(MKOGraph.formatWeight(1.0), "1x");
  assert.equal(MKOGraph.formatWeight(2), "2x");
  assert.equal(MKOGraph.formatWeight(2.5), "2.5x");
  assert.equal(MKOGraph.formatWeight(0), "0x");
  assert.equal(MKOGraph.formatWeight(null), "1x");
  assert.equal(MKOGraph.formatWeight(undefined), "1x");
  assert.equal(MKOGraph.formatWeight(""), "1x");
  assert.equal(MKOGraph.formatWeight("2.5"), "2.5x");
});

// ─── renderMoEGraphSVG smoke ────────────────────────────────────────

test("renderMoEGraphSVG: starts with <svg and contains structural pieces", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: makeDetails(3),
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  assert.equal(typeof svg, "string");
  assert.ok(svg.indexOf("<svg") === 0, "starts with <svg");
  assert.match(svg, /role="img"/);
  assert.match(svg, /aria-label="MoE routing: 3 experts"/);
  assert.match(svg, /<title>MoE routing for 3 experts via gate<\/title>/);
  assert.match(svg, /<defs>/);
  assert.match(svg, /<marker\b[^>]*id="mko-edge-arrow"/);
  assert.match(svg, /viewBox="0 0 \d+(?:\.\d+)? \d+(?:\.\d+)?"/);
});

test("renderMoEGraphSVG: counts paths and text per edge / node match", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: makeDetails(3),
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  // paths: N edges + 1 marker arrow path = 4
  const pathCount = (svg.match(/<path\b/g) || []).length;
  assert.equal(pathCount, 4, "3 edge paths + 1 marker arrow path");
  // rects: N label-bg pills = 3
  const rectCount = (svg.match(/<rect\b/g) || []).length;
  assert.equal(rectCount, 3, "3 edge-label background pills");
  // circles: N+1 (gate + N experts)
  const circleCount = (svg.match(/<circle\b/g) || []).length;
  assert.equal(circleCount, 4, "1 gate + 3 expert circles");
  // texts: N edge labels + N+1 node labels (no sublabel on gate w/o time_ms) = 2N+1
  // Gate has sublabel "MoE router"; experts each have sublabel "<time>ms".
  // Total <text> elements = N edge labels + (N+1) node labels + (N+1) sublabels = 2N+2.
  const textCount = (svg.match(/<text\b/g) || []).length;
  assert.equal(
    textCount, layout.edges.length + 2 * layout.nodes.length,
    "edges + node labels + sublabels: actual=" + textCount +
    " expected=" + (layout.edges.length + 2 * layout.nodes.length));
});

test("renderMoEGraphSVG: provider labels and gate label appear", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [
      { provider: "groq",   weight: 1.0, time_ms: 220 },
      { provider: "ollama", weight: 2.0, time_ms: 880 },
      { provider: "openai", weight: 1.0, time_ms: 410 },
    ],
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  assert.match(svg, />Gate</);
  assert.match(svg, />MoE router</);    // gate sublabel
  assert.match(svg, />groq</);
  assert.match(svg, />ollama</);
  assert.match(svg, />openai</);
});

test("renderMoEGraphSVG: weight labels appear with the right text", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [
      { provider: "a", weight: 1 },
      { provider: "b", weight: 2.5 },
      { provider: "c", weight: 0.5 },
    ],
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  assert.match(svg, />1x</);
  assert.match(svg, />2\.5x</);
  assert.match(svg, />0\.5x</);
});

// ─── Edge annotations ────────────────────────────────────────────────
// Replace weight-only labels with rich annotations carrying
//   weight · time_ms · tokens
// when the source detail includes them. This is the visual differentiator
// for the Radeon Hackathon Track‑2 MoE debug panel.

test("buildEdgeAnnotation: weight‑only falls back to formatWeight", () => {
  const e = { weight: 1.0 };
  assert.equal(MKOGraph.buildEdgeAnnotation(e), "1x");
  assert.equal(MKOGraph.buildEdgeAnnotation({ weight: 2.5 }), "2.5x");
  assert.equal(MKOGraph.buildEdgeAnnotation({ weight: 0 }), "0x");
});

test("buildEdgeAnnotation: includes · separator when time_ms present", () => {
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 1, time_ms: 220 }),
    "1x · 220ms"
  );
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 2, time_ms: 880 }),
    "2x · 880ms"
  );
});

test("buildEdgeAnnotation: includes · separator when tokens present", () => {
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 1, tokens: 332 }),
    "1x · 332 tokens"
  );
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 2.5, tokens: 150 }),
    "2.5x · 150 tokens"
  );
});

test("buildEdgeAnnotation: all three fields ·‑separated", () => {
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 1, time_ms: 220, tokens: 332 }),
    "1x · 220ms · 332 tokens"
  );
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 2, time_ms: 880, tokens: 999 }),
    "2x · 880ms · 999 tokens"
  );
});

test("buildEdgeAnnotation: tokens field is absence‑safe (undefined/null/missing)", () => {
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 1, time_ms: 100 }),
    "1x · 100ms"
  );
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 1, tokens: null, time_ms: 100 }),
    "1x · 100ms"
  );
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 1, tokens: undefined, time_ms: 100 }),
    "1x · 100ms"
  );
});

test("buildEdgeAnnotation: time_ms field is absence‑safe", () => {
  assert.equal(
    MKOGraph.buildEdgeAnnotation({ weight: 1, tokens: 100 }),
    "1x · 100 tokens"
  );
});

test("computeMoEGraphLayout: edge carries tokens and time_ms from detail", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [
      { provider: "groq",   weight: 1, time_ms: 220, tokens: 332 },
      { provider: "ollama", weight: 2, time_ms: 880, tokens: 150 },
    ],
  });
  assert.equal(layout.edges[0].tokens, 332);
  assert.equal(layout.edges[0].time_ms, 220);
  assert.equal(layout.edges[1].tokens, 150);
  assert.equal(layout.edges[1].time_ms, 880);
});

test("computeMoEGraphLayout: edge tokens/time_ms undefined when absent from detail", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "groq", weight: 1 }],  // no tokens, no time_ms
  });
  assert.equal(layout.edges[0].tokens, undefined);
  assert.equal(layout.edges[0].time_ms, undefined);
});

test("renderMoEGraphSVG: edge annotation renders weight·time·tokens in SVG text", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [
      { provider: "a", weight: 1, time_ms: 220, tokens: 332 },
      { provider: "b", weight: 2, time_ms: 880, tokens: 150 },
    ],
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  assert.match(svg, />1x · 220ms · 332 tokens</);
  assert.match(svg, />2x · 880ms · 150 tokens</);
});

test("renderMoEGraphSVG: edge annotation weight‑only when time/tokens absent", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "b", weight: 2.5 }],  // no time_ms, no tokens
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  assert.match(svg, />2\.5x</);
  // Must NOT contain the middle-dot separator — weight only.
  assert.equal(svg.indexOf("\u00B7"), -1,
    "no separator when only weight is present");
});

test("renderMoEGraphSVG: edge annotation weight + time (no tokens)", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "c", weight: 1, time_ms: 410 }],  // no tokens
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  assert.match(svg, />1x · 410ms</);
  assert.equal(svg.indexOf("tokens"), -1, "no 'tokens' suffix when absent");
});

test("renderMoEGraphSVG: edge annotation weight + tokens (no time_ms)", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "d", weight: 0.5, tokens: 150 }],  // no time_ms
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  assert.match(svg, />0\.5x · 150 tokens</);
  assert.equal(svg.indexOf("ms"), -1, "no 'ms' suffix when absent");
});

test("renderMoEGraphSVG: edge annotation XML‑safe with · separator in pill", () => {
  // Ensure the middle-dot character survives SVG pill rendering.
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "e", weight: 1, time_ms: 200, tokens: 400 }],
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  // The pill width must account for the full annotation string.
  assert.match(svg, /1x · 200ms · 400 tokens/);
  // Escaped form (XML-safe): the · is a plain Unicode char, no escaping needed.
  assert.ok(svg.indexOf("1x · 200ms · 400 tokens") !== -1);
});

test("renderMoEGraphSVG: provider name with XML-unsafe chars is escaped", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [{ provider: "weird&<>\"name", weight: 1 }],
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  // The literal XML metacharacters must be escaped.
  assert.match(svg, /weird&amp;&lt;&gt;&quot;name/);
  // Must NOT contain raw '<' or '>' inside a text node (would break SVG).
  assert.ok(!/>weird&<>/.test(svg), "no raw XML metachars in output");
});

test("renderMoEGraphSVG: emits data-id on nodes and edges for testability", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: makeDetails(2),
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  assert.match(svg, /data-id="gate"/);
  assert.match(svg, /data-id="expert-0"/);
  assert.match(svg, /data-id="expert-1"/);
  assert.match(svg, /<g class="mko-dag-edge" data-idx="0">| data-idx="0">/);
  assert.match(svg, /<g class="mko-dag-edge" data-idx="1">| data-idx="1">/);
  assert.match(svg, /data-provider="groq"/);
  assert.match(svg, /data-provider="ollama"/);
});

test("renderMoEGraphSVG: aria-label pluralization is correct", () => {
  const lay1 = MKOGraph.computeMoEGraphLayout({ details: makeDetails(1) });
  const lay4 = MKOGraph.computeMoEGraphLayout({ details: makeDetails(4) });
  assert.match(
    MKOGraph.renderMoEGraphSVG(lay1),
    /aria-label="MoE routing: 1 expert"/
  );
  assert.match(
    MKOGraph.renderMoEGraphSVG(lay4),
    /aria-label="MoE routing: 4 experts"/
  );
});

// ─── <desc> XML safety ──────────────────────────────────────────────
// Round-3 reviewer caught this: descText concatenates provider + sublabel
// labels without escapeXml, so a backend-side name like 'evil<script>'
// would corrupt the rendered <desc> element. The visible label IS
// escaped; this regression pins that the desc path has the same
// XML-safe contract.

test("renderMoEGraphSVG: <desc> body is XML-safe (no raw metachars)", () => {
  const layout = MKOGraph.computeMoEGraphLayout({
    details: [
      // Each provider carries at least one metachar to exercise the
      // <desc> escape path.
      { provider: "evil<script>",       weight: 1, time_ms: 100 },
      { provider: "weird&name",        weight: 2, time_ms: 200 },
      { provider: 'q"uote',             weight: 3, time_ms: 300 },
    ],
  });
  const svg = MKOGraph.renderMoEGraphSVG(layout);
  // Locate the <desc> body via a non-greedy capture (no '<' inside until </desc>).
  const m = svg.match(/<desc>([^<]*)<\/desc>/);
  assert.ok(m, "<desc> element must be present and non-empty");
  const inner = m[1];
  // No raw metachars inside the desc body.
  assert.equal(inner.indexOf("<"),  -1, "raw '<' in <desc> body would corrupt the SVG");
  assert.equal(inner.indexOf(">"),  -1, "raw '>' in <desc> body would corrupt the SVG");
  // If an '&' is present it must be a valid entity reference.
  for (let i = 0; i < inner.length; i++) {
    if (inner.charAt(i) === "&") {
      const tail = inner.slice(i, i + 8);
      assert.match(
        tail, /^&(amp|lt|gt|quot|apos);/,
        "raw '&' in <desc> body must be an entity reference: " + tail,
      );
    }
  }
  // The escaped provider names appear in the desc body.
  assert.match(inner, /evil&lt;script&gt;/,
    "<desc> should contain the escaped form `evil&lt;script&gt;`");
  assert.match(inner, /weird&amp;name/,
    "<desc> should contain the escaped form `weird&amp;name`");
});

test("MKOGraph.renderMoEGraphSVG: desc source applies escapeXml on provider+sublabel (drift pin)", () => {
  // Pure-meta pin: the desc builder must reach for escapeXml. If a
  // future refactor forgets to escape, this assertion fails loudly.
  // We resolve the path against THIS test module's directory (via
  // import.meta.url → fileURLToPath → dirname) so the assertion
  // stays correct regardless of process.cwd(). fs.readFileSync
  // resolves paths against cwd, NOT a require URL — using a plain
  // `"../moko/..."` literal here would break if the runner is invoked
  // from anywhere other than the project root.
  const srcPath = resolve(
    __dirname,
    "..",
    "mko",
    "webui",
    "static",
    "js",
    "moe-graph.js",
  );
  const src = readFileSync(srcPath, "utf8");
  // Find the descClauses.map body and verify escapeXml is called
  // inside it on provider/sublabel/weight.
  const idx = src.indexOf("var descClauses = visible.map");
  assert.notEqual(idx, -1, "descClauses.map present in source");
  // Take a reasonable window after the anchor.
  const slice = src.slice(idx, idx + 800);
  assert.match(slice, /escapeXml\(\s*n\.provider/, "provider must be escapeXml'd");
  assert.match(slice, /escapeXml\(\s*n\.sublabel/, "sublabel must be escapeXml'd");
  assert.match(slice, /escapeXml\(\s*formatWeight/, "weight must be escapeXml'd");
});
