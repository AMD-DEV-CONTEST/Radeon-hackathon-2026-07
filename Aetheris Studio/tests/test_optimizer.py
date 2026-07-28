"""
Unit test suite for Aetheris ROCm Kernel Optimizer subsystem.
Validates optimizer enablement, catalog parameter schema validation, sandbox cloning with SHA-256 integrity and path containment, deterministic C++ source transformation, entropy calculation, candidate registry persistence with correct FlightRecorder API, GPU safety locking, interleaved A/B benchmark execution against isolated instances, and (gpu_required) a real end-to-end run against two isolated vte-server instances on physical hardware.
"""

import hashlib
import tempfile
from pathlib import Path

import pytest

from core.optimizer import is_optimizer_enabled
from core.optimizer.applier import TransformationApplier
from core.optimizer.benchmark import BenchmarkMetrology, GPUSafetyLock
from core.optimizer.catalog import CatalogValidator, TransformationCatalog
from core.optimizer.registry import CandidateRegistry
from core.optimizer.sandbox import PathContainmentError, TemplateSandbox
from core.optimizer.validator import CandidateValidator


@pytest.fixture(autouse=True)
def _cleanup_orig_backup():
    """clone_official_template() always refreshes .orig in the REAL,
    tracked vte_templates_dir now (see sandbox.py's staleness fix) -- any
    test that clones a template leaves that file behind unless something
    removes it. One autouse fixture here beats remembering a try/finally
    in every such test."""
    orig_path = TemplateSandbox().vte_templates_dir / "gemv_q4k.hip.template.orig"
    yield
    if orig_path.exists():
        orig_path.unlink()


def test_optimizer_enablement_flag(monkeypatch):
    monkeypatch.setenv("AETHERIS_OPTIMIZER_ENABLED", "true")
    assert is_optimizer_enabled() is True
    monkeypatch.setenv("AETHERIS_OPTIMIZER_ENABLED", "false")
    assert is_optimizer_enabled() is False


def test_catalog_validator_schema():
    assert CatalogValidator.validate_params({"UNROLL_FACTOR": 4}) is True
    assert CatalogValidator.validate_params({"UNROLL_FACTOR": 5}) is False
    assert CatalogValidator.validate_params({"UNROLL_FACTOR": "4"}) is False


def test_catalog_validator_rejects_removed_block_size():
    """BLOCK_SIZE was removed after it was shown never to change the real
    launch geometry (fixed at GEMV_COALESCED_BLOCK=64 in VTE) and to be
    latently unsafe at 32. An unknown knob must be REJECTED rather than
    silently ignored, which is how it went unnoticed originally."""
    assert CatalogValidator.validate_params({"BLOCK_SIZE": 128, "UNROLL_FACTOR": 4}) is False
    assert CatalogValidator.validate_params({"BLOCK_SIZE": 64}) is False
    assert CatalogValidator.validate_params({"SOME_FUTURE_KNOB": 1, "UNROLL_FACTOR": 4}) is False


def test_applier_never_touches_warp_sums():
    """The removed BLOCK_SIZE substitution used to rewrite this array.
    Nothing in the catalog may resize it again without also making the
    launch geometry itself parameterizable."""
    catalog = TransformationCatalog()
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = TemplateSandbox(sandbox_dir=Path(tmpdir))
        cloned_path = sandbox.clone_official_template("gemv_q4k")
        applier = TransformationApplier()
        for trans in catalog.get_transformations_for_kernel("gemv_q4k"):
            assert "warp_sums[32]" in applier.apply(cloned_path, trans)


def test_transformation_catalog():
    catalog = TransformationCatalog()
    items = catalog.get_transformations_for_kernel("gemv_q4k")
    assert len(items) >= 3
    default_t = catalog.get_default_transformation("gemv_q4k")
    assert default_t is not None
    assert default_t.transformation_id == "base"


def test_catalog_returns_empty_for_unknown_kernel():
    catalog = TransformationCatalog()
    items = catalog.get_transformations_for_kernel("nonexistent_kernel")
    assert items == []
    default_t = catalog.get_default_transformation("nonexistent_kernel")
    assert default_t is None


