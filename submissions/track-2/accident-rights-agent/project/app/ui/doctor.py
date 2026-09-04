"""Local demo preflight checks with no public-model fallback."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from app.demo.business_cases import (
    is_complete_synthetic_pdf,
    repair_existing_experience_cases,
)
from app.demo.golden_case import GOLDEN_CASE_ID, seed_golden_case
from app.evidence.model_client import LocalVLLMClient
from app.schemas.ui import DoctorCheck, WorkflowMode
from app.services.case_service import CaseService


def run_checks(
    *,
    case_root: Path,
    checkpoint_path: Path,
    legal_corpus_path: Path,
    qdrant_path: Path,
    mode: WorkflowMode,
    host: str,
    port: int,
    prepare: bool = False,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    checks.append(
        DoctorCheck(
            name="python",
            status="pass" if sys.version_info >= (3, 10) else "fail",
            detail=sys.version.split()[0],
            blocking=sys.version_info < (3, 10),
        )
    )
    required = ["gradio", "langgraph", "pydantic", "qdrant_client"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    checks.append(
        DoctorCheck(
            name="dependencies",
            status="pass" if not missing else "fail",
            detail=(
                "required Python packages available"
                if not missing
                else f"missing: {', '.join(missing)}"
            ),
            blocking=bool(missing),
            metadata={"required": required},
        )
    )
    checks.append(_writable_check(case_root, "case_root"))
    checks.append(_writable_check(checkpoint_path.parent, "checkpoint_parent"))
    checks.append(_sqlite_check(legal_corpus_path, "legal_corpus"))
    qdrant_ready = qdrant_path.is_dir() and (qdrant_path / "meta.json").is_file()
    checks.append(
        DoctorCheck(
            name="qdrant_index",
            status="pass" if qdrant_ready else "fail",
            detail=str(qdrant_path.resolve()),
            blocking=not qdrant_ready,
        )
    )
    port_available, port_detail = _port_available(host, port)
    checks.append(
        DoctorCheck(
            name="ui_port",
            status="pass" if port_available else "fail",
            detail=port_detail,
            blocking=not port_available,
        )
    )
    if mode is WorkflowMode.LOCAL_VLLM:
        try:
            model = LocalVLLMClient().model_name()
            checks.append(
                DoctorCheck(
                    name="local_vllm",
                    status="pass",
                    detail=f"loopback model: {model}",
                    blocking=False,
                )
            )
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    name="local_vllm",
                    status="fail",
                    detail=str(exc),
                    blocking=True,
                )
            )
    else:
        checks.append(
            DoctorCheck(
                name="model_policy",
                status="pass",
                detail=(
                    "mock mode uses deterministic adapters and declared synthetic "
                    "fixtures; no public API fallback is configured"
                ),
                blocking=False,
            )
        )

    fixture_ready = False
    fixture_detail = ""
    try:
        service = CaseService(case_root)
        repairs: dict[str, int] = {}
        if prepare:
            seed_golden_case(service.workspace)
            repairs = repair_existing_experience_cases(
                service.workspace,
                service.case_ids(),
            )
        fixture = service.export_case(GOLDEN_CASE_ID)
        kinds = {
            getattr(item["kind"], "value", item["kind"])
            for item in fixture["sources"]
        }
        synthetic_pdfs = [
            item
            for item in service.workspace.store(GOLDEN_CASE_ID).list_sources(
                GOLDEN_CASE_ID
            )
            if item.original_name.endswith("-synthetic.pdf")
        ]
        pdfs_valid = bool(synthetic_pdfs) and all(
            is_complete_synthetic_pdf(
                service.workspace.resolve_source(item).read_bytes()
            )
            for item in synthetic_pdfs
        )
        fixture_ready = (
            {"pdf", "image", "video"} <= kinds
            and len(fixture["facts"]) > 0
            and len(fixture["timeline"]) >= 3
            and pdfs_valid
        )
        repaired_count = sum(repairs.values())
        fixture_detail = (
            f"{GOLDEN_CASE_ID}: {len(fixture['sources'])} sources, "
            f"{len(fixture['facts'])} facts, {len(fixture['timeline'])} events, "
            f"valid_pdfs={len(synthetic_pdfs)}, repaired={repaired_count}"
        )
    except Exception as exc:
        fixture_detail = str(exc)
    checks.append(
        DoctorCheck(
            name="golden_fixture",
            status="pass" if fixture_ready else "fail",
            detail=fixture_detail,
            blocking=not fixture_ready,
        )
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=[item.value for item in WorkflowMode],
        default=os.getenv("MODEL_MODE", "mock"),
    )
    parser.add_argument(
        "--case-root", type=Path, default=Path(os.getenv("CASE_ROOT", "data/cases"))
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path(
            os.getenv(
                "ORCHESTRATOR_CHECKPOINT_DB",
                "data/checkpoints/orchestrator.sqlite3",
            )
        ),
    )
    parser.add_argument(
        "--legal-corpus",
        type=Path,
        default=Path(os.getenv("LEGAL_CORPUS_DB", "data/laws/legal_corpus.sqlite3")),
    )
    parser.add_argument(
        "--qdrant",
        type=Path,
        default=Path(os.getenv("QDRANT_PATH", "data/qdrant/legal")),
    )
    parser.add_argument(
        "--host", default=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1")
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    )
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    checks = run_checks(
        case_root=args.case_root,
        checkpoint_path=args.checkpoint,
        legal_corpus_path=args.legal_corpus,
        qdrant_path=args.qdrant,
        mode=WorkflowMode(args.mode),
        host=args.host,
        port=args.port,
        prepare=args.prepare,
    )
    if args.json:
        print(
            json.dumps(
                [item.model_dump(mode="json") for item in checks],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for item in checks:
            marker = "OK" if item.status == "pass" else "FAIL"
            print(f"[{marker}] {item.name}: {item.detail}")
    return 1 if any(item.blocking and item.status != "pass" for item in checks) else 0


def _writable_check(path: Path, name: str) -> DoctorCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        writable = os.access(path, os.W_OK)
        detail = str(path.resolve())
    except Exception as exc:
        writable = False
        detail = str(exc)
    return DoctorCheck(
        name=name,
        status="pass" if writable else "fail",
        detail=detail,
        blocking=not writable,
    )


def _sqlite_check(path: Path, name: str) -> DoctorCheck:
    if not path.is_file():
        return DoctorCheck(
            name=name,
            status="fail",
            detail=f"missing: {path}",
            blocking=True,
        )
    try:
        with closing(sqlite3.connect(path)) as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            tables = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        passed = integrity == "ok" and tables > 0
        detail = f"{path.resolve()} · quick_check={integrity} · tables={tables}"
    except Exception as exc:
        passed = False
        detail = str(exc)
    return DoctorCheck(
        name=name,
        status="pass" if passed else "fail",
        detail=detail,
        blocking=not passed,
    )


def _port_available(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
        return True, f"{host}:{port} available"
    except OSError as exc:
        if isinstance(exc, PermissionError):
            return (
                True,
                f"{host}:{port} bind probe not permitted in this sandbox; "
                "availability will be checked by Gradio at launch",
            )
        return False, f"{host}:{port} unavailable: {exc}"


if __name__ == "__main__":
    raise SystemExit(main())
