from __future__ import annotations

import json
import logging
import math
import os
from copy import deepcopy

import pytest

from specstyle.domain.identifiers import Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.observability import json_logging
from specstyle.observability.json_logging import (
    LogEvent,
    PublicLogText,
    SafeJsonFilter,
    SafeJsonFormatter,
    sanitize_log_value,
)
from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    AttemptId,
    DecisionId,
    JobId,
    RuleId,
)


def _record(msg: object = LogEvent("EVENT"), **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        "specstyle.generation", logging.INFO, "x", 1, msg, (), None
    )
    record.created = 0.0
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class PathLike:
    calls = {"str": 0, "repr": 0}

    def __str__(self) -> str:
        type(self).calls["str"] += 1
        return "PATHLIKE_DECOY"

    def __repr__(self) -> str:
        type(self).calls["repr"] += 1
        return "PATHLIKE_DECOY"


class MaliciousText:
    calls = {"str": 0, "repr": 0}

    def __str__(self) -> str:
        type(self).calls["str"] += 1
        return "MALICIOUS_DECOY"

    def __repr__(self) -> str:
        type(self).calls["repr"] += 1
        return "MALICIOUS_DECOY"


def test_formatter_emits_canonical_golden_json_without_global_mutation() -> None:
    formatter = SafeJsonFormatter()
    before = logging.root.handlers[:]
    rendered = formatter.format(
        _record(safe_context={"attempt_id": 4, "label": PublicLogText("safe")})
    )
    assert rendered == (
        '{"schema_version":"1.0","timestamp":"1970-01-01T00:00:00.000Z",'
        '"level":"INFO","logger":"specstyle.generation","event":"EVENT",'
        '"context":{"attempt_id":4,"label":"safe"}}'
    )
    assert logging.root.handlers == before


def test_formatter_canonicalizes_root_and_nested_context_key_order() -> None:
    formatter = SafeJsonFormatter()
    forward = {"alpha": {"beta": 1, "gamma": 2}, "zeta": 3}
    reverse = {"zeta": 3, "alpha": {"gamma": 2, "beta": 1}}
    rendered = formatter.format(_record(safe_context=forward))
    assert rendered == formatter.format(_record(safe_context=reverse))
    assert rendered == (
        '{"schema_version":"1.0","timestamp":"1970-01-01T00:00:00.000Z",'
        '"level":"INFO","logger":"specstyle.generation","event":"EVENT",'
        '"context":{"alpha":{"beta":1,"gamma":2},"zeta":3}}'
    )


def test_formatter_fallback_emits_exact_compact_canonical_json() -> None:
    assert SafeJsonFormatter().format(_record("raw")) == (
        '{"schema_version":"1.0","timestamp":null,"level":"ERROR",'
        '"logger":"specstyle","event":"LOG_RECORD_REDACTED","context":{}}'
    )


@pytest.mark.parametrize(
    "value", ["raw text", b"bytes", PathLike(), MaliciousText(), RuntimeError("secret")]
)
def test_sanitizer_fail_closes_unsupported_values_without_stringifying(
    value: object,
) -> None:
    rendered = sanitize_log_value(value)
    assert rendered == "[REDACTED_UNSUPPORTED]"
    if type(value) is PathLike:
        assert PathLike.calls == {"str": 0, "repr": 0}
        assert "PATHLIKE_DECOY" not in rendered
    if type(value) is MaliciousText:
        assert MaliciousText.calls == {"str": 0, "repr": 0}
        assert "MALICIOUS_DECOY" not in rendered


def test_sanitizer_does_not_recurse_into_invalid_or_sensitive_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker_a = object()
    marker_b = object()
    sensitive_marker = object()
    entered: set[int] = set()
    real_sanitize = json_logging._sanitize

    def tracked_sanitize(
        value: object, depth: int, nodes: list[int], active: set[int]
    ) -> object:
        if value is marker_a or value is marker_b or value is sensitive_marker:
            entered.add(id(value))
        return real_sanitize(value, depth, nodes, active)

    monkeypatch.setattr(json_logging, "_sanitize", tracked_sanitize)
    assert (
        sanitize_log_value({"alpha": marker_a, "bad-key": marker_b})
        == "[REDACTED_CONTAINER]"
    )
    assert entered == set()
    assert sanitize_log_value({"api_token": sensitive_marker}) == {
        "api_token": "[REDACTED_SENSITIVE]"
    }
    assert entered == set()


