from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STAGES = (
    "architect",
    "research",
    "critic",
    "implementer",
    "verifier",
    "four_a_critic",
    "synthesis",
    "frontier_judge",
    "final_repair",
)
STAGE_PREREQUISITES = {
    "architect": (),
    "research": (),
    "critic": ("architect", "research"),
    "implementer": ("critic",),
    "verifier": ("implementer",),
    "four_a_critic": ("implementer", "verifier"),
    "synthesis": ("implementer", "verifier", "four_a_critic"),
    "frontier_judge": ("synthesis",),
    "final_repair": ("synthesis", "frontier_judge"),
}
QUALITY_PROTOCOL = "frontier-20-lens-v3"
EXPECTED_PROVIDER = "amd_radeon_token_factory"
EXPECTED_EVIDENCE_CLASS = "external_teacher_advisory"
EXPECTED_BATCH_COUNT = 750
SECRET_PATTERN = re.compile(r"rc-[A-Za-z0-9_-]{20,}")
PLACEHOLDER_SOURCE_PATTERN = re.compile(
    r"<official[_ -]?(?:org|repo)>", re.IGNORECASE
)
INFERRED_LICENSE_PATTERN = re.compile(
    r"license[^\n]{0,120}\b(?:inferred|assumed)\b", re.IGNORECASE
)
SCORE_GAMING_PATTERN = re.compile(
    r"revised score[^\n]{0,120}\b(?:pass|16|17|18|19|20)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CorpusIssue:
    stage: str
    batch_id: str
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "batch_id": self.batch_id,
            "code": self.code,
            "detail": self.detail,
        }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def expected_batch_ids() -> tuple[str, ...]:
    return tuple(
        f"{start:04d}-{start + 1:04d}"
        for start in range(1, 1501, 2)
    )


def validate_episode(
    payload: dict[str, Any],
    *,
    stage: str,
    batch_id: str,
    canonical_sha256: str | None = None,
) -> list[CorpusIssue]:
    issues: list[CorpusIssue] = []

    def issue(code: str, detail: str) -> None:
        issues.append(CorpusIssue(stage, batch_id, code, detail))

    expected_todos = batch_id.split("-")
    output = payload.get("output")
    output_text = output if isinstance(output, str) else ""
    if payload.get("schema") != "ProofLaunchTokenFactoryTeacherEpisodeV1":
        issue("schema", "unexpected or missing episode schema")
    if payload.get("status") != "passed":
        issue("status", f"episode status is {payload.get('status')!r}")
    if payload.get("stage") != stage:
        issue("stage", f"record stage is {payload.get('stage')!r}")
    if payload.get("batch_id") != batch_id:
        issue("batch_id", f"record batch_id is {payload.get('batch_id')!r}")
    if payload.get("todo_ids") != expected_todos:
        issue("todo_ids", f"expected {expected_todos!r}")
    if payload.get("quality_protocol") != QUALITY_PROTOCOL:
        issue(
            "quality_protocol",
            f"expected {QUALITY_PROTOCOL!r}",
        )
    if (
        canonical_sha256 is not None
        and payload.get("source_todo_sha256") != canonical_sha256
    ):
        issue(
            "source_todo_sha256",
            "episode is not bound to the current canonical 1,500-task source",
        )
    if payload.get("provider") != EXPECTED_PROVIDER:
        issue("provider", "episode is not an official AMD Token Factory receipt")
    if payload.get("evidence_class") != EXPECTED_EVIDENCE_CLASS:
        issue("evidence_class", "teacher episode has an invalid evidence class")
    if payload.get("competition_core_eligible") is not False:
        issue(
            "truth_boundary",
            "online teacher material must not be competition-core evidence",
        )
    if payload.get("hidden_reasoning_persisted") is not False:
        issue("hidden_reasoning", "hidden reasoning persistence must be false")
    credential = payload.get("credential")
    if not isinstance(credential, dict):
        issue("credential", "credential receipt is missing")
    elif credential.get("persisted") is not False or credential.get("redacted") is not True:
        issue("credential", "credential receipt is not fail-closed and redacted")
    if not output_text.strip():
        issue("output", "visible output is empty")
    elif payload.get("output_sha256") != _sha256_text(output_text):
        issue("output_sha256", "visible output digest does not match")
    if payload.get("finish_reason") == "length":
        issue("truncated_output", "finish_reason=length is not a complete episode")
    quality_violations = payload.get("quality_violations")
    if quality_violations not in ([], ()):
        issue("quality_violations", repr(quality_violations))
    record_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if SECRET_PATTERN.search(record_text):
        issue("secret", "record contains a Token Factory credential pattern")
    if stage in {"architect", "research"}:
        if PLACEHOLDER_SOURCE_PATTERN.search(output_text):
            issue(
                "placeholder_source",
                "record contains an official-source placeholder",
            )
        if INFERRED_LICENSE_PATTERN.search(output_text):
            issue(
                "inferred_license",
                "record infers a license instead of sourcing it",
            )
        if SCORE_GAMING_PATTERN.search(output_text):
            issue(
                "score_gate_gaming",
                "record revises a score to manufacture a pass",
            )
    if stage in {"synthesis", "final_repair"} and output_text:
        try:
            synthesized = json.loads(output_text)
        except json.JSONDecodeError:
            issue("synthesis_invalid_json", "synthesis output is not strict JSON")
        else:
            records = synthesized.get("records")
            required_fields = {
                "todo_id",
                "dependencies",
                "D",
                "A",
                "I",
                "E",
                "implementation_steps",
                "test_ids",
                "acceptance_metrics",
                "budget",
                "stop_rule",
                "rollback",
                "evidence_class",
                "radeon_action",
                "external_blockers",
                "current_status",
            }
            if not isinstance(records, list):
                issue("synthesis_records", "records must be a JSON array")
            else:
                observed_ids = [
                    record.get("todo_id")
                    for record in records
                    if isinstance(record, dict)
                ]
                if observed_ids != expected_todos:
                    issue(
                        "synthesis_todo_coverage",
                        f"expected records for {expected_todos!r}",
                    )
                if any(
                    not isinstance(record, dict)
                    or not required_fields.issubset(record)
                    for record in records
                ):
                    issue(
                        "synthesis_missing_fields",
                        "one or more final records omit required fields",
                    )
                if any(
                    record.get("current_status")
                    not in {"not_started", "in_progress"}
                    for record in records
                    if isinstance(record, dict)
                ):
                    issue(
                        "synthesis_invalid_status",
                        "teacher synthesis cannot mark a task complete",
                    )
    return issues


