"""WF-002 fake CPU end-to-end vertical-slice integration tests.

One CPU command runs four chains: approved, fail to repair to approved,
exhausted to rejected, and unverifiable to manual review. It verifies canonical
parsing, terminal-state isolation, idempotent restart recovery, same-input
determinism, and an import graph free of Torch, Diffusers, and Gradio.

FakeBackend bit-exact behavior derives ``artifact_id`` from ``request_hash``.
The tests use the orchestrator's ``_initial_request`` and
``_expected_artifact_id`` to precompute initial and repaired artifact IDs and
script FakeVerifier accordingly; they do not claim verified Spec replay.
"""

from __future__ import annotations

import ast
import json
import os
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
    RuleScope,
    RuleStatus,
)
from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    JobId,
    RuleId,
    Sha256,
)
from specstyle.exporting.qa_report import assert_canonical_round_trip, parse_strict
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.generation.requests import PreparedControlInput, RenderedPrompt
from specstyle.observability.environment import (
    DeviceInventory,
    EnvironmentSnapshot,
    TextObservation,
    hash_environment,
)
from specstyle.observability.hashing import hash_bytes
from specstyle.repair.actions import (
    INCREASE_STYLE_SCALE,
    build_repair_request,
    plan_repair_action,
)
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.compiled_models import ResourcePin
from specstyle.spec.loader import load_style_spec_text
from specstyle.workflow.orchestrator import (
    FakeJobPlan,
    FakeJobResult,
    _attempt_id,
    _decision_id,
    _expected_artifact_id,
    _initial_request,
    run_fake_job,
)
from tests.unit.spec.test_compiler import context, raw_spec

_OUTPUT = "xhs_grid"
_JOB = JobId("wf002-job")


# --------------------------------------------------------------------------- #
# Shared materials (factories mirror tests/unit/exporting/test_manifest.py)
# --------------------------------------------------------------------------- #


def _spec_text() -> str:
    """JSON (a YAML 1.2 subset) spec using policy 1.0 and manual review.

    ``on_unverifiable=manual_review`` lets one spec exercise both fail-to-repair,
    because FAIL routing ignores ``on_unverifiable``, and
    unverifiable-to-manual-review routing.
    """
    data = raw_spec().model_dump(mode="python", round_trip=True)
    data["repair"]["policy_version"] = "1.0"
    data["verification"]["gate_defaults"]["on_unverifiable"] = "manual_review"
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


def _context_with_style_low():
    """Rename the L2 fidelity rule to STYLE_LOW, affected by style-scale repair."""
    base = context()
    catalog = base.rule_catalogs[0]
    style_low = replace(
        catalog.rules[1],
        rule_id=RuleId("STYLE_LOW"),
        affected_by_actions=(INCREASE_STYLE_SCALE,),
    )
    new_catalog = replace(
        catalog, rules=(catalog.rules[0], style_low, catalog.rules[2])
    )
    return replace(base, rule_catalogs=(new_catalog,))


def _env() -> EnvironmentSnapshot:
    na = TextObservation("UNAVAILABLE", None, "NOT_REPORTED")
    inv = DeviceInventory("UNAVAILABLE", "NOT_INSTALLED", ())
    return EnvironmentSnapshot("1.0", na, na, na, na, na, na, na, na, na, na, inv)


def _source():
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


class _CannyBuilder:
    """Use the source itself as control input with kind canny matching the graph."""

    def build(self, source, graph):  # noqa: ANN001, ANN202
        return PreparedControlInput("canny", source)


def _prompt(compiled):
    graph = compiled.production_graphs[0]
    return RenderedPrompt(
        ResourcePin("template", "r1", Sha256("e" * 64)), graph.preset_id, "a prompt", ""
    )


def _plan():
    return FakeJobPlan(_JOB, (_OUTPUT,), "production", 0, 1)


def _compiled():
    return compile_style_spec(
        load_style_spec_text(_spec_text()), _context_with_style_low()
    )


class _SpyBackend:
    """Wrap FakeBackend to count calls and prove restart does not regenerate."""

    def __init__(self) -> None:
        self._inner = FakeBackend()
        self.generate_calls = 0

    def generate(self, request):  # noqa: ANN001, ANN202
        self.generate_calls += 1
        return self._inner.generate(request)


# --------------------------------------------------------------------------- #
# FakeVerifier test infrastructure
# --------------------------------------------------------------------------- #


