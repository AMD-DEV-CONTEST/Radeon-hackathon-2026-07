from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.publication import build_publication_candidate


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools/audit_framework_story.py"
CONTRACT_PATH = ROOT / "configs/framework-story-v3.json"

SPEC = importlib.util.spec_from_file_location("audit_framework_story", TOOL_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load framework story audit module")
AUDIT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT_MODULE)


def _copy_file(source_root: Path, target_root: Path, relative: str) -> None:
    destination = target_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / relative, destination)


def _minimal_audit_tree(target_root: Path, contract: dict) -> None:
    required = set(AUDIT_MODULE._required_files(contract))
    required.update(
        {
            "configs/framework-mvp-v2.json",
            "configs/robot-port-profile-template-v1.json",
            "configs/robot-port-profile-mantis-stack-bowls-v1.json",
            "tests/fixtures/robot-port-profile-synthetic-v1.json",
            "receipts/framework-mvp-terminal-20260729-v2/terminal.json",
            "receipts/framework-mvp-terminal-20260729-v2/RECEIPT.SHA256SUMS",
        }
    )
    manifest = (
        ROOT
        / "receipts/framework-mvp-terminal-20260729-v2/RECEIPT.SHA256SUMS"
    )
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            _, relative = line.split(maxsplit=1)
            relative = relative.strip()
            if (ROOT / relative).is_file():
                required.add(relative)
    mvp = load_json(ROOT / "configs/framework-mvp-v2.json")
    required.update(mvp["runtime_immutability"])
    for relative in sorted(required):
        _copy_file(ROOT, target_root, relative)


def _failed_ids(result: dict) -> set[str]:
    return set(result["failed_check_ids"])


class FrameworkStoryAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)

    def test_checked_in_story_is_consistent(self) -> None:
        result = AUDIT_MODULE.audit_framework_story(ROOT, self.contract)
        self.assertTrue(result["valid"])
        self.assertEqual(result["failed_check_ids"], [])
        self.assertGreaterEqual(result["check_count"], 50)

    def test_cli_is_deterministic_and_read_only(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        command = [sys.executable, str(TOOL_PATH)]
        first = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        second = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(json.loads(first.stdout)["valid"])

    def test_schema_or_work_package_drift_is_rejected(self) -> None:
        for key, value in (
            ("schema_version", 2),
            ("work_package_id", "WP-WRONG"),
        ):
            with self.subTest(key=key):
                broken = copy.deepcopy(self.contract)
                broken[key] = value
                with self.assertRaises(ContractError):
                    AUDIT_MODULE.audit_framework_story(ROOT, broken)

    def test_visual_policy_contract_drift_is_rejected(self) -> None:
        for key, value in (
            ("redistribute_mantis_assets", True),
            ("raw_asset_payloads_excluded", False),
            ("rendered_mantis_demo_visuals_user_permitted", False),
            ("permission_is_general_license", True),
        ):
            with self.subTest(key=key):
                broken = copy.deepcopy(self.contract)
                broken["asset_policy"][key] = value
                with self.assertRaises(ContractError):
                    AUDIT_MODULE.audit_framework_story(ROOT, broken)

    def test_visual_policy_required_file_removal_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        del broken["visual_policy_invariants"]["files"][
            "docs/FRAMEWORK_STORY_V1.md"
        ]
        with self.assertRaises(ContractError):
            AUDIT_MODULE.audit_framework_story(ROOT, broken)

    def test_visual_policy_required_token_weakening_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["visual_policy_invariants"]["files"]["README.md"].pop()
        with self.assertRaises(ContractError):
            AUDIT_MODULE.audit_framework_story(ROOT, broken)

    def test_visual_policy_forbidden_phrase_removal_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["visual_policy_invariants"]["forbidden_phrases"].pop()
        with self.assertRaises(ContractError):
            AUDIT_MODULE.audit_framework_story(ROOT, broken)

    def test_missing_document_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            (root / "submission/VIDEO_STORYBOARD.md").unlink()
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertFalse(result["valid"])
            self.assertIn(
                "file:submission/VIDEO_STORYBOARD.md",
                _failed_ids(result),
            )

    def test_stale_claim_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\nSmolVLA only after the ACT baseline passes\n",
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("stale_claims", _failed_ids(result))

    def test_broken_local_markdown_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n[broken](docs/does-not-exist.md)\n",
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("markdown_local_links", _failed_ids(result))

    def test_official_g3_or_corrective_terminal_omission_is_rejected(self) -> None:
        replacements = (
            ("0/10", "zero-of-ten", "official_g3:README.md"),
            (
                "COMPLETE_NOT_PROMOTABLE",
                "terminal-redacted",
                "corrective_terminal:README.md",
            ),
        )
        for old, new, expected_failure in replacements:
            with self.subTest(token=old), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _minimal_audit_tree(root, self.contract)
                readme = root / "README.md"
                readme.write_text(
                    readme.read_text(encoding="utf-8").replace(old, new),
                    encoding="utf-8",
                )
                result = AUDIT_MODULE.audit_framework_story(root, self.contract)
                self.assertIn(expected_failure, _failed_ids(result))

    def test_identity_or_asset_boundary_omission_is_rejected(self) -> None:
        replacements = (
            ("Zhiwen Su", "name-redacted", "identity:README.md"),
            ("externalized", "managed-externally", "asset_boundary:README.md"),
        )
        for old, new, expected_failure in replacements:
            with self.subTest(token=old), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _minimal_audit_tree(root, self.contract)
                readme = root / "README.md"
                readme.write_text(
                    readme.read_text(encoding="utf-8").replace(old, new),
                    encoding="utf-8",
                )
                result = AUDIT_MODULE.audit_framework_story(root, self.contract)
                self.assertIn(expected_failure, _failed_ids(result))

    def test_rendered_demo_exception_omission_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            story = root / "docs/FRAMEWORK_STORY_V1.md"
            story.write_text(
                story.read_text(encoding="utf-8").replace(
                    "user-permitted only in the demonstration video",
                    "not available for the demonstration video",
                    1,
                ),
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn(
                "visual_policy:docs/FRAMEWORK_STORY_V1.md",
                _failed_ids(result),
            )

    def test_raw_asset_exclusion_omission_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            story = root / "docs/FRAMEWORK_STORY_V1.md"
            story.write_text(
                story.read_text(encoding="utf-8").replace(
                    "Raw Mantis URDF",
                    "Bundled Mantis URDF",
                    1,
                ),
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn(
                "visual_policy:docs/FRAMEWORK_STORY_V1.md",
                _failed_ids(result),
            )

    def test_total_rendered_video_ban_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\nReports and video must not reproduce unlicensed Mantis screenshots\n",
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("visual_policy_forbidden", _failed_ids(result))

    def test_broad_raw_payload_redistribution_prose_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\nRaw Mantis asset payloads may be redistributed in the public "
                + "repository.\n",
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("visual_policy_contradictions", _failed_ids(result))

    def test_general_license_prose_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\nThe demonstration-video permission is a general license.\n",
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("visual_policy_contradictions", _failed_ids(result))

    def test_wrong_cleanroom_baseline_is_rejected(self) -> None:
        replacements = (
            ("4,738", "7,085"),
            ("multiseed4", "multiseed6"),
            (
                "configs/act-rocm-baseline-v2.json",
                "configs/act-rocm-corrective-multiseed6-v2.json",
            ),
        )
        for old, new in replacements:
            with self.subTest(token=old), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _minimal_audit_tree(root, self.contract)
                guide = root / "docs/REPRODUCIBILITY.md"
                guide.write_text(
                    guide.read_text(encoding="utf-8").replace(old, new),
                    encoding="utf-8",
                )
                result = AUDIT_MODULE.audit_framework_story(root, self.contract)
                self.assertIn("reproducibility_baseline", _failed_ids(result))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            readme = root / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n--training-contract "
                + "configs/act-rocm-corrective-multiseed6-v2.json\n",
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("reproducibility_baseline", _failed_ids(result))

    def test_public_readiness_release_gate_and_boundaries_are_pinned(self) -> None:
        public_documents = (
            "README.md",
            "submission/README.md",
            "submission/README.zh-CN.md",
            "submission/PUBLICATION_CHECKLIST.md",
            "submission/EVIDENCE_MATRIX.md",
            "submission/TECHNICAL_REPORT.md",
            "docs/REPRODUCIBILITY.md",
        )
        forbidden_phrases = (
            "evidence-backed staging candidate",
            "public-delivery staging",
            "skeleton",
            "fresh packaging is required",
            "fresh package and size audit remain required",
            "a fresh release-mode build is required",
            "not yet a public release",
            "not a formal release",
            "publishable release",
            "docs/EXECUTION_PLAN.md",
            ".ops/",
            "证据支撑的暂存候选",
            "公开交付的暂存骨架",
            "框架叙事同步后必须重新打包",
            "正式发布或净室复现完成",
        )
        common_required_phrases = (
            "RELEASE_GO",
            "0/10",
            "timeout",
            "collision_safety",
            "COMPLETE_NOT_PROMOTABLE",
            "CLEANROOM_RUNNER_NO_GO",
            "submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4",
            "220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017",
            "168",
            "URDF",
        )
        english_required_phrases = (
            "ready for an authorized",
            "PR only after",
            "clean-room reproduction",
            "mesh",
            "source asset",
            "derived raw asset",
            "materialization",
            "asset payload",
        )
        english_documents = set(public_documents) - {"submission/README.zh-CN.md"}

        for relative in public_documents:
            with self.subTest(document=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                normalized = " ".join(text.replace(">", " ").split())
                for phrase in forbidden_phrases:
                    self.assertNotIn(phrase, normalized)
                for phrase in common_required_phrases:
                    self.assertIn(phrase, normalized)
                for phrase in english_required_phrases:
                    if relative not in english_documents:
                        continue
                    if phrase == "clean-room reproduction":
                        self.assertIn(phrase, normalized.lower())
                    else:
                        self.assertIn(phrase, normalized)
                lowered = text.lower()
                self.assertIn("mantis", lowered)
                if relative in english_documents:
                    self.assertIn("raw", lowered)
                    self.assertIn("external", lowered)

        chinese = " ".join(
            (ROOT / "submission/README.zh-CN.md")
            .read_text(encoding="utf-8")
            .replace(">", " ")
            .split()
        )
        for phrase in (
            "本地发布候选",
            "获得独立 `RELEASE_GO` 后，该候选才可进入经授权的公开 PR",
            "没有任何 runner 执行",
            "净室复现仍未得到证明，并作为 `LIMITATION` 明示",
            "fork、PR 和提交属于 `PENDING_EXTERNAL` 外部动作",
            "训练 loss 不等于任务成功",
            "外部化",
            "网格",
            "源资产",
            "派生原始资产",
            "物化产物",
            "资产载荷",
            "docs/FRAMEWORK_STORY_V1.md",
            "docs/G3_FAILURE_ATTRIBUTION_SUBMISSION_SPRINT.md",
            "submission/EVIDENCE_MATRIX.md",
        ):
            self.assertIn(phrase, chinese)

        evidence_matrix = (ROOT / "submission/EVIDENCE_MATRIX.md").read_text(
            encoding="utf-8"
        )
        four_seed_row = next(
            line
            for line in evidence_matrix.splitlines()
            if line.startswith("| Four-seed dataset |")
        )
        self.assertIn("4 episodes / 4,738 frames", four_seed_row)
        self.assertIn("`configs/mantis-port-config.json`", four_seed_row)
        self.assertIn("| VERIFIED |", four_seed_row)
        self.assertNotIn(
            "receipts/amd-multiseed4-gate-20260726-v1/", four_seed_row
        )

        checklist = (ROOT / "submission/PUBLICATION_CHECKLIST.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("LIMITATION", checklist)
        self.assertIn("PENDING_EXTERNAL", checklist)
        self.assertNotIn("**OPEN", checklist)

    def test_runtime_or_profile_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            runtime = root / "src/mantis_rocm_bridge/gripper.py"
            runtime.write_text(
                runtime.read_text(encoding="utf-8") + "\n# drift\n",
                encoding="utf-8",
            )
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("runtime_immutability", _failed_ids(result))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            profile_path = (
                root
                / "tests/fixtures/robot-port-profile-synthetic-v1.json"
            )
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["schema_version"] = 2
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("profile_validation", _failed_ids(result))

    def test_entry_terminal_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _minimal_audit_tree(root, self.contract)
            terminal_path = (
                root
                / "receipts/framework-mvp-terminal-20260729-v2/terminal.json"
            )
            terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            terminal["terminal"] = "WRONG"
            terminal_path.write_text(json.dumps(terminal), encoding="utf-8")
            result = AUDIT_MODULE.audit_framework_story(root, self.contract)
            self.assertIn("entry_criterion:0", _failed_ids(result))

    def test_public_candidate_strips_current_and_packages_smoke_receipts(self) -> None:
        source_config = json.loads(
            (ROOT / "configs/mantis-port-config.json").read_text(encoding="utf-8")
        )
        smoke_receipts = (
            "receipts/cloud-amd-act-fresh-training-20260804-v1/training_receipt.json",
            "receipts/cloud-amd-act-fresh-openloop-20260804-v1/receipt.json",
        )

        # A packaged public tree is already sanitized. Reapplying the private-state
        # transform would correctly fail closed, so validate its delivered state.
        if "current" not in source_config:
            for receipt in smoke_receipts:
                self.assertTrue((ROOT / receipt).is_file(), receipt)
            return

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate"
            audit = build_publication_candidate(
                ROOT, ROOT / "configs/publication-allowlist-v1.json", output
            )
            self.assertEqual(audit["status"], "COMPLETE_RELEASE")
            self.assertTrue(audit["promotion_gate_pass"])

            public_tree = output / "public_tree"
            packaged_config = json.loads(
                (public_tree / "configs/mantis-port-config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertNotIn("current", packaged_config)
            self.assertIn("current", source_config)

            manifest = {
                line.split("  ", 1)[1]: line.split("  ", 1)[0]
                for line in (output / "SOURCE_FILES.SHA256SUMS")
                .read_text(encoding="utf-8")
                .splitlines()
            }
            for receipt in smoke_receipts:
                packaged = public_tree / receipt
                self.assertTrue(packaged.is_file(), receipt)
                self.assertEqual(packaged.read_bytes(), (ROOT / receipt).read_bytes())
                self.assertEqual(
                    manifest[receipt],
                    hashlib.sha256(packaged.read_bytes()).hexdigest(),
                )
            mismatches = [
                relative
                for relative, digest in manifest.items()
                if hashlib.sha256((public_tree / relative).read_bytes()).hexdigest()
                != digest
            ]
            self.assertEqual(mismatches, [])

    def test_public_documents_drop_stale_successor_and_cleanroom_smoke_wording(self) -> None:
        public_documents = (
            "README.md",
            "submission/README.md",
            "submission/README.zh-CN.md",
            "submission/PUBLICATION_CHECKLIST.md",
            "submission/EVIDENCE_MATRIX.md",
            "submission/TECHNICAL_REPORT.md",
            "docs/REPRODUCIBILITY.md",
        )
        stale_phrases = (
            "wording successor",
            "wording-only successor",
            "Fresh clean-room",
            "文字后继版本",
        )
        for relative in public_documents:
            text = (ROOT / relative).read_text(encoding="utf-8")
            for phrase in stale_phrases:
                self.assertNotIn(phrase, text, f"{relative}: {phrase!r}")

        evidence_matrix = (ROOT / "submission/EVIDENCE_MATRIX.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("mantis_stack_bowls_multiseed4_gripper_v2_20260726_v1", evidence_matrix)
        self.assertIn("AMD worker pipeline smoke", evidence_matrix)
        self.assertIn("4 episodes / 4,738 frames", evidence_matrix)
        self.assertIn("open_loop_inference_pass=false", evidence_matrix)
        self.assertIn("0.6.2", evidence_matrix)
        self.assertIn("0.4.4", evidence_matrix)
        self.assertIn("six gripper values exceed [0,1]", evidence_matrix)
        for receipt in (
            "receipts/cloud-amd-act-fresh-training-20260804-v1/training_receipt.json",
            "receipts/cloud-amd-act-fresh-openloop-20260804-v1/receipt.json",
        ):
            row = next(
                line for line in evidence_matrix.splitlines() if receipt in line
            )
            self.assertIn("AMD worker pipeline smoke", row)
            self.assertNotIn("Fresh clean-room", row)

    def test_public_documents_payload_boundary_distinguishes_fixtures(self) -> None:
        # The package ships nine synthetic, non-Mantis URDF/STL test fixtures, so
        # blanket "no robot mesh/URDF" denials are false. Each public document
        # that states the payload boundary must restrict the exclusion to raw
        # Mantis assets and name the allowlisted fixtures explicitly.
        cases = {
            "submission/README.md": {
                "blanket": "It contains no robot mesh, URDF",
                "qualified": "raw Mantis mesh, URDF",
                "fixtures": ("nine synthetic", "tests/fixtures"),
            },
            "README.md": {
                "blanket": "No robot meshes, URDFs",
                "qualified": "raw Mantis meshes, URDFs",
                "fixtures": ("nine synthetic", "tests/fixtures"),
            },
            "submission/README.zh-CN.md": {
                "blanket": "任何机器人",
                "qualified": "原始 Mantis",
                "fixtures": ("九个合成", "tests/fixtures"),
            },
        }
        for relative, expected in cases.items():
            with self.subTest(document=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                normalized = " ".join(text.replace(">", " ").split())
                self.assertNotIn(expected["blanket"], normalized)
                self.assertIn(expected["qualified"], normalized)
                for token in expected["fixtures"]:
                    self.assertIn(token, normalized)


if __name__ == "__main__":
    unittest.main()