def validate_corpus(
    corpus_root: Path,
    *,
    require_complete: bool = True,
) -> dict[str, Any]:
    corpus_root = corpus_root.resolve()
    project_root = (
        corpus_root.parents[1]
        if corpus_root.parent.name == "data"
        else corpus_root.parent
    )
    canonical_path = project_root / "docs/CORTEX_X_V10_1500_TODO.md"
    canonical_sha256 = (
        hashlib.sha256(canonical_path.read_bytes()).hexdigest()
        if canonical_path.is_file()
        else None
    )
    batch_ids = expected_batch_ids()
    issues: list[CorpusIssue] = []
    stage_counts: dict[str, int] = {}
    stage_digests: dict[str, str] = {}
    passed_by_stage: dict[str, set[str]] = {stage: set() for stage in STAGES}

    for stage in STAGES:
        stage_root = corpus_root / stage
        observed_files = {
            path.stem: path
            for path in stage_root.glob("*.json")
            if path.is_file()
        }
        stage_counts[stage] = len(observed_files)
        if require_complete:
            for batch_id in batch_ids:
                if batch_id not in observed_files:
                    issues.append(
                        CorpusIssue(
                            stage,
                            batch_id,
                            "missing_episode",
                            "expected batch record is absent",
                        )
                    )
        digests: list[str] = []
        for batch_id, path in sorted(observed_files.items()):
            if batch_id not in batch_ids:
                issues.append(
                    CorpusIssue(
                        stage,
                        batch_id,
                        "unexpected_episode",
                        path.name,
                    )
                )
                continue
            try:
                raw = path.read_text(encoding="utf-8")
                payload = json.loads(raw)
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                issues.append(
                    CorpusIssue(
                        stage,
                        batch_id,
                        "invalid_json",
                        str(error),
                    )
                )
                continue
            episode_issues = validate_episode(
                payload,
                stage=stage,
                batch_id=batch_id,
                canonical_sha256=canonical_sha256,
            )
            issues.extend(episode_issues)
            if not episode_issues:
                passed_by_stage[stage].add(batch_id)
                digests.append(hashlib.sha256(raw.encode("utf-8")).hexdigest())
        stage_digests[stage] = _sha256_text("\n".join(digests))

    for stage, prerequisites in STAGE_PREREQUISITES.items():
        for batch_id in passed_by_stage[stage]:
            for prerequisite in prerequisites:
                if batch_id not in passed_by_stage[prerequisite]:
                    issues.append(
                        CorpusIssue(
                            stage,
                            batch_id,
                            "missing_prerequisite",
                            f"{prerequisite}/{batch_id} is not valid",
                        )
                    )

    valid_counts = {
        stage: len(passed_by_stage[stage])
        for stage in STAGES
    }
    return {
        "schema": "ProofLaunchTokenFactoryCorpusValidationV1",
        "status": "passed" if not issues else "blocked",
        "quality_protocol": QUALITY_PROTOCOL,
        "canonical_todo_sha256": canonical_sha256,
        "corpus_root": corpus_root.as_posix(),
        "expected_batches_per_stage": EXPECTED_BATCH_COUNT,
        "stage_file_counts": stage_counts,
        "stage_valid_counts": valid_counts,
        "stage_content_digests": stage_digests,
        "issue_count": len(issues),
        "issues": [item.as_dict() for item in issues],
        "competition_core_eligible": False,
        "truth_boundary": (
            "A passing receipt proves corpus structure, provenance, integrity, "
            "dependency closure, and anti-fabrication checks only. It does not "
            "prove local Radeon execution, trained-model quality, 4A preference, "
            "or business lift."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("data/tokenfactory_teacher_v10"),
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Validate only observed episodes without requiring all nine stages.",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    receipt = validate_corpus(
        arguments.corpus_root,
        require_complete=not arguments.allow_incomplete,
    )
    serialized = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
