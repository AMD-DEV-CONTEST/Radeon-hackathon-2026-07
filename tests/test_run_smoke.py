"""Project layout smoke tests.

Most logic tests live in `tests/test_slash_commands.mjs` (Node test runner,
exercises the actual JS parser).  This file pins the static layout so a
refactor can't silently drop a script tag, the parser file, or the run-doc
section.

Run:   python -m unittest tests.test_run_smoke
"""
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestProjectLayout(unittest.TestCase):
    """Pin the file layout the slash-command feature relies on."""

    def test_slash_commands_js_exists(self):
        p = REPO_ROOT / "mko" / "webui" / "static" / "js" / "slash-commands.js"
        self.assertTrue(p.is_file(), f"missing parser file: {p}")

    def test_node_test_for_parser_exists(self):
        tests_dir = REPO_ROOT / "tests"
        node_test = tests_dir / "test_slash_commands.mjs"
        self.assertTrue(
            node_test.is_file(),
            f"missing Node test file: {node_test}; expected test_slash_commands.mjs",
        )

    def test_index_html_loads_slash_script_before_app(self):
        html = (REPO_ROOT / "mko" / "webui" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        slash_idx = html.find("slash-commands.js")
        app_idx = html.find("/static/js/app.js")
        self.assertNotEqual(slash_idx, -1, "index.html does not load slash-commands.js")
        self.assertNotEqual(app_idx, -1, "index.html does not load app.js")
        self.assertLess(
            slash_idx, app_idx,
            "slash-commands.js must load BEFORE app.js (the parser must be on window before app.js uses it)",
        )

    def test_app_js_uses_slash_parser(self):
        js = (REPO_ROOT / "mko" / "webui" / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("MKOSlash", js, "app.js does not reference MKOSlash")
        self.assertIn("handleSlashCommand", js, "app.js does not define handleSlashCommand")
        self.assertIn("appendSystemMessage", js, "app.js does not define appendSystemMessage")
        # The interception call must be in sendMessage().
        self.assertIn("MKOSlash.parse", js, "app.js never calls MKOSlash.parse")

    def test_run_md_documents_slash_commands(self):
        run_md = (REPO_ROOT / ".freebuff" / "run.md").read_text(encoding="utf-8")
        for cmd in ("/plan", "/research", "/summary", "/model", "/provider"):
            self.assertIn(cmd, run_md, f".freebuff/run.md is missing mention of {cmd}")


if __name__ == "__main__":
    unittest.main()
class SlashSuggestTests(unittest.TestCase):
    """Pin that the new autocomplete dropdown is wired from parser -> app.js."""

    def test_slash_commands_exports_get_suggestions(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "js" / "slash-commands.js").read_text(encoding="utf-8")
        self.assertIn("getSuggestions: getSuggestions", text,
                      "slash-commands.js must export getSuggestions on the public surface")
        # Grammar header must document the autocomplete contract.
        self.assertIn("getSuggestions(text)", text)
        self.assertIn("null", text)             # hide conditions list `null`
        self.assertIn("rows[]", text)           # and `rows[]`

    def test_app_js_wires_suggest_dropdown(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        # Pure helper is consumed.
        self.assertIn("MKOSlash.getSuggestions", text,
                      "app.js must call MKOSlash.getSuggestions")
        # Lifecycle hooks shipped.
        self.assertIn("wireSlashSuggest", text)
        self.assertIn("renderSuggest", text)
        self.assertIn("applySuggestion", text)
        self.assertIn("onChatKeydownSuggest", text)
        self.assertIn("ensureSuggestEl", text)
        # Keyboard nav events handled.
        self.assertIn("ArrowDown", text)
        self.assertIn("ArrowUp", text)
        # Enter handled but gated by Shift (textarea newline passes through).
        self.assertIn("e.shiftKey", text)

    def test_styles_css_has_suggest_rules(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "css" / "styles.css").read_text(encoding="utf-8")
        # .mko-suggest must be defined AND .open AND .active variants.
        self.assertIn(".mko-suggest", text)
        self.assertIn(".mko-suggest.open", text)
        self.assertIn(".mko-suggest-row", text)
        self.assertIn(".mko-suggest-row.active", text)
        # .input-area must remain the positioning context.
        # (Already true in the existing stylesheet; this test guards
        # against future refactors that drop `position: relative`.)
        self.assertIn(".input-area", text)
        self.assertIn("position: relative", text)
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
        self.assertIn("Agent DAG", text)
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
        # CSS-class selector (".moe-dag-wrap" form, used in CSS + JS).
        self.assertIn("moe-dag-wrap", text,
                         "app.js must wrap the rendered DAG in `.moe-dag-wrap`")
        # Hook into the SVG above the existing expert-card list.
        self.assertIn("insertBefore", text,
                         "renderMoEDAG must insertBefore to sit above the expert cards")

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
