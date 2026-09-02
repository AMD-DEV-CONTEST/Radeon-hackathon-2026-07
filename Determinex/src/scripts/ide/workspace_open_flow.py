"""IDE workspace open / inspect flow.

Read-only inspection. Validates the path, refuses any path-traversal
shenanigans, and runs the existing BuildAdapterRegistry over the
directory. Returns an IDEWorkspaceOpenRecord with the language, build
system, test framework, and a verifier-state token. Source is never
mutated.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from intake.build_adapter_registry import BuildAdapterRegistry  # noqa: E402
from intake.build_adapters import UnknownAdapter  # noqa: E402
from intake.verifier_coverage_matrix import (  # noqa: E402
    CoverageStatus,
    classify_for_build_test,
)

from .workspace_open_record import (
    IDE_WORKSPACE_OPEN_STATUS_TOKENS,
    IDEWorkspaceOpenRecord,
)


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
    return out


def _is_path_escape(raw_path: str) -> bool:
    s = (raw_path or "").replace("\\", "/")
    if not s:
        return True
    if ".." in s.split("/"):
        return True
    return False


class IDEWorkspaceOpenFlow:
    """Stateless inspect flow."""

    def open(self, raw_workspace: str | Path) -> IDEWorkspaceOpenRecord:
        # 1. Path validation.
        ws_str = str(raw_workspace)
        if _is_path_escape(ws_str):
            return self._blocked(
                ws_str,
                "WORKSPACE_OPEN_BLOCKED_PATH_ESCAPE",
                "path contains '..' or empty",
            )
        ws = Path(raw_workspace).resolve()
        if not ws.exists():
            return self._blocked(
                str(ws),
                "WORKSPACE_OPEN_BLOCKED_NOT_A_DIRECTORY",
                "path does not exist",
            )
        if not ws.is_dir():
            return self._blocked(
                str(ws),
                "WORKSPACE_OPEN_BLOCKED_NOT_A_DIRECTORY",
                "path is not a directory",
            )

        before = _hash_tree(ws)

        # 2. Build adapter detection (read-only).
        sel = BuildAdapterRegistry().select(ws)
        adapter = sel.primary

        if adapter is UnknownAdapter:
            after = _hash_tree(ws)
            return IDEWorkspaceOpenRecord(
                decision="WORKSPACE_OPEN_BLOCKED_UNSUPPORTED_REPO",
                workspace=str(ws),
                adapter_name=adapter.name,
                build_system_id=adapter.build_system_id,
                test_framework_id="",
                verifier_state="WORKSPACE_OPEN_VERIFIER_MISSING",
                languages_detected=(),
                source_unchanged=(before == after),
                statuses_seen=(
                    "WORKSPACE_OPEN_BLOCKED_UNSUPPORTED_REPO",
                    "WORKSPACE_OPEN_SOURCE_UNCHANGED" if before == after else "",
                    "WORKSPACE_OPEN_VERIFIER_MISSING",
                ),
                notes=("no build manifest detected",),
            )

        # 3. Verifier coverage state.
        try:
            cov = classify_for_build_test(
                adapter.build_system_id,
                adapter.test_framework_id,
            )
        except (TypeError, KeyError):
            cov = None
        if cov is None or cov is CoverageStatus.MISSING:
            verifier_state = "WORKSPACE_OPEN_VERIFIER_MISSING"
        else:
            verifier_state = "WORKSPACE_OPEN_VERIFIER_AVAILABLE"

        after = _hash_tree(ws)
        return IDEWorkspaceOpenRecord(
            decision="WORKSPACE_OPEN_READY",
            workspace=str(ws),
            adapter_name=adapter.name,
            build_system_id=adapter.build_system_id,
            test_framework_id=adapter.test_framework_id,
            verifier_state=verifier_state,
            languages_detected=(adapter.name,),
            source_unchanged=(before == after),
            statuses_seen=(
                "WORKSPACE_OPEN_READY",
                verifier_state,
                "WORKSPACE_OPEN_SOURCE_UNCHANGED" if before == after else "",
            ),
            evidence_refs=(),
            notes=(),
        )

    @staticmethod
    def _blocked(
        ws: str,
        decision: str,
        note: str,
    ) -> IDEWorkspaceOpenRecord:
        return IDEWorkspaceOpenRecord(
            decision=decision,
            workspace=ws,
            adapter_name="Unknown",
            build_system_id="unknown",
            test_framework_id="",
            verifier_state="WORKSPACE_OPEN_VERIFIER_MISSING",
            languages_detected=(),
            source_unchanged=True,
            statuses_seen=(
                decision,
                "WORKSPACE_OPEN_SOURCE_UNCHANGED",
                "WORKSPACE_OPEN_VERIFIER_MISSING",
            ),
            notes=(note,),
        )


__all__ = [
    "IDEWorkspaceOpenFlow",
    "IDEWorkspaceOpenRecord",
    "IDE_WORKSPACE_OPEN_STATUS_TOKENS",
]