def test_sanitizer_redacts_sensitive_keys_and_container_violations() -> None:
    assert sanitize_log_value({"api_token": PathLike()}) == {
        "api_token": "[REDACTED_SENSITIVE]"
    }
    assert sanitize_log_value({"bad-key": 1}) == "[REDACTED_CONTAINER]"
    assert (
        sanitize_log_value({str(index): index for index in range(65)})
        == "[REDACTED_CONTAINER]"
    )


def test_sanitizer_handles_cycle_shared_depth_and_finite_numbers() -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    shared = [1]
    nested: object = 0
    for _ in range(7):
        nested = [nested]
    assert sanitize_log_value(cycle) == ["[REDACTED_CYCLE]"]
    assert sanitize_log_value([shared, shared]) == [[1], [1]]
    redacted = sanitize_log_value(nested)
    for _ in range(7):
        assert type(redacted) is list
        redacted = redacted[0]
    assert redacted == "[REDACTED_DEPTH]"
    assert sanitize_log_value(math.nan) == "[REDACTED_UNSUPPORTED]"


@pytest.mark.parametrize(
    "text",
    [
        " secret=x",
        "Bearer abc",
        "/private/a",
        "https://u:p@host/x",
        "https://host/x?q=y",
    ],
)
def test_public_log_text_rejects_secrets_urls_and_paths(text: str) -> None:
    with pytest.raises(DomainError):
        PublicLogText(text)


def test_filter_and_formatter_fallback_for_raw_message_args_and_exception() -> None:
    filter_ = SafeJsonFilter()
    formatter = SafeJsonFormatter()
    for record in (_record("raw"), _record(LogEvent("EVENT"), safe_context={"x": 1})):
        record.args = ("bad",)
        assert not filter_.filter(record)
        assert json.loads(formatter.format(record))["event"] == "LOG_RECORD_REDACTED"
    exceptional = _record()
    exceptional.exc_info = (RuntimeError, RuntimeError("secret"), None)
    assert not filter_.filter(exceptional)


def test_filter_rejects_invalid_event_logger_created_level_or_context() -> None:
    filter_ = SafeJsonFilter()
    for record in (_record(LogEvent("EVENT")), _record(LogEvent("EVENT"))):
        record.name = "bad logger!"
        assert not filter_.filter(record)
    record = _record(safe_context={"unsafe": "raw"})
    assert filter_.filter(record)
    record.safe_context = []
    assert not filter_.filter(record)
    record = _record()
    record.created = True
    assert not filter_.filter(record)


class EvilIdentifier(Identifier):
    calls = {"post_init": 0, "property": 0, "str": 0, "repr": 0}
    armed = False

    def __post_init__(self) -> None:
        if type(self).armed:
            type(self).calls["post_init"] += 1
            raise AssertionError("untrusted post-init hook")
        super().__post_init__()

    @property
    def hostile_property(self) -> str:
        type(self).calls["property"] += 1
        raise AssertionError("untrusted property hook")

    def __str__(self) -> str:
        type(self).calls["str"] += 1
        raise AssertionError("untrusted str hook")

    def __repr__(self) -> str:
        type(self).calls["repr"] += 1
        raise AssertionError("untrusted repr hook")

    def __getattribute__(self, name: str) -> object:
        if type(self).armed and name == "value":
            type(self).calls["property"] += 1
            raise AssertionError("untrusted subclass hook")
        return super().__getattribute__(name)


def test_sanitizer_rejects_identifier_subclass_without_accessing_hooks() -> None:
    evil = EvilIdentifier("safe-id")
    EvilIdentifier.calls = {"post_init": 0, "property": 0, "str": 0, "repr": 0}
    EvilIdentifier.armed = True
    assert sanitize_log_value(evil) == "[REDACTED_UNSUPPORTED]"
    assert EvilIdentifier.calls == {"post_init": 0, "property": 0, "str": 0, "repr": 0}


