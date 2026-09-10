"""EXP-001A module-private primitive/JSON helper tests (§13.9, §13.5, §13.7)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from specstyle.domain.identifiers import RuleId, Sha256
from specstyle.errors import DomainError
from specstyle.exporting import qa_report
from specstyle.generation.output_profile_contracts import (
    production_output_profile_capabilities,
)
from specstyle.spec.compiler import compile_style_spec
from tests.unit.spec.test_compiler import context, raw_spec


def test_canonical_json_normalizes_negative_zero() -> None:
    assert qa_report.canonical_json_bytes({"x": float("-0.0")}) == b'{"x":0.0}'
    assert qa_report.canonical_json_bytes([-0.0, 0.0]) == b"[0.0,0.0]"


def test_canonical_json_sorts_keys_compact_and_no_ascii_escape() -> None:
    encoded = qa_report.canonical_json_bytes({"b": 1, "a": "é"})
    assert encoded == b'{"a":"\xc3\xa9","b":1}'


def test_canonical_json_rejects_nan_and_infinity() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            qa_report.canonical_json_bytes({"x": value})


def test_parse_strict_rejects_duplicate_keys() -> None:
    with pytest.raises(DomainError, match="export invariant violation"):
        qa_report.parse_strict(b'{"a":1,"a":2}')


def test_parse_strict_rejects_nan_and_infinity_constants() -> None:
    for payload in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}'):
        with pytest.raises(DomainError, match="export invariant violation"):
            qa_report.parse_strict(payload)


def test_parse_strict_rejects_non_bytes_and_invalid_json() -> None:
    with pytest.raises(DomainError):
        qa_report.parse_strict("not bytes")  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        qa_report.parse_strict(b"{not json}")


def test_assert_canonical_round_trip_rejects_reordered_or_reencoded() -> None:
    payload = b'{"a":1,"b":2}'
    qa_report.assert_canonical_round_trip(payload)
    with pytest.raises(DomainError):
        # Re-serialize with different separators so bytes differ from the original.
        qa_report.assert_canonical_round_trip(b'{"a": 1, "b": 2}')


def test_canonical_material_tags_builtins_identifiers_and_tuples() -> None:
    assert qa_report.canonical_material(None) == ("none",)
    assert qa_report.canonical_material(True) == ("bool", True)
    assert qa_report.canonical_material(1) == ("int", 1)
    assert qa_report.canonical_material(0.5) == ("float", (0.5).hex())
    assert qa_report.canonical_material("s") == ("str", "s")
    assert qa_report.canonical_material(b"\x00") == ("bytes", b"\x00")
    sha = Sha256("a" * 64)
    assert qa_report.canonical_material(sha) == (
        "identifier",
        "specstyle.domain.identifiers",
        "Sha256",
        "a" * 64,
    )
    rule = RuleId("rule-1")
    assert qa_report.canonical_material(rule) == (
        "identifier",
        "specstyle.domain.identifiers",
        "RuleId",
        "rule-1",
    )
    assert qa_report.canonical_material((1, "x")) == (
        "tuple",
        (("int", 1), ("str", "x")),
    )


def test_canonical_material_rejects_unsupported_types() -> None:
    with pytest.raises(DomainError, match="invalid export request"):
        qa_report.canonical_material(object())


def test_build_qa_report_has_fixed_metrics_and_schema() -> None:
    spec = {
        "compiled_spec_sha256": "a" * 64,
        "schema_version": "1.0",
        "spec_id": "spec",
    }
    report = qa_report.build_qa_report(spec=spec, cohorts=[], job_id="job")
    assert report["schema_version"] == "specstyle.export.qa_report.v1"
    assert report["job_id"] == "job"
    assert report["spec"] == spec
    assert set(report["metrics"]) == {
        "between_profile_separation",
        "content_diversity",
        "duplicate_rate",
        "style_fidelity",
        "technical_failure_rate",
        "within_batch_style_dispersion",
    }
    for metric in report["metrics"].values():
        assert metric == {
            "availability": "NOT_PROVIDED",
            "reason": "UPSTREAM_AGGREGATE_NOT_IN_CONTRACT",
            "value": None,
        }


def test_build_qa_report_canonical_bytes_are_stable() -> None:
    spec = {
        "compiled_spec_sha256": "a" * 64,
        "schema_version": "1.0",
        "spec_id": "spec",
    }
    first = qa_report.canonical_json_bytes(
        qa_report.build_qa_report(spec=spec, cohorts=[], job_id="job")
    )
    second = qa_report.canonical_json_bytes(
        qa_report.build_qa_report(spec=spec, cohorts=[], job_id="job")
    )
    assert first == second
    qa_report.assert_canonical_round_trip(first)


def test_graph_primitive_adds_render_contract_only_for_rendered_v2_graph() -> None:
    legacy = compile_style_spec(raw_spec(), context()).production_graphs[0]
    rendered = replace(
        legacy,
        render_contract=production_output_profile_capabilities()[0].render_contract,
    )

    assert "render_contract" not in qa_report.graph_primitive(legacy)
    assert qa_report.graph_primitive(rendered)["render_contract"] == {
        "background": [255, 255, 255],
        "final_resolution": [1080, 1080],
        "fit": "contain_pad",
        "overlay": "disabled",
        "resampling": "lanczos",
        "sequence_semantics": "single_static",
    }


def test_graph_primitive_includes_talking_native_resolution_binding() -> None:
    legacy = compile_style_spec(raw_spec(), context()).production_graphs[0]
    capability = production_output_profile_capabilities()[1]
    talking = replace(
        legacy,
        output_profile="talking_head_cover",
        output_profile_pin=capability.pin,
        resolution=(768, 768),
        render_contract=capability.render_contract,
    )

    primitive = qa_report.graph_primitive(talking)

    assert primitive["resolution"] == [768, 768]
    assert primitive["render_contract"]["native_resolution"] == [768, 768]
    assert primitive["render_contract"]["final_resolution"] == [1080, 1440]
