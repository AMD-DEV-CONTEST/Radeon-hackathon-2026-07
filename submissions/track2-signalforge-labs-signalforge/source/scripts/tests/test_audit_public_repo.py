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
        self.assertIsNone(MODULE.forbidden_path_reason(Path("evidence/public-claims.json")))

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