class FakeVerifier:
    """Fake verifier scripted by artifact ID to rule-status mappings.

    An ITEM rule emits one ``affected=(artifact,)`` result per artifact. A BATCH
    rule emits one result affecting all artifacts. Unscripted rules default to
    PASS so the approved chain needs no script; scores are ``None``.
    """

    def __init__(self) -> None:
        self._scripts: dict[str, dict[str, RuleStatus]] = {}

    def script(self, artifact_id: ArtifactId, outcomes: dict[str, RuleStatus]) -> None:
        self._scripts[artifact_id.value] = dict(outcomes)

    def _status(self, artifact_id: ArtifactId, rule_id: RuleId) -> RuleStatus:
        return self._scripts.get(artifact_id.value, {}).get(
            rule_id.value, RuleStatus.PASS
        )

    def verify(self, artifacts, rules, /):  # noqa: ANN001, ANN202
        results = []
        for rule in rules:
            if rule.scope is RuleScope.ITEM:
                for art in artifacts:
                    results.append(
                        _result(
                            rule.rule_id,
                            self._status(art.artifact_id, rule.rule_id),
                            (art.artifact_id,),
                        )
                    )
            else:  # BATCH emits one result affecting all artifacts.
                status = RuleStatus.PASS
                for art in artifacts:
                    candidate = self._status(art.artifact_id, rule.rule_id)
                    if candidate is not RuleStatus.PASS:
                        status = candidate
                results.append(
                    _result(
                        rule.rule_id,
                        status,
                        tuple(a.artifact_id for a in artifacts),
                    )
                )
        return tuple(results)


def _result(rule_id, status, affected):  # noqa: ANN001, ANN202
    from specstyle.verification.rule_models import RuleResult

    return RuleResult(rule_id, status, affected, None)


# --------------------------------------------------------------------------- #
# Prediction helpers
# --------------------------------------------------------------------------- #


def _materials():
    compiled = _compiled()
    source = _source()
    prompt = _prompt(compiled)
    env = _env()
    env_hash = hash_environment(env)
    return compiled, source, prompt, env, env_hash


def _req0(compiled, source, prompt, env_hash):
    return _initial_request(
        compiled, _plan(), source, prompt, _CannyBuilder(), env_hash, _OUTPUT, 0
    )


def _predict_ids():
    """Precompute initial and round-one style-scale-repaired artifact IDs."""
    compiled, source, prompt, env, env_hash = _materials()
    req0 = _req0(compiled, source, prompt, env_hash)
    initial = ArtifactId(_expected_artifact_id(req0))
    decision = plan_repair_action(
        req0,
        _decision_id(_JOB, _OUTPUT, 0, 1),
        RuleId("STYLE_LOW"),
        INCREASE_STYLE_SCALE,
    )
    repaired_req = build_repair_request(
        req0, decision, _attempt_id(_JOB, _OUTPUT, 0, 1)
    )
    repaired = ArtifactId(_expected_artifact_id(repaired_req))
    return compiled, source, prompt, env, env_hash, initial, repaired


