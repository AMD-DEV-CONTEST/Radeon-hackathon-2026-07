import json
import tempfile
import threading
import unittest
from pathlib import Path

from incident_commander.agent import AgentError, InvestigationService
from incident_commander.store import SessionStore


SAMPLE = Path(__file__).parent.parent / "samples" / "checkout-latency.json"


class FailingClient:
    def choose_tool(self, *args, **kwargs):
        raise RuntimeError("model unavailable")

    def complete(self, *args, **kwargs):
        raise RuntimeError("model unavailable")


class StubClient:
    def choose_tool(self, system, user, tools, max_tokens=256):
        payload = json.loads(user)
        expected = payload["expected_tool"]
        arguments = payload["default_arguments"]
        return type(
            "ToolChoice",
            (),
            {
                "name": expected,
                "arguments": arguments,
                "model": "stub-model",
                "latency_ms": 3.0,
                "usage": {"total_tokens": 5},
            },
        )()

    def complete(self, system, user, max_tokens=256):
        return type(
            "Completion",
            (),
            {"content": "The release introduced database pool contention.", "model": "stub-model", "latency_ms": 4.0, "usage": {}},
        )()


def sample_payload() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


class InvestigationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))
        self.service = InvestigationService(self.store, client=StubClient())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create(self) -> dict:
        return self.service.create("create-1", sample_payload())

    def advance(self, investigation: dict, request_id: str) -> dict:
        return self.service.next(investigation["id"], request_id, investigation["version"])

    def test_create_persists_four_step_plan_and_initial_evidence(self) -> None:
        investigation = self.create()

        self.assertEqual(investigation["version"], 1)
        self.assertEqual(investigation["status"], "idle")
        self.assertEqual([step["kind"] for step in investigation["plan"]], ["tool", "tool", "tool", "synthesis"])
        self.assertEqual(len(investigation["evidence"]), 5)
        self.assertEqual(self.service.get(investigation["id"])["id"], investigation["id"])

    def test_four_steps_execute_three_tools_then_reach_approval(self) -> None:
        investigation = self.create()
        for index in range(4):
            investigation = self.advance(investigation, f"next-{index}")

        tool_events = [event for event in investigation["trace"] if event["kind"] == "tool"]
        self.assertEqual([event["tool"] for event in tool_events], ["get_deployments", "query_metrics", "search_logs"])
        self.assertTrue(all(event["evidence_ids"] for event in tool_events))
        self.assertTrue(all(item.get("adapter") == "local-demo-adapter" for item in investigation["evidence"][5:]))
        self.assertEqual(investigation["status"], "awaiting_approval")
        self.assertEqual(len(investigation["proposed_actions"]), 2)
        self.assertTrue(all(action["approval_status"] == "pending" for action in investigation["proposed_actions"]))

    def test_model_failure_uses_deterministic_tool_fallback(self) -> None:
        service = InvestigationService(self.store, client=FailingClient())
        investigation = service.create("fallback-create", sample_payload())

        investigation = service.next(investigation["id"], "fallback-next", investigation["version"])

        self.assertEqual(investigation["plan"][0]["status"], "completed")
        self.assertTrue(investigation["runtime"]["degraded"])
        self.assertEqual(investigation["trace"][-1]["status"], "fallback")

    def test_remote_runtime_never_receives_incident_evidence(self) -> None:
        class SpyRemoteClient(StubClient):
            calls = 0

            def choose_tool(self, *args, **kwargs):
                self.calls += 1
                return super().choose_tool(*args, **kwargs)

        client = SpyRemoteClient()
        service = InvestigationService(
            self.store,
            client=client,
            runtime={"mode": "remote-api", "degraded": False},
        )
        investigation = service.create("remote-create", sample_payload())

        investigation = service.next(investigation["id"], "remote-next", investigation["version"])

        self.assertEqual(client.calls, 0)
        self.assertEqual(investigation["runtime"]["remote_core_requests"], 0)
        self.assertEqual(investigation["trace"][-1]["status"], "fallback")

    def test_model_and_tool_failure_ends_in_visible_degraded_state(self) -> None:
        class BrokenTools:
            schemas = []

            def execute(self, name, arguments):
                raise RuntimeError("fixture unavailable")

        service = InvestigationService(self.store, client=FailingClient(), tools=BrokenTools())
        investigation = service.create("broken-create", sample_payload())

        investigation = service.next(investigation["id"], "broken-next", investigation["version"])

        self.assertEqual(investigation["status"], "degraded")
        self.assertEqual(investigation["plan"][0]["status"], "failed")
        self.assertEqual(investigation["trace"][-1]["status"], "failed")

    def test_replay_is_idempotent_and_stale_version_conflicts(self) -> None:
        investigation = self.create()
        first = self.service.next(investigation["id"], "same-next", investigation["version"])
        replay = self.service.next(investigation["id"], "same-next", investigation["version"])

        self.assertEqual(replay, first)
        with self.assertRaisesRegex(AgentError, "expected_version") as stale:
            self.service.next(investigation["id"], "different-next", investigation["version"])
        self.assertEqual(stale.exception.status, 409)

    def test_request_id_reuse_with_different_payload_conflicts(self) -> None:
        investigation = self.create()
        for index in range(4):
            investigation = self.advance(investigation, f"advance-{index}")
        first_action = investigation["proposed_actions"][0]
        self.service.decision(
            investigation["id"], "decision-1", investigation["version"], first_action["id"], "approved", "safe"
        )

        with self.assertRaisesRegex(AgentError, "different payload") as conflict:
            self.service.decision(
                investigation["id"], "decision-1", investigation["version"], first_action["id"], "rejected", "unsafe"
            )
        self.assertEqual(conflict.exception.status, 409)

    def test_concurrent_next_executes_only_once(self) -> None:
        investigation = self.create()
        barrier = threading.Barrier(2)
        results = []

        def advance(request_id: str) -> None:
            barrier.wait()
            try:
                results.append(self.service.next(investigation["id"], request_id, investigation["version"]))
            except AgentError as exc:
                results.append(exc)

        threads = [threading.Thread(target=advance, args=(f"concurrent-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        errors = [item for item in results if isinstance(item, AgentError)]
        self.assertEqual(errors[0].status, 409)
        current = self.service.get(investigation["id"])
        self.assertEqual(len([item for item in current["trace"] if item["kind"] == "tool"]), 1)

    def test_interrupted_running_step_is_retried_after_restart(self) -> None:
        investigation = self.create()
        snapshot = self.store.load(investigation["id"])
        snapshot["plan"][0]["status"] = "running"
        self.store.save(snapshot)
        restarted = InvestigationService(SessionStore(Path(self.temp.name)), client=StubClient())

        investigation = restarted.next(investigation["id"], "restart-next", investigation["version"])

        self.assertEqual(investigation["plan"][0]["status"], "completed")
        self.assertTrue(investigation["runtime"]["degraded"])
        self.assertIn("interrupted", investigation["runtime"]["fallback_reason"])

    def test_follow_up_uses_memory_and_only_known_citations(self) -> None:
        investigation = self.create()
        for index in range(4):
            investigation = self.advance(investigation, f"follow-next-{index}")

        investigation = self.service.message(
            investigation["id"], "message-1", investigation["version"], "Why not expand the pool?"
        )

        known = {item["id"] for item in investigation["evidence"]}
        assistant = investigation["messages"][-1]
        self.assertEqual(investigation["messages"][-2]["role"], "user")
        self.assertEqual(assistant["role"], "assistant")
        self.assertTrue(assistant["evidence_ids"])
        self.assertLessEqual(set(assistant["evidence_ids"]), known)

    def test_approval_is_audit_only_and_decisions_are_immutable(self) -> None:
        investigation = self.create()
        for index in range(4):
            investigation = self.advance(investigation, f"decision-next-{index}")
        action = investigation["proposed_actions"][0]

        investigation = self.service.decision(
            investigation["id"], "approve-1", investigation["version"], action["id"], "approved", "operator reviewed"
        )
        decided = next(item for item in investigation["proposed_actions"] if item["id"] == action["id"])
        self.assertEqual(decided["approval_status"], "approved")
        self.assertTrue(decided["simulation_only"])
        self.assertIn("command_preview", decided)

        with self.assertRaisesRegex(AgentError, "already decided") as repeated:
            self.service.decision(
                investigation["id"], "approve-2", investigation["version"], action["id"], "rejected", None
            )
        self.assertEqual(repeated.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
