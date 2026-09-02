#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.artifact_import_operator_guide_record import (
    make_artifact_import_operator_guide_record,
    write_artifact_import_operator_guide_record,
)

FINAL_STATE_RECORD = Path(
    "assurance/evidence/programbench_batch001_import_scan_campaign_final_state/"
    "programbench_batch001_import_scan_campaign_final_state_run_20260528.BATCH001_IMPORT_SCAN_CAMPAIGN_FINAL_STATE_WRITTEN.json"
)
OUTBOX_DIR = Path("assurance/operator_outbox/programbench/batch001_import_scan")
OUTBOX_MANIFEST = OUTBOX_DIR / "manifest.json"
DOC_PATH = Path("docs/PROGRAMBENCH_ARTIFACT_IMPORT_OPERATOR_GUIDE.md")
INBOX_DIR = Path("assurance/operator_inbox/programbench")

ACCEPTABLE_FORMS = [
    "exact digest image tar exported by controlled process",
    "signed internal cache record",
    "registry artifact reference with immutable digest and provenance",
    "local artifact tar with sha256 and source binding",
]

REJECTED_FORMS = [
    "latest tags",
    "name-only images",
    "tag-only pulls",
    "screenshots",
    "prose claims without digest/hash binding",
    "unverified public images",
    "fixture packets",
    "artifact with missing sha256",
    "artifact with mismatched digest",
    "artifact that authorizes execution directly",
]

REQUIRED_FIELDS = [
    "instance_id",
    "image_name",
    "exact_manifest_digest",
    "local_artifact_tar_path or artifact_reference",
    "artifact_file_sha256",
    "source_registry_provenance_notes",
    "digest binding between supplied artifact and manifest digest",
    "operator_identity",
    "operator_signature or local signed evidence convention",
    "timestamp",
]

CLI_COMMANDS = {
    "show_actions": "python scripts/corpus/programbench/programbench_operator_cli.py actions --json",
    "generate_packets": "python scripts/corpus/programbench/programbench_operator_cli.py packets --out assurance/operator_outbox/programbench --json",
    "scan_inbox": "python scripts/corpus/programbench/programbench_operator_cli.py inbox-scan --json",
    "validate_process_inbox": "python scripts/corpus/programbench/programbench_operator_cli.py process-inbox --json",
    "review_live_packets": "python scripts/corpus/programbench/programbench_operator_cli.py review-live-packets --json",
}

HARD_WARNINGS = [
    "packet does not authorize Docker run",
    "packet does not authorize ProgramBench rerun",
    "packet does not authorize training",
    "packet does not bypass scan",
    "packet does not mark executable",
    "packet does not mark cache_ready unless a later quarantine-cache gate defines that separately",
]


@dataclass(slots=True)
class ArtifactImportOperatorGuideConfig:
    root: Path = Path(".")
    write_record: bool = True
    write_doc: bool = True


