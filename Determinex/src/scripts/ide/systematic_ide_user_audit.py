"""Systematic user-facing IDE audit for Determinex.

The audit is intentionally deterministic and conservative. It checks that the
main user surfaces, backend command paths, release gates, and LLM advisory
boundaries are wired. It does not grant release readiness.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide.backend_command_surface import IDEBackendCommandSurface, commands  # noqa: E402
from ide.llm_program_advisor import build_advisory_packet  # noqa: E402

SCHEMA_VERSION = "determinex-systematic-ide-user-audit-v1"


@dataclass(frozen=True)
class AuditCheck:
    check_id: str
    status: str
    evidence: tuple[str, ...] = ()
    exact_blocker: str = ""

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["evidence"] = list(self.evidence)
        return d


@dataclass(frozen=True)
class AuditSection:
    section_id: str
    title: str
    status: str
    checks: tuple[AuditCheck, ...]
    exact_blocker: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
            "exact_blocker": self.exact_blocker,
        }


@dataclass(frozen=True)
class SystematicIDEUserAudit:
    schema_version: str
    generated_at_utc: str
    release_ready: bool
    authority_granted: bool
    sections: tuple[AuditSection, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def blocked_section_ids(self) -> tuple[str, ...]:
        return tuple(section.section_id for section in self.sections if section.status != "passed")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at_utc": self.generated_at_utc,
            "release_ready": self.release_ready,
            "authority_granted": self.authority_granted,
            "blocked_section_ids": list(self.blocked_section_ids),
            "sections": [section.to_dict() for section in self.sections],
            "notes": list(self.notes),
        }


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _normalize_ws(s: str) -> str:
    """Collapse whitespace runs to a single space for substring matching.

    Prose needles that span a JSX text node (e.g. "...remain
    network-denied...") only match while the source happens to keep that
    prose on one line. Prettier is free to rewrap JSX text at printWidth --
    that changes nothing about what the UI renders, but a byte-exact
    substring check broke on it. Found live 2026-07-19: a repo-wide
    `prettier --write .` rewrapped ToolsHub.tsx's network-denied sentence
    across two lines and this check's exact needle stopped matching real,
    unchanged, still-rendered text. Normalizing both sides makes the check
    track content, not incidental line-wrap position.
    """
    return " ".join(s.split())


def _check_contains(root: Path, path: Path, needles: tuple[str, ...], check_id: str) -> AuditCheck:
    text = _read(path)
    normalized_text = _normalize_ws(text)
    missing = [needle for needle in needles if _normalize_ws(needle) not in normalized_text]
    if not path.is_file():
        return AuditCheck(
            check_id, "blocked", (_rel(root, path),), f"missing file: {_rel(root, path)}"
        )
    if missing:
        return AuditCheck(
            check_id,
            "blocked",
            (_rel(root, path),),
            "missing required text: " + ", ".join(missing),
        )
    return AuditCheck(check_id, "passed", (_rel(root, path),))


def _section(section_id: str, title: str, checks: tuple[AuditCheck, ...]) -> AuditSection:
    blockers = [
        check.exact_blocker for check in checks if check.status != "passed" and check.exact_blocker
    ]
    return AuditSection(
        section_id=section_id,
        title=title,
        status="passed" if not blockers else "blocked",
        checks=checks,
        exact_blocker="; ".join(blockers),
    )


def _mission_control_section(root: Path) -> AuditSection:
    mission = root / "frontend/src/lib/missionControl.ts"
    panel = root / "frontend/src/components/MissionControlPanel.tsx"
    return _section(
        "mission_control",
        "Mission Control interactive guide",
        (
            _check_contains(
                root,
                mission,
                (
                    "DETERMINEX_MISSION_CONTROL_MISSIONS",
                    "llm-program-advisor",
                    "MISSION_CONTROL_CLAIM_BOUNDARY",
                    "does not grant release readiness",
                ),
                "mission-control-data-bound",
            ),
            _check_contains(
                root,
                panel,
                (
                    'data-testid="mission-control-panel"',
                    "data-testid={`mission-tab-${candidate.id}`}",
                    'data-testid="mission-next-action"',
                ),
                "mission-control-panel-interactive",
            ),
        ),
    )


def _tools_and_providers_section(root: Path) -> AuditSection:
    tools = root / "frontend/src/components/ToolsHub.tsx"
    return _section(
        "tools_and_providers",
        "Attachable tools and LLM provider routing",
        (
            _check_contains(
                root,
                tools,
                (
                    "Codex",
                    "Claude",
                    "Gemini",
                    "OpenAI",
                    "Ollama Local",
                    "Hybrid Stack",
                    "data-testid={`tools-launch-${id}`}",
                    "ProgramBench and hardened benchmark runners remain network-denied",
                ),
                "tools-provider-routing-visible",
            ),
        ),
    )


def _backend_command_section(root: Path) -> AuditSection:
    command_set = commands()
    required = {
        "inspect_workspace",
        "route_model",
        "diagnose_dry_run",
        "generate_patch_plan_opt_in",
        "source_apply_dry_run",
        "get_human_approval_packet",
        "generate_llm_program_advisory",
    }
    missing = sorted(required - set(command_set))
    checks = [
        AuditCheck(
            "backend-command-set",
            "passed" if not missing else "blocked",
            ("scripts/ide/backend_command_surface.py",),
            "" if not missing else "missing backend command(s): " + ", ".join(missing),
        )
    ]
    surface = IDEBackendCommandSurface()
    for command in sorted(required):
        result = surface.call(command)
        checks.append(
            AuditCheck(
                f"backend-safe-{command}",
                "passed"
                if result.source_mutation_authorized is False and result.training_eligible is False
                else "blocked",
                ("scripts/ide/backend_command_surface.py",),
                ""
                if result.source_mutation_authorized is False and result.training_eligible is False
                else f"{command} opened source mutation or training eligibility",
            )
        )
    return _section("backend_commands", "Backend command surface safety", tuple(checks))


def _release_gate_section(root: Path) -> AuditSection:
    # 2026-07-19: a real local Windows MSI+NSIS build (build_release_package.ps1,
    # after fixing its --bundles "all" bug) now genuinely succeeds, so the release
    # gates evidence honestly no longer contains "windows_msi_not_bundled" -- that
    # string going away is real progress, not staleness. linux_packages remains
    # genuinely unbuilt (needs a Linux host) so it's the current accurate blocker
    # to check for instead. The frontend-facing releaseGateStatus.ts text is left
    # checking the OLD string deliberately: it's what real end users would see
    # about whether a PUBLISHED, downloadable release exists, which is a distinct,
    # still-accurate claim from "a developer can build one locally" -- updating
    # that text is a release-messaging decision, not a test-staleness fix.
    release = root / "frontend/src/lib/releaseGateStatus.ts"
    evidence = (
        root / "assurance/evidence/determinex_release_gate_status/release_gates_20260707.json"
    )
    return _section(
        "release_gates",
        "Release gates and download setup boundaries",
        (
            _check_contains(
                root,
                release,
                (
                    "releaseReady: false",
                    "authorityGranted: false",
                    "determinex_download_bundle_20260707/download_manifest.json",
                    "windows_msi_not_bundled",
                ),
                "frontend-release-boundary",
            ),
            _check_contains(
                root,
                evidence,
                (
                    '"release_ready": false',
                    '"authority_granted": false',
                    "determinex_download_bundle_20260707/download_manifest.json",
                    "linux_packages_not_bundled",
                ),
                "release-evidence-boundary",
            ),
        ),
    )


def _repair_panels_section(root: Path) -> AuditSection:
    bindings = root / "frontend/src/lib/ide-panel-bindings.ts"
    return _section(
        "repair_panels",
        "Repair, diagnosis, verification, and approval panels",
        (
            _check_contains(
                root,
                bindings,
                (
                    "DiagnoseAndPatchPlanPanel",
                    "TempVerifyPanel",
                    "HumanApprovalPanel",
                    "SourceApplyDryRunPanel",
                    'sourceMutation: "BLOCKED"',
                    'defaultMode: "DRY_RUN"',
                ),
                "repair-panel-bindings-safe",
            ),
        ),
    )


def _llm_advisory_section(root: Path) -> AuditSection:
    packet = build_advisory_packet(
        user_request="fix a failing program and explain the verifier plan",
        workspace=root,
    )
    payload = packet.to_dict()
    safe = (
        payload["advisory_only"] is True
        and payload["source_mutation_authorized"] is False
        and payload["training_eligible"] is False
        and payload["universal_verified_support_claimed"] is False
        and payload["llm_contract"]["model_agnostic"] is True
    )
    return _section(
        "llm_program_advisor",
        "LLM-neutral program creation/upkeep/repair advisor",
        (
            AuditCheck(
                "advisory-packet-safe-boundary",
                "passed" if safe else "blocked",
                ("scripts/ide/llm_program_advisor.py",),
                "" if safe else "advisory packet opened authority or universal support claim",
            ),
            _check_contains(
                root,
                root / "frontend/src-tauri/src/ide_repair_bridge.rs",
                (
                    "generate_llm_program_advisory",
                    "source_mutation_authorized: false",
                    "training_eligible: false",
                ),
                "advisory-tauri-command-wired",
            ),
        ),
    )


def collect(root: Path | str | None = None) -> SystematicIDEUserAudit:
    repo_root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    section_builders: tuple[Callable[[Path], AuditSection], ...] = (
        _mission_control_section,
        _tools_and_providers_section,
        _backend_command_section,
        _release_gate_section,
        _repair_panels_section,
        _llm_advisory_section,
    )
    sections = tuple(builder(repo_root) for builder in section_builders)
    return SystematicIDEUserAudit(
        schema_version=SCHEMA_VERSION,
        generated_at_utc=datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        release_ready=False,
        authority_granted=False,
        sections=sections,
        notes=(
            "This audit checks user-facing IDE wiring and proof boundaries.",
            "Passing this audit does not prove public release readiness or universal verified support.",
        ),
    )


def write_report(output_path: Path, root: Path | str | None = None) -> SystematicIDEUserAudit:
    report = collect(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/systematic_ide_user_audit/run_20260707.json"),
    )
    args = parser.parse_args()
    report = write_report(args.output, args.root)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if not report.blocked_section_ids else 2


if __name__ == "__main__":
    raise SystemExit(main())
