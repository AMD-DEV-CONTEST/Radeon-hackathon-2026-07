"""Select a real build-adapter-backed verifier for a workspace.

Uses the locked BuildAdapterRegistry to detect the workspace's
build system, then derives the canonical verifier command from the
adapter's ``test_framework_id``. Verifier is intended to be invoked
through ``intake.hardened_runner.run`` — the registry-derived
command is recorded but NOT executed by this lock.

Decisions:
  - SELECTED                       — adapter matched, command derived
  - BLOCKED_UNSUPPORTED_REPO       — only UnknownAdapter matched
  - BLOCKED_NO_TEST_COMMAND        — adapter has no test_framework_id
  - BLOCKED_HARDENED_RUNNER        — hardened runner module missing
  - BLOCKED_WORKSPACE_MISSING      — workspace path does not exist
"""

from __future__ import annotations

import importlib
import shlex
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from intake.build_adapter_registry import BuildAdapterRegistry  # noqa: E402
from intake.build_adapters import UnknownAdapter  # noqa: E402

from .build_adapter_backed_verifier_selection_record import (
    BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_STATUS_TOKENS,
    BuildAdapterBackedVerifierSelectionRecord,
)

_HARDENED_RUNNER_MODULE = "intake.hardened_runner"


def _hardened_runner_available() -> bool:
    try:
        importlib.import_module(_HARDENED_RUNNER_MODULE)
    except ImportError:
        return False
    return True


def select_verifier(
    *,
    workspace: Path,
    registry: BuildAdapterRegistry | None = None,
) -> BuildAdapterBackedVerifierSelectionRecord:
    ws = Path(workspace).resolve()
    reg = registry or BuildAdapterRegistry()

    if not ws.is_dir():
        return _blocked(
            "BUILD_ADAPTER_VERIFIER_BLOCKED_WORKSPACE_MISSING",
            workspace=str(ws),
            note=f"workspace path does not exist: {ws}",
        )

    if not _hardened_runner_available():
        return _blocked(
            "BUILD_ADAPTER_VERIFIER_BLOCKED_HARDENED_RUNNER",
            workspace=str(ws),
            note=f"hardened runner module {_HARDENED_RUNNER_MODULE!r} unavailable",
        )

    sel = reg.select(ws)
    matched_names = tuple(a.name for a, _ in sel.matched)

    if sel.primary is UnknownAdapter:
        return _blocked(
            "BUILD_ADAPTER_VERIFIER_BLOCKED_UNSUPPORTED_REPO",
            workspace=str(ws),
            note="no real adapter matched; UnknownAdapter is the fallback",
            matched_adapters=matched_names,
        )

    test_framework_id = getattr(sel.primary, "test_framework_id", "")
    # Node adapter offers a refinement based on package.json.
    refine = getattr(sel.primary, "refine_test_framework_id", None)
    if refine is not None:
        try:
            refined = refine(ws)
            if isinstance(refined, str) and refined:
                test_framework_id = refined
        except Exception:
            # Fall back to the default test_framework_id.
            pass

    if not test_framework_id or test_framework_id == "unknown":
        return _blocked(
            "BUILD_ADAPTER_VERIFIER_BLOCKED_NO_TEST_COMMAND",
            workspace=str(ws),
            adapter_name=getattr(sel.primary, "name", ""),
            build_system_id=getattr(sel.primary, "build_system_id", ""),
            note="adapter has no test_framework_id",
            matched_adapters=matched_names,
        )

    # The test_framework_id is a shell-style hint (e.g. "cargo test",
    # "go test", "pytest"). Split deterministically into argv so the
    # downstream hardened runner never sees a string command.
    argv = tuple(shlex.split(test_framework_id))
    if not argv:
        return _blocked(
            "BUILD_ADAPTER_VERIFIER_BLOCKED_NO_TEST_COMMAND",
            workspace=str(ws),
            adapter_name=getattr(sel.primary, "name", ""),
            build_system_id=getattr(sel.primary, "build_system_id", ""),
            note="test_framework_id split to empty argv",
            matched_adapters=matched_names,
        )

    return BuildAdapterBackedVerifierSelectionRecord(
        decision="BUILD_ADAPTER_VERIFIER_SELECTED",
        workspace=str(ws),
        adapter_name=getattr(sel.primary, "name", ""),
        build_system_id=getattr(sel.primary, "build_system_id", ""),
        test_framework_id=test_framework_id,
        verifier_command=argv,
        hardened_runner=_HARDENED_RUNNER_MODULE,
        multi_match=sel.multi_match,
        matched_adapters=matched_names,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "verifier command derived from build adapter",
            "command will be invoked through intake.hardened_runner.run",
            "no source mutation by this lock",
        ),
    )


def _blocked(
    decision: str,
    *,
    workspace: str,
    note: str,
    adapter_name: str = "",
    build_system_id: str = "",
    matched_adapters: tuple[str, ...] = (),
) -> BuildAdapterBackedVerifierSelectionRecord:
    return BuildAdapterBackedVerifierSelectionRecord(
        decision=decision,
        workspace=workspace,
        adapter_name=adapter_name,
        build_system_id=build_system_id,
        test_framework_id="",
        verifier_command=tuple(),
        hardened_runner=_HARDENED_RUNNER_MODULE,
        multi_match=False,
        matched_adapters=matched_adapters,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "select_verifier",
    "BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_STATUS_TOKENS",
    "BuildAdapterBackedVerifierSelectionRecord",
]
