from __future__ import annotations

import hashlib
import io
import os
import stat
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prooflaunch_remix.v10_submission_store import (
    ConflictError,
    IdempotencyConflict,
    IntegrityError,
    LeaseError,
    PersistentRunStore,
    SubmissionStore,
    UnsafePathError,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class DurableSubmissionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "durable-store"
        self.store = SubmissionStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_run(self, suffix: str = "001"):
        return self.store.create_run(
            f"run-{suffix}",
            {
                "org_id": "org-001",
                "project_id": "project-001",
                "campaign_id": f"campaign-{suffix}",
                "objective": "safe social launch",
            },
        )

    def put_artifact(self, payload: bytes = b"prooflaunch-artifact", media_type: str = "image/png"):
        return self.store.artifacts.put(
            io.BytesIO(payload),
            expected_sha256=digest(payload),
            media_type=media_type,
        )

    def test_schema_pragmas_and_private_permissions_are_initialized(self) -> None:
        expected_tables = {
            "runs",
            "artifacts",
            "run_artifacts",
            "approvals",
            "jobs",
            "events",
            "idempotency_commands",
            "learning_memories",
            "strategy_memory_resolutions",
            "memory_capsule_imports",
            "artifact_tenants",
        }
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.database_path.stat().st_mode), 0o600)
        with self.store._connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue(expected_tables.issubset(tables))
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_store_root_must_be_absolute_and_must_not_be_a_symlink(self) -> None:
        with self.assertRaises(UnsafePathError):
            SubmissionStore(Path("client-relative-store"))
        real = Path(self.temporary.name) / "real"
        real.mkdir()
        link = Path(self.temporary.name) / "linked"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(UnsafePathError):
            SubmissionStore(link)

    def test_project_learning_memory_is_append_only_scoped_and_idempotent(self) -> None:
        self.create_run()
        payload = {
            "schema": "ProofLaunchPromotedLearningMemoryV1",
            "next_cycle_decision": "revise_one_variable_then_retest",
            "automatic_strategy_mutation_executed": False,
        }
        first = self.store.record_learning_memory(
            memory_id="learning-001",
            org_id="org-001",
            project_id="project-001",
            source_run_id="run-001",
            observation_id="obs-001",
            approved_by="reviewer@example.test",
            reason="Promote this aggregate learning for the next project cycle.",
            payload=payload,
            approved_at=T0,
        )
        replay = self.store.record_learning_memory(
            memory_id="learning-001",
            org_id="org-001",
            project_id="project-001",
            source_run_id="run-001",
            observation_id="obs-001",
            approved_by="reviewer@example.test",
            reason="Promote this aggregate learning for the next project cycle.",
            payload=payload,
            approved_at=T0,
        )
        self.assertEqual(first, replay)
        self.assertEqual(
            self.store.list_learning_memories("org-001", "project-001"), [first]
        )
        self.assertEqual(self.store.list_learning_memories("org-001", "other"), [])
        with self.assertRaises(ConflictError):
            self.store.record_learning_memory(
                memory_id="learning-001",
                org_id="org-001",
                project_id="project-001",
                source_run_id="run-001",
                observation_id="obs-001",
                approved_by="reviewer@example.test",
                reason="A changed immutable reason.",
                payload=payload,
                approved_at=T0,
            )
        events = self.store.events_after("run-001")
        self.assertEqual(
            [event.event_type for event in events].count("learning_memory_promoted"),
            1,
        )

    def test_memory_capsule_import_requires_immutable_human_review_and_scope(self) -> None:
        capsule = {
            "capsule_id": "capsule-001",
            "capsule_sha256": "b" * 64,
            "context_sha256": "c" * 64,
            "tenant_id": "org-001",
            "project_id": "project-001",
            "context": {},
        }
        staged = self.store.stage_memory_capsule_import(
            capsule,
            org_id="org-001",
            project_id="project-001",
            imported_at=T0,
        )
        self.assertEqual(staged.status, "pending_review")
        self.assertEqual(
            self.store.list_memory_capsule_imports(
                "org-001", "project-001", status="approved"
            ),
            [],
        )
        approved = self.store.review_memory_capsule_import(
            "capsule-001",
            org_id="org-001",
            decision="approve",
            reviewed_by="reviewer@example.test",
            reason="Reviewed the aggregate learning and approved it for this project.",
            reviewed_at=T0 + timedelta(minutes=5),
        )
        self.assertEqual(approved.status, "approved")
        self.assertEqual(
            self.store.list_memory_capsule_imports(
                "org-001", "project-001", status="approved"
            ),
            [approved],
        )
        self.assertEqual(
            self.store.list_memory_capsule_imports("org-002", "project-001"), []
        )
        with self.assertRaises(ConflictError):
            self.store.review_memory_capsule_import(
                "capsule-001",
                org_id="org-001",
                decision="reject",
                reviewed_by="reviewer@example.test",
                reason="Changed decision must fail.",
            )
        with self.assertRaises(ConflictError):
            self.store.stage_memory_capsule_import(
                {**capsule, "tenant_id": "org-002"},
                org_id="org-001",
                project_id="project-001",
            )

    def test_database_target_symlink_fails_closed_before_sqlite_opens_it(self) -> None:
        root = Path(self.temporary.name) / "unsafe-database-store"
        root.mkdir(mode=0o700)
        outside = Path(self.temporary.name) / "outside.sqlite3"
        outside.write_bytes(b"must-not-be-opened")
        (root / "submission.sqlite3").symlink_to(outside)
        with self.assertRaises(UnsafePathError):
            SubmissionStore(root)
        self.assertEqual(outside.read_bytes(), b"must-not-be-opened")

    def test_database_symlink_swap_is_rejected_on_every_new_connection(self) -> None:
        self.create_run()
        outside = Path(self.temporary.name) / "later-outside.sqlite3"
        outside.write_bytes(b"must-remain-untouched")
        self.store.database_path.unlink()
        self.store.database_path.symlink_to(outside)
        with self.assertRaises(UnsafePathError):
            self.store.get_run("run-001")
        self.assertEqual(outside.read_bytes(), b"must-remain-untouched")

    def test_artifact_put_head_and_server_path_are_hash_bound_and_relative(self) -> None:
        payload = b"\x89PNG\r\nprooflaunch"
        record = self.put_artifact(payload)
        self.assertEqual(record.sha256, digest(payload))
        self.assertEqual(record.byte_length, len(payload))
        self.assertFalse(Path(record.relative_path).is_absolute())
        self.assertTrue(record.relative_path.startswith("cas/"))
        self.assertEqual(self.store.artifacts.head(record.sha256), record)
        server_path = self.store.artifacts.resolve_server_path(record.sha256)
        self.assertEqual(server_path.read_bytes(), payload)
        self.assertEqual(stat.S_IMODE(server_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.root / "cas").stat().st_mode), 0o700)

    def test_artifact_put_rejects_digest_mismatch_and_cleans_temporary_bytes(self) -> None:
        payload = b"not-the-declared-object"
        with self.assertRaises(IntegrityError):
            self.store.artifacts.put(
                io.BytesIO(payload),
                expected_sha256="a" * 64,
                media_type="application/octet-stream",
            )
        with self.assertRaises(KeyError):
            self.store.artifacts.head("a" * 64)
        self.assertEqual(list((self.root / "cas").rglob(".put-*.tmp")), [])

    def test_artifact_put_is_idempotent_but_metadata_is_immutable(self) -> None:
        payload = b"same-content"
        first = self.put_artifact(payload, "text/plain")
        second = self.put_artifact(payload, "text/plain")
        self.assertEqual(first, second)
        with self.assertRaises(ConflictError):
            self.put_artifact(payload, "application/json")

    def test_artifact_and_run_access_are_tenant_scoped_below_the_api(self) -> None:
        run = self.create_run()
        artifact = self.put_artifact(b"tenant-a-canary", "application/json")
        self.store.grant_artifact_to_tenant("org-001", artifact.sha256)
        self.assertEqual(
            self.store.require_tenant_artifact("org-001", artifact.sha256),
            artifact,
        )
        self.assertEqual(
            self.store.require_run_tenant(run.run_id, "org-001"), run
        )
        with self.assertRaises(KeyError):
            self.store.require_tenant_artifact("org-002", artifact.sha256)
        with self.assertRaises(KeyError):
            self.store.require_run_tenant(run.run_id, "org-002")

    def test_event_job_and_learning_scope_are_bound_to_run_tenant(self) -> None:
        run = self.create_run()
        event = self.store.append_event(run.run_id, "tenant_canary", {"value": 1})
        self.assertEqual(event.payload["tenant_id"], "org-001")
        job = self.store.enqueue_job(
            "job-tenant-001", run.run_id, kind="prepare", payload={}
        )
        self.assertEqual(job.payload["tenant_id"], "org-001")
        with self.assertRaisesRegex(ConflictError, "job tenant_id"):
            self.store.enqueue_job(
                "job-tenant-002",
                run.run_id,
                kind="prepare",
                payload={"tenant_id": "org-002"},
            )
        with self.assertRaisesRegex(ConflictError, "memory scope"):
            self.store.record_learning_memory(
                memory_id="learning-cross-tenant",
                org_id="org-002",
                project_id="project-001",
                source_run_id=run.run_id,
                observation_id="obs-cross-tenant",
                approved_by="reviewer@example.test",
                reason="This must fail before cross-tenant promotion.",
                payload={
                    "schema": "ProofLaunchPromotedLearningMemoryV1",
                    "automatic_strategy_mutation_executed": False,
                },
                approved_at=T0,
            )

    def test_client_paths_and_traversal_identifiers_fail_closed(self) -> None:
        client_file = Path(self.temporary.name) / "client-secret.txt"
        client_file.write_bytes(b"secret")
        with self.assertRaises(TypeError):
            self.store.artifacts.put(
                client_file,
                expected_sha256=digest(b"secret"),
                media_type="text/plain",
            )
        with self.assertRaises(ValueError):
            self.store.create_run("../escaped", {"objective": "bad"})
        self.create_run()
        artifact = self.put_artifact()
        with self.assertRaises(ValueError):
            self.store.link_artifact("run-001", artifact.sha256, role="../../secret")

    def test_tampered_artifact_path_or_content_fails_head_closed(self) -> None:
        record = self.put_artifact(b"immutable")
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE artifacts SET relative_path = ? WHERE sha256 = ?",
                ("cas/../../outside", record.sha256),
            )
        with self.assertRaises(UnsafePathError):
            self.store.artifacts.head(record.sha256)

        other = self.put_artifact(b"second")
        server_path = self.store.artifacts.resolve_server_path(other.sha256)
        server_path.write_bytes(b"tamper")
        server_path.chmod(0o600)
        with self.assertRaises(IntegrityError):
            self.store.artifacts.head(other.sha256)

    def test_run_state_and_artifact_role_survive_store_reopen(self) -> None:
        created = self.create_run()
        artifact = self.put_artifact()
        self.store.link_artifact(created.run_id, artifact.sha256, role="product_image")
        updated = self.store.transition_run(
            created.run_id,
            expected_status="queued",
            new_status="running",
            details={"worker": "worker-1"},
        )
        reopened = PersistentRunStore(self.root)
        self.assertEqual(reopened.get_run(created.run_id).status, "running")
        self.assertEqual(reopened.get_run(created.run_id).version, updated.version)
        self.assertEqual(
            reopened.linked_artifact(created.run_id, "product_image").sha256,
            artifact.sha256,
        )
        with self.assertRaises(ConflictError):
            reopened.transition_run(
                created.run_id,
                expected_status="queued",
                new_status="failed",
            )

    def test_append_event_is_concurrently_sequenced_and_hash_chained(self) -> None:
        run = self.create_run()
        barrier = threading.Barrier(9)
        errors: list[BaseException] = []

        def append(index: int) -> None:
            try:
                barrier.wait()
                self.store.append_event(run.run_id, "worker_observation", {"index": index})
            except BaseException as error:  # pragma: no cover - retained for assertion output
                errors.append(error)

        threads = [threading.Thread(target=append, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        events = self.store.events_after(run.run_id)
        self.assertEqual([event.sequence for event in events], list(range(1, 10)))
        self.assertTrue(self.store.verify_event_chain(run.run_id))

    def test_last_event_id_returns_only_subsequent_ordered_events(self) -> None:
        run = self.create_run()
        second = self.store.append_event(run.run_id, "audit_started", {"round": 1})
        third = self.store.append_event(run.run_id, "audit_finished", {"passed": True})
        subsequent = self.store.events_after(run.run_id, last_event_id=second.event_id)
        self.assertEqual([event.event_id for event in subsequent], [third.event_id])
        with self.assertRaises(ValueError):
            self.store.events_after(run.run_id, last_event_id=-1)

    def test_event_chain_detects_persisted_payload_tampering(self) -> None:
        run = self.create_run()
        self.store.append_event(run.run_id, "audit_started", {"round": 1})
        self.assertTrue(self.store.verify_event_chain(run.run_id))
        with self.store._connect() as connection:
            connection.execute(
                "UPDATE events SET payload_json = ? WHERE run_id = ? AND sequence = 2",
                ('{"round":2}', run.run_id),
            )
        self.assertFalse(self.store.verify_event_chain(run.run_id))

    def test_approval_is_content_bound_singleton_and_same_record_is_idempotent(self) -> None:
        run = self.create_run()
        preview = digest(b"preview")
        kwargs = dict(
            approval_id="approval-001",
            preview_sha256=preview,
            decision="approve",
            approver="human-reviewer",
            reason="rights and claims verified",
            decided_at=T0,
            payload={"checkpoint": "release"},
        )
        first = self.store.record_approval(run.run_id, **kwargs)
        second = self.store.record_approval(run.run_id, **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(self.store.get_approval(run.run_id), first)
        self.assertEqual(
            [event.event_type for event in self.store.events_after(run.run_id)].count(
                "release_decision_recorded"
            ),
            1,
        )
        with self.assertRaises(ConflictError):
            self.store.record_approval(
                run.run_id,
                **{**kwargs, "approval_id": "approval-002", "decision": "reject"},
            )

    def test_two_concurrent_release_decisions_cannot_both_commit(self) -> None:
        run = self.create_run()
        barrier = threading.Barrier(3)
        outcomes: list[str] = []

        def decide(index: int) -> None:
            barrier.wait()
            try:
                self.store.record_approval(
                    run.run_id,
                    approval_id=f"approval-{index}",
                    preview_sha256=digest(b"same-preview"),
                    decision="approve" if index == 1 else "reject",
                    approver=f"reviewer-{index}",
                    reason="bounded human decision",
                    decided_at=T0,
                )
                outcomes.append("committed")
            except ConflictError:
                outcomes.append("conflict")

        threads = [threading.Thread(target=decide, args=(index,)) for index in (1, 2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertCountEqual(outcomes, ["committed", "conflict"])

    def test_job_enqueue_claim_finish_and_result_survive_reopen(self) -> None:
        run = self.create_run()
        queued = self.store.enqueue_job(
            "job-001", run.run_id, kind="prepare", payload={"attempt": 1}
        )
        self.assertEqual(queued.status, "queued")
        claimed = self.store.claim_next_job("worker-001", lease_seconds=60, now=T0)
        self.assertIsNotNone(claimed)
        assert claimed is not None and claimed.lease_token is not None
        self.assertEqual(claimed.attempts, 1)
        finished = self.store.finish_job(
            claimed.job_id,
            worker_id="worker-001",
            lease_token=claimed.lease_token,
            succeeded=True,
            result={"preview_sha256": digest(b"preview")},
            now=T0 + timedelta(seconds=1),
        )
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(PersistentRunStore(self.root).get_job("job-001"), finished)

    def test_atomic_claim_lease_prevents_two_workers_from_claiming_one_job(self) -> None:
        run = self.create_run()
        self.store.enqueue_job("job-001", run.run_id, kind="prepare", payload={})
        stores = (SubmissionStore(self.root), SubmissionStore(self.root))
        barrier = threading.Barrier(3)
        claims = []

        def claim(index: int) -> None:
            barrier.wait()
            claims.append(stores[index].claim_next_job(f"worker-{index}", now=T0))

        threads = [threading.Thread(target=claim, args=(index,)) for index in (0, 1)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(sum(claim is not None for claim in claims), 1)

    def test_expired_lease_can_be_reclaimed_and_stale_worker_cannot_finish(self) -> None:
        run = self.create_run()
        self.store.enqueue_job("job-001", run.run_id, kind="prepare", payload={})
        first = self.store.claim_next_job("worker-old", lease_seconds=1, now=T0)
        assert first is not None and first.lease_token is not None
        second = self.store.claim_next_job(
            "worker-new", lease_seconds=60, now=T0 + timedelta(seconds=2)
        )
        assert second is not None and second.lease_token is not None
        self.assertEqual(second.attempts, 2)
        with self.assertRaises(LeaseError):
            self.store.finish_job(
                first.job_id,
                worker_id="worker-old",
                lease_token=first.lease_token,
                succeeded=True,
                now=T0 + timedelta(seconds=3),
            )
        finished = self.store.finish_job(
            second.job_id,
            worker_id="worker-new",
            lease_token=second.lease_token,
            succeeded=False,
            error="bounded fixture failure",
            now=T0 + timedelta(seconds=3),
        )
        self.assertEqual(finished.status, "failed")

    def test_idempotency_same_key_and_body_replays_exact_response(self) -> None:
        body = b'{"campaign_id":"campaign-001"}'
        first = self.store.begin_idempotent_command("create-run", "key-001", body)
        self.assertEqual(first.disposition, "new")
        pending = self.store.begin_idempotent_command("create-run", "key-001", body)
        self.assertEqual(pending.disposition, "pending")
        completed = self.store.complete_idempotent_command(
            "create-run",
            "key-001",
            body,
            response_code=201,
            response_body=b'{"run_id":"run-001"}',
        )
        replay = PersistentRunStore(self.root).begin_idempotent_command(
            "create-run", "key-001", body
        )
        self.assertTrue(completed.is_replay)
        self.assertTrue(replay.is_replay)
        self.assertEqual(replay.response_code, 201)
        self.assertEqual(replay.response_body, b'{"run_id":"run-001"}')

    def test_idempotency_same_key_with_different_body_conflicts(self) -> None:
        self.store.begin_idempotent_command("create-run", "key-001", b"body-one")
        with self.assertRaises(IdempotencyConflict):
            self.store.begin_idempotent_command("create-run", "key-001", b"body-two")
        with self.assertRaises(IdempotencyConflict):
            self.store.complete_idempotent_command(
                "create-run",
                "key-001",
                b"body-two",
                response_code=201,
                response_body=b"response",
            )

    def test_orphan_job_fails_before_enqueue(self) -> None:
        with self.assertRaises(KeyError):
            self.store.enqueue_job(
                "job-orphan", "run-missing", kind="prepare", payload={}
            )


if __name__ == "__main__":
    unittest.main()
