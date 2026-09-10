/* ──────────────────────────────────────────────────────────────────────────
 * MKO MoE Graph — pure layout + inline SVG renderer for the Agent DAG
 * canvas inside the chat bubble.
 *
 * UMD-style: `window.MKOGraph` in browsers, `module.exports` in Node.
 *
 * Split into two pure functions so the layout algorithm and the markup
 * can each be unit-tested in node:test without a real DOM:
 *
 *   computeMoEGraphLayout(debugData) → layout | null
 *     Reads the MoE debug payload shape that appendMoeDebug in app.js
 *     already consumes:
 *       debugData = {
 *         details: [ { provider, time_ms, tokens, weight, response } ],
 *         weights:  { [provider]: number },
 *         gate_input_tokens: number,
 *         gate_output_tokens: number,
 *       }
 *     Returns `null` when details is empty / missing — caller skips the
 *     DAG entirely (per design: no placeholder for the empty case).
 *     Otherwise returns:
 *       { width, height, expertCount, nodes[], edges[] }
 *     Nodes are ordered: [gate, expert_0, expert_1, ...]
 *     Edges are ordered: gate→expert_0, gate→expert_1, ...
 *     With a single expert, the expert X equals the gate X (single
 *     vertical edge — the cleanest "N=1" representation).
 *
 *   renderMoEGraphSVG(layout) → string
 *     Pure SVG string. Empty string for null/empty/invalid layout.
 *     Contains:
 *       <svg role="img" aria-label="MoE routing: N experts"...>
 *       <title> ... </title>
 *       <defs><marker id="mko-edge-arrow"> ... </defs>
 *       <g class="mko-dag-edge"> ... one per edge ...
 *       <g class="mko-dag-node mko-dag-node-gate|expert"> ... per node ...
 *
 * The DOM wiring lives in app.js's renderMoEDAG; this file is markup-only.
 * ────────────────────────────────────────────────────────────────────────── */

