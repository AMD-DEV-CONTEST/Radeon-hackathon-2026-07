from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from prooflaunch_remix.gtm_learning_memory import compile_project_learning_context
from prooflaunch_remix.gtm_memory_capsule import (
    MemoryCapsuleError,
    issue_memory_capsule,
    merge_project_learning_contexts,
    verify_memory_capsule,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)
SECRET = b"portable-memory-test-secret-32-bytes-minimum"


def learning_context(memory_id: str = "learning-001", decision: str = "continue"):
    return compile_project_learning_context(
        [
            {
                "memory_id": memory_id,
                "memory_sha256": "a" * 64,
                "source_run_id": "run-001",
                "observation_id": f"observation-{memory_id}",
                "approved_at": "2026-08-02T10:00:00Z",
                "payload": {
                    "schema": "ProofLaunchPromotedLearningMemoryV1",
                    "experiment_id": "experiment-001",
                    "channel": "owned-social",
                    "evidence_class": "aggregate_observation",
                    "next_cycle_decision": decision,
                    "derived_rates": {"conversion_rate": 0.02},
                    "baseline_derived_rates": {"conversion_rate": 0.01},
                },
            }
        ]
    )


class PortableMemoryCapsuleTests(unittest.TestCase):
    def test_capsule_is_deterministic_verifiable_and_scope_bound(self) -> None:
        capsule = issue_memory_capsule(
            learning_context(),
            tenant_id="org-001",
            project_id="project-001",
            signing_secret=SECRET,
            key_id="shared-local-v1",
            issued_at=T0,
            ttl_seconds=3600,
            nonce="1" * 32,
        )
        replay = issue_memory_capsule(
            learning_context(),
            tenant_id="org-001",
            project_id="project-001",
            signing_secret=SECRET,
            key_id="shared-local-v1",
            issued_at=T0,
            ttl_seconds=3600,
            nonce="1" * 32,
        )
        self.assertEqual(capsule, replay)
        self.assertEqual(
            verify_memory_capsule(
                capsule,
                signing_secret=SECRET,
                expected_tenant_id="org-001",
                expected_project_id="project-001",
                now=T0 + timedelta(minutes=10),
            ),
            capsule,
        )
        with self.assertRaises(MemoryCapsuleError):
            verify_memory_capsule(
                capsule,
                signing_secret=SECRET,
                expected_tenant_id="org-002",
                now=T0,
            )
        with self.assertRaises(MemoryCapsuleError):
            verify_memory_capsule(
                capsule,
                signing_secret=b"another-portable-secret-that-is-long-enough",
                expected_tenant_id="org-001",
                now=T0,
            )
        with self.assertRaisesRegex(MemoryCapsuleError, "expired"):
            verify_memory_capsule(
                capsule,
                signing_secret=SECRET,
                expected_tenant_id="org-001",
                now=T0 + timedelta(hours=1),
            )

    def test_tampering_and_authority_escalation_fail_closed(self) -> None:
        capsule = issue_memory_capsule(
            learning_context(),
            tenant_id="org-001",
            project_id="project-001",
            signing_secret=SECRET,
            issued_at=T0,
            nonce="2" * 32,
        )
        for key, value in (
            ("project_id", "project-evil"),
            ("automatic_strategy_mutation_authorized", True),
            ("signature", "0" * 64),
        ):
            tampered = copy.deepcopy(capsule)
            tampered[key] = value
            with self.assertRaises(MemoryCapsuleError):
                verify_memory_capsule(
                    tampered,
                    signing_secret=SECRET,
                    expected_tenant_id="org-001",
                    now=T0,
                )

    def test_merge_deduplicates_identical_memory_and_rejects_conflict(self) -> None:
        original = learning_context()
        self.assertEqual(merge_project_learning_contexts([original, original])["memory_count"], 1)
        conflicting = learning_context(decision="stop")
        with self.assertRaisesRegex(MemoryCapsuleError, "conflicting"):
            merge_project_learning_contexts([original, conflicting])


if __name__ == "__main__":
    unittest.main()
