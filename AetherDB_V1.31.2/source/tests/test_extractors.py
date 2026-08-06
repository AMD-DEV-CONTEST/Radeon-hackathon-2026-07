"""extractors unit tests"""
import unittest, json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extractors.base import extract_json, sanitize_input, ExtractorBase

class TestExtractJson(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(extract_json(""))
        self.assertIsNone(extract_json(None))
    def test_valid_json(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
    def test_code_block(self):
        r = extract_json('```json\n{"k": "v"}\n```')
        self.assertEqual(r, {"k": "v"})
    def test_trailing_comma(self):
        self.assertEqual(extract_json('{"a": 1,}'), {"a": 1})
    def test_invalid(self):
        self.assertIsNone(extract_json("not json"))

class TestSanitizeInput(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(sanitize_input(""), "")
        self.assertEqual(sanitize_input(None), "")
    def test_control_chars(self):
        self.assertEqual(sanitize_input("a\x00b"), "ab")
    def test_truncation(self):
        r = sanitize_input("x" * 5000, max_length=50)
        self.assertTrue(r.endswith("...[truncated]"))

class TestParseResponse(unittest.TestCase):
    def setUp(self):
        class FE(ExtractorBase):
            def _call_llm(self, p): return ""
        self.ex = FE()
    def test_none(self):
        self.assertEqual(self.ex._parse_response(""), ([], []))
    def test_dict(self):
        r = json.dumps({"entities": [{"n": "A"}]})
        e, _ = self.ex._parse_response(r)
        self.assertEqual(len(e), 1)
    def test_list(self):
        r = json.dumps([{"n": "E1"}])
        e, _ = self.ex._parse_response(r)
        self.assertEqual(len(e), 1)

if __name__ == "__main__":
    unittest.main()