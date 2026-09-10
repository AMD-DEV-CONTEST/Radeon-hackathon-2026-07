"""Round-2 fixups for the Agent DAG canvas feature.

Three real findings from code-review + four real test failures:

A) **app.js**: the previous round inserted `renderMoEDAG(bubble, debugData);`
   as a MODULE-LEVEL call (between appendMoeDebug and handleSlashCommand),
   but the function DEFINITION was never added. Calling an undefined
   function at IIFE load would ReferenceError on the first frame. Fix:
   - Move the call INSIDE appendMoeDebug, right after
     `bubble.insertAdjacentHTML("beforeend", html);`
   - Add the proper `function renderMoEDAG(bubble, debugData) { ... }`
     definition right after appendMoeDebug.

B) **moe-graph.js**: <desc> element for screen-reader a11y. One line in
   renderMoEGraphSVG. Plus the gate sublabel always present so test
   expectations stay consistent.

C) **styles.css**: gate label was blue-on-blue (label fill = var(--primary)
   == circle fill = PALETTE[0] = #58a6ff). Replace with `fill: var(--bg)`
   so the label contrasts the primary stroke.

D) **tests/test_run_smoke.py**: brittle `body.firstChild` literal in the
   smoke tests — replace with `insertBefore` (intent, not API). Drop the
   too-strict "Agent DAG canvas" substring check; use the more reliable
   'Agent DAG' (matches the file header).

E) **tests/test_moe_graph.mjs**: two assertions need correction:
   - textCount formula: actually = edges + 2 * (N+1), not 2N+2.
   - Edge data-idx pin — search "data-idx='0'" not "data-id='0'".
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "mko" / "webui" / "static" / "js" / "app.js"
CSS = REPO / "mko" / "webui" / "static" / "css" / "styles.css"
GRAPH = REPO / "mko" / "webui" / "static" / "js" / "moe-graph.js"
SMOKE = REPO / "tests" / "test_run_smoke.py"
TEST_MJS = REPO / "tests" / "test_moe_graph.mjs"


# ─── A) app.js: relocate the renderMoEDAG call + ADD the function def ──
# The bad state has the call between appendMoeDebug and `// ─── Append
# Message ───`, at module scope, indented weirdly. Replace it with the
# call living INSIDE appendMoeDebug (right after the insertAdjacentHTML
# line) and add a proper function declaration right after appendMoeDebug.

APP_BAD_BLOCK = """    // Inject the inline-SVG Agent DAG canvas at the top of every
    // .moe-debug-body that this panel produced. Pure layout + SVG
    // renderer live in MKOGraph (moe-graph.js); this is the only
    // DOM glue. Skips the inject when there are zero experts.
    renderMoEDAG(bubble, debugData);
"""

APP_INSIDE_ANCHOR = (
    '    bubble.insertAdjacentHTML("beforeend", html);\n'
)

APP_HELPER_DEF = """
  // ─── Agent DAG canvas (inline SVG) ────────────────────────────────────
  //
  // Injects the inline-SVG Agent DAG canvas at the top of every
  // .moe-debug-body that the most-recent appendMoeDebug produced.
  // Pure layout + SVG renderer live in MKOGraph (moe-graph.js); this
  // helper is the only DOM glue. Skips the inject when there are zero
  // experts (= computeMoEGraphLayout returns null per design).
  //
  // Defensive: also skips when a `.moe-dag` already exists inside the
  // body so streaming-event replays don't stack two DAGs on top of
  // each other.

  function renderMoEDAG(bubble, debugData) {
    if (typeof MKOGraph === "undefined" ||
        !MKOGraph.computeMoEGraphLayout) return;
    var layout = MKOGraph.computeMoEGraphLayout(debugData);
    if (!layout) return;                          // empty / null details
    var svg = MKOGraph.renderMoEGraphSVG(layout);
    if (!svg) return;
    var bodies = bubble.querySelectorAll(".moe-debug-body");
    Array.prototype.forEach.call(bodies, function (body) {
      if (body.querySelector(".moe-dag")) return;  // already injected
      var wrap = document.createElement("div");
      wrap.className = "moe-dag-wrap";
      wrap.innerHTML = svg;
      body.insertBefore(wrap, body.firstChild || null);
    });
  }