(function (factory) {
  "use strict";
  var exported = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
  if (typeof window !== "undefined") {
    window.MKOGraph = exported;
  }
})(function () {
  "use strict";

  // ─── Geometry constants (all in SVG userspace units) ───────────────
  var NODE_R         = 22;
  var GATE_Y         = 30;
  var EXPERT_Y       = 130;
  var PADDING_X      = 40;
  var MIN_SPACING    = 110;
  var PANEL_HEIGHT   = 200;
  var MIN_WIDTH      = 380;

  // Distinct, color-blind-friendly pastels keyed by an index 0..5.
  // Order is arbitrary but stable across the codebase via djb2 hash.
  var PALETTE = [
    "#58a6ff",  // primary blue    (groq, openai)
    "#a371f7",  // purple          (anthropic, huggingface)
    "#3fb950",  // green           (ollama-local)
    "#d29922",  // amber           (custom)
    "#f85149",  // red
    "#ff7b72",  // coral
  ];

  // ─── Helpers ───────────────────────────────────────────────────────

  // djb2 over provider.toLowerCase() so the same name always maps to
  // the same color regardless of render order. Testable: given name →
  // same color across calls.
  function colorForProvider(name) {
    var s = String(name == null ? "" : name).toLowerCase();
    var hash = 5381;
    for (var i = 0; i < s.length; i++) {
      hash = ((hash << 5) + hash) + s.charCodeAt(i);
      hash = hash | 0;  // keep within 32-bit (signed)
    }
    var idx = Math.abs(hash) % PALETTE.length;
    return PALETTE[idx];
  }

  // Build an edge-annotation label of the form:
  //   "1x"                  — weight only
  //   "1x · 220ms"          — weight + time
  //   "1x · 332 tokens"     — weight + tokens
  //   "1x · 220ms · 332 tokens"  — all three
  // Each field is optional; the field that IS present determines
  // the separator presence. Small Unicode middle-dot (U+00B7)
  // between segments so the pill stays compact.
  function buildEdgeAnnotation(e) {
    var parts = [formatWeight(e.weight)];
    if (e.time_ms != null) parts.push(e.time_ms + "ms");
    if (e.tokens != null) parts.push(e.tokens + " tokens");
    return parts.join(" \u00B7 ");
  }

  // Format weight to a compact label: 1.0 → "1x", 0.5 → "0.5x", 2.7 → "2.7x".
  function formatWeight(w) {
    if (w == null || w === "") return "1x";
    var n = Number(w);
    if (!isFinite(n)) return String(w);
    if (Math.abs(n - Math.round(n)) < 1e-6) return Math.round(n) + "x";
    return n.toFixed(1) + "x";
  }

  // Minimal XML escape so provider names with `<`/`&`/`"` stay well-formed.
  // Currently all KNOWN_PROVIDERS are safe ASCII; this is defensive.
  function escapeXml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&apos;");
  }

  // ─── Pure: layout ──────────────────────────────────────────────────

  function computeMoEGraphLayout(debugData) {
    var d = debugData && typeof debugData === "object" ? debugData : {};
    var rawDetails = Array.isArray(d.details) ? d.details : [];
    var weights = (d.weights && typeof d.weights === "object") ? d.weights : {};
    var N = rawDetails.length;
    if (N === 0) return null;  // design: skip DAG entirely on empty input

    var width = Math.max(MIN_WIDTH, N * MIN_SPACING + PADDING_X * 2);
    var gateX = width / 2;

    var nodes = [];

    // Gate: always at top-center.
    nodes.push({
      id: "gate",
      kind: "gate",
      label: "Gate",
      sublabel: "MoE router",
      x: gateX,
      y: GATE_Y,
      r: NODE_R,
      color: PALETTE[0],  // primary blue
    });

    // Experts: evenly distributed along a single row (or single column
    // for N=1). X positions are deterministic for a given N.
    for (var i = 0; i < N; i++) {
      var detail = rawDetails[i] || {};
      var provider = String(detail.provider != null ? detail.provider : "expert-" + i);
      var wRaw = weights[provider] != null ? weights[provider] : detail.weight;
      var weight = (wRaw == null ? 1.0 : Number(wRaw)) || 1.0;
      var x = N === 1
        ? gateX
        : (PADDING_X + (i / (N - 1)) * (width - PADDING_X * 2));
      nodes.push({
        id: "expert-" + i,
        kind: "expert",
        label: provider,
        sublabel: detail.time_ms != null ? (detail.time_ms + "ms") : "",
        x: x,
        y: EXPERT_Y,
        r: NODE_R,
        color: colorForProvider(provider),
        provider: provider,
        weight: weight,
        tokens: detail.tokens,
      });
    }

    // Edges: gate → each expert, in display order.
    // Each edge carries the weight plus optional tokens/time_ms so the
    // SVG renderer can build a rich annotation label.
    var edges = [];
    for (var j = 0; j < N; j++) {
      var detail = rawDetails[j] || {};
      edges.push({
        from: "gate",
        to: "expert-" + j,
        weight: nodes[j + 1].weight,
        tokens: detail.tokens != null ? Number(detail.tokens) : undefined,
        time_ms: detail.time_ms != null ? Number(detail.time_ms) : undefined,
      });
    }

    return { width: width, height: PANEL_HEIGHT, expertCount: N, nodes: nodes, edges: edges };
  }

  // ─── Pure: SVG renderer ───────────────────────────────────────────

  function renderMoEGraphSVG(layout) {
    // Defensive: refuse to emit broken SVG. Anything null/empty returns "".
    if (!layout || !Array.isArray(layout.nodes) || layout.nodes.length < 2 ||
        !Array.isArray(layout.edges) || layout.edges.length === 0) {
      return "";
    }
    var W = layout.width;
    var H = layout.height;
    var N = layout.expertCount;

    // Defs — single shared arrow marker for all edges.
    // Build a screen-reader-friendly description listing each
    // expert's provider, weight, and time. SR users hear this
    // after the <title>. Cap at first 8 experts so large MoE
    // runs don't produce a runaway announcement.
    var nodesList = layout.nodes.slice(1);
    var visible = nodesList.slice(0, 8);
    var descClauses = visible.map(function (n) {
      // Escape provider + sublabel + weight so a stray `&`/`<`
      // in a backend payload can't corrupt the SVG. Same
      // escapeXml coverage is used elsewhere on labels; this
      // brings the <desc> path into the same XML-safe contract.
      var w = escapeXml(formatWeight(n.weight));
      var t = escapeXml(n.sublabel || '');
      var p = escapeXml(n.provider || 'expert');
      return p + ' weight ' + w + (t ? ' ' + t : '');
    });
    if (nodesList.length > 8) {
      descClauses.push('and ' + (nodesList.length - 8) + ' more');
    }
    var descText = 'MoE routing for ' + N + ' expert'
      + (N === 1 ? '' : 's') + '. ' + descClauses.join('; ');

    var defs =
      '<defs>' +
        '<marker id="mko-edge-arrow" viewBox="0 0 10 10" refX="9" refY="5"' +
          ' markerWidth="6" markerHeight="6" orient="auto-start-reverse">' +
          '<path d="M 0 0 L 10 5 L 0 10 z" fill="#8b949e"/>' +
        '</marker>' +
      '</defs>';

    // Edges — straight lines from gate-bottom to expert-top, with a
    // small SVG <text> weight label at the midpoint resting on a
    // surface-colored pill so it stays legible over any background.
    var byId = {};
    layout.nodes.forEach(function (n) { byId[n.id] = n; });
    var edgeParts = layout.edges.map(function (e, idx) {
      var from = byId[e.from];
      var to = byId[e.to];
      if (!from || !to) return "";
      // Line from gate's bottom edge to the expert's top edge.
      var x1 = from.x;
      var y1 = from.y + from.r;
      var x2 = to.x;
      var y2 = to.y - to.r;
      var mx = (x1 + x2) / 2;
      var my = (y1 + y2) / 2;
      var label = buildEdgeAnnotation(e);
      // Estimate pill width: ~7px per char + 8px horizontal padding.
      var pillW = Math.max(20, label.length * 7 + 8);
      var pillH = 14;
      var pillX = mx - pillW / 2;
      var pillY = my - pillH / 2;
      return (
        '<g class="mko-dag-edge" data-idx="' + idx + '">' +
          '<path class="mko-dag-edge-line" d="M ' + x1 + ' ' + y1 +
            ' L ' + x2 + ' ' + y2 + '" marker-end="url(#mko-edge-arrow)"/>' +
          '<rect class="mko-dag-edge-label-bg" x="' + pillX + '" y="' + pillY +
            '" width="' + pillW + '" height="' + pillH + '" rx="3"/>' +
          '<text class="mko-dag-edge-label" x="' + mx + '" y="' + (my + 4) +
            '" text-anchor="middle">' + escapeXml(label) + '</text>' +
        '</g>'
      );
    }).join("");

    // Nodes — gate + each expert as <g> with circle + label.
    var nodeParts = layout.nodes.map(function (n) {
      var subLabel = n.sublabel
        ? ('<text class="mko-dag-sublabel" x="' + n.x + '" y="' + (n.y + n.r + 16) +
            '" text-anchor="middle">' + escapeXml(n.sublabel) + '</text>')
        : "";
      return (
        '<g class="mko-dag-node mko-dag-node-' + n.kind + '"' +
          ' data-id="' + escapeXml(n.id) + '"' +
          (n.provider ? (' data-provider="' + escapeXml(n.provider) + '"') : '') + '>' +
          '<circle class="mko-dag-circle" cx="' + n.x + '" cy="' + n.y +
            '" r="' + n.r + '" fill="' + n.color + '"/>' +
          '<text class="mko-dag-label" x="' + n.x + '" y="' + (n.y + 4) +
            '" text-anchor="middle">' + escapeXml(n.label) + '</text>' +
          subLabel +
        '</g>'
      );
    }).join("");

    return (
      '<svg class="moe-dag" role="img"' +
        ' aria-label="MoE routing: ' + N + ' expert' + (N === 1 ? "" : "s") + '"' +
        ' viewBox="0 0 ' + W + ' ' + H + '"' +
        ' width="' + W + '" height="' + H + '"' +
        ' preserveAspectRatio="xMidYMid meet">' +
        '<title>MoE routing for ' + N + ' expert' + (N === 1 ? "" : "s") +
          ' via gate</title>' +
        '<desc>' + descText + '</desc>' +
        defs +
        edgeParts +
        nodeParts +
      '</svg>'
    );
  }

  return {
    computeMoEGraphLayout: computeMoEGraphLayout,
    renderMoEGraphSVG: renderMoEGraphSVG,
    // Exposed for tests / future extension.
    colorForProvider: colorForProvider,
    formatWeight: formatWeight,
    buildEdgeAnnotation: buildEdgeAnnotation,
    // Useful for downstream tools that want to live-link to constants.
    constants: {
      NODE_R: NODE_R,
      GATE_Y: GATE_Y,
      EXPERT_Y: EXPERT_Y,
      PADDING_X: PADDING_X,
      MIN_WIDTH: MIN_WIDTH,
      MIN_SPACING: MIN_SPACING,
      PANEL_HEIGHT: PANEL_HEIGHT,
      PALETTE: PALETTE,
    },
  };
});