def test_sandbox_cloning_preserves_original():
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = TemplateSandbox(sandbox_dir=Path(tmpdir))

        original_file = sandbox.vte_templates_dir / "gemv_q4k.hip.template"
        original_hash = hashlib.sha256(original_file.read_bytes()).hexdigest()

        cloned_path = sandbox.clone_official_template("gemv_q4k")
        assert cloned_path.exists()
        assert cloned_path.name == "gemv_q4k_candidate.hip.template"

        post_clone_hash = hashlib.sha256(original_file.read_bytes()).hexdigest()
        assert original_hash == post_clone_hash

        sandbox.cleanup_sandbox()


def test_sandbox_orig_backup_always_refreshed():
    """.orig must always reflect the official template as it stood right
    before the MOST RECENT clone -- not whichever version existed the
    first time a candidate was ever cloned (the old, stale-backup bug)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = TemplateSandbox(sandbox_dir=Path(tmpdir))
        official_file = sandbox.vte_templates_dir / "gemv_q4k.hip.template"
        orig_backup = sandbox.vte_templates_dir / "gemv_q4k.hip.template.orig"
        original_bytes = official_file.read_bytes()

        try:
            sandbox.clone_official_template("gemv_q4k")
            first_backup_hash = hashlib.sha256(orig_backup.read_bytes()).hexdigest()

            official_file.write_bytes(original_bytes + b"\n// simulated promotion\n")
            sandbox.clone_official_template("gemv_q4k")
            second_backup_hash = hashlib.sha256(orig_backup.read_bytes()).hexdigest()

            assert first_backup_hash != second_backup_hash
        finally:
            official_file.write_bytes(original_bytes)
            sandbox.cleanup_sandbox()


def test_sandbox_path_containment_rejects_traversal():
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = TemplateSandbox(sandbox_dir=Path(tmpdir))
        with pytest.raises(PathContainmentError):
            sandbox.clone_official_template("../../../../etc/passwd")
        with pytest.raises(PathContainmentError):
            sandbox.restore_official_from_backup("../../../../etc/passwd")


def test_applier_modifies_unroll_pragma():
    catalog = TransformationCatalog()
    trans = next(
        t for t in catalog.get_transformations_for_kernel("gemv_q4k")
        if t.params.get("UNROLL_FACTOR") == 8
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = TemplateSandbox(sandbox_dir=Path(tmpdir))
        cloned_path = sandbox.clone_official_template("gemv_q4k")

        with open(cloned_path, "r", encoding="utf-8") as f:
            original_code = f.read()

        applier = TransformationApplier()
        rendered = applier.apply(cloned_path, trans)

        assert len(rendered) > 0
        assert "#pragma unroll 8" in rendered
        assert "#pragma unroll\n" not in rendered

        with open(cloned_path, "r", encoding="utf-8") as f:
            post_apply_code = f.read()
        assert original_code == post_apply_code


def test_applier_base_returns_unmodified():
    catalog = TransformationCatalog()
    base_trans = catalog.get_default_transformation("gemv_q4k")
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = TemplateSandbox(sandbox_dir=Path(tmpdir))
        cloned_path = sandbox.clone_official_template("gemv_q4k")

        with open(cloned_path, "r", encoding="utf-8") as f:
            original_code = f.read()

        applier = TransformationApplier()
        rendered = applier.apply(cloned_path, base_trans)
        assert rendered == original_code


def test_entropy_calculator():
    validator = CandidateValidator()
    low_entropy = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    high_entropy = "The quick brown fox jumps over the lazy dog 1234567890!"
    empty = ""
    assert validator.calculate_entropy(low_entropy) < 1.0
    assert validator.calculate_entropy(high_entropy) > 3.0
    assert validator.calculate_entropy(empty) == 0.0


def test_gpu_safety_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        lock = GPUSafetyLock(lock_path=Path(tmpdir) / "test_gpu.lock")
        assert lock.acquire() is True
        lock.release()


def test_validate_urls_detects_byte_divergence(monkeypatch):
    """validate_urls compares two isolated INSTANCE base_urls (not two
    model names, the previous version's fundamental gap -- see
    validator.py's docstring): a real kernel-level correctness bug should
    surface as BYTE_DIVERGENCE, not silently pass."""
    def fake_generate_at(base_url, model_name, messages, temperature=0.0, max_tokens=60):
        text = "same output" if base_url == "http://official" else "DIFFERENT broken output"
        return {"choices": [{"message": {"content": text}}]}

    monkeypatch.setattr("core.optimizer.validator.generate_at", fake_generate_at)
    validator = CandidateValidator()
    ok, reason = validator.validate_urls("http://official", "http://candidate", "some-model")
    assert ok is False
    assert reason.startswith("BYTE_DIVERGENCE")


def test_validate_urls_passes_on_identical_output(monkeypatch):
    def fake_generate_at(base_url, model_name, messages, temperature=0.0, max_tokens=60):
        return {"choices": [{"message": {"content": "The quick brown fox jumps over the lazy dog 123!"}}]}

    monkeypatch.setattr("core.optimizer.validator.generate_at", fake_generate_at)
    validator = CandidateValidator()
    ok, reason = validator.validate_urls("http://official", "http://candidate", "some-model")
    assert ok is True
    assert reason == "BYTE_IDENTICAL_VERIFIED"


def test_interleaved_ab_benchmark_metrology(monkeypatch):
    """generate_at (not the old, model-name-based generate_once) is what
    benchmark.py calls now -- it hits an explicit isolated-instance
    base_url and returns the full response dict, from which
    measure_single_run reads the real usage.decoding_speed_tps."""
    def fake_generate_at(base_url, model_name, messages, temperature=0.0, max_tokens=64):
        rate = 111.0 if "official" in base_url else 133.0
        return {"choices": [{"message": {"content": "fake output"}}], "usage": {"decoding_speed_tps": rate}}

    monkeypatch.setattr("core.optimizer.benchmark.generate_at", fake_generate_at)
    bm = BenchmarkMetrology()
    res = bm.run_interleaved_ab_benchmark("http://official", "http://candidate", "some-model", trials=2)
    assert "reference_tok_s" in res
    assert "candidate_tok_s" in res
    assert res["reference_tok_s"] == 111.0
    assert res["candidate_tok_s"] == 133.0
    assert res["trials_count"] == 2


def test_iqr_significance():
    """Non-overlapping interquartile ranges mean the delta is real; this is
    the test that separates a genuine small win from run-to-run noise."""
    from core.optimizer.benchmark import _is_significant, _spread

    separated = _is_significant(_spread([100.0, 101.0, 99.0, 100.5]), _spread([140.0, 141.0, 139.0, 140.5]))
    overlapping = _is_significant(_spread([100.0, 105.0, 95.0, 110.0]), _spread([101.0, 104.0, 96.0, 109.0]))
    too_few = _is_significant(_spread([100.0]), _spread([140.0]))

    assert separated is True
    assert overlapping is False
    assert too_few is None


def test_engagement_proof_detects_non_engagement(tmp_path):
    """A candidate that compiled byte-identical source, or never compiled
    the kernel at all, must be reported as NOT_ENGAGED: otherwise its
    benchmark number is indistinguishable from a real ~0% result."""
    from core.optimizer.isolated_runner import verify_engagement

    def _mk(root: Path, source: str | None) -> Path:
        logs = root / "logs" / "Codegen"
        logs.mkdir(parents=True, exist_ok=True)
        if source is not None:
            (logs / "gemv_q4k_abc123.hip").write_text(source, encoding="utf-8")
        return root

    official = _mk(tmp_path / "official", "kernel source A")

    engaged, reason = verify_engagement(official, _mk(tmp_path / "differs", "kernel source B"), "gemv_q4k")
    assert engaged is True and reason.startswith("ENGAGED")

    engaged, reason = verify_engagement(official, _mk(tmp_path / "same", "kernel source A"), "gemv_q4k")
    assert engaged is False and "byte-identical" in reason

    engaged, reason = verify_engagement(official, _mk(tmp_path / "never", None), "gemv_q4k")
    assert engaged is False and "never compiled" in reason


def test_graded_decision_gate():
    """KEEP requires correctness AND engagement AND a significant gain over
    the threshold. Everything else stays distinguishable instead of
    collapsing into one rejected flag."""
    from core.optimizer.runner import _decide

    assert _decide(correctness_passed=False)["decision"] == "REVERT"
    assert _decide(correctness_passed=True, engaged=False, engagement_reason="x")["decision"] == "REVERT"
    assert _decide(correctness_passed=True, engaged=True, speedup_pct=-35.0, significant=True)["decision"] == "REVERT"
    assert _decide(correctness_passed=True, engaged=True, speedup_pct=12.0, significant=False)["decision"] == "NEEDS_REVIEW"
    assert _decide(correctness_passed=True, engaged=True, speedup_pct=12.0, significant=None)["decision"] == "NEEDS_REVIEW"
    assert _decide(correctness_passed=True, engaged=True, speedup_pct=0.4, significant=True)["decision"] == "NEEDS_REVIEW"

    keep = _decide(correctness_passed=True, engaged=True, speedup_pct=12.0, significant=True)
    assert keep["decision"] == "KEEP"
    assert keep["validated"] is True


def test_candidate_registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        reg = CandidateRegistry(registry_file=reg_file)
        cand_data = {
            "kernel_name": "gemv_q4k",
            "transformation_id": "unroll_8",
            "speedup_pct": 8.4,
            "validated": True,
        }
        cand_id = reg.register_candidate(cand_data)
        assert cand_id.startswith("cand_gemv_q4k_")
        cands = reg.get_candidates()
        assert len(cands) == 1
        assert cands[0]["id"] == cand_id


@pytest.mark.gpu_required
def test_run_optimization_end_to_end_real_gpu(monkeypatch):
    """The real integration test the previous test suite never had: spins
    up two ACTUAL isolated vte-server instances on physical AMD GPU
    hardware (not mocked), validates correctness, benchmarks with real
    GPU-measured decoding_speed_tps, and confirms a candidate is only ever
    registered with the number genuinely measured in THIS run -- never a
    fixed value. Everything before this test in the file is a fast unit
    test with mocked I/O; this is the one that would have caught the
    original disconnect (validator/benchmark comparing two unrelated model
    NAMES, never a real kernel change) that the old suite's mocks papered
    over completely.

    Asserts on the EVIDENCE CHAIN rather than on a particular verdict: the
    verdict legitimately depends on how this transformation performs on the
    machine running the test, and pinning it would make the test
    hardware-dependent. What must always hold is that every stage produced
    real evidence and that registration follows the decision.
    A registry_file override keeps this test out of the real
    registry.json."""
    monkeypatch.setenv("AETHERIS_OPTIMIZER_ENABLED", "true")
    from core.optimizer.runner import run_optimization

    with tempfile.TemporaryDirectory() as tmpdir:
        registry = CandidateRegistry(registry_file=Path(tmpdir) / "registry.json")
        results = run_optimization(
            "gemv_q4k", transformation_id="unroll_8", trials=2, registry=registry,
        )

        assert len(results) == 1
        entry = results[0]
        assert entry.get("skip_reason") is None, entry.get("skip_reason")

        # Correctness ran, on real hardware, before anything was measured.
        assert entry["correctness"] == "BYTE_IDENTICAL_VERIFIED"
        # The candidate kernel genuinely reached the GPU: this is the check
        # that separates "measured ~0%" from "never actually ran".
        assert entry["engaged"] is True, entry["engagement"]
        # A real measurement, not the 8.4 the old disconnected pipeline
        # always produced from a test fixture.
        assert isinstance(entry["speedup_pct"], float)
        assert entry["speedup_pct"] != 8.4
        assert entry["significant"] in (True, False, None)
        assert entry["decision"] in ("KEEP", "NEEDS_REVIEW", "REVERT")

        # Registration must follow the decision, in both directions.
        registered = registry.get_candidates()
        if entry["decision"] == "KEEP":
            assert len(registered) == 1
            assert registered[0]["speedup_pct"] == entry["speedup_pct"]
        else:
            assert registered == []
