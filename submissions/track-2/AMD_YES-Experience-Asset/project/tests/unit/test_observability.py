from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from app.experience_asset.observability import JsonlTraceSink, TraceEventV1


def test_raw_content_is_removed_from_default_trace(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    sink = JsonlTraceSink(path)
    sanitized = sink.emit(
        TraceEventV1(
            event_id=uuid4(),
            run_id=uuid4(),
            event_type="model.completed",
            occurred_at=datetime.now(UTC),
            attributes={
                "model_id": "Qwen/Qwen2.5-14B-Instruct",
                "elapsed_ms": 123,
                "raw_prompt": "private prompt",
                "raw_response": "private response",
                "source_excerpt": "private source",
            },
        )
    )
    assert sanitized.attributes == {
        "model_id": "Qwen/Qwen2.5-14B-Instruct",
        "elapsed_ms": 123,
    }
    assert sanitized.redacted_fields == ["raw_prompt", "raw_response", "source_excerpt"]
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert "private" not in json.dumps(persisted)
