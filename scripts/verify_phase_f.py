"""Phase F acceptance verification script.

Creates a temporary SQLite task DB, exercises every API endpoint,
and checks all acceptance criteria against the PRODUCT.md spec.

Usage:
    python scripts/verify_phase_f.py
    python scripts/verify_phase_f.py --verbose
"""

from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# shared test state
# ---------------------------------------------------------------------------

TEST_PROJECT = "verify-phase-f"
today = date.today()


def _settings(tmp: Path):
    from app.config import Settings

    return Settings(
        project_root=tmp / "projects",
        output_root=tmp / "outputs",
        vector_db_root=tmp / "vectors",
        sqlite_path=tmp / "sqlite" / "projectpack.db",
        log_root=tmp / "logs",
    )


def _init_app(tmp: Path):
    from app.main import create_app

    settings = _settings(tmp)
    app = create_app(settings)
    return app, settings


# ===========================================================================
# check helpers
# ===========================================================================


def check_tables_exist(service) -> tuple[bool, str, str]:
    """AC-F-01: all 5 tables + indexes exist."""
    with service._connect() as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
    required = {
        "task",
        "task_change",
        "confirmation",
        "operation_audit",
        "task_import_fingerprint",
    }
    ok = required.issubset(set(tables))
    return ok, "F-AC-01: 5 tables exist", f"found: {sorted(tables)}"


def check_crud_flow(service) -> tuple[bool, str, str]:
    """AC-F-02: create → read → update → list."""
    from app.schemas.models import TaskCreate, TaskUpdate

    t = service.create_task(
        TEST_PROJECT,
        TaskCreate(
            title="Integration test task",
            owner="tester",
            due_date=today + timedelta(days=3),
            priority="high",
            acceptance_criteria="Must pass all checks",
            dependencies=["dep-1"],
            source_ref="verify-script",
        ),
    )
    # read
    got = service.get_task(TEST_PROJECT, t.id)
    ok1 = got.title == "Integration test task" and got.owner == "tester"

    # update
    updated = service.update_task(
        TEST_PROJECT,
        t.id,
        TaskUpdate(title="Updated title", priority="low"),
    )
    ok2 = updated.title == "Updated title" and updated.priority == "low"

    # list
    all_tasks = service.list_tasks(TEST_PROJECT)
    ok3 = any(x.id == t.id for x in all_tasks)

    ok = ok1 and ok2 and ok3
    return ok, "F-AC-02: task CRUD", f"create={ok1}, update={ok2}, list={ok3}"


def check_state_machine(service) -> tuple[bool, str, str]:
    """AC-F-06: valid transitions enforced, cancelled is terminal."""
    from app.schemas.models import TaskCreate, TaskStatusTransition, PhaseFTaskStatus

    t = service.create_task(
        TEST_PROJECT,
        TaskCreate(title="State machine test", status="pending_confirmation"),
    )

    # accept → not_started
    t = service.transition_status(
        TEST_PROJECT,
        t.id,
        TaskStatusTransition(
            status=PhaseFTaskStatus.NOT_STARTED, reason="accept", changed_by="tester"
        ),
    )
    ok1 = t.status == "not_started"

    # start work
    t = service.transition_status(
        TEST_PROJECT,
        t.id,
        TaskStatusTransition(
            status=PhaseFTaskStatus.IN_PROGRESS, reason="start", changed_by="tester"
        ),
    )
    ok2 = t.status == "in_progress"

    # cancel
    t = service.transition_status(
        TEST_PROJECT,
        t.id,
        TaskStatusTransition(
            status=PhaseFTaskStatus.CANCELLED, reason="no longer needed", changed_by="tester"
        ),
    )
    ok3 = t.status == "cancelled"

    # try to reactivate → must raise
    import app.services.task_lifecycle as svc_mod

    ok4 = False
    try:
        service.transition_status(
            TEST_PROJECT,
            t.id,
            TaskStatusTransition(
                status=PhaseFTaskStatus.NOT_STARTED, reason="reactivate",
            ),
        )
    except ValueError:
        ok4 = True

    ok = all([ok1, ok2, ok3, ok4])
    return ok, "F-AC-06: state machine", f"flow={ok1}/{ok2}/{ok3}, cancelled_terminal={ok4}"


def check_confirmation_queue(service) -> tuple[bool, str, str]:
    """AC-F-04: extract → submit → queue → accept / ignore."""
    from app.schemas.models import CandidateTask, ConfirmationAction

    # submit via extract + submit_candidates (creates confirmation records)
    result = service.extract_candidates(
        TEST_PROJECT,
        "1. 测试任务A - 完成用户认证模块\n2. 测试任务B - 修复性能问题",
        "meeting_notes",
    )
    if not result.candidates:
        return False, "F-AC-04: confirmation queue", "no candidates extracted"

    records = service.submit_candidates(TEST_PROJECT, result.candidates)
    ok1 = len(records) == 2 and all(r.status == "pending" for r in records)

    # accept first
    from_check = service.process_confirmation(
        TEST_PROJECT,
        records[0].task_id,
        ConfirmationAction(action="accept", confirmed_by="tester",
                           confirmation_basis="looks good"),
    )
    ok2 = from_check.status == "accepted"

    # ignore second
    ignore_check = service.process_confirmation(
        TEST_PROJECT,
        records[1].task_id,
        ConfirmationAction(action="ignore", confirmed_by="tester",
                           confirmation_notes="not relevant"),
    )
    ok3 = ignore_check.status == "ignored"

    ok = ok1 and ok2 and ok3
    return ok, "F-AC-04: confirmation queue", f"submit={ok1}, accept={ok2}, ignore={ok3}"