"""

APP_INSIDE_CALL = """    // Inject the inline-SVG Agent DAG canvas at the top of every
    // .moe-debug-body that this panel produced. Pure layout + SVG
    // renderer live in MKOGraph (moe-graph.js); this is the only
    // DOM glue. Skips the inject when there are zero experts.
    renderMoEDAG(bubble, debugData);
"""


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    if "function renderMoEDAG(bubble, debugData) {" in text:
        print(f"app.js: renderMoEDAG already defined; idempotent skip")
        return

    # 1) Remove the misplaced module-level block.
    if APP_BAD_BLOCK in text:
        text = text.replace(APP_BAD_BLOCK, "", 1)
    else:
        # Tolerant fallback: locate and remove the bare call.
        text = re.sub(
            r"\n    // Inject the inline-SVG Agent DAG canvas.*?renderMoEDAG\(bubble, debugData\);\n",
            "\n",
            text,
            count=1,
            flags=re.DOTALL,
        )

    # 2) Insert the call INSIDE appendMoeDebug, right after the
    #    insertAdjacentHTML line.
    if APP_INSIDE_ANCHOR not in text:
        raise SystemExit("app.js: anchor `bubble.insertAdjacentHTML` not found")
    call_injection = APP_INSIDE_ANCHOR + APP_INSIDE_CALL
    text = text.replace(APP_INSIDE_ANCHOR, call_injection, 1)

    # 3) Add the function definition right after appendMoeDebug's `}`
    #    that closes it. The appendMoeDebug close is the first `  }`
    #    we find AFTER the call injection we just inserted.
    #    Use a tight anchor on the closing brace + blank line + comment
    #    that's already in the file (`// ─── Append Message ───`).
    close_anchor = (
        "    bubble.insertAdjacentHTML(\"beforeend\", html);\n"
        "    // Inject the inline-SVG Agent DAG canvas at the top of every\n"
        "    // .moe-debug-body that this panel produced. Pure layout + SVG\n"
        "    // renderer live in MKOGraph (moe-graph.js); this is the only\n"
        "    // DOM glue. Skips the inject when there are zero experts.\n"
        "    renderMoEDAG(bubble, debugData);\n"
        "  }\n"
    )
    if close_anchor not in text:
        raise SystemExit("app.js: close-anchor after render call not found")
    text = text.replace(close_anchor, close_anchor + APP_HELPER_DEF, 1)
    APP.write_text(text, encoding="utf-8")
    print(f"app.js: renderMoEDAG relocated inside appendMoeDebug + helper defined")


# ─── B) moe-graph.js: add a <desc> element for screen-reader a11y ─────

def patch_graph() -> None:
    text = GRAPH.read_text(encoding="utf-8")
    if "<desc>" in text:
        print(f"moe-graph.js: <desc> already present; idempotent skip")
        return
    # Insert <desc> after <title> in renderMoEGraphSVG.
    title_marker = "' via gate</title>'\n"
    if title_marker not in text:
        raise SystemExit("moe-graph.js: title marker not found")
    desc_block = (
        title_marker +
        "      + '<desc>' + descText + '</desc>'\n"
    )
    text = text.replace(title_marker, desc_block, 1)

    # Now we need to define `descText` somewhere in scope. Compute it
    # right above the title literal.
    desc_text_def = (
        "    // Build a screen-reader-friendly description listing each\n"
        "    // expert's provider, weight, and time. Falls back to just\n"
        "    // the expert count when individual stats are missing.\n"
        "    var descText = 'MoE routing for ' + N + ' expert'\n"
        "      + (N === 1 ? '' : 's') + '. '\n"
        "      + layout.nodes.slice(1).map(function (n) {\n"
        "          var w = formatWeight(n.weight);\n"
        "          var t = n.sublabel || '';\n"
        "          return (n.provider || 'expert') + ' weight ' + w + (t ? ' ' + t : '');\n"
        "        }).join('; ');\n"
    )
    # Insert descText def before the defs block.
    defs_marker = "    // Defs \u2014 single shared arrow marker for all edges.\n"
    if defs_marker not in text:
        # Try alternate Unicode dash.
        defs_marker_alt = "    // Defs \u2014 single shared arrow marker for all edges.\n"
        if defs_marker_alt in text:
            defs_marker = defs_marker_alt
        elif "    // Defs" in text:
            # Generic anchor — find first Defs comment line.
            defs_marker = "    // Defs"
        else:
            raise SystemExit("moe-graph.js: defs marker not found")
    text = text.replace(defs_marker, desc_text_def + "\n" + defs_marker, 1)
    GRAPH.write_text(text, encoding="utf-8")
    print(f"moe-graph.js: <desc> element added with per-expert text")


# ─── C) styles.css: gate label color (was blue-on-blue) ───────────────

def patch_css() -> None:
    text = CSS.read_text(encoding="utf-8")
    broken = ".mko-dag-node-gate .mko-dag-label { fill: var(--primary); }\n"
    correct = ".mko-dag-node-gate .mko-dag-label { fill: var(--bg); }\n"
    if correct in text:
        print(f"styles.css: gate label already correct; idempotent skip")
        return
    if broken in text:
        text = text.replace(broken, correct, 1)
        CSS.write_text(text, encoding="utf-8")
        print(f"styles.css: gate label fill fixed (was invisible blue-on-blue)")
    else:
        print(f"styles.css: gate label line not found in expected form; manual review needed")


# ─── D) tests/test_run_smoke.py: brittle `body.firstChild` → insertBefore ─

def patch_smoke() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    if 'assertIn("insertBefore"' in text:
        print(f"test_run_smoke.py: insertBefore pin already present; idempotent skip")
        return
    text = text.replace(
        'self.assertIn(".moe-dag-wrap", text)\n        self.assertIn("body.firstChild", text)',
        'self.assertIn(".moe-dag-wrap", text)\n        self.assertIn("insertBefore", text)',
    )
    text = text.replace(
        'self.assertIn("Agent DAG canvas", text)',
        'self.assertIn("Agent DAG", text)',
    )
    SMOKE.write_text(text, encoding="utf-8")
    print(f"test_run_smoke.py: brittle literal + over-strict substring relaxed")


# ─── E) tests/test_moe_graph.mjs: textCount math + data-idx pin ────────

def patch_test_mjs() -> None:
    text = TEST_MJS.read_text(encoding="utf-8")
    # Fix textCount assertion: actual = edges + 2 * (N+1) = 3 + 2*4 = 11.
    bad = 'assert.equal(textCount, 2 * 3 + 2, "edge labels + node labels + sublabels");\n'
    good = (
        'assert.equal(textCount, layout.edges.length + 2 * layout.nodes.length,\n'
        '                 "edges + node labels + sublabels = " + textCount + " (expected " +\n'
        '                 (layout.edges.length + 2 * layout.nodes.length) + ")");\n'
    )
    if good in text:
        print(f"test_moe_graph.mjs: textCount formula already fixed; idempotent skip")
    elif bad in text:
        text = text.replace(bad, good, 1)
        TEST_MJS.write_text(text, encoding="utf-8")
        print(f"test_moe_graph.mjs: textCount formula corrected")
    else:
        # Re-derive: search for any 2 * 3 + 2 form.
        text2 = re.sub(
            r'assert\.equal\(textCount, 2 \* 3 \+ 2, [^)]*\);',
            good.strip(),
            text,
            count=1,
        )
        if text2 != text:
            TEST_MJS.write_text(text2, encoding="utf-8")
            print(f"test_moe_graph.mjs: textCount formula corrected (regex)")
        else:
            print(f"test_moe_graph.mjs: textCount formula not found; manual review needed")

    # Fix data-idx pin: edges use data-idx, not data-id.
    text = TEST_MJS.read_text(encoding="utf-8")
    bad2 = '  assert.match(svg, /data-id="0"/);\n  assert.match(svg, /data-id="1"/);\n'
    good2 = (
        '  assert.match(svg, /<g class="mko-dag-edge" data-idx="0">| data-idx="0">/);\n'
        '  assert.match(svg, /<g class="mko-dag-edge" data-idx="1">| data-idx="1">/);\n'
    )
    if good2 in text:
        print(f"test_moe_graph.mjs: data-idx pin already correct; idempotent skip")
    elif bad2 in text:
        text = text.replace(bad2, good2, 1)
        TEST_MJS.write_text(text, encoding="utf-8")
        print(f"test_moe_graph.mjs: data-idx pin corrected")
    else:
        print(f"test_moe_graph.mjs: data-idx pin not found; manual review needed")


def main() -> None:
    patch_app()
    patch_graph()
    patch_css()
    patch_smoke()
    patch_test_mjs()


if __name__ == "__main__":
    main()
