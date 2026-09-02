from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "audit_public_repo.py"
SPEC = importlib.util.spec_from_file_location("audit_public_repo", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicReleaseAuditTests(unittest.TestCase):
    def test_known_synthetic_secret_is_the_only_allowed_match(self) -> None:
        path = Path("internal/privacy/secrets_test.go")
        synthetic = 'value := "hf_abcdefghijklmnopqrstuvwxyz"'
        self.assertEqual(MODULE.scan_secrets(path, synthetic), [])

        real_token = "hf_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
        real = synthetic + f'\nvalue := "{real_token}"'
        findings = MODULE.scan_secrets(path, real)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["kind"], "huggingface_token")

    def test_forbidden_release_paths_fail_closed(self) -> None:
        self.assertIsNotNone(MODULE.forbidden_path_reason(Path("strategy/roadmap.md")))
        self.assertIsNotNone(MODULE.forbidden_path_reason(Path("models/model.gguf")))
        self.assertIsNotNone(MODULE.forbidden_path_reason(Path("evidence/run.log")))
        self.assertIsNotNone(MODULE.forbidden_path_reason(Path("scripts/__pycache__/audit.pyc")))
        self.assertIsNotNone(MODULE.forbidden_path_reason(Path(".venv/lib/package.py")))
        self.assertEqual(
            MODULE.forbidden_path_reason(Path("experiments/sprint32/holdout/cases.json")),
            "sealed evaluation material",
        )
        self.assertIsNone(MODULE.forbidden_path_reason(Path("evidence/public-claims.json")))

    def test_forbidden_file_is_classified_before_payload_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sealed = root / "experiments" / "sprint32" / "holdout" / "cases.json"
            sealed.parent.mkdir(parents=True)
            sealed.write_text("must-not-be-read", encoding="utf-8")

            original_public_files = MODULE.public_files
            original_text_payload = MODULE.text_payload
            original_validate_env = MODULE.validate_env_example
            original_validate_release = MODULE.validate_release_files
            original_verify_artifacts = MODULE.verify_judge_artifacts
            reads: list[Path] = []
            try:
                MODULE.public_files = lambda _root, _output: [Path("experiments/sprint32/holdout/cases.json")]
                MODULE.text_payload = lambda path: reads.append(path) or "unexpected"
                MODULE.validate_env_example = lambda _root: []
                MODULE.validate_release_files = lambda _root: []
                MODULE.verify_judge_artifacts = lambda _root: ([], [])
                report = MODULE.build(root, root / "audit.json")
            finally:
                MODULE.public_files = original_public_files
                MODULE.text_payload = original_text_payload
                MODULE.validate_env_example = original_validate_env
                MODULE.validate_release_files = original_validate_release
                MODULE.verify_judge_artifacts = original_verify_artifacts

            self.assertEqual(reads, [])
            findings = report["checks"]["forbidden_paths"]["findings"]
            self.assertEqual(findings[0]["reason"], "sealed evaluation material")

    def test_allowed_path_symlink_is_rejected_before_payload_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "repo"
            root.mkdir()
            external = parent / "external.txt"
            external.write_text("must-not-be-read", encoding="utf-8")
            alias = root / "fixtures" / "workspace" / "alias.txt"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(external)

            original_public_files = MODULE.public_files
            original_text_payload = MODULE.text_payload
            original_validate_env = MODULE.validate_env_example
            original_validate_release = MODULE.validate_release_files
            original_verify_artifacts = MODULE.verify_judge_artifacts
            reads: list[Path] = []
            try:
                MODULE.public_files = lambda _root, _output: [
                    Path("fixtures/workspace/alias.txt")
                ]
                MODULE.text_payload = lambda path: reads.append(path) or "unexpected"
                MODULE.validate_env_example = lambda _root: []
                MODULE.validate_release_files = lambda _root: []
                MODULE.verify_judge_artifacts = lambda _root: ([], [])
                report = MODULE.build(root, root / "audit.json")
            finally:
                MODULE.public_files = original_public_files
                MODULE.text_payload = original_text_payload
                MODULE.validate_env_example = original_validate_env
                MODULE.validate_release_files = original_validate_release
                MODULE.verify_judge_artifacts = original_verify_artifacts

            self.assertEqual(reads, [])
            findings = report["checks"]["forbidden_paths"]["findings"]
            self.assertEqual(len(findings), 1)
            self.assertIn("path uses a symlink", findings[0]["reason"])

    def test_env_example_rejects_nonempty_credential(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text('API_KEY="real-looking-value"\n', encoding="utf-8")
            self.assertEqual(len(MODULE.validate_env_example(root)), 1)

    def test_release_files_require_resolved_license_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in MODULE.REQUIRED_RELEASE_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n", encoding="utf-8")
            (root / "README.md").write_text(
                "## License\n\nTo be defined before the first implementation release.\n",
                encoding="utf-8",
            )
            self.assertEqual(MODULE.validate_release_files(root), ["README license section is unresolved"])

            (root / "README.md").write_text("## License\n\nApache-2.0.\n", encoding="utf-8")
            self.assertEqual(MODULE.validate_release_files(root), [])


if __name__ == "__main__":
    unittest.main()
