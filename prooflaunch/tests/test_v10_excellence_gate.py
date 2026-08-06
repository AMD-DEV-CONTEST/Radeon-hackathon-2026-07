from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_excellence_gate import (
    EvidenceFacet,
    FacetEvidence,
    evaluate_requirement,
    requirement_for,
    requirements_for_program,
)


ROOT = Path(__file__).resolve().parents[1]


class V10ExcellenceGateTests(unittest.TestCase):
    def test_every_todo_receives_a_double_standard_requirement(self) -> None:
        program = json.loads(
            (ROOT / "evidence" / "v10" / "program-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        requirements = requirements_for_program(program["todos"])
        self.assertEqual(len(requirements), 1500)
        self.assertTrue(all(item.required_facets for item in requirements))
        self.assertTrue(
            all(
                EvidenceFacet.OFFICIAL_PROGRAM_COMPLIANCE
                in item.official_floor
                and EvidenceFacet.STOP_RULE in item.required_facets
                and EvidenceFacet.ROLLBACK in item.required_facets
                and EvidenceFacet.TRUTH_BOUNDARY in item.required_facets
                and EvidenceFacet.MULTI_GPU_PROGRAM_BINDING
                in item.required_facets
                for item in requirements
            )
        )

    def test_generated_manifest_hash_binds_all_requirements(self) -> None:
        import hashlib

        payload = json.loads(
            (
                ROOT
                / "evidence"
                / "v10"
                / "double-standard-requirements.json"
            ).read_text(encoding="utf-8")
        )
        canonical = json.dumps(
            payload["requirements"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            payload["requirements_sha256"],
            hashlib.sha256(canonical).hexdigest(),
        )
        self.assertEqual(
            payload["coverage"]["todos_with_overdelivery_gate"],
            1500,
        )
        self.assertEqual(
            payload["coverage"]["todos_with_required_facets"],
            1500,
        )
        self.assertEqual(
            payload["coverage"]["todos_with_applicable_official_floor"],
            1500,
        )
        self.assertEqual(
            payload["coverage"]["todos_with_direct_submission_floor"],
            100,
        )
        self.assertEqual(
            payload["coverage"]["todos_with_multigpu_program_binding"],
            1500,
        )
        self.assertEqual(
            payload["coverage"][
                "todos_requiring_direct_multigpu_observation"
            ],
            1100,
        )
        self.assertFalse(
            payload["coverage"]["proxy_external_evidence_allowed"],
        )

    def test_training_workstream_requires_nonroutine_evidence(self) -> None:
        requirement = requirement_for("0501", 14)
        required = set(requirement.required_facets)
        for facet in (
            EvidenceFacet.DATA_RIGHTS,
            EvidenceFacet.IMMUTABLE_REVISION,
            EvidenceFacet.ABLATION,
            EvidenceFacet.NEGATIVE_CONTROL,
            EvidenceFacet.MULTI_SEED,
            EvidenceFacet.CALIBRATION,
            EvidenceFacet.MULTIMODAL_RETENTION,
            EvidenceFacet.RADEON_PERFORMANCE,
            EvidenceFacet.MULTI_GPU_RUNTIME,
            EvidenceFacet.MULTI_GPU_EQUIVALENCE,
            EvidenceFacet.MULTI_GPU_EFFICIENCY,
        ):
            self.assertIn(facet, required)

    def test_submission_workstream_requires_official_and_product_evidence(
        self,
    ) -> None:
        requirement = requirement_for("0001", 1)
        required = set(requirement.required_facets)
        for facet in (
            EvidenceFacet.OFFICIAL_ELIGIBILITY,
            EvidenceFacet.OFFICIAL_PROGRAM_COMPLIANCE,
            EvidenceFacet.ENGLISH_MATERIALS,
            EvidenceFacet.OFFICIAL_DELIVERABLES,
            EvidenceFacet.OFFICIAL_FORK_PR,
            EvidenceFacet.RADEON_LOCAL_INFERENCE,
            EvidenceFacet.CLARITY_STABILITY_DIVERSITY,
        ):
            self.assertIn(facet, required)

    def test_empty_evidence_cannot_close_a_todo(self) -> None:
        report = evaluate_requirement(requirement_for("1001", 24), ())
        self.assertFalse(report.passed)
        self.assertTrue(report.missing_facets)

    def test_proxy_cannot_satisfy_external_radeon_evidence(self) -> None:
        requirement = requirement_for("0801", 19)
        proxy = FacetEvidence(
            facet=EvidenceFacet.RADEON_PERFORMANCE,
            observed=True,
            locator="evidence/proxy.json",
            sha256="a" * 64,
            evidence_class="simulated",
            proxy=True,
        )
        report = evaluate_requirement(requirement, (proxy,))
        self.assertFalse(report.passed)
        self.assertIn(
            EvidenceFacet.RADEON_PERFORMANCE.value,
            report.rejected_proxy_facets,
        )


if __name__ == "__main__":
    unittest.main()
