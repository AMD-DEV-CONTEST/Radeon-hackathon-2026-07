from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from buildguard.integration.realtime_slow_loop import RealtimeSlowLoop
from buildguard.realtime.schemas import EventState, RealtimeRiskEvent
from buildguard.schemas.common import BoundingBox, Severity
from buildguard.storage.database import Database
from buildguard.storage.memory import LongTermMemory
from buildguard.vision.conditional_pipeline import ConditionalVisionPublicResult


def test_verified_facts_are_persistent_and_session_clear_is_bounded(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "buildguard.db")
    memory = LongTermMemory(database)
    session_id = "session-facts"
    memory.add_message(session_id, "user", "remember this")
    memory.create_task(session_id, "inspection", "test task")

    fact = memory.add_verified_fact(
        session_id,
        subject="zone-a",
        predicate="requires",
        object_text="helmet",
        source_kind="inspection",
        source_id="inspection-1",
        confidence=0.95,
    )

    assert memory.list_verified_facts(session_id)[0]["object"] == "helmet"
    assert memory.deactivate_verified_fact(session_id, fact["id"])
    assert memory.list_verified_facts(session_id) == []
    assert len(memory.list_verified_facts(session_id, active_only=False)) == 1

    counts = memory.clear_session(session_id)
    assert counts["sessions"] == 1
    assert counts["verified_facts"] == 1
    assert counts["messages"] == 1
    assert counts["tasks"] == 1
    assert memory.list_sessions() == []
    database.dispose()


def test_realtime_slow_loop_starts_lazily_and_drains() -> None:
    handled = threading.Event()
    received: list[str] = []

    def handler(event: RealtimeRiskEvent) -> None:
        received.append(event.id)
        handled.set()

    loop = RealtimeSlowLoop(handler)
    assert loop.thread is None
    now = datetime.now(UTC)
    event = RealtimeRiskEvent(
        camera_id="camera-1",
        event_type="missing_helmet",
        status=EventState.ACTIVE,
        severity=Severity.HIGH,
        started_at=now,
        last_seen_at=now,
        max_confidence=0.9,
        region=BoundingBox(x1=1, y1=1, x2=20, y2=20),
    )

    loop.submit(event)
    assert handled.wait(timeout=2)
    loop.close()

    assert received == [event.id]
    assert loop.metrics() == {
        "queue_length": 0,
        "accepted": 1,
        "completed": 1,
        "failed": 0,
    }


def test_conditional_vision_public_schema_is_json_serializable() -> None:
    schema = ConditionalVisionPublicResult.model_json_schema()
    assert "properties" in schema
    assert "masks" in schema["properties"]
