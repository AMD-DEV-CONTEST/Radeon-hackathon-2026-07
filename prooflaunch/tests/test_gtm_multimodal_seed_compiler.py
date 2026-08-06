from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_multimodal_seed_compiler import (
    MultimodalSeedCompilationError,
    compile_multimodal_seed,
    compile_multimodal_seed_files,
)


ROOT = Path(__file__).resolve().parents[1]


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


class MultimodalSeedCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        execution = json.loads(
            (
                ROOT
                / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/text-creative-challenger-execution.json"
            ).read_text(encoding="utf-8")
        )
        candidate = execution["candidates"][0]["candidate"]
        cls.admission = {
            "schema": "ProofLaunchMultimodalProductionAdmissionV1",
            "public_packet_sha256": "a" * 64,
            "blind_review_aggregate_sha256": "b" * 64,
            "text_challenger_execution_sha256": execution["content_sha256"],
            "selection_request_sha256": "c" * 64,
            "selected_territory_id": candidate["territory_id"],
            "selected_candidate_content_sha256": candidate["candidate_content_sha256"],
            "selected_candidate": candidate,
            "authenticated_approver": "named-director@example.test",
            "selected_at": "2026-08-01T20:00:00+00:00",
            "reason": "The completed blind review cleared the predeclared selection threshold.",
            "human_attestation": "contract fixture",
            "prompt_compilation_authorized": True,
            "gpu_execution_authorized": False,
            "spend_authorized": False,
            "external_publish_authorized": False,
            "effect_claim_eligible": False,
            "automatic_winner_selection_enabled": False,
            "truth_boundary": "Contract fixture only.",
            "content_sha256": None,
        }
        cls.admission["content_sha256"] = digest(cls.admission)
        cls.bindings = json.loads(
            (ROOT / "config/comfyui_execution_bindings_v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.handoff = json.loads(
            (
                ROOT / "artifacts/comfyui-gpu-handoff-20260801/handoff.json"
            ).read_text(encoding="utf-8")
        )

    def test_compiles_four_modalities_but_never_claims_execution(self) -> None:
        first = compile_multimodal_seed(self.admission, self.bindings, self.handoff)
        second = compile_multimodal_seed(self.admission, self.bindings, self.handoff)
        self.assertEqual(first, second)
        self.assertEqual(first["stage_count"], 4)
        self.assertEqual(
            [stage["modality"] for stage in first["stages"]],
            ["image", "video", "audio", "speech"],
        )
        self.assertTrue(first["all_required_modalities_compiled"])
        self.assertFalse(first["all_required_modalities_executable"])
        self.assertTrue(all(not stage["execution_admitted"] for stage in first["stages"]))
        self.assertFalse(first["external_publish_executed"])
        self.assertFalse(first["effect_claim_eligible"])
        self.assertRegex(first["content_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn(
            self.admission["selected_candidate"]["factual_claims"][0],
            first["stages"][0]["values"]["prompt"],
        )

    def test_tamper_or_authority_expansion_fails_closed(self) -> None:
        tampered = copy.deepcopy(self.admission)
        tampered["selected_candidate"]["organizing_idea"] = "tampered"
        with self.assertRaises(MultimodalSeedCompilationError):
            compile_multimodal_seed(tampered, self.bindings, self.handoff)
        expanded = copy.deepcopy(self.admission)
        expanded["gpu_execution_authorized"] = True
        expanded["content_sha256"] = None
        expanded["content_sha256"] = digest(expanded)
        with self.assertRaises(MultimodalSeedCompilationError):
            compile_multimodal_seed(expanded, self.bindings, self.handoff)

    def test_file_compilation_is_private_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for name, payload in (
                ("admission.json", self.admission),
                ("bindings.json", self.bindings),
                ("handoff.json", self.handoff),
            ):
                path = root / name
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths.append(path)
            output = root / "output/compilation.json"
            compile_multimodal_seed_files(*paths, output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(MultimodalSeedCompilationError):
                compile_multimodal_seed_files(*paths, output)


if __name__ == "__main__":
    unittest.main()