class ProgramBenchArtifactImportOperatorGuide:
    def __init__(self, config: ArtifactImportOperatorGuideConfig | None = None) -> None:
        self.config = config or ArtifactImportOperatorGuideConfig()
        self.root = self.config.root

    def build(self) -> dict[str, Any]:
        final_state = self._read_json(FINAL_STATE_RECORD)
        templates = self._read_templates()
        targets = self._target_rows(final_state, templates)

        if not targets:
            status = "ARTIFACT_IMPORT_OPERATOR_GUIDE_BLOCKED_NO_METADATA_ADMITTED_TARGETS"
        elif len(templates) != len(targets):
            status = "ARTIFACT_IMPORT_OPERATOR_GUIDE_BLOCKED_MISSING_PACKET_TEMPLATES"
        else:
            status = "ARTIFACT_IMPORT_OPERATOR_GUIDE_WRITTEN"

        payload = {
            "record_id": "run_20260528",
            "input_final_state": _rel(FINAL_STATE_RECORD),
            "input_outbox_manifest": _rel(OUTBOX_MANIFEST),
            "current_state": {
                "image_names_derived": True,
                "exact_manifest_digests_admitted_metadata_only": len(targets),
                "artifacts_imported": 0,
                "scans_run": 0,
                "execution_authorized": False,
                "cache_ready": False,
                "training_eligible": False,
            },
            "required_packet_type": "artifact_import_provenance",
            "required_fields": REQUIRED_FIELDS,
            "acceptable_forms": ACCEPTABLE_FORMS,
            "rejected_forms": REJECTED_FORMS,
            "operator_flow": {
                "templates_live_at": _rel(OUTBOX_DIR),
                "completed_packets_go_to": _rel(INBOX_DIR),
                "next_gate": "PROGRAMBENCH_BATCH001_OPERATOR_ARTIFACT_IMPORT_PACKET_REVIEW_LOCK_001",
                "only_if_real_packets_exist": True,
            },
            "cli_commands": CLI_COMMANDS,
            "hard_warnings": HARD_WARNINGS,
            "targets": targets,
            "doxygen_included": any(row["instance_id"].startswith("doxygen__") for row in targets),
            "authorization": _closed_auth(),
            "next_unblocker": "SUPPLY_OPERATOR_ARTIFACT_IMPORT_PACKETS_FOR_BATCH001",
        }
        record = make_artifact_import_operator_guide_record(status=status, payload=payload)
        if self.config.write_doc:
            (self.root / DOC_PATH).write_text(render_markdown(record), encoding="utf-8")
        if self.config.write_record:
            write_artifact_import_operator_guide_record(
                record,
                self.root / "assurance/evidence/programbench_artifact_import_operator_guide",
            )
        return record

    def _target_rows(
        self, final_state: dict[str, Any], templates: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for action in final_state.get("per_target_next_action", []):
            instance_id = str(action.get("instance_id") or "")
            if not instance_id or instance_id.startswith("doxygen__"):
                continue
            template = templates.get(instance_id, {})
            rows.append(
                {
                    "instance_id": instance_id,
                    "image": str(template.get("image_name") or ""),
                    "digest": str(
                        action.get("digest") or template.get("exact_manifest_digest") or ""
                    ),
                    "required_packet_type": "artifact_import_provenance",
                    "current_status": "METADATA_ONLY_DIGEST_ADMITTED_IMPORT_REQUIRED",
                    "next_unblocker": "SUPPLY_OPERATOR_ARTIFACT_IMPORT_PACKET",
                    "template_path": _rel(
                        OUTBOX_DIR / f"{instance_id}.artifact_import_provenance.template.json"
                    ),
                    "scan_status": str(action.get("scan_status") or "SCAN_PENDING_ARTIFACT_IMPORT"),
                    "import_status": str(action.get("import_status") or "REQUIRED"),
                    "training_eligible": False,
                    "authorizes_execution": False,
                }
            )
        return rows

    def _read_templates(self) -> dict[str, dict[str, Any]]:
        templates: dict[str, dict[str, Any]] = {}
        if not (self.root / OUTBOX_DIR).is_dir():
            return templates
        for path in sorted(
            (self.root / OUTBOX_DIR).glob("*.artifact_import_provenance.template.json")
        ):
            data = json.loads(path.read_text(encoding="utf-8"))
            instance_id = str(data.get("instance_id") or "")
            if instance_id:
                templates[instance_id] = data
        return templates

    def _read_json(self, rel: Path) -> dict[str, Any]:
        return json.loads((self.root / rel).read_text(encoding="utf-8"))


def render_markdown(record: dict[str, Any]) -> str:
    targets = record.get("targets", [])
    lines = [
        "# ProgramBench Artifact Import Operator Guide",
        "",
        "This guide is for supplying exact artifact import provenance for the 10 Batch001 targets whose official ProgramBench image names and exact registry manifest digests have already been admitted as metadata only.",
        "",
        "This guide is not an import, approval, scan, execution authorization, ProgramBench rerun authorization, cache-readiness decision, or training eligibility decision.",
        "",
        "## Current State",
        "",
        "- Image names derived: yes",
        f"- Exact manifest digests admitted metadata-only: {len(targets)}",
        "- Artifacts imported: 0",
        "- Scans run: 0",
        "- Execution authorized: false",
        "- Cache ready: false",
        "- Training eligible: false",
        "",
        "## Required Operator Evidence",
        "",
    ]
    lines.extend(f"- `{field}`" for field in REQUIRED_FIELDS)
    lines.extend(["", "## Acceptable Forms", ""])
    lines.extend(f"- {item}" for item in ACCEPTABLE_FORMS)
    lines.extend(["", "## Rejected Forms", ""])
    lines.extend(f"- {item}" for item in REJECTED_FORMS)
    lines.extend(
        [
            "",
            "## Inbox And Outbox Flow",
            "",
            f"- Templates live at `{_rel(OUTBOX_DIR)}`.",
            f"- Completed packets should be placed in `{_rel(INBOX_DIR)}`.",
            "- Run inbox scan before any review.",
            "- Run packet validation/process-inbox before live packet review.",
            "- The next gate is `PROGRAMBENCH_BATCH001_OPERATOR_ARTIFACT_IMPORT_PACKET_REVIEW_LOCK_001`, only if real operator packets exist.",
            "",
            "## Commands",
            "",
        ]
    )
    lines.extend(f"- `{command}`" for command in CLI_COMMANDS.values())
    lines.extend(["", "## Hard Warnings", ""])
    lines.extend(f"- {item}" for item in HARD_WARNINGS)
    lines.extend(
        [
            "",
            "## Batch001 Targets",
            "",
            "| instance_id | image | digest | required packet | current status | next unblocker |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in targets:
        lines.append(
            f"| `{row['instance_id']}` | `{row['image']}` | `{row['digest']}` | `{row['required_packet_type']}` | `{row['current_status']}` | `{row['next_unblocker']}` |"
        )
    lines.extend(
        [
            "",
            "## Doxygen",
            "",
            "Doxygen is intentionally not included in this artifact import guide. It remains blocked pending real operator security policy admission, not Batch001 artifact import provenance.",
            "",
        ]
    )
    return "\n".join(lines)


def _closed_auth() -> dict[str, bool]:
    return {
        "docker_run_authorized": False,
        "docker_pull_authorized": False,
        "artifact_import_authorized": False,
        "scan_authorized": False,
        "programbench_rerun_authorized": False,
        "policy_exception_granted": False,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
        "training_rows_written": False,
    }


def _rel(path: Path) -> str:
    return str(path).replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    guide = ProgramBenchArtifactImportOperatorGuide(
        ArtifactImportOperatorGuideConfig(
            write_record=not args.no_write, write_doc=not args.no_write
        )
    )
    record = guide.build()
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(record["status"])
    return 0 if record["status"] == "ARTIFACT_IMPORT_OPERATOR_GUIDE_WRITTEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
