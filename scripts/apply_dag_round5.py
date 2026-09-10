"""Round-5: XSS regression caught by code-reviewer round-3.

Bug: `descText` builds per-expert clauses by string-concatenating
provider name + sublabel without escaping. If the provider name ever
contains `&`, `<`, or `>`, the `<desc>` element is malformed. Same
provider name IS escaped in the visible `<text class="mko-dag-label">`
node via `escapeXml(n.label)`, so the regression is asymmetric.

Fix: run provider, sublabel, and the formatted weight through
`escapeXml` inside the descClauses map. Append a Node test in
tests/test_moe_graph.mjs that pins this safety net so future
maintainers can't silently regress.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GRAPH = REPO / "mko" / "webui" / "static" / "js" / "moe-graph.js"
TEST_MJS = REPO / "tests" / "test_moe_graph.mjs"


def patch_graph() -> None:
    text = GRAPH.read_text(encoding="utf-8")
    bad = (
        "    var descClauses = visible.map(function (n) {\n"
        "      var w = formatWeight(n.weight);\n"
        "      var t = n.sublabel || '';\n"
        "      return (n.provider || 'expert') + ' weight ' + w + (t ? ' ' + t : '');\n"
        "    });\n"
    )
    if bad not in text:
        print(f"[skip] moe-graph.js: descClauses anchor not found")
        return
    good = (
        "    var descClauses = visible.map(function (n) {\n"
        "      // Escape provider + sublabel + weight so a stray `&`/`<`\n"
        "      // in a backend payload can't corrupt the SVG. Same\n"
        "      // escapeXml coverage is used elsewhere on labels; this\n"
        "      // brings the <desc> path into the same XML-safe contract.\n"
        "      var w = escapeXml(formatWeight(n.weight));\n"
        "      var t = escapeXml(n.sublabel || '');\n"
        "      var p = escapeXml(n.provider || 'expert');\n"
        "      return p + ' weight ' + w + (t ? ' ' + t : '');\n"
        "    });\n"
    )
    text = text.replace(bad, good, 1)
    GRAPH.write_text(text, encoding="utf-8")
    print(f"[ok] moe-graph.js: descText clauses now escapeXml provider/sublabel/weight")


def patch_test_mjs() -> None:
    text = TEST_MJS.read_text(encoding="utf-8")
    if "raw '<' in <desc> body" in text:
        print(f"[skip] test_moe_graph.mjs: desc escape test already present")
        return
    addition = r"""

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
  const src = require("fs").readFileSync(
    "../mko/webui/static/js/moe-graph.js",
    "utf8"
  );
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
"""
    text = text.rstrip() + addition
    TEST_MJS.write_text(text, encoding="utf-8")
    print(f"[ok] test_moe_graph.mjs: 2 regression tests added (desc XML-safety + drift pin)")


def main() -> None:
    patch_graph()
    patch_test_mjs()


if __name__ == "__main__":
    main()
