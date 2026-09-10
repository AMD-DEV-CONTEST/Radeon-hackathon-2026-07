"""Apply the two MoE-DAG glue edits that the inline str_replace didn't land:
  1) Append `renderMoEDAG(bubble, debugData);` call + the helper function
     to app.js, immediately after the existing bubble.insertAdjacentHTML
     tail of appendMoeDebug.
  2) Append the .moe-dag* CSS rules to styles.css, immediately after
     the .moe-cost-summary strong block.
Both edits are idempotent: re-running is a no-op if the marker string
is already present.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "mko" / "webui" / "static" / "js" / "app.js"
CSS = REPO / "mko" / "webui" / "static" / "css" / "styles.css"


APP_RENDER_MARKER = "    renderMoEDAG(bubble, debugData);\n  }\n\n  // ─── Agent DAG canvas (inline SVG) ─────────────────────────────"

CSS_DAG_MARKER = "/* ─── MoE Agent DAG canvas (inline SVG)"


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    if APP_RENDER_MARKER in text:
        print(f"app.js: renderMoEDAG wiring already present, skipping")
        return

    # Pinpoint anchor: the exact tail of appendMoeDebug that we know is
    # present in the file (read earlier in the session).
    needle = (
        '    bubble.insertAdjacentHTML("beforeend", html);\n  }\n'
    )
    addition = (
        '\n'
        '  // ─── Agent DAG canvas (inline SVG) ────────────────────'
        '─────────\n'
        '  //\n'
        '  // Renders the MoE routing graph at the top of every\n'
        '  // .moe-debug-body in this bubble. Pure layout + SVG renderer\n'
        '  // live in MKOGraph (mko-graph.js); this is the only DOM glue.\n'
        '  // Returns falsy (= skips the inject) when there are zero\n'
        '  // experts — per design the empty case is rendered by nothing\n'
        '  // at all, no placeholder.\n'
        '\n'
        '  function renderMoEDAG(bubble, debugData) {\n'
        '    if (typeof MKOGraph === "undefined" ||\n'
        '        !MKOGraph.computeMoEGraphLayout) return;\n'
        '    var layout = MKOGraph.computeMoEGraphLayout(debugData);\n'
        '    if (!layout) return;                          // empty details\n'
        '    var svg = MKOGraph.renderMoEGraphSVG(layout);\n'
        '    if (!svg) return;\n'
        '    var bodies = bubble.querySelectorAll(".moe-debug-body");\n'
        '    Array.prototype.forEach.call(bodies, function (body) {\n'
        '      // Defensive: streaming events can fire twice for the same\n'
        '      // MoE run; avoid stacking two DAGs on top of each other.\n'
        '      if (body.querySelector(".moe-dag")) return;\n'
        '      var wrap = document.createElement("div");\n'
        '      wrap.className = "moe-dag-wrap";\n'
        '      wrap.innerHTML = svg;\n'
        '      body.insertBefore(wrap, body.firstChild);\n'
        '    });\n'
        '  }\n'
    )

    # We need to anchor on a slightly larger context — the closing of
    # appendMoeDebug also features a comment "// ─── MoE Debug ──"
    # right after the close brace; we know that comment exists in
    # the file. Use it to disambiguate if multiple insertAdjacentHTML
    # calls exist (none in this file, but defensive).
    def append_render_call(match: "re.Match[str]") -> str:
        head = match.group(0)
        # Skip if our wiring has already been inserted on a prior run.
        if "renderMoEDAG(bubble, debugData);" in head:
            return head
        return head.rstrip() + "\n\n" + (
            '    // Inject the inline-SVG Agent DAG canvas at the top of every\n'
            '    // .moe-debug-body that this panel produced. Pure layout + SVG\n'
            '    // renderer live in MKOGraph (mko-graph.js); this is the only\n'
            '    // DOM glue. Skips the inject when there are zero experts.\n'
            '    renderMoEDAG(bubble, debugData);\n'
        )

    # Find every bubble.insertAdjacentHTML close and append our call +
    # the helper definition right after the function's closing `}`.
    pattern = re.compile(
        r'    bubble\.insertAdjacentHTML\("beforeend", html\);\n  \}\n',
        re.MULTILINE,
    )
    new_text, count = pattern.subn(append_render_call, text)
    if count == 0:
        # Fall back to simpler insertion at the unique line.
        if needle not in text:
            raise SystemExit("app.js: anchor for bubble.insertAdjacentHTML not found")
        new_text = text.replace(needle, needle + "\n" + addition, 1)
    else:
        # Helper definition goes once, after the FIRST (and only) append.
        helper_def = (
            '\n'
            '  // ─── Agent DAG canvas (inline SVG) ────────────────────'
            '─────────'
            '\n'
            '  // (see renderMoEDAG above for the full comment)\n'
            '  // The helper is defined right after appendMoeDebug so it\n'
            '  // can be inlined into the existing function tail.\n'
        )
        # No-op marker so subsequent runs skip.
        new_text = new_text.replace(
            needle + "\n" + addition,
            needle + "\n" + addition,
            1,
        )
    APP.write_text(new_text, encoding="utf-8")
    print(f"app.js: renderMoEDAG wired ({count} sites)")


def patch_css() -> None:
    text = CSS.read_text(encoding="utf-8")
    if CSS_DAG_MARKER in text:
        print(f"styles.css: MoE DAG rules already present, skipping")
        return

    # Anchor on the end of the .moe-cost-summary strong block; we
    # know that block exists in the file.
    needle = (
        ".moe-cost-summary strong {\n"
        "  font-size: 12px;\n"
        "  display: block;\n"
        "  margin-bottom: 6px;\n"
        "}\n"
    )
    if needle not in text:
        raise SystemExit(
            "styles.css: anchor for .moe-cost-summary strong not found"
        )
    rules = (
        "\n"
        "/* ─── MoE Agent DAG canvas (inline SVG) ───────────────────"
        "────── */\n"
        ".moe-dag-wrap {\n"
        "  margin-bottom: 10px;\n"
        "  background: var(--bg);\n"
        "  border: 1px solid var(--border);\n"
        "  border-radius: var(--radius-sm);\n"
        "  padding: 8px;\n"
        "  overflow: hidden;\n"
        "}\n"
        "\n"
        ".moe-dag { display: block; max-width: 100%; height: auto; }\n"
        "\n"
        ".mko-dag-edge-line {\n"
        "  fill: none;\n"
        "  stroke: var(--text-muted);\n"
        "  stroke-width: 1.5;\n"
        "}\n"
        "\n"
        ".mko-dag-edge-label-bg {\n"
        "  fill: var(--surface);\n"
        "  stroke: var(--border);\n"
        "  stroke-width: 0.5;\n"
        "}\n"
        "\n"
        ".mko-dag-edge-label {\n"
        "  fill: var(--text-muted);\n"
        "  font-size: 10px;\n"
        "  font-family: var(--font-mono);\n"
        "}\n"
        "\n"
        ".mko-dag-circle {\n"
        "  stroke: var(--bg);\n"
        "  stroke-width: 2;\n"
        "}\n"
        "\n"
        ".mko-dag-node-gate .mko-dag-circle {\n"
        "  stroke: var(--primary);\n"
        "  stroke-width: 3;\n"
        "}\n"
        "\n"
        ".mko-dag-node-expert .mko-dag-circle {\n"
        "  stroke: var(--border);\n"
        "  stroke-width: 2;\n"
        "}\n"
        "\n"
        ".mko-dag-node-gate .mko-dag-label { fill: var(--primary); }\n"
        ".mko-dag-node-gate:hover .mko-dag-circle { stroke-width: 4; }\n"
        "\n"
        ".mko-dag-label {\n"
        "  fill: var(--text);\n"
        "  font-size: 11px;\n"
        "  font-weight: 600;\n"
        "  font-family: var(--font-ui);\n"
        "  pointer-events: none;\n"
        "}\n"
        "\n"
        ".mko-dag-sublabel {\n"
        "  fill: var(--text-muted);\n"
        "  font-size: 10px;\n"
        "  font-family: var(--font-mono);\n"
        "  pointer-events: none;\n"
        "}\n"
    )
    new_text = text.replace(needle, needle + rules, 1)
    CSS.write_text(new_text, encoding="utf-8")
    print(f"styles.css: MoE DAG rules appended")


def main() -> None:
    patch_app()
    patch_css()


if __name__ == "__main__":
    main()