def _run(
    compiled,
    source,
    prompt,
    env,
    env_hash,
    verifier,
    backend,
    tmp_path,
    bundle_name="wf002-bundle",
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root_fd = os.open(str(tmp_path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        return run_fake_job(
            _spec_text(),
            _context_with_style_low(),
            source,
            prompt,
            _CannyBuilder(),
            env,
            _plan(),
            _make_store(tmp_path),
            root_fd,
            bundle_name,
            verifier=verifier,
            backend=backend,
        )
    finally:
        os.close(root_fd)


def _make_store(tmp_path):
    from specstyle.workflow.job_store import JobStore

    store_dir = tmp_path / "store"
    store_dir.mkdir(parents=True, exist_ok=True)
    return JobStore(store_dir)


# --------------------------------------------------------------------------- #
# Four terminal chains
# --------------------------------------------------------------------------- #


def _configure_verifier(chain, initial, repaired):
    verifier = FakeVerifier()
    if chain == "approved":
        return verifier
    if chain == "repair_approved":
        verifier.script(initial, {"STYLE_LOW": RuleStatus.FAIL})
        return verifier
    if chain == "exhausted_rejected":
        verifier.script(initial, {"STYLE_LOW": RuleStatus.FAIL})
        verifier.script(repaired, {"STYLE_LOW": RuleStatus.FAIL})
        return verifier
    if chain == "unverifiable_manual":
        verifier.script(initial, {"STYLE_LOW": RuleStatus.UNVERIFIABLE})
        return verifier
    raise AssertionError(f"unknown chain {chain}")


_CHAIN_EXPECT = {
    "approved": (
        ArtifactStatus.APPROVED,
        DecisionReason.ALL_REQUIRED_PASS,
        RepairStopReason.PASS_ALL_REQUIRED,
        0,
    ),
    "repair_approved": (
        ArtifactStatus.APPROVED,
        DecisionReason.ALL_REQUIRED_PASS,
        RepairStopReason.PASS_ALL_REQUIRED,
        1,
    ),
    "exhausted_rejected": (
        ArtifactStatus.REJECTED,
        DecisionReason.REPAIR_EXHAUSTED,
        RepairStopReason.NO_IMPROVEMENT,
        1,
    ),
    "unverifiable_manual": (
        ArtifactStatus.MANUAL_REVIEW,
        DecisionReason.MANUAL_POLICY,
        RepairStopReason.MANUAL_REQUEST,
        0,
    ),
}


@pytest.mark.parametrize(
    "chain",
    ["approved", "repair_approved", "exhausted_rejected", "unverifiable_manual"],
)
def test_fake_job_runs_each_terminal_chain(chain: str, tmp_path: Path) -> None:
    compiled, source, prompt, env, env_hash, initial, repaired = _predict_ids()
    verifier = _configure_verifier(chain, initial, repaired)
    result = _run(
        compiled, source, prompt, env, env_hash, verifier, FakeBackend(), tmp_path
    )

    assert result.final_status == "COMPLETED"
    assert result.bundle is not None
    assert len(result.terminals) == 1
    assert len(result.histories) == 1
    decision = result.terminals[0].artifact_decision
    status, reason, stop, rounds = _CHAIN_EXPECT[chain]
    assert decision.artifact_status is status
    assert decision.decision_reason is reason
    assert decision.repair_stop_reason is stop
    assert result.histories[0].rounds == rounds
    # The terminal artifact ID matches the current artifact.
    assert decision.artifact_id == result.histories[0].current_target_artifact_id


# --------------------------------------------------------------------------- #
# INV-WF002-1 canonical parse
# --------------------------------------------------------------------------- #


def test_bundle_documents_canonical_round_trip(tmp_path: Path) -> None:
    compiled, source, prompt, env, env_hash, _initial, _repaired = _predict_ids()
    result = _run(
        compiled, source, prompt, env, env_hash, FakeVerifier(), FakeBackend(), tmp_path
    )
    assert result.final_status == "COMPLETED"
    bundle_dir = tmp_path / "wf002-bundle"
    for name in (
        "manifest.json",
        "qa_report.json",
        "asset_credits.json",
        "style_spec.yaml",
        "environment.json",
    ):
        data = (bundle_dir / name).read_bytes()
        assert_canonical_round_trip(data)
        parse_strict(data)  # Reject duplicate keys, NaN, and infinity.


# --------------------------------------------------------------------------- #
# INV-WF002-2 terminal isolation
# --------------------------------------------------------------------------- #


def test_approved_artifact_lives_only_under_approved(tmp_path: Path) -> None:
    compiled, source, prompt, env, env_hash, _i, _r = _predict_ids()
    result = _run(
        compiled, source, prompt, env, env_hash, FakeVerifier(), FakeBackend(), tmp_path
    )
    bundle_dir = tmp_path / "wf002-bundle"
    artifact_id = result.terminals[0].artifact_decision.artifact_id.value
    assert (bundle_dir / "approved" / _OUTPUT / f"{artifact_id}.png").exists()
    assert not _pngs(bundle_dir / "rejected")
    assert not _pngs(bundle_dir / "manual_review")


def test_rejected_artifact_lives_only_under_rejected(tmp_path: Path) -> None:
    compiled, source, prompt, env, env_hash, initial, repaired = _predict_ids()
    verifier = _configure_verifier("exhausted_rejected", initial, repaired)
    result = _run(
        compiled, source, prompt, env, env_hash, verifier, FakeBackend(), tmp_path
    )
    bundle_dir = tmp_path / "wf002-bundle"
    artifact_id = result.terminals[0].artifact_decision.artifact_id.value
    assert (bundle_dir / "rejected" / "source" / f"{artifact_id}.png").exists()
    assert not _pngs(bundle_dir / "approved")


def test_manual_review_artifact_lives_only_under_manual_review(tmp_path: Path) -> None:
    compiled, source, prompt, env, env_hash, initial, repaired = _predict_ids()
    verifier = _configure_verifier("unverifiable_manual", initial, repaired)
    result = _run(
        compiled, source, prompt, env, env_hash, verifier, FakeBackend(), tmp_path
    )
    bundle_dir = tmp_path / "wf002-bundle"
    artifact_id = result.terminals[0].artifact_decision.artifact_id.value
    assert (bundle_dir / "manual_review" / "source" / f"{artifact_id}.png").exists()
    assert not _pngs(bundle_dir / "approved")


def _pngs(path: Path) -> list[str]:
    if not path.exists():
        return []
    found: list[str] = []
    for entry in path.rglob("*.png"):
        found.append(str(entry))
    return found


# --------------------------------------------------------------------------- #
# INV-WF002-3 deterministic (FakeBackend bit-exact, not Spec replay)
# --------------------------------------------------------------------------- #


def test_same_input_reproduces_bit_exact_bundle_sha(tmp_path: Path) -> None:
    compiled, source, prompt, env, env_hash, _i, _r = _predict_ids()
    r1 = _run(
        compiled,
        source,
        prompt,
        env,
        env_hash,
        FakeVerifier(),
        FakeBackend(),
        tmp_path / "a",
    )
    r2 = _run(
        compiled,
        source,
        prompt,
        env,
        env_hash,
        FakeVerifier(),
        FakeBackend(),
        tmp_path / "b",
    )
    assert r1.final_status == "COMPLETED"
    assert r2.final_status == "COMPLETED"
    assert r1.bundle is not None and r2.bundle is not None
    assert r1.bundle.bundle_sha256 == r2.bundle.bundle_sha256
    assert r1.bundle.payload_sha256 == r2.bundle.payload_sha256


# --------------------------------------------------------------------------- #
# INV-WF002-5 idempotent recovery
# --------------------------------------------------------------------------- #


def test_restart_of_completed_job_skips_generation_and_export(tmp_path: Path) -> None:
    compiled, source, prompt, env, env_hash, _i, _r = _predict_ids()
    store = _make_store(tmp_path)
    root_fd = os.open(str(tmp_path), os.O_RDONLY | os.O_DIRECTORY)
    spec_text = _spec_text()
    ctx = _context_with_style_low()
    builder = _CannyBuilder()
    plan = _plan()
    try:
        first = run_fake_job(
            spec_text,
            ctx,
            source,
            prompt,
            builder,
            env,
            plan,
            store,
            root_fd,
            "wf002-bundle",
            verifier=FakeVerifier(),
            backend=FakeBackend(),
        )
        assert first.final_status == "COMPLETED"
        assert first.bundle is not None
        bundle_dir = tmp_path / "wf002-bundle"
        artifact_id = first.terminals[0].artifact_decision.artifact_id.value
        approved_png = bundle_dir / "approved" / _OUTPUT / f"{artifact_id}.png"
        assert approved_png.exists()
        mtime_before = approved_png.stat().st_mtime_ns

        spy = _SpyBackend()
        second = run_fake_job(
            spec_text,
            ctx,
            source,
            prompt,
            builder,
            env,
            plan,
            store,
            root_fd,
            "wf002-bundle",
            verifier=FakeVerifier(),
            backend=spy,
        )
        assert second.final_status == "COMPLETED"
        assert second.bundle is None  # Published bundle takes the restart shortcut.
        assert spy.generate_calls == 0  # Restart does not regenerate.
        assert approved_png.stat().st_mtime_ns == mtime_before  # Bundle is untouched.
    finally:
        os.close(root_fd)


# --------------------------------------------------------------------------- #
# INV-WF002-4 + import graph
# --------------------------------------------------------------------------- #


def test_orchestrator_import_graph_excludes_torch_diffusers_gradio() -> None:
    import specstyle.workflow.orchestrator as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"torch", "diffusers", "gradio"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    assert not (imported & forbidden), (
        f"orchestrator imports forbidden: {imported & forbidden}"
    )


def test_run_fake_job_is_positional_only_with_keyword_verifier_backend() -> None:
    import inspect

    params = inspect.signature(run_fake_job).parameters
    positional = [
        name
        for name, param in params.items()
        if param.kind is inspect.Parameter.POSITIONAL_ONLY
    ]
    assert positional == [
        "spec_text",
        "context",
        "source",
        "prompt",
        "control_builder",
        "environment",
        "plan",
        "job_store",
        "root_fd",
        "bundle_name",
    ]
    assert set(
        p.name for p in params.values() if p.kind is inspect.Parameter.KEYWORD_ONLY
    ) == {
        "verifier",
        "backend",
    }


def test_fake_job_plan_and_result_are_frozen_slotted() -> None:
    from dataclasses import FrozenInstanceError, fields

    plan = _plan()
    result = FakeJobResult(None, (), (), (), "COMPLETED")
    assert tuple(f.name for f in fields(FakeJobPlan)) == (
        "job_id",
        "output_profiles",
        "generation_profile",
        "variation_index",
        "item_count",
    )
    assert tuple(f.name for f in fields(FakeJobResult)) == (
        "bundle",
        "cohorts",
        "terminals",
        "histories",
        "final_status",
    )
    assert not hasattr(plan, "__dict__")
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        plan.item_count = 2  # type: ignore[misc]
