from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STAGES = (
    "four_a_deep_strategy",
    "four_a_deep_craft",
    "four_a_deep_effectiveness",
    "four_a_deep_synthesis",
)
PREREQUISITES = {
    "four_a_deep_strategy": (),
    "four_a_deep_craft": ("four_a_deep_strategy",),
    "four_a_deep_effectiveness": (
        "four_a_deep_strategy",
        "four_a_deep_craft",
    ),
    "four_a_deep_synthesis": (
        "four_a_deep_strategy",
        "four_a_deep_craft",
        "four_a_deep_effectiveness",
    ),
}
REFERENCE_CASE_IDS = frozenset(
    {
        "os26-ce001g",
        "os26-fi093m",
        "os26-ce002g",
        "os26-ce003g",
        "os26-ce014m",
        "os26-ce010b",
        "os26-ce021m",
        "os26-mi026b",
        "os26-mi003g",
        "os26-be037m",
        "os26-dm049m",
        "os26-dm000g",
        "os26-mi042m",
        "OS26_CE001G",
        "OS26_FI093M",
        "OS26_CE002G",
        "OS26_CE003G",
        "OS26_CE014M",
        "OS26_CE010B",
        "OS26_CE021M",
        "OS26_MI026B",
        "OS26_MI003G",
        "OS26_BE037M",
        "OS26_DM049M",
        "OS26_DM000G",
        "OS26_MI042M",
    }
)
REQUIRED_SYNTHESIS_FIELDS = frozenset(
    {
        "todo_id",
        "reference_case_ids",
        "observed_evidence",
        "strategic_transfer",
        "creative_mechanism",
        "channel_and_craft",
        "effectiveness_test",
        "negative_control",
        "what_not_to_copy",
        "rights_partition",
        "admission_status",
    }
)
EXPECTED_SCHEMA = "ProofLaunchTokenFactoryTeacherEpisodeV1"
EXPECTED_PROTOCOL = "frontier-20-lens-v3"
EXPECTED_PROVIDER = "amd_radeon_token_factory"
EXPECTED_EVIDENCE_CLASS = "external_teacher_advisory"
SECRET_PATTERN = re.compile(r"rc-[A-Za-z0-9_-]{20,}")


@dataclass(frozen=True)
class Issue:
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


