from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.competition_benchmark import (
    DeclaredBaseline,
    ProductSpec,
    build_frozen_manifest,
)
from prooflaunch_remix.radeon_preflight import (
    CHECK_BLOCKED,
    CHECK_PASSED,
    CHECK_WARNING,
    DEPENDENCY_MINIMUMS,
    PREFLIGHT_SCHEMA,
    run_radeon_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeProbe:
    def __init__(
        self,
        *,
        model_revisions: dict[str, set[str]],
    ) -> None:
        self.model_revisions = model_revisions
        self.runtime_payload: dict[str, object] = {
            "torch_version": "2.7.1+rocm6.4",
            "cuda_available": True,
            "device_count": 1,
            "hip_version": "6.4",
            "device_name": "AMD Radeon PRO W7900",
            "total_vram_gb": 48.0,
        }
        self.free_gb = 500.0
        self.ffmpeg: Path | None = None

    def dependency_versions(self, distributions):
        return {distribution: "99.0.0" for distribution in distributions}

    def runtime(self):
        return dict(self.runtime_payload)

    def free_disk_gb(self, path):
        del path
        return self.free_gb

    def ffmpeg_path(self):
        if self.ffmpeg is None:
            raise RuntimeError("test FFmpeg path was not configured")
        return str(self.ffmpeg)

    def cached_model_revisions(self):
        return {
            repo_id: set(revisions)
            for repo_id, revisions in self.model_revisions.items()
        }


class RadeonPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        config_dir = self.root / "config"
        config_dir.mkdir()
        settings = json.loads(
            (ROOT / "config" / "radeon_matrix_adapter.json").read_text(
                encoding="utf-8"
            )
        )
        settings.update(
            {
                "gemma_base_model_path": "models/gemma-base",
                "gemma_adapter_path": "models/gemma-safe-lora",
                "gemma_retention_path": (
                    "models/gemma-safe-lora/multimodal_retention.json"
                ),
            }
        )
        self.settings_path = config_dir / "radeon.json"
        self.settings_path.write_text(
            json.dumps(settings, sort_keys=True),
            encoding="utf-8",
        )
        self.required_model_revisions = {
            settings["qwen_model_id"]: {settings["qwen_model_revision"]},
            settings["grounding_dino_model_id"]: {
                settings["grounding_dino_model_revision"]
            },
            settings["image_model_id"]: {settings["image_model_revision"]},
            settings["siglip_model_id"]: {settings["siglip_model_revision"]},
            settings["ltx_model_id"]: {settings["ltx_model_revision"]},
            settings["sam2_model_id"]: {settings["sam2_model_revision"]},
            settings["clap_model_id"]: {settings["clap_model_revision"]},
        }
        base_dir = self.root / "models" / "gemma-base"
        base_dir.mkdir(parents=True)
        (base_dir / "config.json").write_text("{}", encoding="utf-8")
        (base_dir / "model-00001-of-00001.safetensors").write_bytes(b"base")
        self.lora_dir = self.root / "models" / "gemma-safe-lora"
        self.lora_dir.mkdir(parents=True)
        (self.lora_dir / "adapter_config.json").write_text(
            "{}",
            encoding="utf-8",
        )
        (self.lora_dir / "adapter_model.safetensors").write_bytes(b"lora")
        self.retention_path = self.lora_dir / "multimodal_retention.json"
        self._write_retention(post_accuracy=0.89)

        self.benchmark_dir = self.root / "benchmark"
        input_dir = self.benchmark_dir / "inputs"
        input_dir.mkdir(parents=True)
        products = []
        for index in range(30):
            source = input_dir / f"product-{index:02d}.bin"
            source.write_bytes(f"owned-product-{index}".encode("utf-8"))
            products.append(
                ProductSpec(
                    product_id=f"product-{index:02d}",
                    input_sha256=file_sha(source),
                    rights="owned",
                    source_locator=source.relative_to(
                        self.benchmark_dir
                    ).as_posix(),
                )
            )
        baseline_path = self.benchmark_dir / "baseline-settings.json"
        baseline_path.write_text(
            json.dumps({"system": "frozen-one-shot"}, sort_keys=True),
            encoding="utf-8",
        )
        manifest = build_frozen_manifest(
            benchmark_id="prooflaunch-preflight-test",
            protocol_sha256=hashlib.sha256(b"protocol").hexdigest(),
            prooflaunch_build_sha256=hashlib.sha256(b"build").hexdigest(),
            baseline=DeclaredBaseline(
                name="Frozen One-Shot Ablation",
                version="1.0.0",
                settings_sha256=file_sha(baseline_path),
                source_locator=baseline_path.relative_to(
                    self.benchmark_dir
                ).as_posix(),
            ),
            products=products,
        )
        self.manifest_path = self.benchmark_dir / "manifest.json"
        self.manifest_path.write_text(
            json.dumps(manifest.to_dict(), sort_keys=True),
            encoding="utf-8",
        )
        self.probe = FakeProbe(
            model_revisions=self.required_model_revisions,
        )
        self.probe.ffmpeg = self.root / "ffmpeg"
        self.probe.ffmpeg.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.probe.ffmpeg.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_retention(self, *, post_accuracy: float) -> None:
        self.retention_path.write_text(
            json.dumps(
                {
                    "pre_accuracy": 0.90,
                    "post_accuracy": post_accuracy,
                    "minimum_post_accuracy": 0.85,
                    "maximum_allowed_drop": 0.03,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _checks(report):
        return {item["check_id"]: item for item in report["checks"]}

    def _run(self, **overrides):
        arguments = {
            "settings_path": self.settings_path,
            "manifest_path": self.manifest_path,
            "strict_cache": True,
            "probe": self.probe,
        }
        arguments.update(overrides)
        return run_radeon_preflight(**arguments)

    def test_complete_environment_and_frozen_sources_pass(self) -> None:
        report = self._run()
        checks = self._checks(report)
        self.assertEqual(report["schema"], PREFLIGHT_SCHEMA)
        self.assertTrue(report["passed"])
        self.assertEqual(report["blocker_count"], 0)
        self.assertEqual(report["warning_count"], 0)
        self.assertTrue(
            all(check["status"] == CHECK_PASSED for check in checks.values())
        )
        self.assertEqual(
            checks["frozen_manifest"]["details"]["case_count"],
            450,
        )
        self.assertEqual(
            checks["frozen_manifest"]["details"]["video_case_count"],
            30,
        )
        self.assertEqual(
            checks["frozen_manifest"]["details"][
                "verified_product_source_count"
            ],
            30,
        )
        self.assertEqual(
            set(checks["python_dependencies"]["details"]["minimums"]),
            set(DEPENDENCY_MINIMUMS),
        )

    def test_missing_hip_or_low_vram_blocks_execution(self) -> None:
        self.probe.runtime_payload["hip_version"] = None
        report = self._run()
        self.assertFalse(report["passed"])
        self.assertEqual(
            self._checks(report)["rocm_runtime"]["status"],
            CHECK_BLOCKED,
        )
        self.probe.runtime_payload["hip_version"] = "6.4"
        self.probe.runtime_payload["total_vram_gb"] = 15.9
        report = self._run()
        self.assertEqual(
            self._checks(report)["rocm_runtime"]["status"],
            CHECK_BLOCKED,
        )

    def test_cache_miss_warns_online_but_blocks_strict_mode(self) -> None:
        repo_id = next(iter(self.probe.model_revisions))
        self.probe.model_revisions[repo_id] = {"0" * 40}
        advisory = self._run(strict_cache=False)
        strict = self._run(strict_cache=True)
        self.assertTrue(advisory["passed"])
        self.assertEqual(advisory["warning_count"], 1)
        self.assertEqual(
            self._checks(advisory)["huggingface_model_cache"]["status"],
            CHECK_WARNING,
        )
        self.assertFalse(strict["passed"])
        self.assertEqual(
            self._checks(strict)["huggingface_model_cache"]["status"],
            CHECK_BLOCKED,
        )
        missing = self._checks(strict)["huggingface_model_cache"]["details"][
            "missing_models"
        ]
        self.assertEqual(missing[0]["reason"], "exact_revision_not_cached")

    def test_license_metadata_tamper_blocks_supply_chain(self) -> None:
        settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        settings["ltx_model_license"] = "apache-2.0"
        self.settings_path.write_text(
            json.dumps(settings, sort_keys=True),
            encoding="utf-8",
        )
        report = self._run()
        check = self._checks(report)["model_supply_chain_lock"]
        self.assertFalse(report["passed"])
        self.assertEqual(check["status"], CHECK_BLOCKED)
        self.assertEqual(check["details"]["mismatches"][0]["role"], "video")
        self.assertIn(
            "license",
            check["details"]["mismatches"][0]["differences"],
        )

    def test_failed_gemma_retention_gate_blocks_execution(self) -> None:
        self._write_retention(post_accuracy=0.80)
        report = self._run()
        check = self._checks(report)["gemma_safe_lora"]
        self.assertFalse(report["passed"])
        self.assertEqual(check["status"], CHECK_BLOCKED)
        self.assertIn("failed its frozen gate", check["details"]["error"])

    def test_manifest_source_tamper_blocks_submission_readiness(self) -> None:
        source = self.benchmark_dir / "inputs" / "product-00.bin"
        source.write_bytes(b"tampered-after-freeze")
        report = self._run()
        check = self._checks(report)["frozen_manifest"]
        self.assertFalse(report["passed"])
        self.assertEqual(check["status"], CHECK_BLOCKED)
        self.assertIn("source hash mismatch", check["details"]["error"])

    def test_manifest_omission_is_explicit_warning(self) -> None:
        report = self._run(manifest_path=None)
        check = self._checks(report)["frozen_manifest"]
        self.assertTrue(report["passed"])
        self.assertEqual(check["status"], CHECK_WARNING)
        self.assertEqual(report["warning_count"], 1)


if __name__ == "__main__":
    unittest.main()
