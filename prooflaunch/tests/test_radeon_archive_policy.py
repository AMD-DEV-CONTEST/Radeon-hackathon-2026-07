from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from prooflaunch_remix.v10_final_lock import source_paths
from prooflaunch_remix.v10_todo_evidence import CLOSURE_DEFINITIONS


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_radeon_archive.py"
SPEC = importlib.util.spec_from_file_location("build_radeon_archive", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RadeonArchivePolicyTests(unittest.TestCase):
    def test_machine_local_runtime_is_never_publicly_archived(self) -> None:
        private_candidates = (
            ROOT
            / ".prooflaunch-runtime"
            / "judge-calibration-source"
            / "private_predictions.jsonl",
            ROOT
            / ".prooflaunch-runtime"
            / "judge-calibration"
            / "private"
            / "reviewer_assignments.json",
            ROOT
            / ".prooflaunch-runtime"
            / "submission-api"
            / "state.json",
            ROOT
            / ".prooflaunch-secrets"
            / "blind-review-invitations.json",
            ROOT
            / ".super-site-10x"
            / "outputs"
            / "run"
            / "messages"
            / "prompt.txt",
        )
        with patch.object(Path, "is_file", return_value=True):
            for candidate in private_candidates:
                with self.subTest(candidate=candidate):
                    self.assertFalse(MODULE.should_include(candidate, "v10"))

    def test_only_explicit_public_root_hidden_directory_is_archived(self) -> None:
        public_workflow = ROOT / ".github" / "workflows" / "quality.yml"
        private_unknown = ROOT / ".future-private-state" / "secret.json"
        with patch.object(Path, "is_file", return_value=True):
            self.assertTrue(MODULE.should_include(public_workflow, "v10"))
            self.assertFalse(MODULE.should_include(private_unknown, "v10"))

    def test_private_tokenfactory_outputs_are_never_publicly_archived(
        self,
    ) -> None:
        candidate = (
            ROOT
            / "data"
            / "tokenfactory_teacher_v10"
            / "architect"
            / "0001-0002.json"
        )
        with patch.object(Path, "is_file", return_value=True):
            self.assertFalse(MODULE.should_include(candidate, "v10"))

    def test_redacted_rights_audit_is_included_in_v10_archive(self) -> None:
        candidate = (
            ROOT
            / "evidence"
            / "v10"
            / "tokenfactory-output-rights.json"
        )
        self.assertTrue(candidate.is_file())
        self.assertTrue(MODULE.should_include(candidate, "v10"))
        for relative in (
            "evidence/v10/double-standard-requirements.json",
            "evidence/v10/multigpu-execution-plan.json",
            "evidence/v10/source-reconciliation-300-plus-1200.json",
            "evidence/v10/frontier-free-api-sprint.json",
            "evidence/v10/submission-api-mechanical-fixture.json",
            "evidence/v10/submission-flow-preflight.json",
            "evidence/v10/competition-contract-v3-mechanical-fixture.json",
            "docs/COMPETITION_CONTRACT_V3.md",
            "evidence/v10/reuse-manifest-v1-mechanical-fixture.json",
            "docs/REUSE_MANIFEST_V1.md",
            "config/cortex_x_v10_reuse_manifest_v1.json",
            "evidence/v10/research-ledger-v1-mechanical-fixture.json",
            "docs/RESEARCH_LEDGER_V1.md",
            "config/cortex_x_v10_research_ledger_v1.json",
            "evidence/v10/distillation-stack-v1-mechanical-fixture.json",
            "docs/DISTILLATION_STACK_V1.md",
            "config/cortex_x_v10_distillation_stack_v1.json",
            "evidence/v10/world-model-v1-mechanical-fixture.json",
            "docs/CAMPAIGN_WORLD_MODEL_V1.md",
            "config/cortex_x_v10_world_model_v1.json",
            "evidence/v10/dynamic-topology-v1-mechanical-fixture.json",
            "docs/DYNAMIC_TOPOLOGY_V1.md",
            "config/cortex_x_v10_dynamic_topology_v1.json",
            "evidence/v10/open-materials-v1-audit.json",
            "docs/OPEN_MATERIALS_V1.md",
            "data/v10_open_materials/manifest.json",
            "data/v10_open_materials/sources.jsonl",
            "evidence/v10/source-bundle-2000-audit.json",
            "evidence/v10/cpt-corpus-independent-recount.json",
            "evidence/v10/sft-corpus-15k-independent-audit.json",
            "evidence/v10/preference-pairs-5k-independent-audit.json",
            "evidence/v10/region-preferences-2k-independent-audit.json",
            "evidence/v10/agency-trajectories-1000-independent-replay.json",
            "evidence/v10/repair-episodes-500-independent-audit.json",
            "evidence/v10/gold-candidates-independent-audit.json",
            "evidence/v10/gold-five-human-review-gate.json",
            "evidence/v10/agency-corpus-v2-dataset-card-audit.json",
            "docs/AGENCY_SOURCE_BUNDLE_V2.md",
            "data/v10_source_bundle/manifest.json",
            "data/v10_source_bundle/sources.jsonl",
            "data/v10_trajectory_kd/execution_skill_examples.jsonl",
            "research/negative_experiments/manifest.json",
            "upstream_patches/manifest.json",
            "evidence/RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json",
            "docs/ProofLaunch_Project_Profile.pdf",
            "docs/ProofLaunch_Poster.pptx",
            "docs/ProofLaunch_Submission_Deck.pptx",
            "notebooks/gemma4_emotion_lora_multimodal_safe_v3.ipynb",
        ):
            artifact = ROOT / relative
            self.assertTrue(artifact.is_file())
            self.assertTrue(MODULE.should_include(artifact, "v10"))

    def test_v10_archive_contains_every_final_locked_source_and_closure_artifact(self) -> None:
        omitted_sources = [
            path.relative_to(ROOT).as_posix()
            for path in source_paths(ROOT)
            if not MODULE.should_include(path, "v10")
        ]
        self.assertEqual(omitted_sources, [])
        omitted_closure_artifacts = sorted(
            {
                definition.implementation_path
                for definition in CLOSURE_DEFINITIONS
                if not MODULE.should_include(ROOT / definition.implementation_path, "v10")
            }
        )
        self.assertEqual(omitted_closure_artifacts, [])

    def test_v10_archive_excludes_raw_tokenfactory_panel_outputs_but_keeps_receipt(self) -> None:
        panel = ROOT / "evidence" / "v10" / "tokenfactory-final-panel"
        for artifact in panel.glob("*.json"):
            expected = artifact.name == "receipt.json"
            self.assertEqual(MODULE.should_include(artifact, "v10"), expected)

    def test_every_product_readiness_required_file_is_portable(self) -> None:
        readiness = json.loads(
            (ROOT / "evidence/v10/aug3-product-readiness.json").read_text(
                encoding="utf-8"
            )
        )
        omitted = [
            relative
            for relative in readiness["required_file_sha256"]
            if not MODULE.should_include(ROOT / relative, "v10")
        ]
        self.assertEqual(omitted, [])

    def test_owner_only_private_manifest_mode_is_preserved(self) -> None:
        private_manifest = (
            ROOT
            / "artifacts/local-gtm-creative-benchmark-v5"
            / "portfolio-blind-review-v1"
            / "portfolio-blind-review-private.json"
        )
        self.assertEqual(MODULE.normalized_tarinfo(private_manifest, "x").mode, 0o600)

    def test_large_archive_parts_use_fixed_width_lexically_safe_names(self) -> None:
        names = [
            MODULE.part_filename("v10", index, 9_631)
            for index in (0, 9, 10, 99, 100, 999, 1000, 9630)
        ]
        self.assertEqual(names, sorted(names))
        self.assertEqual(names[0], "prooflaunch-radeon-v10.part-0000")
        self.assertEqual(names[-1], "prooflaunch-radeon-v10.part-9630")


if __name__ == "__main__":
    unittest.main()
