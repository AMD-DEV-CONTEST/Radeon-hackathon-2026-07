from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NotebookContractTests(unittest.TestCase):
    def test_multimodal_safe_notebook_excludes_all_linear_and_towers(self) -> None:
        notebook = json.loads(
            (
                ROOT
                / "notebooks"
                / "gemma4_emotion_lora_multimodal_safe_v2.ipynb"
            ).read_text(encoding="utf-8")
        )
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        code_source = "\n".join(
            "".join(cell.get("source", []))
            for cell in notebook["cells"]
            if cell.get("cell_type") == "code"
        )
        self.assertNotIn('target_modules="all-linear"', code_source)
        self.assertIn('"language_model" in name', source)
        self.assertIn("forbidden_trainable", source)
        self.assertIn("post_visual_retention", source)
        metadata = notebook["metadata"]["prooflaunch"]
        self.assertEqual(metadata["visualRetentionCases"], 4)
        self.assertTrue(metadata["preservesOriginal"])

    def test_radeon_gate_requires_three_local_model_roles(self) -> None:
        notebook = json.loads(
            (
                ROOT / "notebooks" / "prooflaunch_radeon_gate_v4.ipynb"
            ).read_text(encoding="utf-8")
        )
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        for role in ("affect_critic", "image_generation", "image_text_scoring"):
            self.assertIn(role, source)
        self.assertIn("multimodal_retention.json", source)
        self.assertIn("HuggingFaceSigLIP2Scorer", source)
        self.assertIn("release_after_render=True", source)

    def test_v5_gate_requires_grounded_multimodal_video_path(self) -> None:
        notebook = json.loads(
            (
                ROOT / "notebooks" / "prooflaunch_radeon_gate_v5.ipynb"
            ).read_text(encoding="utf-8")
        )
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        for required in (
            "LocalQwen3VLAnalyzer",
            "LocalPDFTextExtractor",
            "ltxv-2b-0.9.8-distilled.yaml",
            "IdentityLockedVideoComposer",
            "CrossMediaReleaseGate",
            "human_release_required",
        ):
            self.assertIn(required, source)
        metadata = notebook["metadata"]["prooflaunch"]
        self.assertEqual(metadata["coResidentHeavyModels"], 1)
        self.assertEqual(metadata["maxRepairs"], 2)
        self.assertTrue(metadata["humanReleaseRequired"])

    def test_v6_gate_requires_2x_specialists_and_post_codec_gates(self) -> None:
        notebook = json.loads(
            (
                ROOT / "notebooks" / "prooflaunch_radeon_gate_v6.ipynb"
            ).read_text(encoding="utf-8")
        )
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        for required in (
            "QualityTier.COMPETITION_2X",
            "LocalGroundingDINO",
            "LocalSAM2VideoTracker",
            "LocalCLAPScorer",
            "EncodedVideoIdentityGate",
            "AudioVideoAlignmentGate",
            "publish_comparison_count",
            "assert not fixture_report.passed",
        ):
            self.assertIn(required, source)
        metadata = notebook["metadata"]["prooflaunch"]
        self.assertEqual(metadata["qualityTier"], "competition_2x")

    def test_v7_gate_requires_case_level_compiler_and_twenty_bars(self) -> None:
        notebook = json.loads(
            (
                ROOT / "notebooks" / "prooflaunch_radeon_gate_v7.ipynb"
            ).read_text(encoding="utf-8")
        )
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        for required in (
            "compile_competition_evidence",
            "benchmark_case_count",
            "video_case_count",
            "baseline-results.jsonl",
            "human-comparisons.csv",
            "seed_diversity_group_pass_rate",
            "CompetitionCaseJournal",
            "BaselineCaseJournal",
            "PHASE_ORDER",
            "RUN_CHECKPOINT_SCHEMA",
            "runner_checkpoints",
            "run_competition_2x_matrix.py",
            "run_radeon_preflight",
            "write_preflight_report",
            "ProofLaunchRadeonPreflightV2",
            "ProofLaunchModelSupplyChainV1",
            "minimum_free_disk_gb=40.0",
            'assert preflight_report["passed"]',
            "prooflaunch_recorded",
            "assert len(contract.metrics) == 20",
            "assert not contract.evaluate(uncompiled_fixture).passed",
        ):
            self.assertIn(required, source)
        metadata = notebook["metadata"]["prooflaunch"]
        self.assertEqual(metadata["schema"], "ProofLaunchRadeonGateV7")
        self.assertEqual(metadata["benchmarkCaseCount"], 450)
        self.assertEqual(metadata["requiredVideoCaseCount"], 30)
        self.assertEqual(metadata["qualityMetricCount"], 20)
        self.assertFalse(metadata["rawAggregateCertificationAllowed"])
        self.assertTrue(metadata["resumableCaseJournalRequired"])
        self.assertEqual(
            metadata["matrixRunnerSchema"],
            "ProofLaunchCompetition2XRunCheckpointV1",
        )
        self.assertTrue(metadata["phaseBatchedMatrixExecution"])
        self.assertEqual(metadata["phaseCount"], 9)
        self.assertEqual(len(metadata["specialistPhaseOrder"]), 9)
        self.assertEqual(metadata["boundedTransientRetries"], 2)
        self.assertTrue(metadata["verifiedShardMerge"])
        self.assertTrue(metadata["artifactHashBindingRequired"])
        self.assertEqual(
            metadata["preflightSchema"],
            "ProofLaunchRadeonPreflightV2",
        )
        self.assertEqual(metadata["preflightVersion"], "2.0.0")
        self.assertTrue(metadata["preflightRequired"])
        self.assertEqual(
            metadata["modelSupplyChainSchema"],
            "ProofLaunchModelSupplyChainV1",
        )
        self.assertEqual(metadata["immutableExternalModelRevisions"], 7)
        self.assertTrue(metadata["exactRevisionCacheRequired"])
        self.assertTrue(metadata["processorWeightRevisionParityRequired"])
        self.assertEqual(metadata["minimumVramGb"], 16)
        self.assertEqual(metadata["minimumFreeDiskGb"], 40)
        self.assertTrue(metadata["manifestSourceHashPreflightRequired"])
        self.assertEqual(metadata["coResidentHeavyModels"], 1)
        self.assertTrue(metadata["encodedIdentityRequired"])
        self.assertTrue(metadata["audioVideoAlignmentRequired"])
        self.assertFalse(metadata["benchmarkCertificationFromSingleFixture"])

    def test_v10_gate_requires_1500_program_training_and_measured_28_bar_gate(
        self,
    ) -> None:
        notebook = json.loads(
            (
                ROOT
                / "notebooks"
                / "prooflaunch_cortex_x_v10_radeon.ipynb"
            ).read_text(encoding="utf-8")
        )
        source = "\n".join(
            "".join(cell.get("source", [])) for cell in notebook["cells"]
        )
        for required in (
            'Path("prooflaunch-radeon-v10.tar.gz")',
            'glob("prooflaunch-radeon-v10.part-*")',
            'Path("prooflaunch-radeon-v10.sha256")',
            "CortexProgram.from_files",
            "len(program.todos) == 1500",
            "QualityTier.CORTEX_X_V10",
            "len(v10_contract.metrics) == 28",
            "default_v10_training_plan",
            "TrainingCorpusManifest",
            "corpus_audit.passed",
            "validate_tokenfactory_corpus.py",
            "validate_four_a_transfer_corpus.py",
            "north_america_4a_research_cohort_2026.json",
            'four_a_manifest["admission"]["training"] is False',
            "frontier-20-lens-v3",
            "double-standard-requirements.json",
            "ProofLaunchV10DoubleStandardRequirementsV1",
            '"todos_with_applicable_official_floor": 1500',
            '"todos_with_direct_submission_floor": 100',
            '"todos_with_overdelivery_gate": 1500',
            '"todos_with_multigpu_program_binding": 1500',
            '"todos_requiring_direct_multigpu_observation": 1100',
            '"proxy_external_evidence_allowed": False',
            "multigpu-execution-plan.json",
            "ProofLaunchV10MultiGpuExecutionPlanV1",
            '"forbidden_training_strategy"',
            '"device_map=auto"',
            "tokenfactory-output-rights.json",
            'teacher_rights["training_eligible"] is False',
            'preflight_report["passed"]',
            "cortex-x-v10-compiled-evidence.json",
            "assert v10_report.passed",
            "simulated/proxy business outcomes",
        ):
            self.assertIn(required, source)
        self.assertNotIn("prooflaunch-radeon-v7", source)
        metadata = notebook["metadata"]["prooflaunch"]
        self.assertEqual(
            metadata["schema"],
            "ProofLaunchCortexXV10RadeonGate",
        )
        self.assertEqual(metadata["todoCount"], 1500)
        self.assertEqual(metadata["workstreamCount"], 36)
        self.assertEqual(metadata["breakthroughBetCount"], 12)
        self.assertEqual(metadata["requiredPromotedBreakthroughs"], 3)
        self.assertEqual(metadata["qualityMetricCount"], 28)
        self.assertEqual(metadata["trainingStageCount"], 6)
        self.assertEqual(metadata["teacherCorpusStageCount"], 9)
        self.assertEqual(metadata["fourATransferStageCount"], 4)
        self.assertEqual(metadata["fourAReferenceAgencyCount"], 10)
        self.assertEqual(metadata["fourAFullyDistilledCaseCount"], 13)
        self.assertEqual(metadata["doubleStandardRequirementCount"], 1500)
        self.assertTrue(metadata["officialFloorAndOverdeliveryRequired"])
        self.assertFalse(metadata["proxyExternalEvidenceAllowed"])
        self.assertEqual(metadata["multiGpuPlanTodoCount"], 1500)
        self.assertEqual(metadata["multiGpuProgramBindingCount"], 1500)
        self.assertEqual(
            metadata["directMultiGpuObservationTodoCount"],
            1100,
        )
        self.assertTrue(metadata["multiGpuRequiredForCompute"])
        self.assertFalse(metadata["allowedSilentSingleGpuFallback"])
        self.assertEqual(
            metadata["multiGpuTrainingStrategyOrder"],
            ["ddp", "fsdp2"],
        )
        self.assertEqual(
            metadata["teacherCorpusQualityProtocol"],
            "frontier-20-lens-v3",
        )
        self.assertEqual(
            metadata["teacherOutputRightsStatus"],
            "rights_review_required",
        )
        self.assertFalse(metadata["teacherOutputTrainingEligible"])
        self.assertEqual(metadata["judgeHumanLabelMinimum"], 100)
        self.assertEqual(
            metadata["archiveName"],
            "prooflaunch-radeon-v10.tar.gz",
        )
        self.assertEqual(
            metadata["archivePartsGlob"],
            "prooflaunch-radeon-v10.part-*",
        )
        self.assertEqual(
            metadata["archiveChecksumName"],
            "prooflaunch-radeon-v10.sha256",
        )
        self.assertTrue(metadata["singleSupervisorStateOwner"])
        self.assertEqual(
            metadata["trainingPlanSchema"],
            "ProofLaunchTrainingPlanMultiGpuV10",
        )
        self.assertEqual(metadata["minimumTrainingWorldSize"], 2)
        self.assertEqual(metadata["preferredTrainingWorldSize"], 4)
        self.assertTrue(metadata["singleRadeonBaselineRequired"])
        self.assertFalse(metadata["singleRadeonMayPromote"])
        self.assertEqual(metadata["maxResidentHeavyModelsPerRank"], 1)
        self.assertFalse(metadata["prefilledV10MetricsAllowed"])

    def test_v10_gate_has_official_first_secret_free_external_route(self) -> None:
        notebook = json.loads(
            (
                ROOT
                / "notebooks"
                / "prooflaunch_cortex_x_v10_radeon.ipynb"
            ).read_text(encoding="utf-8")
        )
        serialized = json.dumps(notebook, ensure_ascii=False)
        self.assertIn("TOKEN_FACTORY_API_KEY_ENV", serialized)
        self.assertIn(
            "https://developer.amd.com.cn/radeon/api/v1/chat/completions",
            serialized,
        )
        self.assertIn("fireworks-fallback.example.json", serialized)
        self.assertIn("competition_core_eligible", serialized)
        self.assertIn("response_content_sha256", serialized)
        self.assertNotIn("Bearer sk-", serialized)
        metadata = notebook["metadata"]["prooflaunch"]
        self.assertEqual(
            metadata["externalInferencePriority"],
            [
                "amd_radeon_token_factory",
                "approved_fireworks_fallback",
            ],
        )
        self.assertFalse(metadata["externalInferenceCompetitionCoreEligible"])
        self.assertFalse(metadata["externalInferenceSecretPersistenceAllowed"])


if __name__ == "__main__":
    unittest.main()
