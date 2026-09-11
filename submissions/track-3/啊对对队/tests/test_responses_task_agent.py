import json
import os
import unittest
from unittest.mock import patch

from parcel_sorter.harness_agent import AgentIdentity
from parcel_sorter.harness_task_bridge import compile_task_directive_for_pi05
from parcel_sorter.responses_task_agent import (
    OpenAICompatibleResponsesTaskAgent,
    ResponsesClientConfig,
    ResponsesTaskAgentError,
)


def _identity() -> AgentIdentity:
    return AgentIdentity(
        agent_id="parcel-task-agent-v21",
        role="task_agent",
        provider="openai-compatible-gateway",
        model="gpt-5.6-luna",
        version="responses-v1",
    )


def _directive(**extra: object) -> dict:
    value = {
        "schema_version": 1,
        "protocol": "parcel-harness-task-directive-v1",
        "directive_id": "directive-episode-1",
        "agent_id": "parcel-task-agent-v21",
        "goal": "move the parcel to destination A",
        "grasp_mode": "top",
        "recovery_strategy": "reobserve",
        "memory_refs": [],
        "rationale": "top face is available",
    }
    value.update(extra)
    return value


class ResponsesTaskAgentTests(unittest.TestCase):
    def _config(self, **overrides: object) -> ResponsesClientConfig:
        values = {
            "base_url": "https://example.invalid/v1",
            "model": "gpt-5.6-luna",
            "primary_attempts": 1,
        }
        values.update(overrides)
        return ResponsesClientConfig(**values)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
    def test_valid_directive_and_bridge(self) -> None:
        captured = {}

        def transport(url, headers, body, timeout):
            captured.update(json.loads(body))
            return {
                "id": "resp-1",
                "model": "gpt-5.6-luna",
                "output_text": json.dumps(_directive()),
            }

        planner = OpenAICompatibleResponsesTaskAgent(
            _identity(), self._config(), transport=transport
        )
        directive = planner.plan({"goal": "sort parcel", "stage": "pregrasp"})
        bridge = compile_task_directive_for_pi05(
            directive, task_agent=planner.identity
        )
        self.assertFalse(captured["store"])
        self.assertEqual(captured["text"]["format"]["type"], "json_schema")
        self.assertEqual(bridge["runtime_grasp_mode"], "top_suction")
        self.assertEqual(bridge["authority"], "task_conditioning_only")
        self.assertFalse(planner.last_trace["fallback_used"])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
    def test_forbidden_action_field_fails_closed(self) -> None:
        def transport(url, headers, body, timeout):
            return {"output_text": json.dumps(_directive(action=[0.0] * 21))}

        planner = OpenAICompatibleResponsesTaskAgent(
            _identity(), self._config(), transport=transport
        )
        with self.assertRaises(ResponsesTaskAgentError):
            planner.plan({"goal": "sort parcel"})
        self.assertEqual(planner.last_trace["status"], "failed_closed")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
    def test_primary_failure_uses_declared_fallback_and_records_it(self) -> None:
        requested_models = []

        def transport(url, headers, body, timeout):
            model = json.loads(body)["model"]
            requested_models.append(model)
            if model == "gpt-5.6-luna":
                raise OSError("upstream timeout")
            return {
                "id": "resp-fallback",
                "model": model,
                "output_text": json.dumps(_directive()),
            }

        planner = OpenAICompatibleResponsesTaskAgent(
            _identity(),
            self._config(fallback_model="gpt-5.5"),
            transport=transport,
        )
        planner.plan({"goal": "sort parcel"})
        self.assertEqual(requested_models, ["gpt-5.6-luna", "gpt-5.5"])
        self.assertTrue(planner.last_trace["fallback_used"])
        self.assertEqual(planner.last_trace["actual_model"], "gpt-5.5")

    def test_missing_key_fails_before_transport(self) -> None:
        planner = OpenAICompatibleResponsesTaskAgent(
            _identity(), self._config(), transport=lambda *args: self.fail()
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ResponsesTaskAgentError, "missing API"):
                planner.plan({"goal": "sort parcel"})


if __name__ == "__main__":
    unittest.main()
