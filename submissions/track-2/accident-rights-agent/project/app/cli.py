"""Command-line entry point for case intake and evidence reconstruction."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.agents.intake import assess_intake
from app.evidence.pipeline import EvidenceReconstructionPipeline
from app.evidence.workspace import CaseWorkspace
from app.graph.workflow import CaseOrchestrator
from app.rag.service import build_retriever
from app.schemas.evidence import SourceRole


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="accident-rights")
    parser.add_argument(
        "--case-root",
        type=Path,
        default=Path("data/cases"),
        help="Local case storage root (default: data/cases).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-case")
    create.add_argument("--case-id")

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("case_id")
    ingest.add_argument("files", nargs="+", type=Path)
    ingest.add_argument(
        "--role",
        choices=[role.value for role in SourceRole],
        default=SourceRole.OTHER.value,
    )

    intake = subparsers.add_parser("intake")
    intake.add_argument("case_id")

    reconstruct = subparsers.add_parser("reconstruct")
    reconstruct.add_argument("case_id")

    export = subparsers.add_parser("export")
    export.add_argument("case_id")
    export.add_argument("--output", type=Path)

    legal_search = subparsers.add_parser("legal-search")
    legal_search.add_argument("query")
    legal_search.add_argument("--top-k", type=int, default=4)

    orchestrate = subparsers.add_parser("orchestrate")
    orchestrate.add_argument("case_id")
    orchestrate.add_argument("--thread-id")
    orchestrate.add_argument(
        "--interrupt-after",
        choices=[
            "intake_complete",
            "evidence_ready",
            "legal_retrieval",
            "vehicle_nature",
            "liability",
            "rights_workflow",
            "verifier",
        ],
    )
    orchestrate.add_argument("--simulate-json-error-at")

    resume = subparsers.add_parser("resume")
    resume.add_argument("thread_id")

    workflow_status = subparsers.add_parser("workflow-status")
    workflow_status.add_argument("thread_id")

    approve = subparsers.add_parser("approve")
    approve.add_argument("thread_id")
    approve.add_argument(
        "--decision",
        required=True,
        choices=["approved", "rejected", "changes_requested"],
    )
    approve.add_argument("--approver", required=True)
    approve.add_argument("--comments", default="")

    for workflow_parser in (orchestrate, resume, workflow_status, approve):
        workflow_parser.add_argument(
            "--checkpoint-path",
            type=Path,
            default=Path(
                os.getenv(
                    "ORCHESTRATOR_CHECKPOINT_DB",
                    "data/checkpoints/orchestrator.sqlite3",
                )
            ),
        )

    args = parser.parse_args(argv)
    workspace = CaseWorkspace(args.case_root)
    try:
        if args.command == "create-case":
            case_id = workspace.create_case(args.case_id)
            _print({"case_id": case_id, "case_dir": str(workspace.case_dir(case_id))})
        elif args.command == "ingest":
            role = SourceRole(args.role)
            records = [
                workspace.ingest_file(args.case_id, path, role=role).to_dict()
                for path in args.files
            ]
            _print({"case_id": args.case_id, "sources": records})
        elif args.command == "intake":
            store = workspace.store(args.case_id)
            _print(assess_intake(store.list_sources(args.case_id)).to_dict())
        elif args.command == "reconstruct":
            summary = EvidenceReconstructionPipeline(workspace).reconstruct(
                args.case_id
            )
            _print(summary.to_dict())
            return 0 if summary.status == "passed" else 2
        elif args.command == "export":
            store = workspace.store(args.case_id)
            payload = store.export_case(args.case_id)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                _print({"case_id": args.case_id, "output": str(args.output.resolve())})
            else:
                _print(payload)
        elif args.command == "legal-search":
            retriever = build_retriever()
            try:
                _print(
                    {
                        "query": args.query,
                        "citations": [
                            item.model_dump(mode="json")
                            for item in retriever.citations(
                                args.query, top_k=args.top_k, candidate_k=10
                            )
                        ],
                        "reranker": retriever.reranker.name,
                        "degraded_reason": retriever.reranker.degraded_reason,
                    }
                )
            finally:
                retriever.close()
        else:
            retriever = build_retriever()
            orchestrator = CaseOrchestrator(
                workspace=workspace,
                retriever=retriever,
                checkpoint_path=args.checkpoint_path,
            )
            try:
                if args.command == "orchestrate":
                    payload = orchestrator.run(
                        args.case_id,
                        thread_id=args.thread_id,
                        interrupt_after=args.interrupt_after,
                        simulate_json_error_at=args.simulate_json_error_at,
                    )
                    _print(payload)
                elif args.command == "resume":
                    _print(orchestrator.resume(args.thread_id))
                elif args.command == "workflow-status":
                    _print(orchestrator.status(args.thread_id))
                else:
                    _print(
                        orchestrator.decide_approval(
                            args.thread_id,
                            decision=args.decision,
                            approver=args.approver,
                            comments=args.comments,
                        )
                    )
            finally:
                orchestrator.close()
                retriever.close()
    except Exception as exc:
        _print(
            {
                "status": "failed",
                "failure_reason": f"{type(exc).__name__}: {exc}",
                "next_step": "Correct the reported input/dependency issue and retry.",
            }
        )
        return 1
    return 0


def _print(value: dict[str, Any]) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            default=lambda item: getattr(item, "value", str(item)),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
