from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from radeonstay.config import Settings, load_env_file
from radeonstay.main import create_application


class SettingsSecurityTests(unittest.TestCase):
    def test_project_env_loads_without_overriding_exported_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "RADEONSTAY_PORT=9000\nRADEONSTAY_HOST='127.0.0.1'\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"RADEONSTAY_PORT": "8123"}, clear=True):
                load_env_file(env_path)
                self.assertEqual(os.environ["RADEONSTAY_PORT"], "8123")
                self.assertEqual(os.environ["RADEONSTAY_HOST"], "127.0.0.1")

    def test_public_binding_is_fail_closed_without_full_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RADEONSTAY_HOST": "0.0.0.0",
                "RADEONSTAY_PUBLIC_DEMO_ENABLED": "1",
            },
            clear=True,
        ):
            settings = Settings.from_env(Path.cwd())
            with self.assertRaisesRegex(ValueError, "Replace the default/example"):
                settings.validate_runtime_security()

    def test_loopback_binding_also_rejects_public_example_secrets(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env(Path.cwd())
            with self.assertRaisesRegex(ValueError, "Replace the default/example"):
                settings.validate_runtime_security()

    def test_runtime_secrets_require_at_least_32_bytes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RADEONSTAY_AUDIT_SECRET": "a" * 31,
                "RADEONSTAY_IDENTITY_SECRET": "b" * 31,
            },
            clear=True,
        ):
            settings = Settings.from_env(Path.cwd())
            with self.assertRaisesRegex(ValueError, "at least 32 bytes"):
                settings.validate_runtime_security()

    def test_non_local_model_endpoint_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"RADEONSTAY_MODEL_BASE_URL": "https://api.example.test/v1"},
            clear=True,
        ):
            settings = Settings.from_env(Path.cwd())
            with self.assertRaisesRegex(ValueError, "local/private"):
                settings.validate_private_model_endpoint()

    def test_custom_settings_cannot_bypass_application_security_validation(self) -> None:
        with patch.dict(
            os.environ,
            {"RADEONSTAY_MODEL_BASE_URL": "https://api.example.test/v1"},
            clear=True,
        ):
            settings = Settings.from_env(Path.cwd())
            with self.assertRaisesRegex(ValueError, "local/private"):
                create_application(settings)


if __name__ == "__main__":
    unittest.main()
