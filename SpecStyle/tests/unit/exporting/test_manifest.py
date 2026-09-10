"""EXP-001A manifest contract tests (§13.1–§13.10, §13.12)."""

from __future__ import annotations

import json
from io import BytesIO

import pytest
from PIL import Image

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.enums import RepairStopReason, RuleStatus
from specstyle.domain.identifiers import AssetId, AttemptId, JobId, Sha256
from specstyle.errors import DomainError
from specstyle.exporting.manifest import (
    AssetCredit,
    ExportCohort,
    ExportItem,
    ExportRequest,
    _prepare_export,
)
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.generation.protocols import run_generation
from specstyle.generation.requests import (
    GenerationRequest,
    PreparedControlInput,
    RenderedPrompt,
)
from specstyle.observability.environment import (
    DeviceInventory,
    EnvironmentSnapshot,
    TextObservation,
    hash_environment,
)
from specstyle.observability.hashing import hash_bytes
from specstyle.repair.history import start_repair_history
from specstyle.repair.loop import RepairTerminal
from specstyle.spec.compiled_models import ResourcePin
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.models import StyleSpecV1
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import RuleResult, VerificationReport
from tests.unit.spec.test_compiler import context, raw_spec


def _compiled():
    raw = raw_spec().model_dump(mode="python")
    raw["repair"]["policy_version"] = "1.0"
    return compile_style_spec(StyleSpecV1.model_validate(raw), context())


def _env() -> EnvironmentSnapshot:
    na = TextObservation("UNAVAILABLE", None, "NOT_REPORTED")
    inv = DeviceInventory("UNAVAILABLE", "NOT_INSTALLED", ())
    return EnvironmentSnapshot("1.0", na, na, na, na, na, na, na, na, na, na, inv)


def _production_source():
    buf = BytesIO()
    Image.new("RGB", (1024, 1024), "red").save(buf, "PNG")
    content = buf.getvalue()
    plan = PreprocessPlan(
        (1024, 1024),
        "contain_pad",
        (0, 0, 0),
        ResourcePin("processor", "r1", Sha256("f" * 64)),
    )
    return preprocess_image(
        content, AssetRef(AssetId("source"), hash_bytes(content)), plan
    )


def _production_request(env=None) -> GenerationRequest:
    if env is None:
        env = _env()
    compiled = _compiled()
    source = _production_source()
    graph = compiled.production_graphs[0]
    prompt = RenderedPrompt(
        ResourcePin("template", "r1", Sha256("e" * 64)), graph.preset_id, "a prompt", ""
    )
    control = PreparedControlInput("canny", source)
    return GenerationRequest(
        JobId("job"),
        AttemptId("attempt"),
        None,
        compiled,
        "production",
        "xhs_grid",
        source,
        (AssetRef(AssetId("style"), graph.style_reference_hashes[0]),),
        prompt,
        control,
        0,
        hash_environment(env),
    )


def _approved_item(env=None):
    request = _production_request(env)
    artifact = run_generation(FakeBackend(), request)
    plan = request.compiled_spec.verification_plans[0]
    report = VerificationReport(
        (artifact.ref,),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(rule.rule_id, RuleStatus.PASS, (artifact.ref.artifact_id,), None)
            for rule in plan.applicable_rule_definitions
        ),
    )
    history = start_repair_history(request, artifact, report)
    decision = decide_artifact(
        report,
        artifact.ref.artifact_id,
        repair_stop_reason=RepairStopReason.PASS_ALL_REQUIRED,
    )
    terminal = RepairTerminal(decision, None)
    return ExportItem(history, terminal, None), request, artifact, report


def _credits(request: GenerationRequest) -> tuple[AssetCredit, ...]:
    spec = request.compiled_spec.source_spec
    style_ref = spec.assets.style_references[0]
    return (
        AssetCredit(request.source.source, ("input",), None, None, None, None),
        AssetCredit(
            request.style_references[0],
            ("style_reference",),
            style_ref.source_url,
            style_ref.license,
            style_ref.attribution,
            style_ref.consent,
        ),
    )


def _export_request(env=None) -> ExportRequest:
    if env is None:
        env = _env()
    item, request, _artifact, report = _approved_item(env)
    cohort = ExportCohort("xhs_grid", report, (item,))
    return ExportRequest((cohort,), env, _credits(request))