def test_sanitizer_revalidates_forged_exact_identifier_and_sha_values() -> None:
    forged_id = object.__new__(Identifier)
    object.__setattr__(forged_id, "value", "not valid!")
    forged_sha = object.__new__(Sha256)
    object.__setattr__(forged_sha, "value", "A" * 64)
    assert sanitize_log_value(forged_id) == "[REDACTED_UNSUPPORTED]"
    assert sanitize_log_value(forged_sha) == "[REDACTED_UNSUPPORTED]"


@pytest.mark.parametrize(
    "unsafe",
    [
        "note /private/path",
        "note ~/private",
        "note C:\\private",
        "note //server/share",
        r"note \\server\share",
        "bearer value",
        "password=value",
        "passwd=value",
        "secret=value",
        "token=value",
        "authorization=value",
        "credential=value",
        "cookie=value",
        "session=value",
        "api_key=value",
        "api-key=value",
        "apikey=value",
        "access_key=value",
        "access-key=value",
        "accesskey=value",
        "private_key=value",
        "private-key=value",
        "privatekey=value",
        "client_secret=value",
        "client-secret=value",
        "clientsecret=value",
        "ftp://user:pass@example.test/a",
        "http://user:pass@example.test/a",
        "https://host/a?q=x",
        "https://host/a#fragment",
        "http://[",
        "file://safe",
    ],
)
def test_public_log_text_rejects_every_unsafe_lexical_form(unsafe: str) -> None:
    with pytest.raises(DomainError, match="^public log text is unsafe$") as raised:
        PublicLogText(unsafe)
    assert unsafe not in str(raised.value)


@pytest.mark.parametrize("created", [1e308, 10**1000, math.nan, math.inf, -1, True])
def test_invalid_created_always_filters_and_formats_as_fallback(
    created: object,
) -> None:
    record = _record()
    record.created = created
    assert not SafeJsonFilter().filter(record)
    assert (
        json.loads(SafeJsonFormatter().format(record))["event"] == "LOG_RECORD_REDACTED"
    )


def test_formatter_rejects_forged_invalid_event_and_level() -> None:
    event = object.__new__(LogEvent)
    object.__setattr__(event, "value", "bad event")
    record = _record(event)
    assert not SafeJsonFilter().filter(record)
    assert (
        json.loads(SafeJsonFormatter().format(record))["event"] == "LOG_RECORD_REDACTED"
    )
    record = _record()
    record.levelname = "BAD"
    assert not SafeJsonFilter().filter(record)


def test_sanitizer_enforces_node_limit_without_mutating_input() -> None:
    source = list(range(129))
    sanitized = sanitize_log_value(source)
    assert source == list(range(129))
    assert sanitized == "[REDACTED_CONTAINER]"


def test_sanitizer_canonicalizes_64_key_nested_dicts_at_node_limit() -> None:
    forward = {
        f"key_{index:02d}": {"alpha": index, "beta": index} for index in range(64)
    }
    reverse = {
        f"key_{index:02d}": {"beta": index, "alpha": index}
        for index in reversed(range(64))
    }
    forward_primitive = sanitize_log_value(forward)
    reverse_primitive = sanitize_log_value(reverse)
    assert forward_primitive == reverse_primitive
    assert "[REDACTED_NODES]" in json.dumps(forward_primitive)
    formatter = SafeJsonFormatter()
    assert formatter.format(_record(safe_context=forward)) == formatter.format(
        _record(safe_context=reverse)
    )


def test_sanitizer_enforces_cumulative_node_limit_for_lists() -> None:
    source = [[index] for index in range(64)]
    result = sanitize_log_value(source)
    assert type(result) is list
    assert "[REDACTED_NODES]" in result[-1]


@pytest.mark.parametrize(
    "value_type",
    [
        Identifier,
        JobId,
        AssetId,
        AttemptId,
        ArtifactId,
        DecisionId,
        RuleId,
        Sha256,
        PublicLogText,
    ],
)
def test_sanitizer_fails_closed_for_uninitialized_exact_scalars(
    value_type: type[object],
) -> None:
    assert sanitize_log_value(object.__new__(value_type)) == "[REDACTED_UNSUPPORTED]"


@pytest.mark.parametrize(
    "value_type",
    [
        Identifier,
        JobId,
        AssetId,
        AttemptId,
        ArtifactId,
        DecisionId,
        RuleId,
        Sha256,
        PublicLogText,
    ],
)
def test_sanitizer_rejects_forced_illegal_exact_values(
    value_type: type[object],
) -> None:
    value = (
        Sha256("a" * 64)
        if value_type is Sha256
        else PublicLogText("safe")
        if value_type is PublicLogText
        else value_type("safe-id")
    )
    object.__setattr__(value, "value", "secret=private")
    assert sanitize_log_value(value) == "[REDACTED_UNSUPPORTED]"


