from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.sample_decode_gate import (
    EXPECTED_LEROBOT_DATASET_QUALNAME,
    LeRobotRuntimeFrameSource,
    LeRobotSampleFrameSource,
    DecodedFrame,
    DecodedImage,
    audit_sample_decode,
    sample_offsets,
)


ROOT = Path(__file__).resolve().parents[1]
GATE = load_json(ROOT / "configs/sample-decode-gate-v1.json")

ENV_SHAPE = (3, 240, 320)
WRIST_SHAPE = (3, 240, 424)
IMAGE_FEATURES = (
    "observation.images.env_cam",
    "observation.images.left_wrist_cam",
    "observation.images.right_wrist_cam",
)


def _good_image(shape):
    return DecodedImage(shape=tuple(shape), finite=True, min_value=0.0, max_value=1.0)


def _good_frame(global_index, *, env_shape=ENV_SHAPE):
    base = 0.01 * global_index
    return DecodedFrame(
        global_index=global_index,
        observation_state=[base + 0.1 * j for j in range(16)],
        action=[base + 0.2 * j for j in range(16)],
        images={
            "observation.images.env_cam": _good_image(env_shape),
            "observation.images.left_wrist_cam": _good_image(WRIST_SHAPE),
            "observation.images.right_wrist_cam": _good_image(WRIST_SHAPE),
        },
    )