def test_prepare_export_produces_canonical_documents() -> None:
    export_request = _export_request()
    prepared = _prepare_export(export_request)

    paths = {f.relative_path for f in prepared.payload_files}
    assert "manifest.json" not in paths
    assert {
        "asset_credits.json",
        "environment.json",
        "qa_report.json",
        "style_spec.yaml",
    } <= paths
    assert prepared.manifest_file.relative_path == "manifest.json"
    assert prepared.manifest_file.sha256 == hash_bytes(prepared.manifest_file.content)
    assert prepared.manifest_file.size_bytes == len(prepared.manifest_file.content)
    for f in prepared.payload_files:
        assert f.sha256 == hash_bytes(f.content)
        assert f.size_bytes == len(f.content)


def test_approved_artifact_routed_to_approved_path() -> None:
    prepared = _prepare_export(_export_request())
    approved = [
        f for f in prepared.payload_files if f.relative_path.startswith("approved/")
    ]
    assert len(approved) == 1
    assert approved[0].relative_path.startswith("approved/xhs_grid/")
    assert approved[0].relative_path.endswith(".png")


def test_digests_are_recomputable_from_bytes() -> None:
    prepared = _prepare_export(_export_request())
    file_entries = [
        {"path": f.relative_path, "sha256": f.sha256.value, "size_bytes": f.size_bytes}
        for f in sorted(prepared.payload_files, key=lambda x: x.relative_path)
    ]
    payload_material = {"domain": "specstyle.export.payload.v1", "files": file_entries}
    payload_bytes = json.dumps(
        payload_material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert hash_bytes(payload_bytes) == prepared.payload_sha256

    manifest_sha = hash_bytes(prepared.manifest_file.content)
    bundle_material = {
        "domain": "specstyle.export.bundle.v1",
        "manifest_sha256": manifest_sha.value,
        "payload_sha256": prepared.payload_sha256.value,
    }
    bundle_bytes = json.dumps(
        bundle_material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    assert hash_bytes(bundle_bytes) == prepared.bundle_sha256


def test_canonical_bytes_are_deterministic() -> None:
    first = _prepare_export(_export_request())
    second = _prepare_export(_export_request())
    assert first.manifest_file.content == second.manifest_file.content
    assert first.payload_sha256 == second.payload_sha256
    assert first.bundle_sha256 == second.bundle_sha256
    assert [f.content for f in first.payload_files] == [
        f.content for f in second.payload_files
    ]


def test_manifest_has_exact_top_level_keys() -> None:
    prepared = _prepare_export(_export_request())
    manifest = json.loads(prepared.manifest_file.content)
    assert set(manifest) == {
        "asset_credits",
        "cohorts",
        "environment",
        "files",
        "job_id",
        "payload_sha256",
        "qa_report",
        "schema_version",
        "style_spec",
    }
    assert manifest["schema_version"] == "specstyle.export.manifest.v1"
    assert manifest["job_id"] == "job"
    assert manifest["payload_sha256"] == prepared.payload_sha256.value


def test_qa_report_metrics_all_not_provided() -> None:
    prepared = _prepare_export(_export_request())
    qa_bytes = next(
        f.content for f in prepared.payload_files if f.relative_path == "qa_report.json"
    )
    qa = json.loads(qa_bytes)
    assert set(qa["metrics"]) == {
        "between_profile_separation",
        "content_diversity",
        "duplicate_rate",
        "style_fidelity",
        "technical_failure_rate",
        "within_batch_style_dispersion",
    }
    for metric in qa["metrics"].values():
        assert metric == {
            "availability": "NOT_PROVIDED",
            "reason": "UPSTREAM_AGGREGATE_NOT_IN_CONTRACT",
            "value": None,
        }


def _preview_request(env=None) -> GenerationRequest:
    if env is None:
        env = _env()
    raw = raw_spec().model_dump(mode="python")
    raw["repair"]["policy_version"] = "1.0"
    compiled = compile_style_spec(StyleSpecV1.model_validate(raw), context())
    buf = BytesIO()
    Image.new("RGB", (512, 512), "red").save(buf, "PNG")
    content = buf.getvalue()
    plan = PreprocessPlan(
        (512, 512),
        "contain_pad",
        (0, 0, 0),
        ResourcePin("processor", "r1", Sha256("f" * 64)),
    )
    source = preprocess_image(
        content, AssetRef(AssetId("source"), hash_bytes(content)), plan
    )
    graph = compiled.preview_graphs[0]
    prompt = RenderedPrompt(
        ResourcePin("template", "r1", Sha256("e" * 64)), graph.preset_id, "a prompt", ""
    )
    control = PreparedControlInput("canny", source)
    return GenerationRequest(
        JobId("job"),
        AttemptId("attempt"),
        None,
        compiled,
        "preview",
        "xhs_grid",
        source,
        (AssetRef(AssetId("style"), graph.style_reference_hashes[0]),),
        prompt,
        control,
        0,
        hash_environment(env),
    )


def _preview_item(env=None):
    request = _preview_request(env)
    artifact = run_generation(FakeBackend(), request)
    plan = request.compiled_spec.verification_plans[0]
    report = VerificationReport(
        (artifact.ref,),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(r.rule_id, RuleStatus.PASS, (artifact.ref.artifact_id,), None)
            for r in plan.applicable_rule_definitions
        ),
    )
    history = start_repair_history(request, artifact, report)
    decision = decide_artifact(
        report,
        artifact.ref.artifact_id,
        repair_stop_reason=RepairStopReason.PASS_ALL_REQUIRED,
    )
    return (
        ExportItem(history, RepairTerminal(decision, None), None),
        request,
        artifact,
        report,
    )


def test_rejects_preview_generation_profile() -> None:
    item, request, _artifact, report = _preview_item()
    cohort = ExportCohort("xhs_grid", report, (item,))
    with pytest.raises(DomainError, match="invalid export request"):
        ExportRequest((cohort,), _env(), _credits(request))


def test_rejects_forged_compiled_spec_hash() -> None:
    item, _request, _artifact, _report = _approved_item()
    forged = item.history
    object.__setattr__(
        forged.current_request.compiled_spec, "compiled_spec_hash", Sha256("0" * 64)
    )
    with pytest.raises(DomainError, match="invalid export request"):
        ExportItem(forged, item.terminal, None)


def _env_b() -> EnvironmentSnapshot:
    available = TextObservation("AVAILABLE", "Linux", None)
    na = TextObservation("UNAVAILABLE", None, "NOT_REPORTED")
    inv = DeviceInventory("UNAVAILABLE", "NOT_INSTALLED", ())
    return EnvironmentSnapshot(
        "1.0", available, na, na, na, na, na, na, na, na, na, inv
    )


def test_rejects_environment_hash_mismatch() -> None:
    env_a = _env()
    env_b = _env_b()
    item, request, _artifact, report = _approved_item(env_a)
    cohort = ExportCohort("xhs_grid", report, (item,))
    with pytest.raises(DomainError, match="invalid export request"):
        ExportRequest((cohort,), env_b, _credits(request))


def test_rejects_missing_credit() -> None:
    item, request, _artifact, report = _approved_item()
    cohort = ExportCohort("xhs_grid", report, (item,))
    env = _env()
    # Supply only input credit, omitting style credit.
    incomplete = (
        AssetCredit(request.source.source, ("input",), None, None, None, None),
    )
    with pytest.raises(DomainError, match="invalid export request"):
        ExportRequest((cohort,), env, incomplete)


def test_rejects_extra_credit() -> None:
    item, request, _artifact, report = _approved_item()
    cohort = ExportCohort("xhs_grid", report, (item,))
    env = _env()
    credits = list(_credits(request))
    credits.append(
        AssetCredit(
            AssetRef(AssetId("extra"), Sha256("0" * 64)),
            ("input",),
            None,
            None,
            None,
            None,
        )
    )
    with pytest.raises(DomainError, match="invalid export request"):
        ExportRequest((cohort,), env, tuple(credits))


def test_rejects_unordered_credits() -> None:
    item, request, _artifact, report = _approved_item()
    cohort = ExportCohort("xhs_grid", report, (item,))
    env = _env()
    credits = tuple(reversed(_credits(request)))
    with pytest.raises(DomainError, match="invalid export request"):
        ExportRequest((cohort,), env, credits)


def test_rejects_style_provenance_mismatch() -> None:
    item, request, _artifact, report = _approved_item()
    cohort = ExportCohort("xhs_grid", report, (item,))
    env = _env()
    spec = request.compiled_spec.source_spec
    style_ref = spec.assets.style_references[0]
    bad_style = AssetCredit(
        request.style_references[0],
        ("style_reference",),
        "https://example.com/wrong",  # Does not match the spec.
        style_ref.license,
        style_ref.attribution,
        style_ref.consent,
    )
    credits = (
        AssetCredit(request.source.source, ("input",), None, None, None, None),
        bad_style,
    )
    with pytest.raises(DomainError, match="invalid export request"):
        ExportRequest((cohort,), env, credits)


def test_rejects_accepted_with_override() -> None:
    from specstyle.domain.enums import ArtifactStatus, DecisionReason
    from specstyle.verification.rule_models import ArtifactDecision

    item, request, artifact, report = _approved_item()
    override = ArtifactDecision(
        artifact.ref.artifact_id,
        ArtifactStatus.MANUAL_REVIEW,
        DecisionReason.MANUAL_POLICY,
        RepairStopReason.MANUAL_REQUEST,
        True,
    )
    with pytest.raises(DomainError, match="export invariant violation"):
        terminal = RepairTerminal(override, None)
        override_item = ExportItem(item.history, terminal, None)
        cohort = ExportCohort("xhs_grid", report, (override_item,))
        ExportRequest((cohort,), _env(), _credits(request))


def test_prepare_export_invokes_no_filesystem_or_network(monkeypatch) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("filesystem or network touched")

    monkeypatch.setattr("os.open", _boom)
    monkeypatch.setattr("os.write", _boom)
    monkeypatch.setattr("os.replace", _boom)
    monkeypatch.setattr("os.rename", _boom)
    monkeypatch.setattr("shutil.copy", _boom, raising=False)
    monkeypatch.setattr("socket.socket", _boom, raising=False)
    monkeypatch.setattr("os.environ", {}, raising=False)
    monkeypatch.setattr("os.getenv", _boom, raising=False)
    _prepare_export(_export_request())
    _prepare_export(_export_request())


def test_asset_credits_has_exact_keys_and_complete_flag() -> None:
    prepared = _prepare_export(_export_request())
    credits_bytes = next(
        f.content
        for f in prepared.payload_files
        if f.relative_path == "asset_credits.json"
    )
    credits = json.loads(credits_bytes)
    assert set(credits) == {"assets", "complete", "schema_version"}
    assert credits["schema_version"] == "specstyle.export.asset_credits.v1"
    assert credits["complete"] is False
    for entry in credits["assets"]:
        assert set(entry) == {
            "asset",
            "attribution",
            "consent",
            "license",
            "missing_fields",
            "provenance_status",
            "roles",
            "source_url",
        }
    assert credits["assets"][0]["provenance_status"] == "MISSING"
    assert credits["assets"][0]["missing_fields"] == [
        "source_url",
        "license",
        "attribution",
        "consent",
    ]
    assert credits["assets"][1]["provenance_status"] == "COMPLETE"
    assert credits["assets"][1]["missing_fields"] == []


def test_canonical_documents_round_trip_strict() -> None:
    from specstyle.exporting import qa_report as _qa_report

    prepared = _prepare_export(_export_request())
    for f in prepared.payload_files:
        if f.relative_path.endswith((".json", ".yaml")):
            parsed = _qa_report.parse_strict(f.content)
            assert _qa_report.canonical_json_bytes(parsed) == f.content
    _qa_report.assert_canonical_round_trip(prepared.manifest_file.content)


def test_i007_approved_file_hash_matches_manifest_and_content() -> None:
    prepared = _prepare_export(_export_request())
    manifest = json.loads(prepared.manifest_file.content)
    file_by_path = {entry["path"]: entry for entry in manifest["files"]}
    approved = [
        f for f in prepared.payload_files if f.relative_path.startswith("approved/")
    ]
    assert approved
    for f in approved:
        entry = file_by_path[f.relative_path]
        assert entry["sha256"] == f.sha256.value
        assert entry["size_bytes"] == f.size_bytes
        assert f.sha256 == hash_bytes(f.content)


def test_rejected_artifact_routed_to_rejected_path() -> None:
    request = _production_request()
    artifact = run_generation(FakeBackend(), request)
    plan = request.compiled_spec.verification_plans[0]
    report = VerificationReport(
        (artifact.ref,),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(rule.rule_id, RuleStatus.FAIL, (artifact.ref.artifact_id,), None)
            for rule in plan.applicable_rule_definitions
        ),
    )
    history = start_repair_history(request, artifact, report)
    decision = decide_artifact(
        report,
        artifact.ref.artifact_id,
        repair_stop_reason=RepairStopReason.NO_IMPROVEMENT,
    )
    item = ExportItem(history, RepairTerminal(decision, None), None)
    cohort = ExportCohort("xhs_grid", report, (item,))
    prepared = _prepare_export(ExportRequest((cohort,), _env(), _credits(request)))
    rejected = [
        f for f in prepared.payload_files if f.relative_path.startswith("rejected/")
    ]
    assert len(rejected) == 1
    assert rejected[0].relative_path.startswith("rejected/source/")
    assert not any(
        f.relative_path.startswith("approved/") for f in prepared.payload_files
    )
