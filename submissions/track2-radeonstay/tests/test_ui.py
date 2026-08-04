from __future__ import annotations

from radeonstay.domain import PermissionDenied
from radeonstay.ui import (
    _confirmation_is_permanently_invalid,
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