def _load_cli_module():
    """Load the tools/ CLI as an isolated module (tools is not a package)."""

    path = ROOT / "tools" / "audit_mantis_lerobot_sample_decode.py"
    spec = importlib.util.spec_from_file_location(
        "audit_mantis_lerobot_sample_decode_cli", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class FakeFrameSource:
    """In-memory, dependency-free FrameSource for CPU-only unit tests."""

    def __init__(self, bounds, *, overrides=None, decode_errors=None,
                 total_episodes=None, total_frames=None, runtime_indexed=False,
                 loader_mode="test_double_runtime", lerobot_class_path=None,
                 len_dataset="_unset_", cuda_available=False, decode_path=None):
        self._bounds = dict(bounds)
        self._overrides = overrides or {}
        self._decode_errors = set(decode_errors or ())
        self._runtime_indexed = runtime_indexed
        self.total_frames = (
            total_frames
            if total_frames is not None
            else sum(length for _, length in self._bounds.values())
        )
        self.total_episodes = (
            total_episodes if total_episodes is not None else len(self._bounds)
        )
        self.info = {
            "total_episodes": self.total_episodes,
            "total_frames": self.total_frames,
            "codebase_version": "v3.0",
            "features": {
                "observation.state": {"shape": [16]},
                "action": {"shape": [16]},
                "observation.images.env_cam": {"shape": [240, 320, 3], "dtype": "image"},
                "observation.images.left_wrist_cam": {"shape": [240, 424, 3], "dtype": "image"},
                "observation.images.right_wrist_cam": {"shape": [240, 424, 3], "dtype": "image"},
            },
        }
        self.stats = {"observation.state": {"min": [0.0] * 16}}
        self.info_sha256 = "0" * 64
        self.stats_sha256 = "1" * 64
        self.codebase_version = "v3.0"
        self.lerobot_version = "0.4.2"
        self.lerobot_version_source = "test_double"
        self.loader_mode = loader_mode
        self.decode_path = (
            decode_path
            if decode_path is not None
            else (
                LeRobotRuntimeFrameSource.DECODE_PATH
                if loader_mode == "lerobot_runtime"
                else LeRobotSampleFrameSource.DECODE_PATH
            )
        )
        self.lerobot_class_path = (
            lerobot_class_path
            if lerobot_class_path is not None
            else (EXPECTED_LEROBOT_DATASET_QUALNAME if loader_mode == "lerobot_runtime" else None)
        )
        if len_dataset == "_unset_":
            self.len_dataset = (
                None if loader_mode == "parquet_crosscheck" else self.total_frames
            )
        else:
            self.len_dataset = len_dataset
        self.cpu_device_semantics = {"torch_cuda_is_available": cuda_available}

    def episode_bounds(self):
        return {ep: (first, length) for ep, (first, length) in self._bounds.items()}

    def decode(self, global_index):
        if global_index in self._decode_errors:
            raise RuntimeError(f"injected decode failure at {global_index}")
        overridden = global_index in self._overrides
        frame = self._overrides.get(global_index, _good_frame(global_index))
        # Only the synthetic default frames get runtime enrichment; explicit
        # overrides (e.g. an injected bad frame_index) are returned verbatim.
        if self._runtime_indexed and not overridden:
            frame = self._enrich_runtime(frame, global_index)
        return frame

    def _enrich_runtime(self, frame, global_index):
        # Mimic a LeRobot runtime item: frame_index is intra-episode, the
        # timestamp grows with the frame, episode_index is the owning episode.
        owning = None
        for episode, (first_global, length) in self._bounds.items():
            if first_global <= global_index < first_global + length:
                owning = episode, first_global
                break
        if owning is None:
            return frame
        episode, first_global = owning
        intra = global_index - first_global
        return DecodedFrame(
            global_index=frame.global_index,
            observation_state=frame.observation_state,
            action=frame.action,
            images=frame.images,
            frame_index=intra,
            timestamp=intra / 30.0,
            episode_index=episode,
        )


def _two_episodes():
    # Episode 0: length 3 -> globals [0, 1, 2]; episode 1: length 4 -> globals [3, 5, 6].
    return {0: (0, 3), 1: (3, 4)}


class SampleOffsetsTests(unittest.TestCase):
    def test_empty_length_decodes_nothing(self):
        self.assertEqual(sample_offsets(0), [])

    def test_single_frame_episode_decodes_once(self):
        self.assertEqual(sample_offsets(1), [0])

    def test_two_frame_episode_decodes_both(self):
        self.assertEqual(sample_offsets(2), [0, 1])

    def test_three_frame_episode_picks_first_mid_last(self):
        self.assertEqual(sample_offsets(3), [0, 1, 2])

    def test_even_length_picks_lower_median(self):
        self.assertEqual(sample_offsets(4), [0, 2, 3])


class SampleDecodeGateTests(unittest.TestCase):
    def _audit(self, source):
        return audit_sample_decode(source, gate=GATE, gate_sha256="g" * 64)

    def test_clean_two_episode_dataset_passes(self):
        receipt = self._audit(FakeFrameSource(_two_episodes()))
        self.assertTrue(receipt["sample_decode_gate_pass"], receipt["issues"])
        self.assertEqual(receipt["issues"], [])
        self.assertEqual(receipt["inspected_episodes"], 2)
        self.assertEqual(receipt["decoded_samples"], 6)
        self.assertEqual(
            receipt["inspected_global_indices"], [0, 1, 2, 3, 5, 6]
        )
        self.assertEqual(
            receipt["samples_per_episode"], {"0": [0, 1, 2], "1": [0, 2, 3]}
        )
        self.assertEqual(receipt["total_episodes"], 2)
        self.assertEqual(receipt["total_frames"], 7)
        self.assertEqual(receipt["codebase_version"], "v3.0")
        self.assertTrue(receipt["codebase_version_recognized"])
        self.assertEqual(receipt["gate_sha256"], "g" * 64)
        self.assertEqual(receipt["info_sha256"], "0" * 64)
        self.assertEqual(receipt["stats_sha256"], "1" * 64)
        for feature in IMAGE_FEATURES:
            self.assertEqual(
                receipt["decoded_image_shapes"][feature],
                list(WRIST_SHAPE if "wrist" in feature else ENV_SHAPE),
            )
        self.assertIn("claim_boundary", receipt)
        self.assertIn("does not prove learned-policy success", receipt["claim_boundary"])
        # Observed ranges are populated for every decoded sample.
        for feature in ("observation.state", "action"):
            self.assertIsNotNone(receipt["observed_ranges"][feature]["min"][0])
            self.assertIsNotNone(receipt["observed_ranges"][feature]["max"][0])

    def test_non_finite_state_vector_is_rejected(self):
        bad = _good_frame(1)
        bad = DecodedFrame(
            global_index=1,
            observation_state=[float("nan")] + bad.action[:1] + [0.0] * 14,
            action=bad.action,
            images=bad.images,
        )
        source = FakeFrameSource(_two_episodes(), overrides={1: bad})
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("invalid_vector:observation.state:0:1", receipt["issues"])
        # The bad frame contributes no observed range; others still do.
        self.assertIsNotNone(
            receipt["observed_ranges"]["observation.state"]["max"][0]
        )

    def test_wrong_length_vector_is_rejected(self):
        bad = DecodedFrame(
            global_index=0,
            observation_state=[0.0] * 15,
            action=[0.0] * 16,
            images=_good_frame(0).images,
        )
        source = FakeFrameSource({0: (0, 1)}, overrides={0: bad})
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("invalid_vector:observation.state:0:0", receipt["issues"])

    def test_image_shape_mismatch_is_rejected(self):
        bad = _good_frame(2, env_shape=(3, 240, 321))
        source = FakeFrameSource(_two_episodes(), overrides={2: bad})
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn(
            "image_shape_mismatch:observation.images.env_cam:0:2", receipt["issues"]
        )
        # The mismatched sample is rejected, but the valid env_cam samples still
        # record the correct CHW shape.
        self.assertEqual(
            receipt["decoded_image_shapes"]["observation.images.env_cam"],
            [3, 240, 320],
        )

    def test_image_value_out_of_range_is_rejected(self):
        bad = _good_frame(3)
        bad = DecodedFrame(
            global_index=3,
            observation_state=bad.observation_state,
            action=bad.action,
            images={
                "observation.images.env_cam": DecodedImage(
                    shape=ENV_SHAPE, finite=True, min_value=-0.1, max_value=1.0
                ),
                "observation.images.left_wrist_cam": _good_image(WRIST_SHAPE),
                "observation.images.right_wrist_cam": _good_image(WRIST_SHAPE),
            },
        )
        source = FakeFrameSource(_two_episodes(), overrides={3: bad})
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn(
            "image_value_out_of_range:observation.images.env_cam:1:0", receipt["issues"]
        )

    def test_non_finite_image_is_rejected(self):
        bad = _good_frame(5)
        bad = DecodedFrame(
            global_index=5,
            observation_state=bad.observation_state,
            action=bad.action,
            images={
                "observation.images.env_cam": DecodedImage(
                    shape=ENV_SHAPE, finite=False, min_value=0.0, max_value=1.0
                ),
                "observation.images.left_wrist_cam": _good_image(WRIST_SHAPE),
                "observation.images.right_wrist_cam": _good_image(WRIST_SHAPE),
            },
        )
        source = FakeFrameSource(_two_episodes(), overrides={5: bad})
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("image_not_finite:observation.images.env_cam:1:2", receipt["issues"])

    def test_decode_failure_is_recorded_without_aborting(self):
        source = FakeFrameSource(_two_episodes(), decode_errors={6})
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("decode_error:1:3:RuntimeError", receipt["issues"])
        # The other five samples still decoded.
        self.assertEqual(receipt["decoded_samples"], 5)

    def test_episode_count_mismatch_is_detected(self):
        # info declares two episodes but only one is observed.
        source = FakeFrameSource({0: (0, 3)}, total_episodes=2)
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("episode_count_mismatch", receipt["issues"])

    def test_non_contiguous_episode_indices_are_detected(self):
        source = FakeFrameSource({1: (0, 3)})
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("episode_index_not_contiguous_from_zero", receipt["issues"])

    def test_zero_length_episode_is_reported(self):
        source = FakeFrameSource({0: (0, 0), 1: (0, 3)}, total_episodes=2, total_frames=3)
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("episode_zero_length:0", receipt["issues"])
        self.assertEqual(receipt["decoded_samples"], 3)


class RuntimeLoaderEvidenceTests(unittest.TestCase):
    """The default loader's receipt must carry real-runtime evidence fields."""

    def _audit(self, source):
        return audit_sample_decode(source, gate=GATE, gate_sha256="g" * 64)

    def test_clean_runtime_double_records_runtime_evidence(self):
        source = FakeFrameSource(
            _two_episodes(), runtime_indexed=True, loader_mode="lerobot_runtime"
        )
        receipt = self._audit(source)
        self.assertTrue(receipt["sample_decode_gate_pass"], receipt["issues"])
        self.assertEqual(receipt["loader_mode"], "lerobot_runtime")
        self.assertEqual(receipt["lerobot_class_path"], EXPECTED_LEROBOT_DATASET_QUALNAME)
        self.assertEqual(receipt["len_dataset"], 7)
        self.assertIn("LeRobotDataset", receipt["decode_path"])
        self.assertEqual(
            receipt["episodes_dataset_index_bounds"],
            {
                "0": {"dataset_from_index": 0, "dataset_to_index": 3, "length": 3},
                "1": {"dataset_from_index": 3, "dataset_to_index": 7, "length": 4},
            },
        )
        # Sample boundaries are populated because the runtime double supplies them.
        self.assertEqual(receipt["index_boundaries"], {"min": 0, "max": 6})
        self.assertEqual(receipt["frame_index_boundaries"], {"min": 0, "max": 3})
        self.assertIsNotNone(receipt["timestamp_boundaries"]["min"])
        self.assertIsNotNone(receipt["timestamp_boundaries"]["max"])
        self.assertEqual(receipt["cpu_device_semantics"]["torch_cuda_is_available"], False)

    def test_len_dataset_mismatch_is_rejected(self):
        source = FakeFrameSource(
            _two_episodes(), len_dataset=99, loader_mode="lerobot_runtime"
        )
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("len_dataset_mismatch:99:7", receipt["issues"])

    def test_cuda_available_is_rejected_as_cpu_violation(self):
        source = FakeFrameSource(_two_episodes(), cuda_available=True)
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("cuda_available_expected_cpu", receipt["issues"])

    def test_runtime_class_path_must_match_expected_qualname(self):
        source = FakeFrameSource(
            _two_episodes(),
            loader_mode="lerobot_runtime",
            lerobot_class_path="something.Else",
        )
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("lerobot_class_path_unexpected:something.Else", receipt["issues"])

    def test_parquet_crosscheck_mode_records_crosscheck_evidence(self):
        source = FakeFrameSource(_two_episodes(), loader_mode="parquet_crosscheck")
        receipt = self._audit(source)
        self.assertTrue(receipt["sample_decode_gate_pass"], receipt["issues"])
        self.assertEqual(receipt["loader_mode"], "parquet_crosscheck")
        self.assertIsNone(receipt["lerobot_class_path"])
        self.assertIsNone(receipt["len_dataset"])
        self.assertIn("cross-check", receipt["decode_path"])
        self.assertIn("does NOT use the LeRobot runtime", receipt["decode_path"])

    def test_invalid_frame_index_is_reported(self):
        bad = _good_frame(0)
        bad = DecodedFrame(
            global_index=bad.global_index,
            observation_state=bad.observation_state,
            action=bad.action,
            images=bad.images,
            frame_index=-1,
            timestamp=0.0,
        )
        source = FakeFrameSource(_two_episodes(), overrides={0: bad}, runtime_indexed=True)
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("frame_index_invalid:0:0", receipt["issues"])

    def test_invalid_timestamp_is_reported(self):
        bad = _good_frame(0)
        bad = DecodedFrame(
            global_index=bad.global_index,
            observation_state=bad.observation_state,
            action=bad.action,
            images=bad.images,
            frame_index=0,
            timestamp=float("nan"),
        )
        source = FakeFrameSource(_two_episodes(), overrides={0: bad}, runtime_indexed=True)
        receipt = self._audit(source)
        self.assertFalse(receipt["sample_decode_gate_pass"])
        self.assertIn("timestamp_invalid:0:0", receipt["issues"])


class SampleDecodeCLITests(unittest.TestCase):
    """Argument handling and refuse-overwrite for the bounded-decode CLI."""

    def setUp(self):
        self.cli = _load_cli_module()
        self._stdout = io.StringIO()
        self._patcher = contextlib.redirect_stdout(self._stdout)
        self._patcher.__enter__()
        self._orig_runtime = self.cli.LeRobotRuntimeFrameSource
        self._orig_parquet = self.cli.LeRobotSampleFrameSource
        self._orig_audit = self.cli.audit_sample_decode

    def _patch_sources(self, runtime=None, parquet=None):
        if runtime is not None:
            self.cli.LeRobotRuntimeFrameSource = runtime
        if parquet is not None:
            self.cli.LeRobotSampleFrameSource = parquet

    def tearDown(self):
        self._patcher.__exit__(None, None, None)
        self.cli.LeRobotRuntimeFrameSource = self._orig_runtime
        self.cli.LeRobotSampleFrameSource = self._orig_parquet
        self.cli.audit_sample_decode = self._orig_audit

    def test_lerobot_loader_requires_repo_id(self):
        with self.assertRaises(SystemExit) as ctx:
            self.cli.main(["/tmp/does-not-matter", "--loader", "lerobot"])
        self.assertEqual(ctx.exception.code, 2)

    def test_default_loader_is_lerobot_runtime(self):
        captured = {}

        class RuntimeStub:
            def __init__(self, repo_id, dataset_root):
                captured["repo_id"] = repo_id
                captured["dataset_root"] = Path(dataset_root)
                captured["loader_mode"] = "lerobot_runtime"

        def fake_audit(frame_source, *, gate, gate_sha256):
            return {"sample_decode_gate_pass": True, "loader_mode": "lerobot_runtime"}

        self._patch_sources(runtime=RuntimeStub)
        self.cli.audit_sample_decode = fake_audit
        rc = self.cli.main(["/tmp/ds", "--repo-id", "mantis/multiseed4"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured["repo_id"], "mantis/multiseed4")
        self.assertTrue(captured["dataset_root"].is_absolute())

    def test_parquet_loader_dispatches_to_parquet_source_without_repo_id(self):
        captured = {}

        class ParquetStub:
            def __init__(self, dataset_root):
                captured["dataset_root"] = Path(dataset_root)

        def fake_audit(frame_source, *, gate, gate_sha256):
            return {"sample_decode_gate_pass": True, "loader_mode": "parquet_crosscheck"}

        self._patch_sources(parquet=ParquetStub)
        self.cli.audit_sample_decode = fake_audit
        rc = self.cli.main(["/tmp/ds", "--loader", "parquet"])
        self.assertEqual(rc, 0)
        self.assertTrue(captured["dataset_root"].is_absolute())

    def test_refuses_to_overwrite_existing_output(self):
        def fake_audit(frame_source, *, gate, gate_sha256):
            return {"sample_decode_gate_pass": True}

        self._patch_sources(
            runtime=lambda repo_id, dataset_root: object(),
            parquet=lambda dataset_root: object(),
        )
        self.cli.audit_sample_decode = fake_audit
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "receipt.json"
            existing.write_text('{"preexisting": true}', encoding="utf-8")
            with self.assertRaises(SystemExit) as ctx:
                self.cli.main(
                    [str(existing.parent / "ds"), "--repo-id", "mantis/x",
                     "--output", str(existing)]
                )
            self.assertEqual(ctx.exception.code, 2)
            # The immutable pre-existing file is untouched.
            self.assertEqual(
                json.loads(existing.read_text(encoding="utf-8")),
                {"preexisting": True},
            )

    def test_non_passing_receipt_returns_exit_code_two(self):
        def fake_audit(frame_source, *, gate, gate_sha256):
            return {"sample_decode_gate_pass": False}

        self._patch_sources(runtime=lambda repo_id, dataset_root: object())
        self.cli.audit_sample_decode = fake_audit
        rc = self.cli.main(["/tmp/ds", "--repo-id", "mantis/x"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
