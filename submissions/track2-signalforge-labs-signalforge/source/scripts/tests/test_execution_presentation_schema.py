import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


class ExecutionPresentationSchemaTests(unittest.TestCase):
    def load(self, name: str) -> dict:
        schema = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return schema

    def test_presentation_contract_is_versioned_and_privacy_safe(self) -> None:
        schema = self.load("execution-presentation.schema.json")
        self.assertEqual(
            schema["properties"]["schemaVersion"]["const"],
            "signalforge/execution-presentation/v1",
        )
        self.assertFalse(schema["additionalProperties"])
        for forbidden in (
            "chainOfThought",
            "hiddenPrompt",
            "rawPrompt",
            "rawResponse",
            "credential",
            "privateMemory",
        ):
            self.assertNotIn(forbidden, schema["properties"])

    def test_every_presentation_array_and_text_is_bounded(self) -> None:
        schema = self.load("execution-presentation.schema.json")

        def walk(node: object, path: str = "$") -> None:
            if isinstance(node, dict):
                if node.get("type") == "array":
                    self.assertIn("maxItems", node, f"unbounded array at {path}")
                if node.get("type") == "string" and "const" not in node and "enum" not in node:
                    self.assertTrue(
                        "maxLength" in node or "pattern" in node or node.get("format") == "date-time",
                        f"unbounded string at {path}",
                    )
                for key, value in node.items():
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        walk(schema)

    def test_execution_plan_bounds_checklists_and_references(self) -> None:
        schema = self.load("execution-plan.schema.json")
        self.assertEqual(schema["$defs"]["idArray"]["maxItems"], 64)
        self.assertEqual(
            schema["$defs"]["step"]["properties"]["checklist"]["maxItems"],
            64,
        )


if __name__ == "__main__":
    unittest.main()
