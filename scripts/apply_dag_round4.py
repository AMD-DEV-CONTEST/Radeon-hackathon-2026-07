"""Round-4: the last two wrinkles.

(A) test_run_smoke.py — `.moe-dag-wrap` (with leading dot) is a CSS-class
    selector string. In app.js the className assignment uses the literal
    `"moe-dag-wrap"` (no leading dot). Both forms are useful to pin:
    the CSS form to ensure the style contract stays, the JS form to
    ensure the runtime tagging stays. Replace the single assertion
    with both.

(B) moe-graph.js — anchor indent was wrong (real content uses 8 spaces,
    not 6). Insert `<desc>` element + the descText builder properly.

(C) README.md + .freebuff/run.md — short paragraph noting the Agent
    DAG canvas so a reader of either doc sees the new feature.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GRAPH = REPO / "mko" / "webui" / "static" / "js" / "moe-graph.js"
SMOKE = REPO / "tests" / "test_run_smoke.py"
README = REPO / "README.md"
RUNMD = REPO / ".freebuff" / "run.md"


def patch_graph() -> None:
    text = GRAPH.read_text(encoding="utf-8")
    if "<desc>" in text and "descText" in text:
        print(f"[skip] moe-graph.js: desc element already present")
        return

    # Insert descText builder right before the defs block.
    desc_text_def = (
        "    // Build a screen-reader-friendly description listing each\n"
        "    // expert's provider, weight, and time. SR users hear this\n"
        "    // after the <title>. Cap at first 8 experts so large MoE\n"
        "    // runs don't produce a runaway announcement.\n"
        "    var nodesList = layout.nodes.slice(1);\n"
        "    var visible = nodesList.slice(0, 8);\n"
        "    var descClauses = visible.map(function (n) {\n"
        "      var w = formatWeight(n.weight);\n"
        "      var t = n.sublabel || '';\n"
        "      return (n.provider || 'expert') + ' weight ' + w + (t ? ' ' + t : '');\n"
        "    });\n"
        "    if (nodesList.length > 8) {\n"
        "      descClauses.push('and ' + (nodesList.length - 8) + ' more');\n"
        "    }\n"
        "    var descText = 'MoE routing for ' + N + ' expert'\n"
        "      + (N === 1 ? '' : 's') + '. ' + descClauses.join('; ');\n"
    )

    # Anchor: real content at line ~185 uses 4-space indent for `var defs =`.
    if "    var defs =\n      '<defs>' +" not in text:
        print(f"[skip] moe-graph.js: defs anchor not found")
        return
    text = text.replace(
        "    // Defs \u2014 single shared arrow marker for all edges.\n"
        "    var defs =\n"
        "      '<defs>' +",
        "    // Defs \u2014 single shared arrow marker for all edges.\n"
        + desc_text_def
        + "\n"
        + "    var defs =\n"
        + "      '<defs>' +",
        1,
    )

    # Anchor for the <desc>: after ' via gate</title>' + on its own line,
    # then `defs +` (8 spaces) on the next line.
    desc_marker = (
        "          ' via gate</title>' +\n"
        "        defs +"
    )
    if desc_marker not in text:
        print(f"[skip] moe-graph.js: ' via gate</title>' +\\n        defs anchor not found")
        return
    text = text.replace(
        desc_marker,
        "          ' via gate</title>' +\n"
        "        '<desc>' + descText + '</desc>' +\n"
        "        defs +",
        1,
    )
    GRAPH.write_text(text, encoding="utf-8")
    print(f"[ok] moe-graph.js: <desc> + descText builder added")


def patch_smoke() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    needle = '        self.assertIn(".moe-dag-wrap", text)\n        self.assertIn("insertBefore", text)'
    if needle not in text:
        print(f"[skip] test_run_smoke.py: target assertion block already replaced")
        return
    replacement = (
        '        # CSS-class selector (".moe-dag-wrap" form, used in CSS + JS).\n'
        '        self.assertIn("moe-dag-wrap", text,\n'
        '                         "app.js must wrap the rendered DAG in `.moe-dag-wrap`")\n'
        '        # Hook into the SVG above the existing expert-card list.\n'
        '        self.assertIn("insertBefore", text,\n'
        '                         "renderMoEDAG must insertBefore to sit above the expert cards")'
    )
    text = text.replace(needle, replacement, 1)
    SMOKE.write_text(text, encoding="utf-8")
    print(f"[ok] test_run_smoke.py: split .moe-dag-wrap into CSS + JS forms")


def patch_readme() -> None:
    text = README.read_text(encoding="utf-8")
    if "Agent DAG canvas" in text:
        print(f"[skip] README.md: Agent DAG section already present")
        return
    # Find a section anchor: §6/§7 already covers slash commands. Add §8
    # for the DAG canvas immediately after the slash commands prose.
    anchor = "Update `.freebuff/run.md` § 6 + `.freebuff/run.md` § 6"
    if anchor not in text:
        # Add near the bottom or after another marker.
        anchor = "## 5. ✅ Continuous integration (CI)"
    block = (
        "\n\n"
        "### 7. 🔀 Agent DAG canvas (in-app)\n\n"
        "When a chat response carries a `moe_debug` event (the MoE agent's\n"
        "router telemetry), the assistant bubble prepends an inline-SVG Agent\n"
        "DAG canvas above the existing expert cards: gate at top, each expert\n"
        "node spaced below, edges labeled with weight. Decorative chrome\n"
        "(`.moe-dag-wrap`) reuses existing CSS variables. Collapsible alongside\n"
        "the rest of the panel via the existing 🔀 MoE Debug header.\n\n"
        "Pure layout + SVG renderer live in `mko/webui/static/js/moe-graph.js`\n"
        "(UMD-exported `window.MKOGraph`); `app.js`'s `renderMoEDAG(bubble, debugData)`\n"
        "is the only DOM glue. Tests: `tests/test_moe_graph.mjs` exercises the\n"
        "layout + renderer; `tests/test_run_smoke.py`'s `MoEDagTests` pins\n"
        "the wiring end-to-end.\n"
    )
    text = text.replace(anchor, anchor + block, 1)
    README.write_text(text, encoding="utf-8")
    print(f"[ok] README.md: §7 Agent DAG canvas added")


def patch_runmd() -> None:
    text = RUNMD.read_text(encoding="utf-8")
    if "Agent DAG canvas" in text and "MKOGraph" in text:
        print(f"[skip] run.md: Agent DAG section already present")
        return
    # Add right after the Slash-command autocomplete subsection.
    anchor = " (`tests/test_moe_graph.mjs` for Node tests,"
    # Anchor at: "Slash-command autocomplete" heading or the descriptions line.
    if "Slash-command autocomplete" in text:
        needle = "Pure helper: `MKOSlash.getSuggestions(text)` returns `null`"
        if needle in text:
            text = text.replace(
                needle,
                "### Agent DAG canvas (MoE routing)\n\n"
                "When the assistant stream contains a `moe_debug` event, the chat\n"
                "bubble prepends an inline-SVG graph above the existing expert\n"
                "cards. Gate at top; each expert node spaced below; edges\n"
                "labeled with weight; deterministic DJB2-hashed palette so the\n"
                "same provider always maps to the same color across renders.\n\n"
                "Pure pieces (`moe-graph.js`, exposed on `window.MKOGraph`):\n\n"
                "- `computeMoEGraphLayout(debugData)` — returns `null` for empty details,\n"
                "  otherwise `{ width, height, expertCount, nodes[], edges[] }`. Gate\n"
                "  placed at top center; experts distributed evenly below; N=1\n"
                "  case places the single expert directly under the gate on the\n"
                "  same X column.\n"
                "- `renderMoEGraphSVG(layout)` — pure SVG string with `<title>`,\n"
                "  `<desc>`, `<defs>` (arrow marker), one `<g class=\"mko-dag-edge\">`\n"
                "  per edge with a weight label, and one `<g class=\"mko-dag-node\">`\n"
                "  per node (circle + label + sublabel).\n"
                "- `colorForProvider(name)` / `formatWeight(w)` — exported for\n"
                "  forward-compatible use (e.g., colored badges elsewhere).\n\n"
                "DOM glue (`app.js`): `renderMoEDAG(bubble, debugData)` queries\n"
                "`bubble.querySelectorAll('.moe-debug-body')`, forEach, and\n"
                "prepends a `.moe-dag-wrap` block at the top of each body. The\n"
                "existing `🔀 MoE Debug` header toggle collapses the whole panel.\n\n"
                + needle,
                1,
            )
            RUNMD.write_text(text, encoding="utf-8")
            print(f"[ok] run.md: Agent DAG canvas subsection added")
        else:
            print(f"[skip] run.md: anchor not found")
    else:
        print(f"[skip] run.md: Slash-command autocomplete anchor missing")


def main() -> None:
    patch_graph()
    patch_smoke()
    patch_readme()
    patch_runmd()


if __name__ == "__main__":
    main()
