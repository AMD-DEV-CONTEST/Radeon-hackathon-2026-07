from __future__ import annotations

import json
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from radeonstay.auth import LocalIdentityProvider  # noqa: E402
from radeonstay.contracts import (  # noqa: E402
    AgentPlan,
    ChatRequest,
    ConfirmRequest,
    PlanStep,
)
from radeonstay.domain import (  # noqa: E402
    HotelService,
    HotelStore,
    PermissionDenied,
    ValidationError,
    actor_reference,
    build_tool_registry,
)
from radeonstay.orchestrator import RadeonStayService  # noqa: E402
from radeonstay.planning import DeterministicPlanner  # noqa: E402
from radeonstay.retrieval import PolicyChunk, PolicyRetriever  # noqa: E402


class FixedPlanner:
    backend_name = "fixed-unittest-planner"

    def __init__(self, plan: AgentPlan) -> None:
        self.plan = plan
        self.calls: list[dict[str, Any]] = []

    def create_plan(
        self,
        message: str,
        *,
        policy_context: str,
        tool_specs: list[dict[str, Any]],
        conversation_summary: str = "",
    ) -> AgentPlan:
        self.calls.append(
            {
                "message": message,
                "policy_context": policy_context,
                "tool_specs": tool_specs,
                "conversation_summary": conversation_summary,
            }
        )
        return self.plan.model_copy(deep=True)


class RecordingAnswerModel:
    backend_name = "recording-answer-model"

    def __init__(
        self,
        *,
        citation_ids: list[str] | None = None,
        raw_content: str | None = None,
    ) -> None:
        self.messages: list[dict[str, str]] = []
        self.closed = False
        self.citation_ids = ["c1"] if citation_ids is None else citation_ids
        self.raw_content = raw_content
        self.trace_active = False
        self.trace_calls: list[dict[str, Any]] = []
        self.trace_start_count = 0
        self.trace_finish_count = 0
        self.trace_errors: list[str] = []

    def chat(self, messages, **kwargs):
        del kwargs
        self.messages = messages
        if self.trace_active:
            self.trace_calls.append({"ok": True})
        content = self.raw_content
        if content is None:
            content = json.dumps({"citation_ids": self.citation_ids})
        return SimpleNamespace(
            content=content,
        )

    def start_trace(self) -> None:
        self.trace_start_count += 1
        self.trace_active = True
        self.trace_calls = []

    def finish_trace(self) -> list[dict[str, Any]]:
        self.trace_finish_count += 1
        calls = list(self.trace_calls)
        self.trace_calls = []
        self.trace_active = False
        return calls

    def mark_last_trace_error(self, error: Exception) -> None:
        self.trace_errors.append(type(error).__name__)
        if self.trace_calls:
            self.trace_calls[-1]["ok"] = False
            self.trace_calls[-1]["error_type"] = type(error).__name__

    def health(self):
        return {"ok": True, "backend": self.backend_name}

    def close(self) -> None:
        self.closed = True


def multi_policy_retriever() -> PolicyRetriever:
    return PolicyRetriever(
        [
            PolicyChunk(
                document=f"Test Policy {index}",
                section="Room Holds",
                text=f"Hold a standard room policy evidence {index}.",
                source_path=f"memory://test-policy-{index}",
                ordinal=index,
            )
            for index in range(1, 5)
        ]
    )


def room_hold_plan() -> AgentPlan:
    return AgentPlan(
        objective="Read local inventory and prepare one room hold.",
        response_language="English",
        steps=[
            PlanStep(
                step_id="availability",
                tool="hotel.check_availability",
                arguments={
                    "check_in": "2030-09-10",
                    "check_out": "2030-09-12",
                    "guests": 2,
                    "room_type": "standard",
                },
                reason="Read authoritative local room inventory first.",
            ),
            PlanStep(
                step_id="hold",
                tool="hotel.hold_booking",
                arguments={
                    "check_in": "2030-09-10",
                    "check_out": "2030-09-12",
                    "guests": 2,
                    "room_type": "standard",
                },
                reason="Prepare the requested hold without executing it silently.",
                depends_on=["availability"],
            ),
        ],
    )


class RadeonStayOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = HotelStore(":memory:")
        self.store.initialize(seed=True)
        registry = build_tool_registry(HotelService(self.store))

        self.identity = LocalIdentityProvider(
            "orchestrator-unittest-identity-secret"
        )
        self.alice_token = self.identity.issue(user_id="guest-alice", role="guest")
        self.bob_token = self.identity.issue(user_id="guest-bob", role="guest")
        self.staff_token = self.identity.issue(user_id="staff-sofia", role="staff")

        self.planner = FixedPlanner(room_hold_plan())
        retriever = PolicyRetriever(
            [
                PolicyChunk(
                    document="Test Hotel Policy",
                    section="Room Holds",
                    text=(
                        "Room availability and reservation holds are checked locally. "
                        "A write requires explicit guest confirmation."
                    ),
                    source_path="memory://test-policy",
                    ordinal=0,
                )
            ]
        )
        self.service = RadeonStayService(
            identity_provider=self.identity,
            registry=registry,
            retriever=retriever,
            planner=self.planner,
            audit_secret="orchestrator-unittest-audit-secret",
            answer_model=None,
        )

    def tearDown(self) -> None:
        self.service.close()

    def start_hold(
        self,
        *,
        session_id: str = "session-hold",
        request_id: str = "request-hold",
    ):
        return self.service.chat(
            ChatRequest(
                session_id=session_id,
                request_id=request_id,
                identity_token=self.alice_token,
                message="Hold a standard room from 2030-09-10 to 2030-09-12.",
            )
        )

    def test_read_pending_confirm_and_idempotent_confirmation_replay(self) -> None:
        response = self.start_hold()
        receipts = {receipt.tool: receipt for receipt in response.receipts}

        self.assertEqual(receipts["hotel.check_availability"].status, "ok")
        self.assertEqual(
            receipts["hotel.check_availability"].data["items"][0]["available_rooms"],
            8,
        )
        self.assertEqual(receipts["hotel.hold_booking"].status, "pending_confirmation")
        self.assertEqual(len(response.pending_actions), 1)
        pending = response.pending_actions[0]
        self.assertEqual(pending.tool, "hotel.hold_booking")
        self.assertEqual(pending.session_id, "session-hold")
        self.assertEqual(pending.preview_data["total_cents"], 25_800)
        self.assertEqual(pending.preview_data["currency"], "CNY")
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM confirmation_tokens"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM idempotency_records"
            ).fetchone()[0],
            0,
        )

        confirmation = ConfirmRequest(
            session_id="session-hold",
            identity_token=self.alice_token,
            confirmation_token=pending.token,
        )
        completed = self.service.confirm(confirmation)
        self.assertEqual(completed.status, "ok")
        self.assertEqual(completed.tool, "hotel.hold_booking")
        self.assertEqual(completed.data["booking"]["status"], "held")

        events_before_replay = self.service.audit_events(
            "session-hold", self.alice_token
        )
        replayed = self.service.confirm(confirmation)
        events_after_replay = self.service.audit_events(
            "session-hold", self.alice_token
        )

        self.assertEqual(replayed.model_dump(), completed.model_dump())
        self.assertEqual(len(events_after_replay), len(events_before_replay))
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM idempotency_records"
            ).fetchone()[0],
            1,
        )

    def test_chinese_modify_preview_shows_old_new_and_delta_prices(self) -> None:
        held = self.start_hold(session_id="session-modify-preview")
        completed = self.service.confirm(
            ConfirmRequest(
                session_id="session-modify-preview",
                identity_token=self.alice_token,
                confirmation_token=held.pending_actions[0].token,
            )
        )
        booking_id = completed.data["booking"]["booking_id"]
        self.service.planner = FixedPlanner(
            AgentPlan(
                objective="Preview a one-night extension in Chinese.",
                response_language="中文",
                steps=[
                    PlanStep(
                        step_id="modify",
                        tool="hotel.modify_booking",
                        arguments={
                            "booking_id": booking_id,
                            "check_out": "2030-09-13",
                        },
                        reason="Show the authoritative price change before confirmation.",
                    )
                ],
            )
        )

        response = self.service.chat(
            ChatRequest(
                session_id="session-modify-preview",
                request_id="request-modify-preview",
                identity_token=self.alice_token,
                message="把退房日期改到 2030-09-13，先给我确认价格。",
            )
        )

        self.assertEqual(len(response.pending_actions), 1)
        pending = response.pending_actions[0]
        self.assertEqual(pending.preview_data["current"]["total_cents"], 25_800)
        self.assertEqual(pending.preview_data["proposed"]["total_cents"], 38_700)
        self.assertEqual(pending.preview_data["price_delta_cents"], 12_900)
        self.assertIn("总价 CNY 258.00", response.answer)
        self.assertIn("总价 CNY 387.00", response.answer)
        self.assertIn("价差 +CNY 129.00", response.answer)

    def test_modify_confirmation_rejects_stale_authoritative_price(self) -> None:
        held = self.start_hold(session_id="session-stale-modify")
        completed = self.service.confirm(
            ConfirmRequest(
                session_id="session-stale-modify",
                identity_token=self.alice_token,
                confirmation_token=held.pending_actions[0].token,
            )
        )
        booking_id = completed.data["booking"]["booking_id"]
        self.service.planner = FixedPlanner(
            AgentPlan(
                objective="Preview a one-night extension.",
                steps=[
                    PlanStep(
                        step_id="modify",
                        tool="hotel.modify_booking",
                        arguments={
                            "booking_id": booking_id,
                            "check_out": "2030-09-13",
                        },
                        reason="Require a fresh confirmation for authoritative terms.",
                    )
                ],
            )
        )
        preview = self.service.chat(
            ChatRequest(
                session_id="session-stale-modify",
                request_id="request-stale-modify",
                identity_token=self.alice_token,
                message="Extend this stay by one night.",
            )
        )
        self.assertEqual(
            preview.pending_actions[0].preview_data["proposed"]["total_cents"],
            38_700,
        )

        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE rooms SET nightly_rate_cents = 13900 WHERE room_type = 'standard'"
            )

        with self.assertRaisesRegex(PermissionDenied, "authoritative preview terms changed"):
            self.service.confirm(
                ConfirmRequest(
                    session_id="session-stale-modify",
                    identity_token=self.alice_token,
                    confirmation_token=preview.pending_actions[0].token,
                )
            )
        row = self.store.connection.execute(
            "SELECT check_out, total_cents FROM bookings WHERE booking_id = ?",
            (booking_id,),
        ).fetchone()
        self.assertEqual(
            (row["check_out"], row["total_cents"]),
            ("2030-09-12", 25_800),
        )
        token_row = self.store.connection.execute(
            "SELECT used_at FROM confirmation_tokens WHERE used_at IS NULL"
        ).fetchone()
        self.assertIsNotNone(token_row)
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM idempotency_records"
            ).fetchone()[0],
            1,
        )

        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE rooms SET nightly_rate_cents = 12900 WHERE room_type = 'standard'"
            )
        confirm_request = ConfirmRequest(
            session_id="session-stale-modify",
            identity_token=self.alice_token,
            confirmation_token=preview.pending_actions[0].token,
        )
        confirmed = self.service.confirm(confirm_request)
        self.assertEqual(confirmed.data["booking"]["check_out"], "2030-09-13")
        self.assertEqual(confirmed.data["booking"]["total_cents"], 38_700)
        self.assertEqual(
            self.service.confirm(confirm_request).model_dump(),
            confirmed.model_dump(),
        )

    def test_confirmation_rejects_wrong_identity_and_wrong_session(self) -> None:
        response = self.start_hold(session_id="session-owned-by-alice")
        token = response.pending_actions[0].token

        with self.assertRaises(PermissionDenied):
            self.service.confirm(
                ConfirmRequest(
                    session_id="session-owned-by-alice",
                    identity_token=self.bob_token,
                    confirmation_token=token,
                )
            )

        with self.assertRaises(ValidationError):
            self.service.confirm(
                ConfirmRequest(
                    session_id="different-alice-session",
                    identity_token=self.alice_token,
                    confirmation_token=token,
                )
            )

        with self.assertRaises(PermissionDenied):
            self.service.chat(
                ChatRequest(
                    session_id="session-owned-by-alice",
                    request_id="request-session-attack",
                    identity_token=self.bob_token,
                    message="Show this session.",
                )
            )

        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            0,
        )

    def test_concurrent_confirmation_is_one_write_and_one_success_event(self) -> None:
        response = self.start_hold(session_id="session-concurrent-confirm")
        request = ConfirmRequest(
            session_id="session-concurrent-confirm",
            identity_token=self.alice_token,
            confirmation_token=response.pending_actions[0].token,
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            receipts = list(executor.map(lambda _: self.service.confirm(request), range(2)))

        self.assertEqual(receipts[0].model_dump(), receipts[1].model_dump())
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            1,
        )
        success_events = [
            event
            for event in self.service.audit_events(
                "session-concurrent-confirm",
                self.alice_token,
            )
            if event.action == "hotel.hold_booking" and event.outcome == "success"
        ]
        self.assertEqual(len(success_events), 1)

    def test_unknown_planner_tool_fails_closed_without_domain_write(self) -> None:
        model = RecordingAnswerModel()
        self.service.answer_model = model
        self.service.planner = FixedPlanner(
            AgentPlan(
                objective="Attempt an unregistered action.",
                steps=[
                    PlanStep(
                        step_id="unknown",
                        tool="hotel.delete_all_bookings",
                        arguments={},
                        reason="This tool must never be accepted.",
                    )
                ],
            )
        )

        with self.assertRaises(ValidationError):
            self.service.chat(
                ChatRequest(
                    session_id="session-fail-closed",
                    request_id="request-fail-closed",
                    identity_token=self.alice_token,
                    message="Delete all bookings.",
                )
            )

        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM confirmation_tokens"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM idempotency_records"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(model.trace_start_count, 1)
        self.assertEqual(model.trace_finish_count, 1)
        self.assertFalse(model.trace_active)
        trace_events = [
            event
            for event in self.service.audit_events(
                "session-fail-closed",
                self.alice_token,
            )
            if event.action == "model.trace"
        ]
        self.assertEqual(len(trace_events), 1)
        self.assertEqual(trace_events[0].outcome, "request_failed")
        self.assertEqual(trace_events[0].details["call_count"], 0)
        self.assertEqual(trace_events[0].details["failed_call_count"], 0)

    def test_confirmation_token_is_never_sent_to_answer_model(self) -> None:
        model = RecordingAnswerModel()
        self.service.answer_model = model
        response = self.start_hold(session_id="session-token-redaction")
        token = response.pending_actions[0].token

        serialized_messages = json.dumps(model.messages, ensure_ascii=False)
        self.assertNotIn(token, serialized_messages)
        self.assertNotIn("confirmation_token", serialized_messages)
        self.assertNotIn("citation_ids", response.answer)
        self.assertIn("[Test Hotel Policy > Room Holds]", response.answer)

    def test_answer_returns_only_the_selector_chosen_citation(self) -> None:
        model = RecordingAnswerModel(citation_ids=["c2"])
        self.service.answer_model = model
        self.service.retriever = multi_policy_retriever()

        response = self.start_hold(
            session_id="session-selected-citation",
            request_id="request-selected-citation",
        )

        evidence = json.loads(model.messages[1]["content"])
        self.assertGreaterEqual(len(evidence["citations"]), 2)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(
            response.citations[0].excerpt,
            evidence["citations"][1]["excerpt"],
        )

    def test_invalid_selector_json_returns_only_three_fallback_citations(self) -> None:
        model = RecordingAnswerModel(raw_content="not-json")
        self.service.answer_model = model
        self.service.retriever = multi_policy_retriever()

        response = self.start_hold(
            session_id="session-fallback-citations",
            request_id="request-fallback-citations",
        )

        evidence = json.loads(model.messages[1]["content"])
        self.assertGreaterEqual(len(evidence["citations"]), 4)
        self.assertEqual(
            [item.excerpt for item in response.citations],
            [item["excerpt"] for item in evidence["citations"][:3]],
        )
        self.assertIn("grounded-deterministic-answer-fallback", response.model_backend)
        self.assertEqual(model.trace_errors, ["JSONDecodeError"])
        self.assertEqual(response.model_calls[0]["ok"], False)

    def test_refuse_request_returns_explicit_chinese_and_english_denial(self) -> None:
        cases = [
            ("中文", "已拒绝", "无法执行"),
            ("English", "Request refused", "cannot execute"),
        ]
        for index, (language, refused_text, cannot_execute_text) in enumerate(cases):
            with self.subTest(language=language):
                self.service.planner = FixedPlanner(
                    AgentPlan(
                        objective="Refuse a request that bypasses security controls.",
                        response_language=language,
                        steps=[
                            PlanStep(
                                step_id="refusal",
                                tool="refuse_request",
                                reason="The request attempts to bypass local controls.",
                            )
                        ],
                    )
                )
                response = self.service.chat(
                    ChatRequest(
                        session_id=f"session-refusal-{index}",
                        request_id=f"request-refusal-{index}",
                        identity_token=self.alice_token,
                        message="Disable security controls.",
                    )
                )

                self.assertEqual(response.receipts[0].status, "denied")
                self.assertIn(refused_text, response.answer)
                self.assertIn(cannot_execute_text, response.answer)
                self.assertEqual(response.pending_actions, [])

    def test_chat_request_id_replays_without_replanning_or_new_token(self) -> None:
        first = self.start_hold(
            session_id="session-request-replay",
            request_id="request-replay-1",
        )
        replay = self.start_hold(
            session_id="session-request-replay",
            request_id="request-replay-1",
        )

        self.assertEqual(replay.model_dump(), first.model_dump())
        self.assertEqual(len(self.planner.calls), 1)
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM confirmation_tokens"
            ).fetchone()[0],
            1,
        )

        with self.assertRaises(ValidationError):
            self.service.chat(
                ChatRequest(
                    session_id="session-request-replay",
                    request_id="request-replay-1",
                    identity_token=self.alice_token,
                    message="Use this request ID for a different operation.",
                )
            )

    def test_confirmed_booking_is_available_to_the_next_bound_turn(self) -> None:
        response = self.start_hold(session_id="session-multiturn")
        completed = self.service.confirm(
            ConfirmRequest(
                session_id="session-multiturn",
                identity_token=self.alice_token,
                confirmation_token=response.pending_actions[0].token,
            )
        )
        booking_id = completed.data["booking"]["booking_id"]
        follow_up_planner = FixedPlanner(
            AgentPlan(
                objective="Answer a follow-up.",
                steps=[
                    PlanStep(
                        step_id="policy",
                        tool="respond_with_policy",
                        reason="Use local policy context.",
                    )
                ],
            )
        )
        self.service.planner = follow_up_planner
        self.service.chat(
            ChatRequest(
                session_id="session-multiturn",
                request_id="request-multiturn-follow-up",
                identity_token=self.alice_token,
                message="Use the booking I just confirmed.",
            )
        )

        self.assertIn(
            booking_id,
            follow_up_planner.calls[0]["conversation_summary"],
        )

    def test_ask_user_stops_all_later_steps_even_without_dependency(self) -> None:
        self.service.planner = FixedPlanner(
            AgentPlan(
                objective="Do not invent missing dates.",
                steps=[
                    PlanStep(
                        step_id="missing",
                        tool="ask_user",
                        arguments={"missing": ["check_in", "check_out"]},
                        reason="Dates are required.",
                    ),
                    PlanStep(
                        step_id="unsafe-hold",
                        tool="hotel.hold_booking",
                        arguments={
                            "room_type": "standard",
                            "check_in": "2030-01-01",
                            "check_out": "2030-01-02",
                            "guests": 1,
                        },
                        reason="This must be blocked until the user responds.",
                    ),
                ],
            )
        )
        response = self.service.chat(
            ChatRequest(
                session_id="session-needs-input",
                request_id="request-needs-input",
                identity_token=self.alice_token,
                message="Book a room without dates.",
            )
        )

        self.assertEqual(response.receipts[0].status, "needs_input")
        self.assertEqual(response.receipts[1].status, "error")
        self.assertEqual(response.pending_actions, [])
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM confirmation_tokens"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM idempotency_records"
            ).fetchone()[0],
            0,
        )

    def test_guest_scoped_audit_chain_is_valid_and_private(self) -> None:
        response = self.start_hold(session_id="session-audit")
        self.service.confirm(
            ConfirmRequest(
                session_id="session-audit",
                identity_token=self.alice_token,
                confirmation_token=response.pending_actions[0].token,
            )
        )

        events = self.service.audit_events("session-audit", self.alice_token)
        self.assertGreaterEqual(len(events), 6)
        self.assertTrue(all(event.chain_valid for event in events))
        self.assertEqual(events[0].previous_hash, "0" * 64)
        for previous, current in zip(events, events[1:]):
            self.assertEqual(current.previous_hash, previous.event_hash)
        self.assertEqual(
            {event.actor_ref for event in events},
            {actor_reference("guest-alice")},
        )

        serialized = json.dumps(
            [event.model_dump(mode="json") for event in events],
            ensure_ascii=False,
        )
        self.assertNotIn("guest-alice", serialized)
        self.assertNotIn(self.alice_token, serialized)
        self.assertNotIn(response.pending_actions[0].token, serialized)

        with self.assertRaises(PermissionDenied):
            self.service.audit_events("session-audit", self.bob_token)
        staff_view = self.service.audit_events("session-audit", self.staff_token)
        self.assertEqual(
            [event.event_hash for event in staff_view],
            [event.event_hash for event in events],
        )

    def test_deterministic_planner_preserves_explicit_dates_and_tool_names(self) -> None:
        planner = DeterministicPlanner()
        plan = planner.create_plan(
            "Please hold a room from 2031-01-15 to 2031-01-18.",
            policy_context="ignored",
            tool_specs=[],
            conversation_summary="ignored",
        )

        self.assertEqual(
            [step.tool for step in plan.steps],
            [
                "respond_with_policy",
                "hotel.check_availability",
                "hotel.quote_stay",
                "hotel.hold_booking",
            ],
        )
        for step in plan.steps[1:]:
            self.assertEqual(step.arguments["check_in"], "2031-01-15")
            self.assertEqual(step.arguments["check_out"], "2031-01-18")
        self.assertEqual(
            plan.steps[2].arguments["room_type"],
            "{{availability.items.0.room_type}}",
        )
        self.assertEqual(plan.steps[3].arguments["room_type"], "{{quote.room_type}}")

        missing_dates = planner.create_plan(
            "Please hold a room.",
            policy_context="ignored",
            tool_specs=[],
            conversation_summary="ignored",
        )
        self.assertEqual(
            [step.tool for step in missing_dates.steps],
            ["respond_with_policy", "ask_user"],
        )
        self.assertEqual(
            missing_dates.steps[-1].arguments["missing"],
            ["check_in", "check_out"],
        )

    def test_deterministic_plan_references_execute_through_pending_hold(self) -> None:
        self.service.planner = DeterministicPlanner()
        response = self.service.chat(
            ChatRequest(
                session_id="session-deterministic",
                request_id="request-deterministic",
                identity_token=self.alice_token,
                message="请保留 2031-03-10 到 2031-03-12 的房间。",
            )
        )

        self.assertEqual(
            [receipt.status for receipt in response.receipts],
            ["ok", "ok", "ok", "pending_confirmation"],
        )
        self.assertEqual(response.pending_actions[0].arguments["room_type"], "standard")
        self.assertIn("权威总价 CNY 258.00", response.answer)


if __name__ == "__main__":
    unittest.main()
