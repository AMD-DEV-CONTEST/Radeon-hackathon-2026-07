"""CPU fixtures for reliability fault injection (no tests.* imports)."""

from __future__ import annotations

import json
from dataclasses import replace
from io import BytesIO

from PIL import Image

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.enums import (
    RepairStopReason,
    RuleLevel,
    RuleScope,
    RuleStatus,
)
from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    AttemptId,
    Identifier,
    JobId,
    RuleId,
    Sha256,
)
from specstyle.exporting.manifest import (
    AssetCredit,
    ExportCohort,
    ExportItem,
    ExportRequest,
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
from specstyle.repair.actions import INCREASE_STYLE_SCALE
from specstyle.repair.history import start_repair_history
from specstyle.repair.loop import RepairTerminal
from specstyle.spec.compiled_models import (
    CompilerContext,
    EncoderCapability,
    ModelCapability,
    OutputProfileCapability,
    ResourcePin,
    RuleCapability,
    RuleCatalogCapability,
    RuntimeCapability,
    StrengthMappingCapability,
    StrengthMappingEntry,
    ThresholdMetricCapability,
    ThresholdProfileCapability,
)
from specstyle.spec.compiler import compile_style_spec
from specstyle.spec.loader import load_style_spec_text
from specstyle.spec.models import StyleSpecV1
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import RuleResult, VerificationReport
from specstyle.workflow.orchestrator import (
    FakeJobPlan,
    _initial_request,
)

_OUTPUT = "xhs_grid"
_JOB = JobId("wf002-job")


def _sha(character: str) -> Sha256:
    return Sha256(character * 64)


def _pin(name: str, character: str) -> ResourcePin:
    return ResourcePin(name, "r1", _sha(character))


def sample_style_spec() -> StyleSpecV1:
    return StyleSpecV1.model_validate(
        {
            "schema_version": "1.0",
            "schema_uri": "schemas/style-spec-1.0.schema.json",
            "metadata": {
                "spec_id": "spec",
                "name": "Spec",
                "author": "author",
                "created_at": "2026-07-30T00:00:00Z",
                "parent_spec": None,
            },
            "runtime": {
                "backend": "rocm",
                "rocm_version": "6",
                "torch_version": "2",
                "diffusers_version": "0",
                "dtype": "float16",
            },
            "models": {
                "base": {"id": "base", "revision": "r1", "sha256": "a" * 64},
                "ip_adapter": {"id": "adapter", "revision": "r1", "sha256": "b" * 64},
                "controlnet": {
                    "type": "canny",
                    "id": "control",
                    "revision": "r1",
                    "sha256": "c" * 64,
                },
            },
            "assets": {
                "style_references": (
                    {
                        "asset_sha256": "d" * 64,
                        "source_url": "https://example.com/a",
                        "license": "CC0",
                        "attribution": "author",
                        "consent": "not_applicable",
                    },
                )
            },
            "profiles": {
                "preview": {
                    "pipeline": "sdxl_turbo",
                    "resolution": (512, 512),
                    "steps": 4,
                    "guidance_scale": 0.0,
                },
                "production": {
                    "pipeline": "sdxl_base",
                    "resolution": (1024, 1024),
                    "steps": 30,
                    "guidance_scale": 5.0,
                    "scheduler": "euler",
                },
            },
            "style": {
                "preset_id": "preset",
                "user_strength": 0.7,
                "preview_ip_adapter_scale": 0.55,
                "production_ip_adapter_scale": 0.72,
            },
            "generation": {
                "img2img_strength": 0.45,
                "controlnet_scale": 0.7,
                "seed_policy": "per_asset_deterministic",
                "batch_execution": "sequential",
            },
            "domain": {
                "profile": "product_instance",
                "verifier_version": None,
                "fidelity_required": False,
            },
            "outputs": {"profiles": ("xhs_grid",)},
            "verification": {
                "ruleset_version": "1",
                "gate_defaults": {
                    "on_unverifiable": "reject",
                    "on_warning": "manual_review",
                },
                "l2": {
                    "encoder_id": "encoder",
                    "encoder_revision": "r1",
                    "preprocessing_version": "p1",
                    "threshold_profile": {
                        "id": "l2-profile",
                        "revision": "r1",
                        "sha256": "e" * 64,
                    },
                },
                "l3": None,
            },
            "repair": {
                "policy_version": "1",
                "max_rounds": 1,
                "stop_after_no_improvement": 1,
            },
            "replay_contract": {
                "mode": "semantic",
                "tolerated_metric_delta": {
                    "l2_style_fidelity": 0.0,
                    "l3_fidelity": 0.0,
                },
                "new_batch": {
                    "contract": "same_compiled_graph_and_gate_definitions",
                    "per_item_metric_equality_required": False,
                },
            },
        }
    )


def sample_compiler_context() -> CompilerContext:
    runtime_pin = _pin("runtime", "f")
    encoder_pin = _pin("encoder", "9")
    verifier = _pin("verifier", "8")
    rules = (
        RuleCapability(
            RuleId("l1"),
            "L1_TECHNICAL",
            RuleLevel.L1,
            RuleScope.ITEM,
            "always_required",
            ("product_instance",),
            ("xhs_grid",),
            verifier,
            "none",
            None,
            1,
            (),
        ),
        RuleCapability(
            RuleId("style"),
            "L2_STYLE_FIDELITY",
            RuleLevel.L2,
            RuleScope.ITEM,
            "always_required",
            ("product_instance",),
            ("xhs_grid",),
            verifier,
            "l2",
            Identifier("style-metric"),
            2,
            (Identifier("repair-style"),),
        ),
        RuleCapability(
            RuleId("batch"),
            "L2_BATCH_CONSISTENCY",
            RuleLevel.L2,
            RuleScope.BATCH,
            "always_advisory",
            ("product_instance",),
            ("xhs_grid",),
            verifier,
            "l2",
            Identifier("batch-metric"),
            3,
            (),
        ),
    )
    return CompilerContext(
        _pin("compiler", "7"),
        (RuntimeCapability(runtime_pin, "rocm", "6", "2", "0", "float16"),),
        (
            ModelCapability(
                "base",
                _pin("base", "a"),
                None,
                ("sdxl_turbo", "sdxl_base"),
                ("float16",),
                (runtime_pin.sha256,),
            ),
            ModelCapability(
                "ip_adapter",
                _pin("adapter", "b"),
                None,
                ("sdxl_turbo", "sdxl_base"),
                ("float16",),
                (runtime_pin.sha256,),
            ),
            ModelCapability(
                "controlnet",
                _pin("control", "c"),
                "canny",
                ("sdxl_turbo", "sdxl_base"),
                ("float16",),
                (runtime_pin.sha256,),
            ),
        ),
        (
            EncoderCapability(
                encoder_pin, "p1", "layer", "cosine", (runtime_pin.sha256,)
            ),
        ),
        (
            StrengthMappingCapability(
                _pin("mapping", "6"),
                Identifier("preset"),
                (
                    StrengthMappingEntry(0.0, 0.0, 0.0),
                    StrengthMappingEntry(0.7, 0.55, 0.72),
                    StrengthMappingEntry(1.0, 1.0, 1.0),
                ),
            ),
        ),
        (
            OutputProfileCapability(
                _pin("output", "5"),
                "xhs_grid",
                ("product_instance",),
                ("preview", "production"),
            ),
        ),
        (RuleCatalogCapability("1", _pin("rules", "4"), rules),),
        (
            ThresholdProfileCapability(
                _pin("l2-profile", "e"),
                "l2",
                "l2",
                "VALIDATED",
                Identifier("preset"),
                "product_instance",
                encoder_pin,
                None,
                (
                    ThresholdMetricCapability(Identifier("style-metric"), ">=", 0.5),
                    ThresholdMetricCapability(Identifier("batch-metric"), "<=", 0.3),
                ),
                _sha("1"),
                _sha("2"),
                _sha("3"),
            ),
        ),
        (),
    )


def sample_spec_text() -> str:
    data = sample_style_spec().model_dump(mode="python", round_trip=True)
    data["repair"]["policy_version"] = "1.0"
    data["verification"]["gate_defaults"]["on_unverifiable"] = "manual_review"
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


def sample_context_with_style_low() -> CompilerContext:
    base = sample_compiler_context()
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


def sample_environment() -> EnvironmentSnapshot:
    na = TextObservation("UNAVAILABLE", None, "NOT_REPORTED")
    inv = DeviceInventory("UNAVAILABLE", "NOT_INSTALLED", ())
    return EnvironmentSnapshot("1.0", na, na, na, na, na, na, na, na, na, na, inv)


def sample_source():
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


class CannyBuilder:
    def build(self, source, graph):
        return PreparedControlInput("canny", source)


def sample_prompt(compiled):
    graph = compiled.production_graphs[0]
    return RenderedPrompt(
        ResourcePin("template", "r1", Sha256("e" * 64)),
        graph.preset_id,
        "a prompt",
        "",
    )


def sample_plan() -> FakeJobPlan:
    return FakeJobPlan(_JOB, (_OUTPUT,), "production", 0, 1)


def sample_compiled():
    return compile_style_spec(
        load_style_spec_text(sample_spec_text()), sample_context_with_style_low()
    )


class ScriptedVerifier:
    """Scriptable FakeVerifier for reliability/integration CPU paths."""

    def __init__(self) -> None:
        self._scripts: dict[str, dict[str, RuleStatus]] = {}

    def script(self, artifact_id: ArtifactId, outcomes: dict[str, RuleStatus]) -> None:
        self._scripts[artifact_id.value] = dict(outcomes)

    def _status(self, artifact_id: ArtifactId, rule_id: RuleId) -> RuleStatus:
        return self._scripts.get(artifact_id.value, {}).get(
            rule_id.value, RuleStatus.PASS
        )

    def verify(self, artifacts, rules, /):
        results = []
        for rule in rules:
            if rule.scope is RuleScope.ITEM:
                for art in artifacts:
                    results.append(
                        RuleResult(
                            rule.rule_id,
                            self._status(art.artifact_id, rule.rule_id),
                            (art.artifact_id,),
                            None,
                        )
                    )
            else:
                status = RuleStatus.PASS
                for art in artifacts:
                    candidate = self._status(art.artifact_id, rule.rule_id)
                    if candidate is not RuleStatus.PASS:
                        status = candidate
                results.append(
                    RuleResult(
                        rule.rule_id,
                        status,
                        tuple(a.artifact_id for a in artifacts),
                        None,
                    )
                )
        return tuple(results)


def sample_materials():
    compiled = sample_compiled()
    source = sample_source()
    prompt = sample_prompt(compiled)
    env = sample_environment()
    env_hash = hash_environment(env)
    return compiled, source, prompt, env, env_hash


def sample_root_request(compiled, source, prompt, env_hash):
    return _initial_request(
        compiled,
        sample_plan(),
        source,
        prompt,
        CannyBuilder(),
        env_hash,
        _OUTPUT,
        0,
    )


def sample_production_request(env=None) -> GenerationRequest:
    if env is None:
        env = sample_environment()
    raw = sample_style_spec().model_dump(mode="python")
    raw["repair"]["policy_version"] = "1.0"
    compiled = compile_style_spec(
        StyleSpecV1.model_validate(raw), sample_compiler_context()
    )
    source = sample_source()
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


def sample_approved_export_request(env=None) -> ExportRequest:
    """Valid ExportRequest with APPROVED artifact for export_bundle fail-closed tests."""
    if env is None:
        env = sample_environment()
    request = sample_production_request(env)
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
    item = ExportItem(history, terminal, None)
    cohort = ExportCohort("xhs_grid", report, (item,))
    style_ref = request.compiled_spec.source_spec.assets.style_references[0]
    credits = (
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
    return ExportRequest((cohort,), env, credits)