def expected_batch_ids() -> tuple[str, ...]:
    return tuple(
        f"{start:04d}-{start + 1:04d}"
        for start in range(1, 1501, 2)
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_episode(
    payload: dict[str, Any],
    *,
    stage: str,
    batch_id: str,
    canonical_sha256: str | None = None,
) -> list[Issue]:
    issues: list[Issue] = []

    def issue(code: str, detail: str) -> None:
        issues.append(Issue(stage, batch_id, code, detail))

    expected_todos = batch_id.split("-")
    output = payload.get("output")
    output_text = output if isinstance(output, str) else ""
    if payload.get("schema") != EXPECTED_SCHEMA:
        issue("schema", "unexpected or missing episode schema")
    if payload.get("status") != "passed":
        issue("status", f"episode status is {payload.get('status')!r}")
    if payload.get("stage") != stage:
        issue("stage", f"record stage is {payload.get('stage')!r}")
    if payload.get("batch_id") != batch_id:
        issue("batch_id", f"record batch_id is {payload.get('batch_id')!r}")
    if payload.get("todo_ids") != expected_todos:
        issue("todo_ids", f"expected {expected_todos!r}")
    if payload.get("quality_protocol") != EXPECTED_PROTOCOL:
        issue("quality_protocol", f"expected {EXPECTED_PROTOCOL!r}")
    if (
        canonical_sha256 is not None
        and payload.get("source_todo_sha256") != canonical_sha256
    ):
        issue(
            "source_todo_sha256",
            "episode is not bound to the canonical 1,500-task source",
        )
    if payload.get("provider") != EXPECTED_PROVIDER:
        issue("provider", "episode is not an official AMD Token Factory receipt")
    if payload.get("evidence_class") != EXPECTED_EVIDENCE_CLASS:
        issue("evidence_class", "unexpected evidence class")
    if payload.get("competition_core_eligible") is not False:
        issue("truth_boundary", "teacher output cannot be competition-core evidence")
    if payload.get("hidden_reasoning_persisted") is not False:
        issue("hidden_reasoning", "hidden reasoning persistence must be false")
    credential = payload.get("credential")
    if not isinstance(credential, dict):
        issue("credential", "credential receipt is absent")
    elif credential.get("persisted") is not False or credential.get("redacted") is not True:
        issue("credential", "credential receipt is not redacted and fail-closed")
    if not output_text.strip():
        issue("output", "visible output is empty")
    elif payload.get("output_sha256") != _sha256_text(output_text):
        issue("output_sha256", "visible output digest does not match")
    if payload.get("finish_reason") == "length":
        issue("truncated_output", "finish_reason=length is incomplete")
    if payload.get("quality_violations") not in ([], ()):
        issue("quality_violations", repr(payload.get("quality_violations")))
    if SECRET_PATTERN.search(json.dumps(payload, ensure_ascii=False)):
        issue("secret", "record contains a Token Factory credential pattern")
    if stage == "four_a_deep_synthesis":
        context_sha256 = payload.get("four_a_context_sha256")
        if (
            not isinstance(context_sha256, str)
            or len(context_sha256) != 64
            or any(character not in "0123456789abcdef" for character in context_sha256)
        ):
            issue(
                "four_a_context_sha256",
                "post-expansion stage is not bound to the frozen Top-10 context",
            )

    if stage == "four_a_deep_synthesis" and output_text:
        try:
            document = json.loads(output_text)
        except json.JSONDecodeError:
            issue("synthesis_invalid_json", "synthesis output is not strict JSON")
        else:
            records = document.get("records")
            if not isinstance(records, list):
                issue("synthesis_records", "records must be an array")
            else:
                observed_todos = [
                    item.get("todo_id")
                    for item in records
                    if isinstance(item, dict)
                ]
                if observed_todos != expected_todos:
                    issue(
                        "synthesis_todo_coverage",
                        f"expected ordered TODO records {expected_todos!r}",
                    )
                for index, record in enumerate(records):
                    if not isinstance(record, dict):
                        issue("synthesis_record_type", f"record {index} is not an object")
                        continue
                    if not REQUIRED_SYNTHESIS_FIELDS.issubset(record):
                        issue(
                            "synthesis_missing_fields",
                            f"record {index} omits required transfer fields",
                        )
                    references = record.get("reference_case_ids")
                    if not isinstance(references, list) or any(
                        reference not in REFERENCE_CASE_IDS for reference in references
                    ):
                        issue(
                            "synthesis_reference_ids",
                            f"record {index} contains an unbound reference case",
                        )
                    if record.get("rights_partition") != "research_reference":
                        issue(
                            "synthesis_rights_partition",
                            f"record {index} changed the research partition",
                        )
                    if record.get("admission_status") not in {"research_only", "hold"}:
                        issue(
                            "synthesis_admission_status",
                            f"record {index} has an invalid admission status",
                        )
                    if references and not str(record.get("what_not_to_copy", "")).strip():
                        issue(
                            "synthesis_copy_boundary",
                            f"record {index} has references but no non-copy boundary",
                        )
    return issues


def validate_corpus(
    corpus_root: Path,
    *,
    require_complete: bool = True,
) -> dict[str, Any]:
    corpus_root = corpus_root.resolve()
    project_root = corpus_root.parents[1]
    canonical_path = project_root / "docs/CORTEX_X_V10_1500_TODO.md"
    canonical_sha256 = (
        hashlib.sha256(canonical_path.read_bytes()).hexdigest()
        if canonical_path.is_file()
        else None
    )
    issues: list[Issue] = []
    batch_ids = expected_batch_ids()
    valid_by_stage: dict[str, set[str]] = {stage: set() for stage in STAGES}
    observed_counts: dict[str, int] = {}
    stage_digests: dict[str, str] = {}
    reference_bound_records = 0
    hold_records = 0
    context_digests: dict[str, set[str]] = {
        "four_a_deep_synthesis": set(),
    }

    for stage in STAGES:
        stage_root = corpus_root / stage
        observed = {
            path.stem: path
            for path in stage_root.glob("*.json")
            if path.is_file()
        }
        observed_counts[stage] = len(observed)
        if require_complete:
            for batch_id in batch_ids:
                if batch_id not in observed:
                    issues.append(
                        Issue(stage, batch_id, "missing_episode", "expected record absent")
                    )
        for batch_id, path in sorted(observed.items()):
            if batch_id not in batch_ids:
                issues.append(
                    Issue(stage, batch_id, "unexpected_episode", "unexpected batch id")
                )
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                issues.append(Issue(stage, batch_id, "invalid_json", str(error)))
                continue
            episode_issues = validate_episode(
                payload,
                stage=stage,
                batch_id=batch_id,
                canonical_sha256=canonical_sha256,
            )
            issues.extend(episode_issues)
            if stage in context_digests and isinstance(
                payload.get("four_a_context_sha256"), str
            ):
                context_digests[stage].add(payload["four_a_context_sha256"])
            if not episode_issues:
                valid_by_stage[stage].add(batch_id)
                if stage == "four_a_deep_synthesis":
                    records = json.loads(payload["output"])["records"]
                    reference_bound_records += sum(
                        bool(item["reference_case_ids"]) for item in records
                    )
                    hold_records += sum(
                        item["admission_status"] == "hold" for item in records
                    )
        digest_material = "".join(
            hashlib.sha256(path.read_bytes()).hexdigest()
            for _, path in sorted(observed.items())
        )
        stage_digests[stage] = _sha256_text(digest_material)

    for stage, prerequisites in PREREQUISITES.items():
        for batch_id in valid_by_stage[stage]:
            for prerequisite in prerequisites:
                if batch_id not in valid_by_stage[prerequisite]:
                    issues.append(
                        Issue(
                            stage,
                            batch_id,
                            "missing_valid_prerequisite",
                            f"{prerequisite}/{batch_id} is not valid",
                        )
                    )

    observed_context_digests = set().union(*context_digests.values())
    if require_complete and len(observed_context_digests) != 1:
        issues.append(
            Issue(
                "four_a_deep_synthesis",
                "*",
                "four_a_context_inconsistent",
                "all synthesis records must share one frozen Top-10 context",
            )
        )

    complete = all(
        len(valid_by_stage[stage]) == len(batch_ids) for stage in STAGES
    )
    return {
        "schema": "ProofLaunchFourATransferCorpusValidationV1",
        "status": "passed" if not issues and (complete or not require_complete) else "blocked",
        "corpus_root": str(corpus_root),
        "canonical_todo_sha256": canonical_sha256,
        "expected_batch_count_per_stage": len(batch_ids),
        "require_complete": require_complete,
        "complete": complete,
        "observed_counts": observed_counts,
        "valid_counts": {
            stage: len(valid_by_stage[stage]) for stage in STAGES
        },
        "reference_bound_synthesis_records": reference_bound_records,
        "hold_synthesis_records": hold_records,
        "stage_digests": stage_digests,
        "four_a_context_sha256": (
            next(iter(observed_context_digests))
            if len(observed_context_digests) == 1
            else None
        ),
        "issue_count": len(issues),
        "issues": [item.as_dict() for item in issues],
        "competition_core_eligible": False,
        "truth_boundary": (
            "Official AMD Token Factory teacher outputs are source-bound research "
            "advisory material, not model-training, Radeon-execution, human-preference, "
            "campaign-effectiveness, or TODO-completion evidence."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("data/tokenfactory_teacher_v10"),
    )
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = validate_corpus(
        args.corpus_root,
        require_complete=not args.allow_incomplete,
    )
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if receipt["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
