import unittest
from html.parser import HTMLParser
from pathlib import Path


class InterfaceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.html_attrs = {}
        self.by_id = {}
        self.script_sources = []
        self.translation_keys = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "html":
            self.html_attrs = values
        if element_id := values.get("id"):
            self.by_id[element_id] = (tag, values)
        if tag == "script" and values.get("src"):
            self.script_sources.append(values["src"])
        for name in ("data-i18n", "data-i18n-placeholder", "data-i18n-aria"):
            if values.get(name):
                self.translation_keys.append(values[name])


class WebContractTests(unittest.TestCase):
    def test_page_exposes_trust_console_workflow_landmarks(self):
        html = Path("web/index.html").read_text(encoding="utf-8")

        for marker in [
            'id="modeBadge"',
            'id="planList"',
            'id="toolList"',
            'id="confirmButton"',
            'id="benchmarkList"',
            'id="comparisonCard"',
            'id="auditDownload"',
            'id="benchmarkDownload"',
            'id="themeToggle"',
            'id="apiToggle"',
            'id="apiPanel"',
            'id="providerModeRemote"',
            'id="providerModeLocal"',
            'id="apiEndpoint"',
            'id="apiModel"',
            'id="apiKey"',
            'id="rememberApi"',
            'id="testApiButton"',
            'id="applyApiButton"',
            'id="apiFeedback"',
        ]:
            self.assertIn(marker, html)

    def test_page_has_accessible_navigation_and_live_status(self):
        html = Path("web/index.html").read_text(encoding="utf-8")

        self.assertIn('aria-label="Trust console sections"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('href="/static/favicon.svg"', html)
        self.assertIn('aria-current="location"', html)

    def test_page_exposes_an_accessible_bilingual_switch_before_app_boot(self):
        parser = InterfaceParser()
        parser.feed(Path("web/index.html").read_text(encoding="utf-8"))

        self.assertEqual(parser.html_attrs.get("lang"), "en")
        self.assertIn("languageToggle", parser.by_id)
        tag, attributes = parser.by_id["languageToggle"]
        self.assertEqual(tag, "button")
        self.assertEqual(attributes.get("data-i18n"), "language.switch")
        self.assertEqual(attributes.get("data-i18n-aria"), "language.aria")
        self.assertLess(
            parser.script_sources.index("/static/i18n.js"),
            parser.script_sources.index("/static/app.js"),
        )
        self.assertLess(
            parser.script_sources.index("/static/ui-state.js"),
            parser.script_sources.index("/static/app.js"),
        )
        self.assertLess(
            parser.script_sources.index("/static/markdown.js"),
            parser.script_sources.index("/static/app.js"),
        )
        self.assertGreaterEqual(len(parser.translation_keys), 40)

    def test_answer_and_api_panel_have_accessible_semantics(self):
        parser = InterfaceParser()
        parser.feed(Path("web/index.html").read_text(encoding="utf-8"))

        self.assertEqual(parser.by_id["answer"][0], "div")
        self.assertEqual(parser.by_id["apiPanel"][1].get("role"), "dialog")
        self.assertEqual(parser.by_id["apiFeedback"][1].get("aria-live"), "polite")
        self.assertEqual(parser.by_id["apiKey"][1].get("type"), "password")
        self.assertEqual(parser.by_id["providerModeRemote"][1].get("value"), "remote")
        self.assertEqual(parser.by_id["providerModeLocal"][1].get("value"), "rocm-local")
        self.assertEqual(parser.by_id["providerModeRemote"][1].get("name"), "providerMode")
        self.assertEqual(parser.by_id["providerModeLocal"][1].get("name"), "providerMode")
        self.assertEqual(parser.by_id["themeToggle"][1].get("type"), "button")

    def test_provider_required_error_replaces_answer_and_opens_api_panel(self):
        source = Path("web/app.js").read_text(encoding="utf-8")

        self.assertIn('error.code = data.error?.code || ""', source)
        self.assertIn('if (error.code === "provider_required")', source)
        self.assertIn('renderAnswer(t("answer.apiRequired"))', source)
        self.assertIn("toggleApiPanel(true)", source)

    def test_first_render_fallbacks_are_localizable_before_api_requests_finish(self):
        parser = InterfaceParser()
        parser.feed(Path("web/index.html").read_text(encoding="utf-8"))

        self.assertEqual(parser.by_id["healthStatus"][1].get("data-i18n"), "health.checking")
        self.assertEqual(parser.by_id["auditList"][1].get("data-i18n"), "audit.empty")
        for key in [
            "runtime.framework",
            "runtime.inference",
            "runtime.provider",
            "runtime.documents",
            "runtime.boundary",
            "runtime.loading",
        ]:
            self.assertIn(key, parser.translation_keys)

    def test_runtime_omits_competition_core_row_and_posts_explicit_mode(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        source = Path("web/app.js").read_text(encoding="utf-8")

        self.assertNotIn('data-i18n="runtime.eligibility"', html)
        self.assertNotIn('"runtime.developmentOnly"', source)
        self.assertIn("mode: config.mode", source)
        self.assertIn('mode === "remote" && !config.apiKey', source)

    def test_radeon_proof_is_reviewer_first_with_collapsed_retest_controls(self):
        parser = InterfaceParser()
        parser.feed(Path("web/index.html").read_text(encoding="utf-8"))
        source = Path("web/app.js").read_text(encoding="utf-8")

        for element_id in [
            "radeonProofStatus", "radeonProofFacts", "radeonMetrics", "radeonStack",
            "radeonSources", "radeonBoundary", "retestPanel",
        ]:
            self.assertIn(element_id, parser.by_id)
        self.assertEqual(parser.by_id["retestPanel"][0], "details")
        self.assertNotIn("open", parser.by_id["retestPanel"][1])
        self.assertIn("async function loadRadeonEvidence()", source)
        self.assertIn("function renderRadeonEvidence(data)", source)
        self.assertIn('requestJson("/api/rocm-evidence")', source)


if __name__ == "__main__":
    unittest.main()
