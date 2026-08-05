"""tests/test_pb_taxonomy.py — single-source-of-truth invariant for the
ProgramBench failure-family taxonomy.

Previously the same 19-family regex table lived in three files:
  - scripts/determinex_pb_taxonomy.py     (now THE source)
  - scripts/failure_classifier.py      (was duplicate; now re-exports)
  - scripts/run_ledger.py              (was duplicate; now lazy-imports)
  - scripts/mass_run_v2_aggregate.py   (was duplicate; now aliases)

If those copies drift the cockpit silently disagrees with itself: the monitor
might rank one family on top while the advisor / aggregator rank another. This
test makes that drift impossible to land without a failing CI gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `scripts/` importable like the cockpit does at runtime
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from determinex_pb_taxonomy import (  # noqa: E402
    FAMILY_NAMES,
    FAMILY_PATTERNS,
    INFRA,
    TIER_1,
    TIER_2,
    classify_one,
    classify_test_results,
    tier_of,
)

# ---------------------------------------------------------------------------
# Fixture — representative failure messages spanning the taxonomy
# ---------------------------------------------------------------------------

# (test_name, message, expected_family)
_FIXTURE: list[tuple[str, str, str]] = [
    (
        "test_unknown_flag_is_rejected[--bogus]",
        "AssertionError: assert 'unexpected argument' in 'tool: unknown option: --bogus\\n'",
        "rc_2_unknown_option",
    ),
    ("test_missing_input_arg", "tool: missing argument: <input>", "rc_2_missing_arg"),
    (
        "test_help_flag",
        "AssertionError: 'usage:' not in expected help output",
        "help_text_mismatch",
    ),
    ("test_version_format", "assert 'tool 1.2.3' == result.stdout", "version_format"),
    ("test_stdin_reads_when_piped", "stdin pipe handling failed", "stdin_handling"),
    ("test_empty_input_returns_zero", "empty input should exit 0", "empty_input"),
    ("test_invalid_value", "invalid value for --width: abc", "invalid_value"),
    (
        "test_nonexistent_file",
        "tool: cannot access 'missing.txt': No such file or directory",
        "file_not_found",
    ),
    ("test_multiple_positionals", "multiple inputs processing order mismatch", "multiple_inputs"),
    (
        "test_no_color_disables_ansi",
        "expected --no-color to disable ANSI codes",
        "no_color_negation",
    ),
    ("test_output_to_file[-o]", "--output flag did not redirect stdout", "output_flag"),
    ("test_config_file_override", "--config flag did not load custom config", "config_file"),
    ("test_json_output", "--json output not valid JSON", "json_io"),
    ("test_format_yaml", "--format yaml did not switch encoding", "format_flag"),
    ("test_list_subcommand", "--list did not enumerate items", "list_subcommand"),
    ("test_filter_pattern", "--filter applied incorrectly", "filter_flag"),
    ("test_check_mode_returns_1", "--check returned 0 on lint failure", "check_mode"),
    ("test_export_csv", "test_export_csv: format mismatch", "export_flag"),
    ("test_image_hash", "hash_executable_failed: docker exec returned 1", "hash_executable_fail"),
    ("test_some_unique_thing", "an unmatched message pattern", "other"),
]


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------


def test_family_names_unique():
    """Every family key in FAMILY_PATTERNS must be unique — duplicates would
    mask the second pattern silently."""
    names = [n for n, _ in FAMILY_PATTERNS]
    assert len(names) == len(set(names)), f"duplicate family names: {names}"


def test_family_names_set_includes_other():
    """FAMILY_NAMES exposes every named family + the 'other' catch-all."""
    assert "other" in FAMILY_NAMES
    assert all(n in FAMILY_NAMES for n, _ in FAMILY_PATTERNS)
    assert len(FAMILY_NAMES) == len(FAMILY_PATTERNS) + 1


def test_tier_partition_is_clean():
    """Every named family belongs to exactly one tier (no overlap, no gaps)."""
    all_named = {n for n, _ in FAMILY_PATTERNS}
    partitioned = TIER_1 | TIER_2 | INFRA
    assert all_named == partitioned, (
        f"tier partition mismatch: missing={all_named - partitioned}  extra={partitioned - all_named}"
    )
    # No family in two tiers
    assert not (TIER_1 & TIER_2)
    assert not (TIER_1 & INFRA)
    assert not (TIER_2 & INFRA)


def test_tier_of_lookups():
    assert tier_of("rc_2_unknown_option") == "tier-1"
    assert tier_of("json_io") == "tier-2"
    assert tier_of("hash_executable_fail") == "infra"
    assert tier_of("other") == "other"
    assert tier_of("does_not_exist") == "other"


# ---------------------------------------------------------------------------
# Classification behavior
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("test_name,msg,expected", _FIXTURE)
def test_classify_one_maps_correctly(test_name, msg, expected):
    assert classify_one(test_name, msg) == expected, (
        f"{test_name!r} + {msg!r} -> {classify_one(test_name, msg)} != {expected}"
    )


def test_classify_test_results_aggregates():
    """classify_test_results counts failures per family, skips passed/skipped."""
    results = [
        {"status": "passed", "name": "test_x"},
        {
            "status": "failure",
            "name": "test_unknown_flag",
            "extra": {"message": "unknown option: --foo"},
        },
        {
            "status": "failure",
            "name": "test_unknown_flag2",
            "extra": {"message": "unknown option: --bar"},
        },
        {"status": "skipped", "name": "test_y"},
        {"status": "failure", "name": "test_help", "extra": {"message": "usage: expected"}},
    ]
    c = classify_test_results(results)
    assert c["rc_2_unknown_option"] == 2
    assert c["help_text_mismatch"] == 1
    assert sum(c.values()) == 3  # only failures counted


# ---------------------------------------------------------------------------
# Single-source-of-truth invariant — the load-bearing test
# ---------------------------------------------------------------------------


def test_all_consumers_agree_with_central_taxonomy():
    """The three previous taxonomy duplicates must now route through the
    central module. This test imports each consumer's public classify path
    and proves they produce byte-identical histograms on the fixture."""
    import failure_classifier as fc  # noqa: E402
    import mass_run_v2_aggregate as agg  # noqa: E402
    import run_ledger as rl  # noqa: E402

    # Build a synthetic test_results list from the fixture (skip "other"
    # because the fixture's "other" entry isn't matched by any pattern —
    # it lives in classify_one's fallback path).
    test_results = [
        {"status": "failure", "name": name, "extra": {"message": msg}}
        for name, msg, _expected in _FIXTURE
    ]

    central = classify_test_results(test_results)
    via_fc = fc.classify_test_results(test_results)
    via_rl = rl._classify_failures(test_results)
    # mass_run_v2_aggregate exposes classify(name, msg), so build the same dict
    via_agg: dict[str, int] = {}
    for name, msg, _ in _FIXTURE:
        via_agg[agg.classify(name, msg)] = via_agg.get(agg.classify(name, msg), 0) + 1

    assert dict(central) == dict(via_fc), (
        f"failure_classifier disagrees with central: {dict(via_fc) - dict(central)} / {dict(central) - dict(via_fc)}"
    )
    assert dict(central) == dict(via_rl), (
        f"run_ledger disagrees with central: {dict(via_rl) - dict(central)} / {dict(central) - dict(via_rl)}"
    )
    assert dict(central) == via_agg, (
        f"mass_run_v2_aggregate disagrees with central: {via_agg} vs {dict(central)}"
    )
