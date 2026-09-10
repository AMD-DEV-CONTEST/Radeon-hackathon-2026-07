"""Idempotent append of MoEDagTests to tests/test_run_smoke.py."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SMOKE = REPO / "tests" / "test_run_smoke.py"

BLOCK = '''
class MoEDagTests(unittest.TestCase):
    """Pin the Agent DAG canvas is wired (parser in moe-graph.js, DOM
    glue in app.js, CSS rules in styles.css, test runner in
    tests/test_moe_graph.mjs)."""

    def test_moe_graph_js_exists(self):
        p = REPO_ROOT / "mko" / "webui" / "static" / "js" / "moe-graph.js"
        self.assertTrue(p.is_file(), f"missing MoE graph file: {p}")

    def test_node_test_for_moe_graph_exists(self):
        node_test = REPO_ROOT / "tests" / "test_moe_graph.mjs"
        self.assertTrue(
            node_test.is_file(),
            f"missing Node test for MoE DAG: {node_test}",
        )

    def test_moe_graph_exports_public_surface(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "js" / "moe-graph.js").read_text(
            encoding="utf-8"
        )
        # Layout + renderer exposed on window.MKOGraph + module.exports.
        self.assertIn("computeMoEGraphLayout: computeMoEGraphLayout", text,
                      "moe-graph.js must export computeMoEGraphLayout")
        self.assertIn("renderMoEGraphSVG: renderMoEGraphSVG", text,
                      "moe-graph.js must export renderMoEGraphSVG")
        # Grammar / contract header documented.
        self.assertIn("Agent DAG canvas", text)
        self.assertIn("computeMoEGraphLayout(debugData)", text)

    def test_app_js_wires_dag_renderer_into_moe_debug(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        # The helper is defined.
        self.assertIn("renderMoEDAG", text,
                      "app.js must define renderMoEDAG")
        # And called inside appendMoeDebug flow.
        self.assertIn("renderMoEDAG(bubble, debugData)", text,
                      "app.js must call renderMoEDAG(bubble, debugData) after appendMoeDebug")
        # MKOGraph is referenced (defensive guard / null-safe).
        self.assertIn("MKOGraph", text)
        self.assertIn("MKOGraph.computeMoEGraphLayout", text)
        self.assertIn("MKOGraph.renderMoEGraphSVG", text)
        # Defensive guard: skip when no experts.
        self.assertIn(".moe-dag-wrap", text)
        self.assertIn("body.firstChild", text)

    def test_index_html_loads_moe_graph_before_app(self):
        html = (REPO_ROOT / "mko" / "webui" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        moe_idx = html.find("/static/js/moe-graph.js")
        app_idx = html.find("/static/js/app.js")
        self.assertNotEqual(moe_idx, -1,
                            "index.html does not load moe-graph.js")
        self.assertNotEqual(app_idx, -1,
                            "index.html does not load app.js")
        self.assertLess(moe_idx, app_idx,
                        "moe-graph.js must load BEFORE app.js "
                        "(the renderer must be on window before app.js uses it)")

    def test_styles_css_has_dag_rules(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )
        # Wrap, SVG, and node rules must be present.
        self.assertIn(".moe-dag-wrap", text)
        self.assertIn(".moe-dag", text)
        self.assertIn(".mko-dag-edge-line", text)
        self.assertIn(".mko-dag-edge-label", text)
        self.assertIn(".mko-dag-circle", text)
        self.assertIn(".mko-dag-node-gate", text)
        self.assertIn(".mko-dag-node-expert", text)
        # Gate and expert color rules drive the visible difference.
        self.assertIn(".mko-dag-node-gate .mko-dag-circle", text)
        self.assertIn(".mko-dag-node-gate .mko-dag-label", text)
'''


def main() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    if "MoEDagTests" in text:
        print(f"MoEDagTests already present, skipping")
        return
    new_text = text.rstrip() + BLOCK
    SMOKE.write_text(new_text, encoding="utf-8")
    print(f"appended MoEDagTests to {SMOKE}")


if __name__ == "__main__":
    main()
