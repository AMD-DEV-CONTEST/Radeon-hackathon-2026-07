from __future__ import annotations

from types import SimpleNamespace

from radeonstay.domain import PermissionDenied
from radeonstay.ui import (
    _confirmation_is_permanently_invalid,
    _next_demo_prompt,
    _performance_display,
    _remaining_confirmations_after_error,
)


def test_stale_authoritative_preview_is_removed_from_ui_queue() -> None:
    error = PermissionDenied(
        "confirmation token is invalid, expired, mismatched, or its authoritative "
        "preview terms changed; request a fresh preview"
    )

    assert _confirmation_is_permanently_invalid(error)
    assert (
        _remaining_confirmations_after_error([{"token": "stale"}], "stale", error)
        == []
    )
    assert _remaining_confirmations_after_error(
        [{"token": "stale"}, {"token": "next"}],
        "stale",
        error,
    ) == [{"token": "next"}]


def test_retryable_confirmation_error_stays_in_ui_queue() -> None:
    error = ValueError("temporary database busy")
    pending = [{"token": "first"}, {"token": "second"}]

    assert not _confirmation_is_permanently_invalid(error)
    assert _remaining_confirmations_after_error(pending, "first", error) == [
        {"token": "second"},
        {"token": "first"},
    ]


def test_confirmed_hold_prefills_transfer_prompt_with_real_booking_id() -> None:
    receipt = SimpleNamespace(
        tool="hotel.hold_booking",
        data={"booking": {"booking_id": "RSV-REAL-123"}},
    )

    prompt = _next_demo_prompt(receipt)

    assert "RSV-REAL-123" in prompt
    assert "机场接送" in prompt
    assert "预览" in prompt
    assert "确认" in prompt


def test_confirmed_demo_writes_prefill_safe_next_steps() -> None:
    ticket_prompt = _next_demo_prompt(
        SimpleNamespace(tool="hotel.create_service_ticket", data={"ticket_id": "TKT-1"})
    )
    consent_prompt = _next_demo_prompt(
        SimpleNamespace(tool="memory.set_consent", data={"enabled": True})
    )
    preference_prompt = _next_demo_prompt(
        SimpleNamespace(
            tool="memory.remember_preference",
            data={"key": "quiet_room", "saved": True},
        )
    )

    assert "启用本地偏好记忆" in ticket_prompt
    assert "预览" in ticket_prompt and "确认" in ticket_prompt
    assert "quiet_room=high_floor" in consent_prompt
    assert "预览" in consent_prompt and "确认" in consent_prompt
    assert "只读" in preference_prompt
    assert "不要执行任何写操作" in preference_prompt


def test_performance_display_exposes_local_model_evidence() -> None:
    response = SimpleNamespace(
        model_backend="local-llm-planner; answer=validated-template",
        elapsed_ms=321.5,
        timings_ms={"planning": 200.0, "tools": 10.0},
        model_calls=[{"ok": True, "effective_output_tokens_per_second": 42.0}],
    )

    assert _performance_display(response) == {
        "model_backend": "local-llm-planner; answer=validated-template",
        "elapsed_ms": 321.5,
        "timings_ms": {"planning": 200.0, "tools": 10.0},
        "model_calls": [{"ok": True, "effective_output_tokens_per_second": 42.0}],
    }
