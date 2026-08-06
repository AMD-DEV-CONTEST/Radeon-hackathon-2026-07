from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prooflaunch_remix.benchmark_runner import (
    PHASE_ORDER,
    ArtifactOutput,
    BenchmarkPhase,
    BenchmarkRunnerError,
    CompetitionMatrixRunner,
    StillAudit,
    TransientActivityError,
    VideoAudit,
    merge_sharded_results,
)
from prooflaunch_remix.competition_benchmark import (
    DeclaredBaseline,
    ProductSpec,
    _load_case_results,
    build_frozen_manifest,
)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeRadeonAdapter:
    def __init__(
        self,
        *,
        transient_case: str | None = None,
        permanent_case: str | None = None,
        crash_case: str | None = None,
        with_sidecars: bool = False,
    ) -> None:
        self.transient_case = transient_case
        self.permanent_case = permanent_case
        self.crash_case = crash_case
        self.with_sidecars = with_sidecars
        self.transient_failures = 0
        self.crashed_once = False
        self.active_phase: BenchmarkPhase | None = None
        self.loaded: list[BenchmarkPhase] = []
        self.released: list[BenchmarkPhase] = []
        self.calls: dict[str, int] = {}

    def _called(self, key: str) -> None:
        self.calls[key] = self.calls.get(key, 0) + 1

    def identity(self) -> dict:
        return {
            "adapter_id": "fake-radeon-local",
            "version": "1.0.0",
            "settings_sha256": "a" * 64,
            "system_kind": "prooflaunch",
            "uses_closed_online_api": False,
        }

    def load_phase(self, phase: BenchmarkPhase) -> dict:
        if self.active_phase is not None:
            raise AssertionError("two heavy phases are resident")
        self.active_phase = phase
        self.loaded.append(phase)
        return {"model_ref": f"fake/{phase.value}:1"}

    def release_phase(self, phase: BenchmarkPhase) -> None:
        if self.active_phase != phase:
            raise AssertionError("released the wrong phase")
        self.released.append(phase)
        self.active_phase = None

    def prepare_product(self, product, source_path: Path) -> dict:
        self._called(f"prepare:{product.product_id}")
        return {"source_sha256": file_sha(source_path)}

    def understand_product(self, product, prepared) -> dict:
        self._called(f"understand:{product.product_id}")
        return {"product_id": product.product_id, "prepared": dict(prepared)}

    def ground_product(self, product, prepared, understanding) -> dict:
        del prepared, understanding
        self._called(f"ground:{product.product_id}")
        return {
            "product_box_xyxy": [2.0, 2.0, 14.0, 14.0],
            "model_ref": "fake/grounding-dino:1",
        }

    def plan_product(self, product, prepared, understanding, grounding) -> dict:
        del prepared, understanding, grounding
        self._called(f"plan:{product.product_id}")
        return {
            "headline": f"{product.product_id} launch",
            "visual_direction": "evidence-led studio launch",
            "target_emotion": "joy",
            "model_ref": "fake/gemma-emotion:1",
        }

    def generate_still(
        self,
        case,
        product,
        understanding,
        grounding,
        plan,
        output_path: Path,
    ) -> ArtifactOutput:
        del product, understanding, grounding, plan
        key = f"generate_still:{case.case_id}"
        self._called(key)
        if case.case_id == self.crash_case and not self.crashed_once:
            self.crashed_once = True
            raise KeyboardInterrupt("simulated process interruption")
        if case.case_id == self.permanent_case:
            raise RuntimeError("invalid local model configuration")
        if case.case_id == self.transient_case and self.transient_failures < 2:
            self.transient_failures += 1
            raise TransientActivityError("temporary ROCm allocation failure")
        Image.new(
            "RGB",
            (16, 16),
            (case.seed % 251, len(case.aspect_ratio) * 20, 90),
        ).save(output_path)
        sidecars = ()
        if self.with_sidecars:
            sidecar = output_path.with_suffix(".selection.json")
            sidecar.write_text(
                json.dumps({"case_id": case.case_id, "seed": case.seed}),
                encoding="utf-8",
            )
            sidecars = (sidecar,)
        return ArtifactOutput(
            path=output_path,
            model_ref="fake/sdxl-local:1",
            peak_vram_gb=12.0,
            metadata={"seed": case.seed},
            sidecars=sidecars,
        )

    def audit_still(
        self,
        case,
        product,
        understanding,
        grounding,
        plan,
        still,
    ) -> StillAudit:
        del product, understanding, grounding, plan, still
        self._called(f"audit_still:{case.case_id}")
        return StillAudit(
            repairs=1,
            unsupported_claim_count=0,
            observation_count=3,
            located_observation_count=3,
            image_identity_pass=True,
            cross_media_pass=True,
            peak_vram_gb=5.0,
        )

    def generate_video(
        self,
        case,
        product,
        understanding,
        grounding,
        plan,
        still,
        output_path: Path,
    ) -> ArtifactOutput:
        del product, understanding, grounding, plan, still
        self._called(f"generate_video:{case.case_id}")
        output_path.write_bytes(f"video:{case.case_id}".encode("utf-8"))
        return ArtifactOutput(
            path=output_path,
            model_ref="fake/ltx-video-local:1",
            peak_vram_gb=18.0,
            metadata={"seed": case.seed},
        )

    def track_video(self, case, product, grounding, still, video) -> dict:
        del product, grounding, still, video
        self._called(f"track_video:{case.case_id}")
        return {
            "passed": True,
            "frame_coverage": 1.0,
            "nonempty_mask_rate": 1.0,
            "model_ref": "fake/sam2:1",
        }

    def audit_video(
        self,
        case,
        product,
        understanding,
        grounding,
        plan,
        still,
        video,
        tracking,
    ) -> VideoAudit:
        del product, understanding, grounding, plan, still, video, tracking
        self._called(f"audit_video:{case.case_id}")
        return VideoAudit(
            preencode_video_identity_pass=True,
            encoded_video_identity_pass=True,
            audio_video_alignment_pass=True,
            cross_media_pass=True,
            peak_vram_gb=6.0,
        )


class CompetitionMatrixRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        input_dir = self.root / "inputs"
        input_dir.mkdir()
        products = []
        for index in range(30):
            source = input_dir / f"product-{index:02d}.bin"
            source.write_bytes(f"owned-product-{index:02d}".encode("utf-8"))
            products.append(
                ProductSpec(
                    product_id=f"product-{index:02d}",
                    input_sha256=file_sha(source),
                    rights="owned",
                    source_locator=f"inputs/{source.name}",
                )
            )
        self.manifest = build_frozen_manifest(
            benchmark_id="runner-test",
            protocol_sha256="b" * 64,
            prooflaunch_build_sha256="c" * 64,
            baseline=DeclaredBaseline(
                name="Frozen Baseline",
                version="1.0",
                settings_sha256="d" * 64,
                source_locator="baseline/settings.json",
            ),
            products=products,
        )
        self.manifest_path = self.root / "manifest.json"
        self.manifest_path.write_text(
            json.dumps(self.manifest.to_dict(), sort_keys=True),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def runner(
        self,
        adapter: FakeRadeonAdapter,
        *,
        run_name: str,
        shard_index: int = 0,
        shard_count: int = 450,
        resume: bool = False,
        max_retries: int = 2,
    ) -> CompetitionMatrixRunner:
        return CompetitionMatrixRunner(
            manifest_path=self.manifest_path,
            run_dir=self.root / run_name,
            adapter=adapter,
            resume=resume,
            shard_index=shard_index,
            shard_count=shard_count,
            max_retries=max_retries,
            sleeper=lambda _: None,
        )

    def test_phase_order_is_deterministic_and_models_never_co_reside(self) -> None:
        adapter = FakeRadeonAdapter()
        runner = self.runner(adapter, run_name="phase-order", shard_index=10)
        summary = runner.run()
        self.assertEqual(adapter.loaded, list(PHASE_ORDER))
        self.assertEqual(adapter.released, list(PHASE_ORDER))
        self.assertIsNone(adapter.active_phase)
        self.assertEqual(summary["selected_case_count"], 1)
        self.assertEqual(summary["video_case_count"], 1)
        self.assertEqual(summary["finalized_case_count"], 1)

    def test_resume_does_not_repeat_successful_activity(self) -> None:
        first_adapter = FakeRadeonAdapter()
        self.runner(first_adapter, run_name="resume").run()
        first_calls = dict(first_adapter.calls)
        second_adapter = FakeRadeonAdapter()
        summary = self.runner(
            second_adapter,
            run_name="resume",
            resume=True,
        ).run()
        self.assertTrue(first_calls)
        self.assertEqual(second_adapter.calls, {})
        self.assertEqual(second_adapter.loaded, [])
        self.assertEqual(summary["finalized_case_count"], 1)

    def test_resume_rejects_tampered_product_input(self) -> None:
        adapter = FakeRadeonAdapter()
        runner = self.runner(adapter, run_name="tampered-input")
        runner.run()
        product = runner.product_by_id[runner.cases[0].product_id]
        source = self.manifest_path.parent / product.source_locator
        source.write_bytes(b"tampered-owned-product")
        with self.assertRaisesRegex(
            BenchmarkRunnerError,
            "product input hash mismatch",
        ):
            self.runner(
                FakeRadeonAdapter(),
                run_name="tampered-input",
                resume=True,
            )

    def test_resume_rejects_tampered_artifact_sidecar(self) -> None:
        adapter = FakeRadeonAdapter(with_sidecars=True)
        runner = self.runner(adapter, run_name="tampered-sidecar")
        runner.run()
        case = runner.cases[0]
        sidecar = (
            runner.run_dir
            / "artifacts"
            / "stills"
            / f"{case.case_id}.selection.json"
        )
        sidecar.write_text('{"tampered":true}', encoding="utf-8")
        with self.assertRaisesRegex(
            BenchmarkRunnerError,
            "sidecar 0 hash mismatch",
        ):
            self.runner(
                FakeRadeonAdapter(with_sidecars=True),
                run_name="tampered-sidecar",
                resume=True,
            )

    def test_transient_activity_retries_twice_then_succeeds(self) -> None:
        case = self.manifest.cases[0]
        adapter = FakeRadeonAdapter(transient_case=case.case_id)
        summary = self.runner(adapter, run_name="transient").run()
        self.assertEqual(
            adapter.calls[f"generate_still:{case.case_id}"],
            3,
        )
        self.assertEqual(summary["failed_activity_count"], 0)

    def test_unknown_exception_is_permanent_and_not_retried(self) -> None:
        case = self.manifest.cases[0]
        adapter = FakeRadeonAdapter(permanent_case=case.case_id)
        runner = self.runner(adapter, run_name="permanent")
        summary = runner.run()
        self.assertEqual(
            adapter.calls[f"generate_still:{case.case_id}"],
            1,
        )
        self.assertGreater(summary["failed_activity_count"], 0)
        gate_path = runner.run_dir / "gates" / f"{case.case_id}.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        self.assertFalse(gate["completed"])
        self.assertTrue(gate["crashed"])

    def test_process_interruption_resumes_from_running_checkpoint(self) -> None:
        case = self.manifest.cases[0]
        interrupted = FakeRadeonAdapter(crash_case=case.case_id)
        with self.assertRaises(KeyboardInterrupt):
            self.runner(interrupted, run_name="interrupted").run()
        checkpoint_path = (
            self.root
            / "interrupted"
            / "run-checkpoint.shard-000-of-450.json"
        )
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(
            checkpoint["activities"][f"generate_still:{case.case_id}"]["status"],
            "running",
        )
        recovered = FakeRadeonAdapter()
        summary = self.runner(
            recovered,
            run_name="interrupted",
            resume=True,
        ).run()
        self.assertEqual(summary["finalized_case_count"], 1)
        self.assertEqual(
            recovered.calls[f"generate_still:{case.case_id}"],
            1,
        )

    def test_manifest_has_exactly_thirty_video_cases(self) -> None:
        runner = self.runner(
            FakeRadeonAdapter(),
            run_name="video-count",
            shard_count=1,
        )
        self.assertEqual(len(runner.cases), 450)
        self.assertEqual(sum(case.video_required for case in runner.cases), 30)

    def test_shards_are_disjoint_and_cover_manifest_in_order(self) -> None:
        selected = []
        for shard_index in range(7):
            runner = self.runner(
                FakeRadeonAdapter(),
                run_name="shards",
                shard_index=shard_index,
                shard_count=7,
            )
            selected.append(tuple(case.case_id for case in runner.cases))
        flattened = [case_id for shard in selected for case_id in shard]
        self.assertEqual(len(flattened), 450)
        self.assertEqual(len(set(flattened)), 450)
        reconstructed = []
        for index, case in enumerate(self.manifest.cases):
            shard = index % 7
            offset = index // 7
            reconstructed.append(selected[shard][offset])
        self.assertEqual(
            reconstructed,
            [case.case_id for case in self.manifest.cases],
        )

    def test_closed_online_adapter_is_rejected(self) -> None:
        adapter = FakeRadeonAdapter()
        adapter.identity = lambda: {
            **FakeRadeonAdapter().identity(),
            "uses_closed_online_api": True,
        }
        with self.assertRaisesRegex(
            BenchmarkRunnerError,
            "closed online inference",
        ):
            self.runner(adapter, run_name="closed-api")

    def test_two_complete_shards_merge_into_compiler_valid_result_set(self) -> None:
        run_dir = self.root / "merge"
        for shard_index in range(2):
            CompetitionMatrixRunner(
                manifest_path=self.manifest_path,
                run_dir=run_dir,
                adapter=FakeRadeonAdapter(),
                shard_index=shard_index,
                shard_count=2,
                sleeper=lambda _: None,
            ).run()
        summary = merge_sharded_results(
            manifest_path=self.manifest_path,
            run_dir=run_dir,
            shard_count=2,
        )
        results = _load_case_results(
            Path(str(summary["output_path"])),
            self.manifest,
        )
        self.assertEqual(summary["merged_case_count"], 450)
        self.assertEqual(
            [item.case_id for item in results],
            [case.case_id for case in self.manifest.cases],
        )
        self.assertEqual(
            sum(
                item.video_output_sha256 is not None
                for item in results
            ),
            30,
        )


if __name__ == "__main__":
    unittest.main()
