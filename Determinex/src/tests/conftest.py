"""
tests/conftest.py — pytest bootstrap for Determinex.

Puts the project root, `scripts/`, and `determinex_trainer/` on sys.path so tests
can `import hive.*`, `import determinex_cloak`, etc. without invoking pytest
plugins or PYTHONPATH gymnastics.

Also exposes a couple of light fixtures shared by the cloak and swebench
smoke tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "scripts", _ROOT / "determinex_trainer"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Fixture projects include intentionally broken repos for intake/corpus tests;
# they are data, not test modules for the Determinex suite itself.
collect_ignore = ["fixtures"]

# Some scripts read DETERMINEX_ROOT to anchor logs/state. Keep tests isolated
# from the user's real logs by default.
os.environ.setdefault("DETERMINEX_ROOT", str(_ROOT))
os.environ.setdefault(
    "DETERMINEX_PROGRAMBENCH_EVIDENCE_WRITE_ROOT",
    str(_ROOT / ".tmp" / "pytest-programbench-evidence"),
)
os.environ.setdefault(
    "DETERMINEX_PROGRAMBENCH_OPERATOR_OUTBOX_WRITE_ROOT",
    str(_ROOT / ".tmp" / "pytest-programbench-operator-outbox"),
)


# Safety-posture env vars (DeterminexSettings' fail-closed defaults) must not
# leak in from the developer's own .env -- found live 2026-07-21: Ryan's local
# .env sets DETERMINEX_ALLOW_CLOUD_FALLBACK=1 for his own convenience, and
# once any test/module transitively called load_dotenv() (several scripts
# under scripts/ do, unconditionally, at import time), that value stuck in
# os.environ for the rest of the pytest process -- breaking ~15 "fail closed
# by default" lock tests across dev/intake/models/repair, but only when run
# as part of the full suite (order-dependent), never in isolation. Strip these
# before every test so the lock tests always see the code's real defaults;
# a test that wants a non-default value still can via its own monkeypatch.
_SAFETY_ENV_VARS = (
    "DETERMINEX_SAFETY_MODE",
    "DETERMINEX_ONLINE_DISCOVERY",
    "DETERMINEX_ALLOW_CLOUD_FALLBACK",
    "DETERMINEX_ALLOW_UNSANDBOXED",
    "DETERMINEX_REQUIRE_CLOAK",
    "DETERMINEX_OFFLINE_OBSERVER",
)


@pytest.fixture(autouse=True)
def _isolate_safety_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for _var in _SAFETY_ENV_VARS:
        monkeypatch.delenv(_var, raising=False)


# Two security scanners write their result to a COMMITTED path by design:
#   dependency_scan  -> assurance/security/dependency_scan.json
#   verify_installed -> assurance/security/installed_drift.json
# Several tests run them for real (correctly -- mocking a security gate proves nothing), so a plain
# `pytest` finished with those two tracked files modified. Two problems with that, and the second is
# the serious one: a contributor on a clean checkout cannot tell whether they broke something, and a
# test run silently REPLACES committed security evidence -- today only a fresh `generated_at`, but
# had a verdict actually changed, the new result would land in a tracked file with nobody prompted to
# look at it.
#
# Redirected here rather than in one test file because it is a property of the suite, not of any one
# test: this was first fixed locally in test_maintenance_bay_live_scan_lock.py and the files came
# back dirty from a different test on the next full run. Same reasoning as the
# DETERMINEX_PROGRAMBENCH_EVIDENCE_WRITE_ROOT redirect above.
#
# Session-scoped so the two imports and patches happen once, not once per test.
_TRACKED_SCANNER_OUTPUTS = (
    ("dependency_scan", "_SCAN_OUTPUT"),
    ("verify_installed", "_OUTPUT"),
    # Added after the first version of this fixture missed it. container_scan proved the point the
    # hard way: a full-suite run rewrote assurance/security/container_scan.json with a genuinely
    # CHANGED verdict -- image_count 9 -> 10, unpinned_count 0 -> 1 -- because a stray
    # docker/welcome-to-docker:latest had appeared on the dev machine. Not a timestamp; a security
    # finding, silently committed-adjacent. Exactly the failure this fixture exists to prevent.
    #
    # Redirecting DEFAULT_OUT sends `container_scan.main()` to tmp. security_gate then reads the
    # committed file, which is fine: the gate is advisory inventory (its own comment says so), and
    # the test's purpose is that every gate composes and runs, not that the image list is live.
    ("container_scan", "DEFAULT_OUT"),
)


@pytest.fixture(scope="session", autouse=True)
def _scanner_output_off_tracked_paths(tmp_path_factory: pytest.TempPathFactory):
    """Keep real scanner runs real, but never let them overwrite committed evidence."""
    import importlib

    sec = _ROOT / "scripts" / "security"
    if str(sec) not in sys.path:
        sys.path.insert(0, str(sec))

    out_dir = tmp_path_factory.mktemp("scanner-output")
    patcher = pytest.MonkeyPatch()
    for module_name, attr in _TRACKED_SCANNER_OUTPUTS:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            # A missing optional scanner must not break the entire suite's collection.
            continue
        # Both read the module global at call time, so patching the attribute is enough.
        patcher.setattr(module, attr, out_dir / f"{module_name}.json", raising=False)
    yield
    patcher.undo()


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A throwaway directory shaped like a tiny project root."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


@pytest.fixture
def sample_python_module(tmp_repo: Path) -> Path:
    """Write a small Python module the cloak tests can obfuscate."""
    src = tmp_repo / "src" / "app.py"
    src.write_text(
        "def compute_total(price, qty):\n"
        "    discount = 0.1 if qty > 10 else 0.0\n"
        "    return price * qty * (1 - discount)\n"
        "\n"
        "class OrderRecord:\n"
        "    def __init__(self, sku, qty):\n"
        "        self.sku = sku\n"
        "        self.qty = qty\n",
        encoding="utf-8",
    )
    return src


# ---------------------------------------------------------------------------------------
# Evidence-dependent locks: skip where the evidence tree is deliberately absent.
# ---------------------------------------------------------------------------------------
# `assurance/` is on publish_mirror.NEVER, so the PUBLIC checkout has no evidence tree and
# 226 `test_evidence_*` functions across 123 lock files assert on artifacts that cannot be
# there. They failed in CI not because anything regressed but because the artifacts are
# deliberately not distributed -- and CI that is red for a structural reason is CI that
# people learn to ignore.
#
# Centralised rather than marked file by file: 123 files is 123 chances to miss one, and
# every new lock test would inherit the same trap. The guards stay FULLY live in the
# development checkout, which is the only place the evidence exists to be guarded.
_EVIDENCE_INDEX = (
    Path(__file__).resolve().parent.parent / "assurance" / "evidence" / "evidence_index.json"
)

_EVIDENCE_TESTS = frozenset(
    {
        "test_evidence_artifact_present",
        "test_evidence_index_entry_present",
        # The `*_final_state_lock` family evaluates a record assembled FROM the evidence tree,
        # and fails with "evidence artifact file missing on disk: assurance/evidence/...".
        # Named individually rather than exempting their modules: those five modules hold 61
        # tests of which only these 20 read evidence, and skipping all 61 to cover 20 is the
        # over-skip this file already has one scar from.
        "test_aggregate_invariants",
        "test_all_six_dimensions_closed",
        "test_all_two_dimensions_closed",
        "test_live_evaluation_all_dimensions_closed",
        "test_live_evaluation_all_eight_dimensions_closed",
        "test_live_evaluation_passes",
        "test_live_evaluation_safe_for_cross_lane_boundary",
        "test_missing_rung_blocks",
        "test_next_recommended_is_repo_clinic_fixture_repair",
        "test_next_recommended_rung_is_python_cli_splash",
        "test_synthetic_full_skeleton_passes",
        "test_synthetic_repo_passes_when_complete",
        "test_synthetic_skeleton_passes",
    }
)


def evidence_tree_present(index: Path | None = None) -> bool:
    """Does this checkout have the evidence ARTEFACTS, not merely the index?

    Separate from the hook so the rule itself is directly testable.

    Keying on the index file alone was wrong the moment the index became publishable on its
    own: `determinex evidence validate` needs it and its 1,837 manifests live under
    locks/sentinel/, so shipping the 1.2 MB index (without the 273 MB of artefacts) fixed
    two CI jobs -- and simultaneously took the coverage job from 63 failures to 202, because
    this predicate started reporting a tree that was not there and every evidence lock ran
    against artefacts that do not exist. The artefacts are what the tests read, so the
    artefacts are what to look for.
    """
    idx = index or _EVIDENCE_INDEX
    if not idx.is_file():
        return False
    try:
        return any(child.is_dir() for child in idx.parent.iterdir())
    except OSError:
        return False


def _module_missing_data_paths(module) -> list[Path]:
    """assurance/ paths a test module DECLARES that this checkout does not have.

    Scoped to `assurance/` ON PURPOSE, and that scope was measured rather than reasoned.
    Widening it to `corpus/` too -- on the apparently sound grounds that the public mirror
    ships only the corpus knowledge layer -- was a disaster: against a real public clone it
    took skipped from 260 to 2,187 and passed from 4,392 to 2,491. About 1,900 passing tests
    were switched off to convert 26 failures, because a module declaring ten corpus paths of
    which one was absent had ALL of its tests skipped, most of which never touched it.

    Turning off working tests to make CI green is precisely the failure this repository
    guards against elsewhere (`pb_override_scan --guard`). The narrow rule is the correct
    one: `assurance/` is never published at all, so a module declaring a path under it in a
    public checkout genuinely cannot verify what it claims to.
    """
    out: list[Path] = []
    for attr in vars(module).values():
        if isinstance(attr, Path) and "assurance" in attr.parts and not attr.exists():
            out.append(attr)
    if out:
        return out
    # Fallback: a module can build its evidence path INSIDE a function, where `vars()`
    # cannot see it -- test_determinex_cli.py does exactly that. Falling back to the source
    # text is safe because the per-test name gate still applies: a module merely mentioning
    # assurance/ exempts nothing on its own.
    src = getattr(module, "__file__", None)
    if src and not _EVIDENCE_INDEX.is_file():
        try:
            if "assurance" in Path(src).read_text(encoding="utf-8", errors="replace"):
                return [_EVIDENCE_INDEX]
        except OSError:
            pass
    return out


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Skip evidence-dependent locks when the evidence tree is absent -- and only then.

    Deliberately NOT a name pattern: a filter that guesses would silently disable tests
    nobody intended to disable, which is the failure mode this repository already guards
    against (`pb_override_scan --guard`) in the ProgramBench submission context. The
    condition here is a fact about the checkout, not about a test's name -- and where the
    evidence tree exists, which is every development checkout, nothing is skipped at all.

    That last clause is load-bearing and was briefly untrue. Without this early return the
    per-module check fired on any DECLARED assurance path that happened not to exist, and
    tests/models/test_real_local_model_provider_config_lock.py declares
    assurance/evidence/local_model_configs, which this repository does not have -- so two
    tests were skipped on the development box. Disabling the rule showed both PASS. The
    exemption exists for a checkout with NO evidence tree, not for a module that names a
    directory it does not need.
    """
    if evidence_tree_present():
        return
    cache: dict[str, list[Path]] = {}
    for item in items:
        module = getattr(item, "module", None)
        if module is None:
            continue
        name = module.__name__
        if name not in cache:
            cache[name] = _module_missing_data_paths(module)
        missing = cache[name]
        if not missing:
            continue
        # Module-level exemption is too blunt even scoped to assurance/: a module that
        # DECLARES an evidence path usually has many tests that never touch it. Skipping the
        # whole module took skipped from 260 to 2,175 against a real public clone -- ~1,900
        # tests switched off to cover a handful. Require the test itself to be about
        # evidence, so the rest of the module is still held to every assertion.
        if item.name not in _EVIDENCE_TESTS and "evidence" not in item.name:
            continue
        item.add_marker(
            pytest.mark.skip(
                reason=f"this checkout does not ship assurance/ (publish_mirror.NEVER), which "
                f"this test asserts on (missing: {missing[0].name}); the evidence lock "
                f"was NOT verified in this run"
            )
        )