def test_filter_rejects_publicly_constructed_then_forged_log_event() -> None:
    event = LogEvent("SAFE_EVENT")
    object.__setattr__(event, "value", "secret=private")
    record = _record(event)
    assert not SafeJsonFilter().filter(record)
    assert SafeJsonFormatter().format(record) == (
        '{"schema_version":"1.0","timestamp":null,"level":"ERROR",'
        '"logger":"specstyle","event":"LOG_RECORD_REDACTED","context":{}}'
    )


def test_filter_and_formatter_are_total_for_uninitialized_or_foreign_record() -> None:
    event = object.__new__(LogEvent)
    assert not SafeJsonFilter().filter(object())  # type: ignore[arg-type]
    assert not SafeJsonFilter().filter(_record(event))
    fallback = {
        "schema_version": "1.0",
        "timestamp": None,
        "level": "ERROR",
        "logger": "specstyle",
        "event": "LOG_RECORD_REDACTED",
        "context": {},
    }
    assert json.loads(SafeJsonFormatter().format(_record(event))) == fallback
    assert json.loads(SafeJsonFormatter().format(object())) == fallback  # type: ignore[arg-type]


def test_public_http_without_secret_parts_is_allowed() -> None:
    assert (
        PublicLogText("https://example.test/public").value
        == "https://example.test/public"
    )
    assert PublicLogText("http://example.test").value == "http://example.test"


def test_filter_rejects_exc_text_and_stack_info_without_mutation() -> None:
    for attribute in ("exc_text", "stack_info"):
        record = _record(safe_context={"nested": {"count": 1}})
        original_context = record.safe_context
        setattr(record, attribute, "private-secret")
        assert not SafeJsonFilter().filter(record)
        assert record.safe_context is original_context
        assert (
            json.loads(SafeJsonFormatter().format(record))["event"]
            == "LOG_RECORD_REDACTED"
        )


def test_sanitizer_text_key_and_numeric_boundaries() -> None:
    assert sanitize_log_value(-(2**63)) == -(2**63)
    assert sanitize_log_value(2**63 - 1) == 2**63 - 1
    assert sanitize_log_value(-(2**63) - 1) == "[REDACTED_UNSUPPORTED]"
    assert sanitize_log_value(2**63) == "[REDACTED_UNSUPPORTED]"
    assert sanitize_log_value(float("inf")) == "[REDACTED_UNSUPPORTED]"
    assert sanitize_log_value(float("-inf")) == "[REDACTED_UNSUPPORTED]"
    assert sanitize_log_value(float("nan")) == "[REDACTED_UNSUPPORTED]"
    assert sanitize_log_value({"a" * 64: 1}) == {"a" * 64: 1}
    assert sanitize_log_value({"a" * 65: 1}) == "[REDACTED_CONTAINER]"
    assert sanitize_log_value({1: "secret"}) == "[REDACTED_CONTAINER]"


def test_public_log_text_length_boundaries() -> None:
    assert PublicLogText("a" * 512).value == "a" * 512
    with pytest.raises(DomainError, match="^public log text is unsafe$"):
        PublicLogText("a" * 513)


def test_formatter_does_not_read_environment_or_mutate_nested_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def secret_environment(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return "private-token"

    context = {"nested": {"count": 1}}
    record = _record(safe_context=context)
    monkeypatch.setattr(os, "getenv", secret_environment)
    rendered = SafeJsonFormatter().format(record)
    assert calls == 0
    assert "private-token" not in rendered
    assert record.safe_context is context
    assert context == {"nested": {"count": 1}}


def test_filter_and_formatter_leave_complete_record_and_nested_context_unchanged() -> (
    None
):
    context = {"nested": {"values": [1, 2]}}
    record = _record(safe_context=context)
    before = deepcopy(record.__dict__)
    assert SafeJsonFilter().filter(record)
    assert json.loads(SafeJsonFormatter().format(record))["context"] == context
    assert record.__dict__ == before
    assert record.safe_context is context