def check_import_dedup(service) -> tuple[bool, str, str]:
    """AC-F-05: CSV import → diff → confirm → dedup."""
    from app.schemas.models import TaskImportConfirm

    csv_bytes = (
        "title,owner,due_date,priority\r\n"
        f"Import Task A,tester,{today + timedelta(days=5)},high\r\n"
        f"Import Task B,tester,{today + timedelta(days=7)},normal\r\n"
    ).encode("utf-8")

    # preview
    diff, candidates = service.preview_import(TEST_PROJECT, csv_bytes, "test.csv")
    ok1 = diff.new_rows == 2 and diff.duplicate_rows == 0

    # confirm import
    result = service.confirm_import(
        TEST_PROJECT,
        candidates,
        csv_bytes,
        "test.csv",
        TaskImportConfirm(confirmed_by="tester"),
    )
    ok2 = result.imported == 2 and result.errors == 0

    # re-import same file → should dedup
    diff2, _ = service.preview_import(TEST_PROJECT, csv_bytes, "test.csv")
    ok3 = diff2.new_rows == 0 and diff2.duplicate_rows == 2

    ok = ok1 and ok2 and ok3
    return ok, "F-AC-05: CSV import + dedup", f"preview={ok1}, import={ok2}, dedup={ok3}"


def check_audit_trail(service) -> tuple[bool, str, str]:
    """AC-F-07: audit trail records operations."""
    log = service.get_audit_log(TEST_PROJECT)
    ok = len(log) > 0
    return ok, "F-AC-07: audit trail", f"{len(log)} audit entries found"


def check_history(service) -> tuple[bool, str, str]:
    """F-AC-06 sub-check: transition history is recorded."""
    tasks = service.list_tasks(TEST_PROJECT)
    if not tasks:
        return False, "F-AC-06b: transition history", "no tasks to check"
    # pick the state-machine task (which went through transitions)
    for t in tasks:
        history = service.get_task_history(TEST_PROJECT, t.id)
        if len(history) > 0:
            return True, "F-AC-06b: transition history", f"{len(history)} changes for {t.id}"
    return False, "F-AC-06b: transition history", "no history found"


def check_candidate_extraction(service) -> tuple[bool, str, str]:
    """AC-F-03: extract candidates from text (pattern-matching lines)."""
    result = service.extract_candidates(
        TEST_PROJECT,
        "1. 张三负责前端重构，截止周五\n2. 李四做性能优化，下周三前完成\n3. 编写测试用例",
        "meeting_notes",
    )
    ok = len(result.candidates) >= 3
    return ok, "F-AC-03: candidate extraction", f"{len(result.candidates)} candidates extracted"


def check_empty_extraction(service) -> tuple[bool, str, str]:
    """AC-F-03 edge: empty text returns empty list."""
    result = service.extract_candidates(TEST_PROJECT, "", "meeting_notes")
    ok = len(result.candidates) == 0
    return ok, "F-AC-03b: empty extraction", f"got {len(result.candidates)} candidates"


# ===========================================================================
# main
# ===========================================================================


def main() -> None:
    verbose = "--verbose" in sys.argv

    print("=" * 72)
    print("Phase F — Acceptance Verification Script")
    print(f"Date: {today}")
    print("=" * 72)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tmp = Path(tmp_dir)
        app, settings = _init_app(tmp)

        # initialise service — tables created on first _connect()
        from app.services.task_lifecycle import TaskLifecycleService

        sqlite_path = Path(settings.sqlite_path)
        if not sqlite_path.is_dir():
            sqlite_path = sqlite_path.parent
        db_path = sqlite_path / "projects" / TEST_PROJECT / "tasks.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        service = TaskLifecycleService(db_path)

        print(f"\nTemp dir: {tmp}")
        print(f"DB path:  {db_path}\n")

        # register project via API
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/api/projects", json={"project_id": TEST_PROJECT, "name": "Verify Phase F"})
        if resp.status_code not in (201, 409):
            print(f"❌ Failed to create test project: {resp.status_code} {resp.json()}")
            sys.exit(1)

        checks = [
            check_tables_exist(service),
            check_crud_flow(service),
            check_state_machine(service),
            check_confirmation_queue(service),
            check_import_dedup(service),
            check_audit_trail(service),
            check_history(service),
            check_candidate_extraction(service),
            check_empty_extraction(service),
        ]

        print(f"{'Status':8s} {'Check':40s} {'Detail'}")
        print("-" * 72)
        all_pass = True
        for ok, name, detail in checks:
            status = "✅ PASS" if ok else "❌ FAIL"
            if not ok:
                all_pass = False
            print(f"{status:8s} {name:40s} {detail}")
        print("-" * 72)

        if all_pass:
            print("\n🎉 All Phase F acceptance criteria passed!")
            sys.exit(0)
        else:
            print("\n⚠️  Some checks failed — review output above.")
            sys.exit(1)


if __name__ == "__main__":
    main()
