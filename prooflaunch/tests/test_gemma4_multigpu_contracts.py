from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Gemma4MultigpuContractTests(unittest.TestCase):
    def test_v3_notebook_is_strict_and_multimodal_safe(self) -> None:
        path = (
            ROOT
            / "notebooks"
            / "gemma4_emotion_lora_multimodal_safe_v3.ipynb"
        )
        notebook = json.loads(path.read_text(encoding="utf-8"))
        source = "\n".join(
            "".join(cell.get("source", []))
            if isinstance(cell.get("source", []), list)
            else str(cell.get("source", ""))
            for cell in notebook["cells"]
        )
        code_source = "\n".join(
            "".join(cell.get("source", []))
            if isinstance(cell.get("source", []), list)
            else str(cell.get("source", ""))
            for cell in notebook["cells"]
            if cell.get("cell_type") == "code"
        )
        self.assertNotIn("\x08", source)
        self.assertIn("AutoModelForMultimodalLM", source)
        self.assertIn("normalized if normalized in VALID_LABELS", source)
        self.assertIn("TEXT_LORA_PROJECTION_PATTERN", source)
        self.assertNotIn('target_modules="all-linear"', code_source)
        self.assertIn("frozen_modality_fingerprints", source)
        self.assertIn('split="validation"', source)
        self.assertIn("final_test_metrics", source)
        self.assertIn("PROOFLAUNCH_GEMMA_MODEL_REVISION", source)
        self.assertIn("PROOFLAUNCH_GEMMA_DATASET_REVISION", source)
        self.assertIn(
            "Final profile requires immutable model and dataset revisions",
            source,
        )
        metadata = notebook["metadata"]["prooflaunch"]
        self.assertEqual(
            metadata["schema"],
            "ProofLaunchMultimodalSafeGemmaNotebookV3",
        )
        self.assertTrue(metadata["strictExactLabelScoring"])
        self.assertTrue(metadata["positiveTextProjectionAllowlist"])
        self.assertTrue(metadata["frozenModalityFingerprintRequired"])
        self.assertTrue(metadata["testUsedOnceAfterSelection"])
        self.assertTrue(metadata["immutableRevisionsRequiredForFinal"])
        self.assertFalse(metadata["deviceMapTrainingAllowed"])
        self.assertTrue(metadata["globalBatchInvariantRequired"])
        self.assertTrue(metadata["everyRankReceiptRequired"])
        self.assertEqual(
            metadata["multiGpuAdmissionScript"],
            "scripts/verify_multigpu_training_admission.py",
        )

    def test_distributed_trainer_has_no_device_map_keyword(self) -> None:
        path = ROOT / "scripts" / "train_gemma4_emotion_multigpu.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        keywords = {
            keyword.arg
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg is not None
        }
        self.assertNotIn("device_map", keywords)
        source = path.read_text(encoding="utf-8")
        self.assertIn("AutoModelForMultimodalLM", source)
        self.assertIn("TEXT_LORA_PATTERN", source)
        self.assertIn("test_used_during_training", source)
        self.assertIn("expected-world-size", source)
        self.assertIn("expected-global-batch-size", source)
        self.assertIn("RUN_PROFILES", source)
        self.assertIn("distributed-ranks", source)
        self.assertIn("training_complete", source)
        self.assertIn("final_validation_metrics", source)
        self.assertIn("os.replace", source)
        self.assertIn("torch.version.hip", source)

    def test_accelerate_profiles_match_declared_world_sizes(self) -> None:
        ddp2 = (
            ROOT / "configs" / "accelerate" / "rocm_2gpu_ddp.yaml"
        ).read_text(encoding="utf-8")
        ddp4 = (
            ROOT / "configs" / "accelerate" / "rocm_4gpu_ddp.yaml"
        ).read_text(encoding="utf-8")
        fsdp2 = (
            ROOT / "configs" / "accelerate" / "rocm_2gpu_fsdp2.yaml"
        ).read_text(encoding="utf-8")
        single = (
            ROOT
            / "configs"
            / "accelerate"
            / "rocm_1gpu_baseline.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn('distributed_type: "NO"', single)
        self.assertIn("num_processes: 1", single)
        self.assertIn("distributed_type: MULTI_GPU", ddp2)
        self.assertIn("num_processes: 2", ddp2)
        self.assertIn("num_processes: 4", ddp4)
        self.assertIn("distributed_type: FSDP", fsdp2)
        self.assertIn("fsdp_version: 2", fsdp2)
        self.assertNotIn("fsdp_use_orig_params", fsdp2)
        self.assertIn(
            "fsdp_transformer_layer_cls_to_wrap: Gemma4TextDecoderLayer",
            fsdp2,
        )
        admission = (
            ROOT / "scripts" / "verify_multigpu_training_admission.py"
        ).read_text(encoding="utf-8")
        for required in (
            "comparison_contract_drift",
            "insufficient_multi_gpu_repeats",
            "speedup_below_floor",
            "parallel_efficiency_below_floor",
            "eval_loss_regression",
            "training_complete",
        ):
            self.assertIn(required, admission)

    def test_rocm_preflight_requires_collective_success(self) -> None:
        source = (
            ROOT / "scripts" / "verify_rocm_multigpu.py"
        ).read_text(encoding="utf-8")
        self.assertIn("torch.version.hip", source)
        self.assertIn('init_process_group(backend="nccl")', source)
        self.assertIn("all_reduce", source)
        self.assertIn("RCCL all-reduce preflight failed", source)


if __name__ == "__main__":
    unittest.main()
