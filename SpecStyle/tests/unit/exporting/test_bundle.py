"""EXP-001B bundle publish contract tests (§13.2, §13.11, §13.12)."""

from __future__ import annotations

from dataclasses import replace
import json
import os
import stat
from pathlib import Path

import pytest
from PIL import Image

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RepairStopReason, RuleStatus
from specstyle.errors import DomainError
from specstyle.exporting.bundle import ExportedFile, export_bundle
from specstyle.exporting.manifest import ExportCohort, ExportItem, _prepare_export
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.output_profile_contracts import (
    production_output_profile_capabilities,
)
from specstyle.generation.output_profiles import render_production_output
from specstyle.generation.protocols import GeneratedArtifact, run_generation
from specstyle.observability.hashing import hash_bytes
from specstyle.repair.history import start_repair_history
from specstyle.repair.loop import RepairTerminal
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import RuleResult, VerificationReport
from tests.unit.exporting.test_manifest import (
    _credits,
    _env,
    _export_request,
    _production_request,
)
# Reuse EXP-001A frozen input builders without modifying its test module.


def _root_fd(tmp_path: Path) -> int:
    return os.open(os.fspath(tmp_path), os.O_RDONLY | os.O_DIRECTORY)


def _terminal(report, artifact, *, reason: RepairStopReason) -> RepairTerminal:
    decision = decide_artifact(
        report, artifact.ref.artifact_id, repair_stop_reason=reason
    )
    return RepairTerminal(decision, None)


def _rejected_request():
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
    item = ExportItem(
        history,
        _terminal(report, artifact, reason=RepairStopReason.NO_IMPROVEMENT),
        None,
    )
    cohort = ExportCohort("xhs_grid", report, (item,))
    return _build_request((cohort,), _credits(request))


def _build_request(cohorts, credits) -> object:
    from specstyle.exporting.manifest import ExportRequest

    return ExportRequest(cohorts, _env(), credits)


def _manual_review_request():
    request = _production_request()
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
    item = ExportItem(
        history,
        _terminal(report, artifact, reason=RepairStopReason.MANUAL_REQUEST),
        None,
    )
    cohort = ExportCohort("xhs_grid", report, (item,))
    return _build_request((cohort,), _credits(request))


def _rendered_v2_request():
    legacy = _production_request()
    capability = production_output_profile_capabilities()[0]
    compiled = replace(
        legacy.compiled_spec,
        production_graphs=(
            replace(
                legacy.compiled_spec.production_graphs[0],
                output_profile_pin=capability.pin,
                render_contract=capability.render_contract,
            ),
        ),
        verification_plans=(
            replace(
                legacy.compiled_spec.verification_plans[0],
                output_profile_pin=capability.pin,
            ),
        ),
    )
    request = replace(legacy, compiled_spec=compiled)
    native = run_generation(FakeBackend(), request)
    content = render_production_output(native.content, capability)
    artifact = GeneratedArtifact(
        ArtifactRef(native.ref.artifact_id, hash_bytes(content)),
        content,
        native.request_hash,
        native.generation_fingerprint,
    )
    plan = compiled.verification_plans[0]
    report = VerificationReport(
        (artifact.ref,),
        plan.applicable_rule_definitions,
        tuple(
            RuleResult(rule.rule_id, RuleStatus.PASS, (artifact.ref.artifact_id,), None)
            for rule in plan.applicable_rule_definitions
        ),
    )
    history = start_repair_history(request, artifact, report)
    item = ExportItem(
        history,
        _terminal(report, artifact, reason=RepairStopReason.PASS_ALL_REQUIRED),
        None,
    )
    return _build_request(
        (ExportCohort("xhs_grid", report, (item,)),), _credits(request)
    )


# --------------------------------------------------------------------------- #
# Happy path & frozen ABI
# --------------------------------------------------------------------------- #


