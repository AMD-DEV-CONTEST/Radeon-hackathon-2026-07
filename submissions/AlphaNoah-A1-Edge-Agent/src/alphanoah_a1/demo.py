"""Command-line demonstration of AlphaNoah's first complete workflow."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

from .exceptions import (
    AlphaNoahError,
    AnalysisProviderError,
    InvalidStateTransition,
    ObjectNotFoundError,
    SkillResolutionError,
)
from .golden_path import (
    DEFAULT_RESTAURANT_KNOWLEDGE_FILE,
    build_restaurant_aircon_golden_path,
)
from .models import HumanReviewOutcome, PostReviewResult
from .knowledge import ContextBuilder, JsonKnowledgeRepository
from .provider_cli import (
    add_provider_commands,
    run_doctor,
    run_provider_management,
)
from .providers import (
    OllamaAnalysisProvider,
    ReliabilityPolicy,
    ReliableAnalysisProvider,
)
from .skills.demo import DEMO_SKILL_DEFINITIONS
from .skills.resolver import DeterministicSkillResolver
from .runtime import AlphaNoahRuntime

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVENT = REPOSITORY_ROOT / "examples" / "synthetic_food_sop_event.json"
DEFAULT_EVIDENCE = (
    REPOSITORY_ROOT / "examples" / "synthetic_corrective_evidence.json"
)
DEFAULT_DATABASE = REPOSITORY_ROOT / "tmp" / "alphanoah_demo.sqlite3"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def print_step(label: str, value: str) -> None:
    print(f"[{label:<20}] {value}")


def run_demo(args: argparse.Namespace) -> int:
    runtime = AlphaNoahRuntime(str(args.db))
    if args.reset:
        runtime.store.reset()

    event_fixture = load_json(args.event)
    evidence_fixture = load_json(args.evidence)
    if event_fixture.get("data_notice") != "Synthetic demo data":
        raise ValueError("Demo event must be labeled 'Synthetic demo data'.")
    if evidence_fixture.get("data_notice") != "Synthetic demo data":
        raise ValueError("Demo evidence must be labeled 'Synthetic demo data'.")
    if (
        event_fixture.get("incident_notice")
        != "Not a real production incident"
        or evidence_fixture.get("incident_notice")
        != "Not a real production incident"
    ):
        raise ValueError(
            "Demo fixtures must be labeled 'Not a real production incident'."
        )

    print("AlphaNoah A1 - synthetic food SOP closed-loop demo")
    print("Synthetic demo data / Not a real production incident")
    print(f"SQLite: {args.db}")
    print()

    event = runtime.create_event(
        event_type=event_fixture["event_type"],
        source=event_fixture["source"],
        location=event_fixture["location"],
        asset_id=event_fixture["asset_id"],
        reporter=event_fixture["reporter"],
        description=event_fixture["description"],
        attachments=event_fixture["attachments"],
        metadata=event_fixture["metadata"],
        raw_input_ref=event_fixture["raw_input_ref"],
        normalized_input=event_fixture["normalized_input"],
        actor="system:demo-ingest",
    )
    print_step("NEW", event.event_id)

    decision, hook = runtime.analyze_event(event.event_id)
    print_step(
        "ANALYZED",
        f"{decision.decision_type}; severity={decision.risk_level}",
    )
    print_step(hook.target_status.value, hook.reason)

    choice = args.decision or input("Human decision [approve/reject]: ").strip()
    if choice == "approve":
        outcome = HumanReviewOutcome.APPROVED
        comment = "Approved explicitly by the CLI demo operator."
    elif choice == "reject":
        outcome = HumanReviewOutcome.REJECTED
        comment = "Rejected explicitly by the CLI demo operator."
    else:
        raise ValueError("Human decision must be 'approve' or 'reject'.")

    runtime.submit_human_review(
        decision.decision_id,
        reviewer=args.reviewer,
        outcome=outcome,
        comment=comment,
    )
    print_step(outcome.value, f"reviewer={args.reviewer}")

    if outcome is HumanReviewOutcome.REJECTED:
        final_event = runtime.store.get_event(event.event_id)
        print_step("FINAL", final_event.status.value)
        _print_timeline(runtime, event.event_id)
        return 0

    task = runtime.create_task(
        decision.decision_id,
        actor=args.reviewer,
        deadline=event_fixture["task_deadline"],
    )
    print_step("TASK_CREATED", task.task_id)
    runtime.start_task(task.task_id, actor=task.assignee)
    print_step("IN_PROGRESS", task.assignee)

    evidence = runtime.submit_evidence(
        task.task_id,
        evidence_type=evidence_fixture["evidence_type"],
        file_or_data_ref=evidence_fixture["file_or_data_ref"],
        submitted_by=task.assignee,
        description=evidence_fixture["description"],
        idempotency_key=f"demo-evidence:{event.event_id}",
    )
    print_step("EVIDENCE_SUBMITTED", evidence.evidence_id)
    runtime.begin_review(task.task_id, actor="rule:synthetic-evidence-review-v1")
    print_step("UNDER_REVIEW", "synthetic evidence validation")

    review_result = (
        PostReviewResult.PASSED
        if args.review_result == "pass"
        else PostReviewResult.NEEDS_MORE_EVIDENCE
    )
    review = runtime.review_task(
        task.task_id,
        reviewer_or_model="rule:synthetic-evidence-review-v1",
        result=review_result,
        comment=(
            "Synthetic follow-up value satisfies the demo review policy."
            if review_result is PostReviewResult.PASSED
            else "Synthetic evidence is intentionally marked insufficient."
        ),
    )
    final_event = runtime.store.get_event(event.event_id)
    print_step("REVIEW", f"{review.result.value}; closed={review.closed}")
    print_step("FINAL", final_event.status.value)
    _print_timeline(runtime, event.event_id)
    return 0


def _print_timeline(runtime: AlphaNoahRuntime, event_id: str) -> None:
    event = runtime.store.get_event(event_id)
    print()
    print(f"Audit timeline ({event.trace_id})")
    for index, record in enumerate(runtime.store.list_audit(event.trace_id), 1):
        transition = (
            f"{record.previous_state or '-'} -> "
            f"{record.new_state or '-'}"
        )
        print(
            f"{index:02d}. {record.timestamp} | {record.actor} | "
            f"{record.action} | {record.object_type}:{record.object_id} | "
            f"{transition}"
        )


def _open_read_only(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {database}")
    connection = sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _print_trace_rows(rows: list[sqlite3.Row], trace_id: str) -> None:
    print(f"Audit timeline ({trace_id})")
    if not rows:
        print("No audit records found.")
        return
    for index, row in enumerate(rows, 1):
        record = json.loads(row["payload"])
        transition = (
            f"{record.get('previous_state') or '-'} -> "
            f"{record.get('new_state') or '-'}"
        )
        print(
            f"{index:02d}. {record['timestamp']} | {record['actor']} | "
            f"{record['action']} | "
            f"{record['object_type']}:{record['object_id']} | "
            f"{transition}"
        )


def run_read_only(args: argparse.Namespace) -> int:
    """Inspect persisted records without initializing or mutating the runtime."""

    if args.reset:
        print("--reset cannot be used with read-only commands.", file=sys.stderr)
        return 2

    try:
        with closing(_open_read_only(args.db)) as connection:
            if args.command == "list":
                rows = connection.execute(
                    """
                    SELECT payload
                    FROM events
                    ORDER BY updated_at, event_id
                    """
                ).fetchall()
                print("Events")
                if not rows:
                    print("No events found.")
                for row in rows:
                    event = json.loads(row["payload"])
                    print(
                        f"{event['event_id']} | {event['status']} | "
                        f"{event['trace_id']} | {event['timestamp']} | "
                        f"{event['source']}"
                    )
                return 0

            if args.resource == "event":
                row = connection.execute(
                    "SELECT payload FROM events WHERE event_id = ?",
                    (args.identifier,),
                ).fetchone()
                if row is None:
                    print(
                        f"Event not found: {args.identifier}",
                        file=sys.stderr,
                    )
                    return 1
                print(
                    json.dumps(
                        json.loads(row["payload"]),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0

            if args.resource == "decision":
                row = connection.execute(
                    "SELECT payload FROM decisions WHERE decision_id = ?",
                    (args.identifier,),
                ).fetchone()
                if row is None:
                    print(
                        f"Decision not found: {args.identifier}",
                        file=sys.stderr,
                    )
                    return 1
                print(
                    json.dumps(
                        json.loads(row["payload"]),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0

            rows = connection.execute(
                """
                SELECT payload
                FROM audit_records
                WHERE trace_id = ?
                ORDER BY sequence
                """,
                (args.identifier,),
            ).fetchall()
            _print_trace_rows(rows, args.identifier)
            return 0 if rows else 1
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(f"Read-only inspection failed: {exc}", file=sys.stderr)
        return 2


def run_analysis(args: argparse.Namespace) -> int:
    """Explicitly analyze one NEW Event without coupling analysis to QR POST."""

    if args.reset:
        print("--reset cannot be used with analyze.", file=sys.stderr)
        return 2
    if not args.model:
        print(
            "A model tag is required via --model or "
            "ALPHANOAH_OLLAMA_MODEL.",
            file=sys.stderr,
        )
        return 2
    try:
        context_builder = None
        if args.knowledge_file is not None:
            if not args.knowledge_file.is_file():
                raise ValueError(
                    "knowledge file does not exist: "
                    + args.knowledge_file.name
                )
            context_builder = ContextBuilder(
                JsonKnowledgeRepository(args.knowledge_file)
            )
        ollama_provider = OllamaAnalysisProvider(
            base_url=args.base_url,
            model=args.model,
            connect_timeout_seconds=args.connect_timeout,
            total_timeout_seconds=args.total_timeout,
            max_prompt_bytes=args.max_prompt_bytes,
            max_request_bytes=args.max_request_bytes,
            max_response_bytes=args.max_response_bytes,
            model_digest=args.model_digest,
            keep_alive=args.keep_alive,
            num_ctx=args.num_ctx,
        )
        provider = ReliableAnalysisProvider(
            ollama_provider,
            policy=ReliabilityPolicy(
                timeout_seconds=args.total_timeout,
                max_retry=args.max_retry,
            ),
            context_builder=context_builder,
        )
        skill_resolver = (
            DeterministicSkillResolver(DEMO_SKILL_DEFINITIONS)
            if args.demo_skills
            else None
        )
        runtime = AlphaNoahRuntime(str(args.db))
        decision, hook_result = runtime.analyze_event_with_provider(
            args.identifier,
            provider=provider,
            skill_resolver=skill_resolver,
        )
        event = runtime.store.get_event(args.identifier)
    except (ValueError, AnalysisProviderError) as exc:
        failure_type = getattr(exc, "failure_type", "configuration")
        print(f"Analysis failed ({failure_type}): {exc}", file=sys.stderr)
        return 1
    except (
        InvalidStateTransition,
        ObjectNotFoundError,
        SkillResolutionError,
    ) as exc:
        print(f"Analysis rejected: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "event_id": event.event_id,
                "trace_id": event.trace_id,
                "decision_id": decision.decision_id,
                "event_status": event.status.value,
                "decision_status": decision.status.value,
                "hook_action": hook_result.action.value,
                "model_or_rule": decision.model_or_rule,
                "requires_human_review": decision.requires_human_review,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def run_restaurant_aircon_demo(args: argparse.Namespace) -> int:
    """Run the synthetic Task 05A flow with explicit human checkpoints."""

    if args.provider == "ollama" and not args.model:
        print(
            "A model tag is required for Ollama mode via --model or "
            "ALPHANOAH_OLLAMA_MODEL.",
            file=sys.stderr,
        )
        return 2
    try:
        raw_provider = None
        if args.provider == "ollama":
            raw_provider = OllamaAnalysisProvider(
                base_url=args.base_url,
                model=args.model,
                connect_timeout_seconds=args.connect_timeout,
                total_timeout_seconds=args.total_timeout,
                model_digest=args.model_digest,
            )
        application = build_restaurant_aircon_golden_path(
            args.db,
            raw_provider=raw_provider,
            knowledge_file=args.knowledge_file,
            reliability_policy=ReliabilityPolicy(
                timeout_seconds=args.total_timeout,
                max_retry=args.max_retry,
            ),
        )
        if args.reset:
            application.runtime.store.reset()

        print("AlphaNoah Task 05A - restaurant air-conditioner golden path")
        print("Synthetic demo data / Not a real production incident")
        print("No equipment control or operating authorization is performed.")
        event = application.submit_incident()
        print_step("QR SUBMITTED", event.event_id)
        print_step("EVENT", f"{event.status.value}; trace={event.trace_id}")

        analysis = application.analyze(event.event_id)
        print_step(
            "SKILL",
            (
                f"{analysis.selected_skill_id}@"
                f"{analysis.selected_skill_version}"
            ),
        )
        if analysis.knowledge_matches:
            for match in analysis.knowledge_matches:
                reason = ",".join(match.matched_fields) or "lexical"
                print_step(
                    "KNOWLEDGE",
                    (
                        f"{match.document_id}; score={match.score}; "
                        f"matched={reason}"
                    ),
                )
        else:
            print_step("KNOWLEDGE", "no reviewed context selected")
        print_step(
            "ANALYSIS",
            (
                f"validation={analysis.validation_status}; "
                f"status={analysis.event_status}; "
                f"decision={analysis.decision_id}"
            ),
        )

        human_choice = input(
            "Human review [approve/reject/cancel]: "
        ).strip().lower()
        if human_choice == "cancel" or not human_choice:
            print_step("HUMAN REVIEW", "cancelled; no task created")
            _print_golden_timeline(application, event.event_id)
            return 0
        if human_choice == "reject":
            application.submit_human_review(
                analysis.decision_id,
                outcome=HumanReviewOutcome.REJECTED,
                comment="Explicit rejection by the Task 05A CLI reviewer.",
            )
            final_event = application.runtime.store.get_event(event.event_id)
            print_step("HUMAN REVIEW", "REJECTED")
            print_step("FINAL", final_event.status.value)
            _print_golden_timeline(application, event.event_id)
            return 0
        if human_choice != "approve":
            print(
                "Human review must be approve, reject, or cancel.",
                file=sys.stderr,
            )
            return 2

        application.submit_human_review(
            analysis.decision_id,
            outcome=HumanReviewOutcome.APPROVED,
            comment="Explicit approval by the Task 05A CLI reviewer.",
        )
        print_step("HUMAN REVIEW", "APPROVED")
        task = application.create_approved_task(analysis.decision_id)
        print_step(
            "TASK",
            f"{task.task_id}; assignee={task.assignee}; status={task.status}",
        )

        continue_task = input(
            "Start task and submit synthetic evidence? [y/N]: "
        ).strip().lower()
        if continue_task not in {"y", "yes"}:
            print_step("FINAL", "TASK_CREATED")
            _print_golden_timeline(application, event.event_id)
            return 0
        application.start_task(task.task_id)
        evidence = application.submit_synthetic_evidence(task.task_id)
        application.begin_evidence_review(task.task_id)
        print_step("EVIDENCE", evidence.evidence_id)

        close_choice = input(
            "Accept synthetic evidence and close? [y/N]: "
        ).strip().lower()
        if close_choice not in {"y", "yes"}:
            print_step("FINAL", "UNDER_REVIEW")
            _print_golden_timeline(application, event.event_id)
            return 0
        review = application.review_evidence(
            task.task_id,
            result=PostReviewResult.PASSED,
            comment="Explicit acceptance of synthetic evidence.",
        )
        final_event = application.runtime.store.get_event(event.event_id)
        print_step("REVIEW", f"{review.result.value}; closed={review.closed}")
        print_step("FINAL", final_event.status.value)
        _print_golden_timeline(application, event.event_id)
        return 0
    except (AlphaNoahError, ValueError) as exc:
        failure_type = getattr(exc, "failure_type", "application")
        print(
            f"Golden-path demo failed ({failure_type}): {exc}",
            file=sys.stderr,
        )
        return 1
    except (OSError, sqlite3.Error):
        print(
            "Golden-path demo failed (local_storage): "
            "a required local resource was unavailable.",
            file=sys.stderr,
        )
        return 1


def _print_golden_timeline(application: object, event_id: str) -> None:
    print()
    print("Persisted audit timeline")
    for entry in application.timeline(event_id):
        print(
            f"{entry.sequence:02d}. {entry.timestamp} | {entry.actor} | "
            f"{entry.action} | {entry.entity_type}:{entry.entity_id} | "
            f"{entry.summary}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the first validation workflow or inspect its SQLite records."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--decision",
        choices=("approve", "reject"),
        help="Explicit CLI operator decision; omit for an interactive prompt.",
    )
    parser.add_argument(
        "--reviewer",
        default="human:demo-operator",
        help="Human identity; must start with 'human:'.",
    )
    parser.add_argument(
        "--review-result",
        choices=("pass", "more"),
        default="pass",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear records only in the explicitly selected demo database.",
    )
    commands = parser.add_subparsers(dest="command")
    list_parser = commands.add_parser(
        "list",
        help="List persisted records without changing runtime state.",
    )
    list_parser.add_argument("resource", choices=("events",))
    show_parser = commands.add_parser(
        "show",
        help="Show one event, decision, or trace without changing runtime state.",
    )
    show_parser.add_argument(
        "resource", choices=("event", "decision", "trace")
    )
    show_parser.add_argument("identifier")
    analyze_parser = commands.add_parser(
        "analyze",
        help="Explicitly analyze one NEW Event through a local provider.",
    )
    analyze_parser.add_argument("resource", choices=("event",))
    analyze_parser.add_argument("identifier")
    analyze_parser.add_argument(
        "--provider",
        choices=("ollama",),
        default="ollama",
    )
    analyze_parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "ALPHANOAH_OLLAMA_BASE_URL",
            "http://127.0.0.1:11434",
        ),
    )
    analyze_parser.add_argument(
        "--model",
        default=os.environ.get("ALPHANOAH_OLLAMA_MODEL"),
    )
    analyze_parser.add_argument(
        "--model-digest",
        default=os.environ.get("ALPHANOAH_OLLAMA_MODEL_DIGEST"),
    )
    analyze_parser.add_argument(
        "--connect-timeout",
        type=float,
        default=5.0,
    )
    analyze_parser.add_argument(
        "--total-timeout",
        type=float,
        default=60.0,
    )
    analyze_parser.add_argument(
        "--max-retry",
        type=int,
        default=1,
        help="Retry transient model failures at most this many times (0-3).",
    )
    knowledge_file = os.environ.get("ALPHANOAH_KNOWLEDGE_FILE")
    analyze_parser.add_argument(
        "--knowledge-file",
        type=Path,
        default=Path(knowledge_file) if knowledge_file else None,
        help=(
            "Optional reviewed local JSON knowledge repository; "
            "no vector retrieval is performed."
        ),
    )
    analyze_parser.add_argument(
        "--demo-skills",
        action="store_true",
        help=(
            "Enable the two deterministic synthetic Task 04.5C demo Skills."
        ),
    )
    analyze_parser.add_argument(
        "--max-prompt-bytes",
        type=int,
        default=65_536,
    )
    analyze_parser.add_argument(
        "--max-request-bytes",
        type=int,
        default=131_072,
    )
    analyze_parser.add_argument(
        "--max-response-bytes",
        type=int,
        default=1_048_576,
    )
    analyze_parser.add_argument("--keep-alive", default="5m")
    analyze_parser.add_argument(
        "--num-ctx",
        type=int,
        help=(
            "Optional context length confirmed on the target host; "
            "no value is guessed by default."
        ),
    )
    restaurant_parser = commands.add_parser(
        "restaurant-aircon",
        help=(
            "Run the synthetic restaurant A08 air-conditioner golden path."
        ),
    )
    restaurant_parser.add_argument(
        "--provider",
        choices=("fake", "ollama"),
        default="fake",
    )
    restaurant_parser.add_argument(
        "--knowledge-file",
        type=Path,
        default=DEFAULT_RESTAURANT_KNOWLEDGE_FILE,
    )
    restaurant_parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "ALPHANOAH_OLLAMA_BASE_URL",
            "http://127.0.0.1:11434",
        ),
    )
    restaurant_parser.add_argument(
        "--model",
        default=os.environ.get("ALPHANOAH_OLLAMA_MODEL"),
    )
    restaurant_parser.add_argument(
        "--model-digest",
        default=os.environ.get("ALPHANOAH_OLLAMA_MODEL_DIGEST"),
    )
    restaurant_parser.add_argument(
        "--connect-timeout",
        type=float,
        default=5.0,
    )
    restaurant_parser.add_argument(
        "--total-timeout",
        type=float,
        default=60.0,
    )
    restaurant_parser.add_argument(
        "--max-retry",
        type=int,
        default=1,
    )
    add_provider_commands(commands)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "analyze":
        return run_analysis(args)
    if args.command == "restaurant-aircon":
        return run_restaurant_aircon_demo(args)
    if args.command == "provider":
        return run_provider_management(args)
    if args.command == "doctor":
        return run_doctor(args)
    if args.command is not None:
        return run_read_only(args)
    return run_demo(args)


if __name__ == "__main__":
    raise SystemExit(main())
