"""Tests for MODEL_ROUTER_LOCK_001.

The model router promotes the prose-only ``scripts/model_advisor.py``
into a typed routing surface. These tests assert that:

  * Every task class routes deterministically (same inputs → same record).
  * Unsupported task classes (including UNKNOWN) fail closed.
  * Stale model ids are detected and block.
  * Missing local model availability falls back along the chain.
  * Dry-run mode never sets execution_authorized=True.
  * NO_MODEL is allowed for explanation/summary tasks.
  * No corpus mutation, no source mutation, no T:/ dependency.
  * Config defaults fail closed (DRY_RUN, no network, no unverified ids).
  * The evidence record validates against its lock manifest.
  * The audit's path rule for scripts/models/ is registered.
  * The architecture gauntlet remains green (rolled-up under a separate
    check; here we just assert the audit counts the router did not
    introduce new BLOCKED_UNSAFE / MUST_MIGRATE / UNKNOWN sites).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

router_mod = importlib.import_module("models.model_router")
record_mod = importlib.import_module("models.model_router_record")
inventory_mod = importlib.import_module("models.model_inventory")
audit_mod = importlib.import_module("dev.parallel_execution_layer_audit")

TaskClass = router_mod.TaskClass
ModelRole = router_mod.ModelRole
RouteDecision = router_mod.RouteDecision
RouterMode = router_mod.RouterMode
RouterConfig = router_mod.RouterConfig
ModelRouter = router_mod.ModelRouter
LocalModelInventory = inventory_mod.LocalModelInventory
RouteRecord = record_mod.RouteRecord

LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "model_router"
LOCK_PATH = LOCKS_DIR / "MODEL_ROUTER_LOCK_001.json"


STATUS_TOKENS = frozenset(
    {
        "MODEL_ROUTER_READY",
        "ROUTER_DRY_RUN_DEFAULT",
        "ROUTER_FAILS_CLOSED_ON_UNKNOWN",
        "ROUTER_DETECTS_STALE_MODEL_ID",
        "ROUTER_FALLBACK_CHAIN_DETERMINISTIC",
        "ROUTER_NO_NETWORK",
        "ROUTER_NO_SUBPROCESS",
        "ROUTER_NO_T_DRIVE",
        "ROUTER_NO_CORPUS_MUTATION",
        "ROUTER_NO_SOURCE_MUTATION",
        "ROUTER_TRAINING_ELIGIBILITY_FALSE",
        "ROUTER_CORPUS_WRITE_FALSE",
        "ROUTER_EXECUTION_AUTHORIZED_ONLY_LIVE",
        "ROUTER_INVENTORY_PASSIVE",
        "ROUTER_RECORD_SERIALIZABLE",
        "STALE_DEFAULT_REPLACED_IN_CODEBASE_EXPLORER",
        "AUDIT_PATH_RULE_REGISTERED",
        "PROGRAMBENCH_PRESERVED",
        "SAFETY_DEFAULTS_RESPECTED",
    }
)


def _flat(text: str) -> str:
    """Collapse whitespace runs so a source grep survives the formatter.

    These guards match exact source text. `ruff format` changed the exact whitespace they
    keyed on -- three spaces before a comment became two, two after a comma became one, a
    one-line argument pair got split across two -- and every one of them went silently
    vacuous, reporting "found in no files", which is also what they print when the thing they
    guard has been DELETED. A guard whose blind mode is indistinguishable from the condition
    it guards against is not guarding.

    Comparing flattened text keeps the check identical -- same tokens, same order -- while
    dropping a dependency on spacing that a formatter is entitled to change at any time.
    """
    return re.sub(r"\s+", " ", text)


def _sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_signed_evidence() -> dict[str, str]:
    out: dict[str, str] = {}
    if EVIDENCE_INDEX.is_file():
        out["assurance/evidence/evidence_index.json"] = _sha256(EVIDENCE_INDEX) or ""
    for p in sorted(LOCKS_DIR.glob("*.json")):
        rel = p.relative_to(_REPO_ROOT)
        out[str(rel).replace("\\", "/")] = _sha256(p) or ""
    return out


# ---------------------------------------------------------------------------
# Status / closed set
# ---------------------------------------------------------------------------


def test_status_tokens_match_expected_set():
    expected = {
        "MODEL_ROUTER_READY",
        "ROUTER_DRY_RUN_DEFAULT",
        "ROUTER_FAILS_CLOSED_ON_UNKNOWN",
        "ROUTER_DETECTS_STALE_MODEL_ID",
        "ROUTER_FALLBACK_CHAIN_DETERMINISTIC",
        "ROUTER_NO_NETWORK",
        "ROUTER_NO_SUBPROCESS",
        "ROUTER_NO_T_DRIVE",
        "ROUTER_NO_CORPUS_MUTATION",
        "ROUTER_NO_SOURCE_MUTATION",
        "ROUTER_TRAINING_ELIGIBILITY_FALSE",
        "ROUTER_CORPUS_WRITE_FALSE",
        "ROUTER_EXECUTION_AUTHORIZED_ONLY_LIVE",
        "ROUTER_INVENTORY_PASSIVE",
        "ROUTER_RECORD_SERIALIZABLE",
        "STALE_DEFAULT_REPLACED_IN_CODEBASE_EXPLORER",
        "AUDIT_PATH_RULE_REGISTERED",
        "PROGRAMBENCH_PRESERVED",
        "SAFETY_DEFAULTS_RESPECTED",
    }
    assert set(STATUS_TOKENS) == expected


# ---------------------------------------------------------------------------
# Enum / default-route invariants
# ---------------------------------------------------------------------------


def test_default_routes_cover_every_task_class_except_unknown():
    covered = set(router_mod.DEFAULT_ROUTES.keys())
    expected = set(TaskClass) - {TaskClass.UNKNOWN}
    assert covered == expected, (
        f"DEFAULT_ROUTES must cover every TaskClass except UNKNOWN; "
        f"missing={expected - covered}, extra={covered - expected}"
    )


def test_unknown_is_explicitly_absent_from_default_routes():
    assert TaskClass.UNKNOWN not in router_mod.DEFAULT_ROUTES


def test_role_to_model_id_includes_current_ids_only():
    """Every populated role maps to a CURRENT_MODEL_IDS entry (or empty)."""
    for role, mid in router_mod.DEFAULT_ROLE_TO_MODEL_ID.items():
        if role is ModelRole.NO_MODEL:
            assert mid == ""
            continue
        assert mid in router_mod.CURRENT_MODEL_IDS, (
            f"Role {role.value} default maps to {mid!r} which is not in "
            f"CURRENT_MODEL_IDS — likely a stale id leak."
        )


def test_stale_ids_disjoint_from_current_ids():
    overlap = router_mod.STALE_MODEL_IDS & router_mod.CURRENT_MODEL_IDS
    assert not overlap, f"STALE / CURRENT overlap: {overlap}"


def test_stale_ids_include_codebase_explorer_historical_defaults():
    """The two stale defaults that lived in codebase_explorer.py lines 58-59
    (engineer-v10-dsl / observer-v5-dsl) must be in STALE_MODEL_IDS."""
    assert "determinex-engineer-v10-dsl" in router_mod.STALE_MODEL_IDS
    assert "determinex-observer-v5-dsl" in router_mod.STALE_MODEL_IDS


# ---------------------------------------------------------------------------
# Router config defaults
# ---------------------------------------------------------------------------


def test_default_router_mode_is_dry_run():
    cfg = RouterConfig()
    assert cfg.default_mode is RouterMode.DRY_RUN


def test_default_allow_network_models_false():
    cfg = RouterConfig()
    assert cfg.allow_network_models is False


def test_default_allow_unverified_model_ids_false():
    cfg = RouterConfig()
    assert cfg.allow_unverified_model_ids is False


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def test_empty_inventory_blocks_all_roles_to_no_model():
    inv = LocalModelInventory.empty()
    assert not inv  # __bool__
    assert not inv.is_available("determinex-engineer-v11-dsl")


def test_inventory_of_returns_frozenset_membership():
    inv = LocalModelInventory.of(["determinex-engineer-v11-dsl"])
    assert "determinex-engineer-v11-dsl" in inv
    assert "anything-else" not in inv


def test_inventory_from_env_uses_env_var(monkeypatch):
    monkeypatch.setenv("DETERMINEX_BUILDER_MODEL", "determinex-engineer-v11-dsl")
    monkeypatch.setenv("DETERMINEX_OBSERVER_MODEL", "determinex-observer-v6-dsl")
    monkeypatch.setenv("DETERMINEX_ARCHITECT_MODEL", "determinex-sentinel-v5-dsl")
    monkeypatch.setenv("DETERMINEX_ROUTER_AVAILABLE_MODELS", "x-extra-1,x-extra-2")
    inv = LocalModelInventory.from_env()
    assert inv.is_available("determinex-engineer-v11-dsl")
    assert inv.is_available("x-extra-1")
    assert inv.is_available("x-extra-2")


# ---------------------------------------------------------------------------
# Routing — each task class
# ---------------------------------------------------------------------------


def _fully_stocked_router() -> ModelRouter:
    """A router whose inventory has every current id."""
    inv = LocalModelInventory.of(sorted(router_mod.CURRENT_MODEL_IDS))
    return ModelRouter(inventory=inv)


@pytest.mark.parametrize("tc", [t for t in TaskClass if t is not TaskClass.UNKNOWN])
def test_every_known_task_class_routes_in_dry_run(tc):
    r = _fully_stocked_router()
    rec = r.route(tc, mode=RouterMode.DRY_RUN)
    assert rec.task_class == tc.value
    assert rec.requested_mode == RouterMode.DRY_RUN.value
    assert rec.execution_authorized is False
    assert rec.corpus_write_authorized is False
    assert rec.training_eligible is False
    # Either we picked a role or NO_MODEL — never blocked for a known class.
    assert not rec.is_blocked


@pytest.mark.parametrize("tc", [t for t in TaskClass if t is not TaskClass.UNKNOWN])
def test_every_known_task_class_routes_deterministically(tc):
    r1 = _fully_stocked_router()
    r2 = _fully_stocked_router()
    a = r1.route(tc).to_dict()
    b = r2.route(tc).to_dict()
    assert a == b, f"Route for {tc.value} is non-deterministic"


# ---------------------------------------------------------------------------
# Fail-closed: UNKNOWN
# ---------------------------------------------------------------------------


def test_unknown_task_class_is_blocked():
    r = _fully_stocked_router()
    rec = r.route(TaskClass.UNKNOWN)
    assert rec.decision == RouteDecision.ROUTE_BLOCKED_UNSUPPORTED_TASK_CLASS.value
    assert rec.execution_authorized is False
    assert rec.is_blocked


def test_unknown_string_task_class_normalizes_to_unknown_and_blocks():
    r = _fully_stocked_router()
    rec = r.route("NOT_A_REAL_TASK_CLASS")
    assert rec.task_class == TaskClass.UNKNOWN.value
    assert rec.decision == RouteDecision.ROUTE_BLOCKED_UNSUPPORTED_TASK_CLASS.value
    assert rec.execution_authorized is False


# ---------------------------------------------------------------------------
# Fail-closed: stale model ids
# ---------------------------------------------------------------------------


def test_stale_id_routed_via_role_blocks():
    """If a router's role_to_model_id maps to a stale id, the router
    short-circuits with ROUTE_BLOCKED_STALE_MODEL_ID."""
    cfg = RouterConfig(
        role_to_model_id={
            ModelRole.FAST_LOCAL: "determinex-observer-v5-dsl",  # stale
            ModelRole.STRONG_LOCAL: "determinex-sentinel-v5-dsl",
            ModelRole.CODE_SPECIALIST: "determinex-engineer-v11-dsl",
            ModelRole.REASONING_SPECIALIST: "determinex-sentinel-v5-dsl",
            ModelRole.NO_MODEL: "",
        },
    )
    r = ModelRouter(
        config=cfg,
        inventory=LocalModelInventory.of(
            sorted(router_mod.CURRENT_MODEL_IDS | {"determinex-observer-v5-dsl"})
        ),
    )
    rec = r.route(TaskClass.GENERAL_EXPLANATION)
    assert rec.decision == RouteDecision.ROUTE_BLOCKED_STALE_MODEL_ID.value
    assert rec.stale_model_id_detected is True
    assert rec.execution_authorized is False


# ---------------------------------------------------------------------------
# Fallback chain — missing preferred falls forward
# ---------------------------------------------------------------------------


def test_missing_preferred_falls_back():
    """If FAST_LOCAL not present but STRONG_LOCAL is, the router selects
    STRONG_LOCAL for REPO_TRIAGE with ROUTE_DRY_RUN_SELECTED."""
    inv = LocalModelInventory.of(["determinex-sentinel-v5-dsl"])  # only strong
    r = ModelRouter(inventory=inv)
    rec = r.route(TaskClass.REPO_TRIAGE, mode=RouterMode.DRY_RUN)
    assert rec.selected_route == ModelRole.STRONG_LOCAL.value
    assert rec.selected_model_id == "determinex-sentinel-v5-dsl"
    assert rec.decision == RouteDecision.ROUTE_DRY_RUN_SELECTED.value


def test_missing_preferred_live_uses_fallback_decision():
    inv = LocalModelInventory.of(["determinex-sentinel-v5-dsl"])  # only strong
    r = ModelRouter(inventory=inv)
    rec = r.route(TaskClass.REPO_TRIAGE, mode=RouterMode.LIVE)
    assert rec.selected_route == ModelRole.STRONG_LOCAL.value
    assert rec.decision == RouteDecision.ROUTE_FALLBACK_SELECTED.value
    assert rec.execution_authorized is True


def test_no_local_model_falls_through_to_no_model_for_summary():
    """VERIFIER_SUMMARY's chain terminates in NO_MODEL — empty inventory
    must produce ROUTE_NO_MODEL_REQUIRED, never blocked."""
    r = ModelRouter(inventory=LocalModelInventory.empty())
    rec = r.route(TaskClass.VERIFIER_SUMMARY, mode=RouterMode.LIVE)
    assert rec.decision == RouteDecision.ROUTE_NO_MODEL_REQUIRED.value
    assert rec.selected_route == ModelRole.NO_MODEL.value
    assert rec.execution_authorized is False
    assert rec.is_no_model


# ---------------------------------------------------------------------------
# Dry-run never authorizes execution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tc", [t for t in TaskClass if t is not TaskClass.UNKNOWN])
def test_dry_run_never_authorizes_execution(tc):
    r = _fully_stocked_router()
    rec = r.route(tc, mode=RouterMode.DRY_RUN)
    assert rec.execution_authorized is False, (
        f"Dry-run for {tc.value} flipped execution_authorized to True"
    )


def test_default_mode_is_dry_run_when_unspecified():
    r = _fully_stocked_router()
    rec = r.route(TaskClass.REPO_TRIAGE)
    assert rec.requested_mode == RouterMode.DRY_RUN.value
    assert rec.execution_authorized is False


# ---------------------------------------------------------------------------
# Corpus + training-eligibility invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [RouterMode.DRY_RUN, RouterMode.LIVE])
@pytest.mark.parametrize("tc", list(TaskClass))
def test_routing_never_authorizes_corpus_write_or_training_eligibility(tc, mode):
    r = _fully_stocked_router()
    rec = r.route(tc, mode=mode)
    assert rec.corpus_write_authorized is False
    assert rec.training_eligible is False


# ---------------------------------------------------------------------------
# Reproducibility: same config + same inventory → same record
# ---------------------------------------------------------------------------


def test_record_is_reproducible_from_config_and_inventory():
    inv = LocalModelInventory.of(["determinex-engineer-v11-dsl", "determinex-sentinel-v5-dsl"])
    cfg = RouterConfig()
    a = ModelRouter(config=cfg, inventory=inv).route(TaskClass.PATCH_GENERATION).to_dict()
    b = ModelRouter(config=cfg, inventory=inv).route(TaskClass.PATCH_GENERATION).to_dict()
    assert a == b


# ---------------------------------------------------------------------------
# Record serializability
# ---------------------------------------------------------------------------


def test_route_record_is_json_serializable():
    r = _fully_stocked_router()
    rec = r.route(TaskClass.REPO_TRIAGE)
    blob = rec.to_json()
    parsed = json.loads(blob)
    assert parsed["task_class"] == TaskClass.REPO_TRIAGE.value
    assert parsed["execution_authorized"] is False


def test_route_record_to_dict_round_trips_via_json():
    r = _fully_stocked_router()
    rec = r.route(TaskClass.BUILD_DIAGNOSIS)
    parsed = json.loads(rec.to_json())
    assert parsed == rec.to_dict()


# ---------------------------------------------------------------------------
# Source / corpus immutability (no module-level mutation)
# ---------------------------------------------------------------------------


def test_router_calls_do_not_mutate_signed_evidence_or_locks():
    before = _hash_signed_evidence()
    r = _fully_stocked_router()
    for tc in TaskClass:
        r.route(tc, mode=RouterMode.DRY_RUN)
        r.route(tc, mode=RouterMode.LIVE)
    after = _hash_signed_evidence()
    assert before == after, "Router exercise mutated signed evidence/locks"


def test_router_modules_do_not_import_subprocess_or_urllib():
    """Hard invariant: scripts/models/* must not import subprocess or urllib.

    The router is a pure decision surface. Even an unused import would
    suggest a future-edit hazard.
    """
    for fname in ("model_router.py", "model_router_record.py", "model_inventory.py", "__init__.py"):
        src = (_REPO_ROOT / "scripts" / "models" / fname).read_text(encoding="utf-8")
        assert "import subprocess" not in src, f"{fname} imports subprocess"
        assert "from subprocess" not in src, f"{fname} imports from subprocess"
        assert "import urllib" not in src, f"{fname} imports urllib"
        assert "from urllib" not in src, f"{fname} imports from urllib"
        # No socket / http.client either.
        assert "import socket" not in src, f"{fname} imports socket"
        assert "import http" not in src, f"{fname} imports http"


def test_router_modules_do_not_reference_t_drive():
    for fname in ("model_router.py", "model_router_record.py", "model_inventory.py", "__init__.py"):
        src = (_REPO_ROOT / "scripts" / "models" / fname).read_text(encoding="utf-8")
        assert "T:/" not in src and "T:\\" not in src, f"{fname} mentions T:/ drive"


# ---------------------------------------------------------------------------
# codebase_explorer stale-id fix
# ---------------------------------------------------------------------------


def test_codebase_explorer_no_longer_defaults_to_stale_ids():
    src = (_REPO_ROOT / "scripts" / "codebase_explorer.py").read_text(encoding="utf-8")
    # Old stale defaults must be gone as positional defaults.
    assert _flat(
        'os.getenv("DETERMINEX_BUILDER_MODEL", "determinex-engineer-v10-dsl")'
    ) not in _flat(src)
    assert _flat(
        'os.getenv("DETERMINEX_OBSERVER_MODEL", "determinex-observer-v5-dsl")'
    ) not in _flat(src)
    # New current defaults must be present.
    assert _flat('os.getenv("DETERMINEX_BUILDER_MODEL", "determinex-engineer-v11-dsl")') in _flat(
        src
    )
    assert 'os.getenv("DETERMINEX_OBSERVER_MODEL", "determinex-observer-v6-dsl")' in src


# ---------------------------------------------------------------------------
# Audit path rule
# ---------------------------------------------------------------------------


def test_audit_path_rule_registered_for_scripts_models():
    """The audit must classify any new scripts/models/* file as
    LEGACY_EXEMPT_READ_ONLY (the router is a decision-only surface)."""
    rules = audit_mod.CLASSIFICATION_RULES
    matched = [r for r in rules if r.pattern.match("scripts/models/model_router.py")]
    assert matched, "No path rule matched scripts/models/model_router.py"
    # Pick the first match (rule order is significant)
    rule = matched[0]
    assert rule.classification == "LEGACY_EXEMPT_READ_ONLY"


# ---------------------------------------------------------------------------
# Audit count guard — router must not introduce regressions
# ---------------------------------------------------------------------------


def test_audit_counts_invariants_preserved():
    """Running the audit must keep BLOCKED_UNSAFE=0, MUST_MIGRATE=0,
    UNKNOWN=0, and PROGRAMBENCH_OUT_OF_SCOPE>=56."""
    report = audit_mod.run_audit(_REPO_ROOT / "scripts")
    counts = report.counts_by_classification()
    assert counts.get("BLOCKED_UNSAFE", 0) == 0
    assert counts.get("MUST_MIGRATE_TO_HARDENED_RUNNER", 0) == 0
    assert counts.get("UNKNOWN_REQUIRES_REVIEW", 0) == 0
    assert counts.get("PROGRAMBENCH_OUT_OF_SCOPE", 0) >= 56


# ---------------------------------------------------------------------------
# Lock manifest + evidence file
# ---------------------------------------------------------------------------


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file(), f"Missing lock manifest: {LOCK_PATH}"
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "MODEL_ROUTER_LOCK_001"
    assert blob.get("scope_discipline", {}).get("programbench_touched", True) is False
    assert blob.get("scope_discipline", {}).get("docker_pulls", True) is False
    # status_tokens in manifest must be a subset of the test's expected set.
    manifest_tokens = set(blob.get("status_tokens", []))
    assert manifest_tokens.issubset(STATUS_TOKENS), (
        f"Manifest claims tokens not in the closed set: {manifest_tokens - STATUS_TOKENS}"
    )


def test_evidence_run_artifact_exists_and_references_lock():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates, f"No evidence artifact found in {EVIDENCE_DIR}"
    latest = candidates[-1]
    blob = json.loads(latest.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "MODEL_ROUTER_LOCK_001"
    assert "router_invariants" in blob or "invariants" in blob


def test_evidence_index_includes_model_router_entry():
    if not EVIDENCE_INDEX.is_file():
        pytest.skip("evidence_index.json not present")
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "MODEL_ROUTER_LOCK_001" in ids, "evidence_index missing MODEL_ROUTER_LOCK_001"