def test_export_bundle_publishes_approved_bundle(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        bundle = export_bundle(_export_request(), root_fd, "approved_bundle")
    finally:
        os.close(root_fd)

    assert bundle.bundle_name == "approved_bundle"
    assert (
        bundle.manifest_sha256
        == _prepare_export(_export_request()).manifest_file.sha256
    )
    bundle_root = tmp_path / "approved_bundle"
    assert bundle_root.is_dir()
    # manifest present and on-disk hash matches returned digest
    manifest_bytes = (bundle_root / "manifest.json").read_bytes()
    assert bundle.manifest_sha256 == hash_bytes(manifest_bytes)


def test_bundle_root_device_inode_match_root_fd(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        st = os.fstat(root_fd)
        bundle = export_bundle(_export_request(), root_fd, "root_id")
    finally:
        os.close(root_fd)
    assert bundle.root_device == st.st_dev
    assert bundle.root_inode == st.st_ino


def test_bundle_files_relative_include_manifest_sorted(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        bundle = export_bundle(_export_request(), root_fd, "files_check")
    finally:
        os.close(root_fd)
    paths = [f.relative_path for f in bundle.files]
    assert paths == sorted(paths)
    assert "manifest.json" in paths
    assert all("/" not in p.split("/")[-1] for p in paths)
    for f in bundle.files:
        assert isinstance(f, ExportedFile)
        assert f.sha256.value == f.sha256.value  # Sha256 present


def test_bundle_files_hashes_match_on_disk(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        bundle = export_bundle(_export_request(), root_fd, "hashes")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "hashes"
    for f in bundle.files:
        on_disk = (bundle_root / f.relative_path).read_bytes()
        assert hash_bytes(on_disk).value == f.sha256.value
        assert len(on_disk) == f.size_bytes


# --------------------------------------------------------------------------- #
# Target validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad_name", ["a/b", "a/../b", "-bad", ".dot", "a b", "ünîcode"]
)
def test_bundle_name_rejects_invalid(tmp_path: Path, bad_name: str) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="invalid export target"):
            export_bundle(_export_request(), root_fd, bad_name)
    finally:
        os.close(root_fd)
    assert not (tmp_path / bad_name).exists()


def test_bundle_name_too_long(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        with pytest.raises(DomainError, match="invalid export target"):
            export_bundle(_export_request(), root_fd, "a" * 129)
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("bad_fd", [True, False, "1", 1.0, 1j])
def test_target_root_fd_rejects_non_exact_int(tmp_path: Path, bad_fd: object) -> None:
    with pytest.raises(DomainError, match="invalid export target"):
        export_bundle(_export_request(), bad_fd, "x")  # type: ignore[arg-type]


def test_target_root_fd_must_be_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "not_a_dir"
    file_path.write_text("x")
    fd = os.open(os.fspath(file_path), os.O_RDONLY)
    try:
        with pytest.raises(DomainError, match="invalid export target"):
            export_bundle(_export_request(), fd, "x")
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- #
# Filesystem layout
# --------------------------------------------------------------------------- #


def test_directory_modes_0700_and_file_modes_0600(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_export_request(), root_fd, "modes")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "modes"
    assert stat.S_IMODE(bundle_root.stat().st_mode) == 0o700
    for sub in ("approved", "approved/xhs_grid", "rejected", "manual_review"):
        assert stat.S_IMODE((bundle_root / sub).stat().st_mode) == 0o700
    for f in bundle_root.rglob("*"):
        if f.is_file():
            assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_always_on_directories_created_even_when_empty(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_export_request(), root_fd, "dirs")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "dirs"
    for sub in (
        "approved",
        "approved/xhs_grid",
        "approved/talking_head_cover",
        "approved/background_sequence",
        "rejected",
        "manual_review",
    ):
        assert (bundle_root / sub).is_dir(), f"missing always-on dir {sub}"


def test_no_unexpected_directories_created(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_export_request(), root_fd, "nodescript")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "nodescript"
    rel_dirs = {
        p.relative_to(bundle_root).as_posix()
        for p in bundle_root.rglob("*")
        if p.is_dir()
    }
    assert rel_dirs == {
        "approved",
        "approved/xhs_grid",
        "approved/talking_head_cover",
        "approved/background_sequence",
        "rejected",
        "manual_review",
    }


# --------------------------------------------------------------------------- #
# Digests & canonical round-trip on disk
# --------------------------------------------------------------------------- #


def test_manifest_payload_bundle_sha_recomputable_from_disk(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        bundle = export_bundle(_export_request(), root_fd, "digests")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "digests"
    manifest_bytes = (bundle_root / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    file_entries = sorted(
        (
            {"path": e["path"], "sha256": e["sha256"], "size_bytes": e["size_bytes"]}
            for e in manifest["files"]
        ),
        key=lambda e: e["path"],
    )
    payload_material = {"domain": "specstyle.export.payload.v1", "files": file_entries}
    payload_bytes = json.dumps(
        payload_material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert bundle.payload_sha256 == hash_bytes(payload_bytes)
    bundle_material = {
        "domain": "specstyle.export.bundle.v1",
        "manifest_sha256": hash_bytes(manifest_bytes).value,
        "payload_sha256": bundle.payload_sha256.value,
    }
    bundle_bytes = json.dumps(
        bundle_material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert bundle.bundle_sha256 == hash_bytes(bundle_bytes)


def test_canonical_documents_round_trip_on_disk(tmp_path: Path) -> None:
    from specstyle.exporting import qa_report as _qa

    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_export_request(), root_fd, "canonical")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "canonical"
    for path in (
        "manifest.json",
        "qa_report.json",
        "asset_credits.json",
        "environment.json",
        "style_spec.yaml",
    ):
        data = (bundle_root / path).read_bytes()
        _qa.assert_canonical_round_trip(data)


# --------------------------------------------------------------------------- #
# PNG readback properties
# --------------------------------------------------------------------------- #


def test_png_readback_resolution_mode_frames_metadata(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_export_request(), root_fd, "png")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "png"
    manifest = json.loads((bundle_root / "manifest.json").read_bytes())
    res_by_path: dict[str, tuple[int, int]] = {}
    for cohort in manifest["cohorts"]:
        for item in cohort["items"]:
            res_by_path[item["final_artifact"]["relative_path"]] = tuple(
                item["initial_attempt"]["graph"]["resolution"]
            )
    pngs = list(bundle_root.rglob("*.png"))
    assert pngs
    for png in pngs:
        with Image.open(png) as im:
            assert im.mode == "RGB"
            assert getattr(im, "n_frames", 1) == 1
            assert im.info == {}
            rel = png.relative_to(bundle_root).as_posix()
            assert (im.width, im.height) == res_by_path[rel]


def test_rendered_v2_png_readback_uses_final_resolution(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_rendered_v2_request(), root_fd, "rendered_v2")
    finally:
        os.close(root_fd)

    png = next((tmp_path / "rendered_v2" / "approved" / "xhs_grid").glob("*.png"))
    with Image.open(png) as image:
        assert image.size == (1080, 1080)


def test_talking_readback_binds_native_and_final_resolutions() -> None:
    from specstyle.exporting import bundle as bundle_module
    from specstyle.exporting.qa_report import graph_primitive

    legacy = _production_request().graph
    capability = production_output_profile_capabilities()[1]
    talking = replace(
        legacy,
        output_profile="talking_head_cover",
        output_profile_pin=capability.pin,
        resolution=(768, 768),
        render_contract=capability.render_contract,
    )
    primitive = graph_primitive(talking)

    assert bundle_module._final_graph_resolution(primitive) == (1080, 1440)
    primitive["render_contract"]["native_resolution"] = [1024, 1024]
    with pytest.raises(DomainError, match="^export hash mismatch$"):
        bundle_module._final_graph_resolution(primitive)
    del primitive["render_contract"]["native_resolution"]
    with pytest.raises(DomainError, match="^export hash mismatch$"):
        bundle_module._final_graph_resolution(primitive)


def test_background_readback_accepts_pinned_single_index_zero_contract() -> None:
    from specstyle.exporting import bundle as bundle_module
    from specstyle.exporting.qa_report import graph_primitive

    legacy = _production_request().graph
    capability = production_output_profile_capabilities()[2]
    background = replace(
        legacy,
        output_profile="background_sequence",
        output_profile_pin=capability.pin,
        resolution=(768, 768),
        render_contract=capability.render_contract,
    )
    manifest = {
        "cohorts": [
            {
                "output_profile": "background_sequence",
                "items": [
                    {
                        "sequence_index": 0,
                        "final_artifact": {
                            "relative_path": (
                                "approved/background_sequence/000000_artifact.png"
                            )
                        },
                        "initial_attempt": {"graph": graph_primitive(background)},
                    }
                ],
            }
        ]
    }

    assert bundle_module._resolution_by_path(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ) == {"approved/background_sequence/000000_artifact.png": (1920, 1080)}


@pytest.mark.parametrize(
    "mutation",
    ("none", "one", "bool", "leaf", "profile", "second_item"),
)
def test_background_readback_rejects_sequence_contract_drift(mutation: str) -> None:
    from specstyle.exporting import bundle as bundle_module
    from specstyle.exporting.qa_report import graph_primitive

    legacy = _production_request().graph
    capability = production_output_profile_capabilities()[2]
    background = replace(
        legacy,
        output_profile="background_sequence",
        output_profile_pin=capability.pin,
        resolution=(768, 768),
        render_contract=capability.render_contract,
    )
    item = {
        "sequence_index": 0,
        "final_artifact": {
            "relative_path": "approved/background_sequence/000000_artifact.png"
        },
        "initial_attempt": {"graph": graph_primitive(background)},
    }
    cohort = {"output_profile": "background_sequence", "items": [item]}
    if mutation == "none":
        item["sequence_index"] = None
    elif mutation == "one":
        item["sequence_index"] = 1
    elif mutation == "bool":
        item["sequence_index"] = True
    elif mutation == "leaf":
        item["final_artifact"]["relative_path"] = (
            "approved/background_sequence/000001_artifact.png"
        )
    elif mutation == "profile":
        cohort["output_profile"] = "xhs_grid"
    else:
        cohort["items"].append(
            {
                **item,
                "sequence_index": 1,
                "final_artifact": {
                    "relative_path": ("approved/background_sequence/000001_other.png")
                },
            }
        )

    manifest = json.dumps(
        {"cohorts": [cohort]}, sort_keys=True, separators=(",", ":")
    ).encode()
    with pytest.raises(DomainError, match="^export hash mismatch$"):
        bundle_module._resolution_by_path(manifest)


# --------------------------------------------------------------------------- #
# Forbidden APIs
# --------------------------------------------------------------------------- #


def test_no_path_resolve_shutil_or_plain_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    def _boom(*a: object, **k: object) -> None:
        raise AssertionError("forbidden convenience API touched")

    monkeypatch.setattr(os, "rename", _boom)
    monkeypatch.setattr(os, "replace", _boom)
    monkeypatch.setattr(shutil, "copy", _boom, raising=False)
    monkeypatch.setattr(shutil, "move", _boom, raising=False)
    monkeypatch.setattr(shutil, "rmtree", _boom, raising=False)
    root_fd = _root_fd(tmp_path)
    try:
        bundle = export_bundle(_export_request(), root_fd, "noconv")
    finally:
        os.close(root_fd)
    assert bundle.bundle_name == "noconv"


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


def test_rejected_routed_to_rejected_subdir(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_rejected_request(), root_fd, "rej")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "rej"
    rejected = list((bundle_root / "rejected").rglob("*.png"))
    assert len(rejected) == 1
    assert (
        rejected[0].relative_to(bundle_root).as_posix().startswith("rejected/source/")
    )
    assert not list((bundle_root / "approved" / "xhs_grid").glob("*.png"))


def test_manual_review_routed_to_manual_review_subdir(tmp_path: Path) -> None:
    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(_manual_review_request(), root_fd, "mr")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "mr"
    review = list((bundle_root / "manual_review").rglob("*.png"))
    assert len(review) == 1
    assert (
        review[0]
        .relative_to(bundle_root)
        .as_posix()
        .startswith("manual_review/source/")
    )
    assert not list((bundle_root / "approved" / "xhs_grid").glob("*.png"))


# --------------------------------------------------------------------------- #
# Determinism & I-007
# --------------------------------------------------------------------------- #


def test_export_is_deterministic_reproducible(tmp_path: Path) -> None:
    fds = (_root_fd(tmp_path),)
    try:
        b1 = export_bundle(_export_request(), fds[0], "det1")
    finally:
        os.close(fds[0])
    root_fd = _root_fd(tmp_path)
    try:
        b2 = export_bundle(_export_request(), root_fd, "det2")
    finally:
        os.close(root_fd)
    assert b1.manifest_sha256 == b2.manifest_sha256
    assert b1.payload_sha256 == b2.payload_sha256
    assert b1.bundle_sha256 == b2.bundle_sha256


def test_i007_approved_hash_and_status(tmp_path: Path) -> None:
    request = _export_request()
    prepared = _prepare_export(request)
    approved = [
        f for f in prepared.payload_files if f.relative_path.startswith("approved/")
    ]
    assert approved
    source_png = approved[0]

    root_fd = _root_fd(tmp_path)
    try:
        export_bundle(request, root_fd, "i007")
    finally:
        os.close(root_fd)
    bundle_root = tmp_path / "i007"
    on_disk = (bundle_root / source_png.relative_path).read_bytes()
    assert hash_bytes(on_disk) == source_png.sha256
    assert hash_bytes(on_disk).value == source_png.sha256.value

    manifest = json.loads((bundle_root / "manifest.json").read_bytes())
    entry_by_path = {e["path"]: e for e in manifest["files"]}
    assert entry_by_path[source_png.relative_path]["sha256"] == source_png.sha256.value
    statuses = {
        item["final_decision"]["artifact_status"]
        for cohort in manifest["cohorts"]
        for item in cohort["items"]
    }
    assert statuses == {"APPROVED"}
