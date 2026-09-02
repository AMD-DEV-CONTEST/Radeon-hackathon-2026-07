"""Stage E — Unified error codes tests."""

import pytest

from app.observability.error_codes import APP_ERROR_CODES, get_error


# ── Error codes dictionary ─────────────────────────────────────────────────


def test_error_codes_cover_all_required_categories() -> None:
    """APP_ERROR_CODES includes codes for all Stage E error scenarios."""
    required = {
        "INTERNAL_ERROR",
        "NOT_FOUND",
        "PROJECT_NOT_FOUND",
        "PROJECT_ID_INVALID",
        "PROJECT_ALREADY_EXISTS",
        "RUN_NOT_FOUND",
        "RUN_ALREADY_EXECUTED",
        "RUN_ALREADY_CANCELLED",
        "RUN_CANCEL_TOO_LATE",
        "RUN_WRONG_STATUS",
        "FILE_TOO_LARGE",
        "FILE_EXTENSION_NOT_ALLOWED",
        "FILE_MIME_MISMATCH",
        "FILE_NAME_TOO_LONG",
        "FILE_EMPTY",
        "FILE_VIRUS_DETECTED",
        "VALIDATION_ERROR",
        "CLEANUP_PARTIAL_FAILURE",
    }
    assert set(APP_ERROR_CODES.keys()) >= required


def test_error_codes_have_consistent_structure() -> None:
    """Every error code has 'code', 'message', and 'user_message'."""
    for key, entry in APP_ERROR_CODES.items():
        assert "code" in entry, f"Missing 'code' in {key}"
        assert "message" in entry, f"Missing 'message' in {key}"
        assert "user_message" in entry, f"Missing 'user_message' in {key}"
        assert entry["code"] == key


def test_get_error_returns_known_code() -> None:
    """get_error returns structured error for known codes."""
    result = get_error("FILE_TOO_LARGE")
    assert result["error_code"] == "FILE_TOO_LARGE"
    assert result["message"] != ""
    assert result["user_message"] != ""


def test_get_error_returns_internal_error_for_unknown_code() -> None:
    """get_error falls back to INTERNAL_ERROR for unknown codes."""
    result = get_error("NONEXISTENT_CODE")
    assert result["error_code"] == "INTERNAL_ERROR"


def test_get_error_merges_extra_details() -> None:
    """Extra kwargs are merged into 'details' field."""
    result = get_error("FILE_TOO_LARGE", max_size="50MB", actual="120MB")
    assert result["error_code"] == "FILE_TOO_LARGE"
    assert "details" in result
    assert result["details"]["max_size"] == "50MB"
    assert result["details"]["actual"] == "120MB"


def test_error_codes_map_to_http_status_pattern() -> None:
    """Verify logical grouping of error codes for HTTP status mapping."""
    # 404 family
    not_found_codes = {"NOT_FOUND", "PROJECT_NOT_FOUND", "RUN_NOT_FOUND"}
    for code in not_found_codes:
        assert code in APP_ERROR_CODES

    # 422 family
    validation_codes = {
        "PROJECT_ID_INVALID", "VALIDATION_ERROR",
        "FILE_TOO_LARGE", "FILE_EXTENSION_NOT_ALLOWED",
        "FILE_MIME_MISMATCH", "FILE_NAME_TOO_LONG", "FILE_EMPTY",
    }
    for code in validation_codes:
        assert code in APP_ERROR_CODES

    # 409 family
    conflict_codes = {
        "PROJECT_ALREADY_EXISTS", "RUN_ALREADY_EXECUTED",
        "RUN_ALREADY_CANCELLED", "RUN_CANCEL_TOO_LATE",
    }
    for code in conflict_codes:
        assert code in APP_ERROR_CODES
