from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from radeonstay.config import Settings, load_env_file, request_configuration_sha256
from radeonstay.main import (
    build_startup_preflight,
    create_application,
    load_runtime_proof,
)


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
                self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)

    def test_environment_path_must_be_a_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.mkdir()

            with self.assertRaisesRegex(ValueError, "regular file"):
                load_env_file(env_path)

    def test_startup_preflight_rejects_a_nonregular_environment_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").mkdir()
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_env(root)
            health = {
                "ok": True,
                "inventory": {"ok": True},
                "policy_chunks": 1,
                "tools": ["hotel.quote_stay"],
                "runtime_proof": {
                    "required": False,
                    "evidence_eligible": False,
                },
            }
            with patch(
                "radeonstay.main.readiness_report",
                return_value=health,
            ), patch.object(
                Settings,
                "runtime_security_report",
                return_value={"ok": True},
            ):
                preflight = build_startup_preflight(settings, object())

            environment = preflight["checks"]["environment_file"]
            self.assertFalse(preflight["ok"])
            self.assertTrue(environment["present"])
            self.assertFalse(environment["ok"])

    def test_runtime_directory_and_database_artifacts_are_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "runtime" / "radeonstay.db"
            with patch.dict(
                os.environ,
                {"RADEONSTAY_DATABASE_PATH": str(database_path)},
                clear=True,
            ):
                settings = Settings.from_env(root)
            settings.ensure_runtime_dirs()
            self.assertEqual(
                stat.S_IMODE(database_path.parent.stat().st_mode),
                0o700,
            )

            for path in settings.database_related_paths():
                path.write_text("private", encoding="utf-8")
                path.chmod(0o644)
            settings.secure_runtime_files()

            self.assertTrue(settings.runtime_security_report()["ok"])
            for path in settings.database_related_paths():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_exact_sqlite_memory_database_skips_filesystem_permission_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {}, clear=True):
                settings = replace(
                    Settings.from_env(Path(directory)),
                    database_path=Path(":memory:"),
                )

            settings.ensure_runtime_dirs()
            settings.secure_runtime_files()
            report = settings.runtime_security_report()

            self.assertTrue(settings.uses_in_memory_database)
            self.assertEqual(settings.database_related_paths(), ())
            self.assertTrue(report["ok"])
            self.assertEqual(report["storage"], "memory")
            self.assertFalse(report["directory"]["required"])

    def test_model_thinking_flag_is_explicitly_configurable(self) -> None:
        with patch.dict(
            os.environ,
            {"RADEONSTAY_MODEL_ENABLE_THINKING": "1"},
            clear=True,
        ):
            self.assertTrue(Settings.from_env(Path.cwd()).model_enable_thinking)
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(Settings.from_env(Path.cwd()).model_enable_thinking)

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

    def test_loopback_public_tunnel_requires_ui_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                Settings.from_env(Path(directory)),
                audit_secret="a" * 32,
                identity_secret="b" * 32,
                public_demo_enabled=True,
                ui_username="",
                ui_password="",
            )

            with self.assertRaisesRegex(ValueError, "Public demo access"):
                settings.validate_runtime_security()

    def test_loopback_public_tunnel_enables_auth_and_hides_staff_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                Settings.from_env(Path(directory)),
                audit_secret="a" * 32,
                identity_secret="b" * 32,
                public_demo_enabled=True,
                ui_username="judge",
                ui_password="public-demo-password",
                isolated_demo=True,
                demo_run_id="judge-transient-model",
                runtime_proof_path=Path(directory) / "runtime-proof.json",
                runtime_instance_path=Path(directory) / "runtime-instance.json",
                database_path=(
                    Path(directory)
                    / "runtime"
                    / "radeonstay-judge-transient-model.db"
                ),
            )
            identity_provider = SimpleNamespace(
                demo_tokens=Mock(return_value={"Guest Alice": "token"}),
            )
            service = SimpleNamespace(identity_provider=identity_provider, close=Mock())
            api = SimpleNamespace(state=SimpleNamespace())

            with (
                patch("radeonstay.main.build_service", return_value=service),
                patch(
                    "radeonstay.main.build_startup_preflight",
                    return_value={
                        "ok": False,
                        "checks": {
                            name: {"ok": True}
                            for name in (
                                "environment_file",
                                "runtime_permissions",
                                "inventory",
                                "policies",
                                "tools",
                                "runtime_proof",
                                "demo_isolation",
                            )
                        }
                        | {"local_model": {"ok": False}},
                    },
                ),
                patch("radeonstay.main.create_api", return_value=api),
                patch("radeonstay.main.build_ui", return_value=object()),
                patch(
                    "radeonstay.main.gr.mount_gradio_app",
                    return_value="mounted",
                ) as mount,
            ):
                application = create_application(settings)

            self.assertEqual(application, "mounted")
            self.assertTrue(api.state.operations_enabled)
            identity_provider.demo_tokens.assert_called_once_with(include_staff=False)
            self.assertEqual(
                mount.call_args.kwargs["auth"],
                ("judge", "public-demo-password"),
            )

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

    def test_custom_settings_cannot_bypass_application_security_validation(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {"RADEONSTAY_MODEL_BASE_URL": "https://api.example.test/v1"},
            clear=True,
        ):
            settings = Settings.from_env(Path.cwd())
            with self.assertRaisesRegex(ValueError, "local/private"):
                create_application(settings)

    def test_nested_runtime_proof_is_normalized_and_strictly_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof_path = root / "runtime-proof.json"
            proof_path.write_text(
                json.dumps(
                    {
                        "status": "verified",
                        "binding_valid": True,
                        "telemetry_active": True,
                        "request_configuration_sha256": (
                            request_configuration_sha256(
                                {
                                    "thinking_enabled": False,
                                    "schema_constrained": True,
                                    "fused_plan_evidence": True,
                                }
                            )
                        ),
                        "service_configuration_sha256": "e" * 64,
                        "inference_identity": {
                            "model_alias": "qwen3.6-35b-a3b-q6k",
                            "model_file_sha256": "a" * 64,
                            "llama_server_sha256": "b" * 64,
                        },
                        "single_request_rocm_observation": {
                            "rocm_version": "7.2.1",
                            "gfx_target": "gfx1100",
                            "reported_product_string": "AMD Radeon Graphics",
                            "compute_units": 96,
                            "offloaded_model_layers": "41/41",
                        },
                    }
                ),
                encoding="utf-8",
            )
            settings = replace(
                Settings.from_env(root),
                runtime_proof_path=proof_path,
            )

            proof = load_runtime_proof(settings)

            self.assertTrue(proof["required"])
            self.assertTrue(proof["evidence_eligible"])
            self.assertTrue(proof["model_alias_matches_config"])
            self.assertTrue(proof["request_configuration_matches_config"])
            self.assertEqual(proof["gpu_arch"], "gfx1100")
            self.assertEqual(proof["offloaded_layers"], 41)
            self.assertEqual(proof["total_layers"], 41)

            payload = json.loads(proof_path.read_text(encoding="utf-8"))
            payload["single_request_rocm_observation"][
                "offloaded_model_layers"
            ] = "42/42"
            proof_path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertFalse(load_runtime_proof(settings)["evidence_eligible"])

            payload["single_request_rocm_observation"][
                "offloaded_model_layers"
            ] = "41/41"
            payload["binding_valid"] = False
            proof_path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertFalse(load_runtime_proof(settings)["evidence_eligible"])

            payload.update(
                {
                    "schema_version": 2,
                    "status": "accepted_final",
                    "run_id": "matrix-E",
                    "binding_valid": True,
                    "c2_commit": "c" * 40,
                    "reference_label": "A",
                    "winner_label": "E",
                    "winner_assessment_accepted": True,
                    "winner_report_sha256": "d" * 64,
                    "winner_core_metric": "concurrency_4_throughput",
                    "winner_core_improvement_percent": 12.5,
                    "candidate_source_index_sha256": "1" * 64,
                    "quality_qualified_candidate_count": 8,
                    "quality_negative_label": "none",
                    "quality_negative_manifest_sha256": None,
                    "stability_report_sha256": "2" * 64,
                    "stability_run_count": 5,
                    "stability_run_ids_sha256": "3" * 64,
                    "soak_report_sha256": "4" * 64,
                    "soak_run_id": "soak-E",
                    "soak_duration_seconds": 1800.0,
                    "final_evidence_accepted": True,
                }
            )
            proof_path.write_text(json.dumps(payload), encoding="utf-8")
            accepted = load_runtime_proof(settings)
            self.assertTrue(accepted["release_metadata_valid"])
            self.assertTrue(accepted["evidence_eligible"])

            payload["request_configuration_sha256"] = "f" * 64
            proof_path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertFalse(load_runtime_proof(settings)["evidence_eligible"])
            payload["request_configuration_sha256"] = (
                settings.request_configuration_sha256
            )

            payload["winner_assessment_accepted"] = False
            proof_path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertFalse(load_runtime_proof(settings)["evidence_eligible"])

    def test_isolated_demo_uses_run_bound_database_and_allows_safe_reopen(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {
                    "RADEONSTAY_DATABASE_PATH": "runtime/radeonstay.db",
                    "RADEONSTAY_ISOLATED_DEMO": "1",
                    "RADEONSTAY_DEMO_RUN_ID": "judge-run-001",
                },
                clear=True,
            ):
                settings = Settings.from_env(root)

            self.assertEqual(
                settings.database_path.name,
                "radeonstay-judge-run-001.db",
            )
            settings.ensure_runtime_dirs()
            settings.database_path.write_bytes(b"existing-demo")
            settings.ensure_runtime_dirs()

            self.assertEqual(
                stat.S_IMODE(settings.database_path.stat().st_mode),
                0o600,
            )

    def test_isolated_demo_rejects_insecure_or_orphaned_database_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {
                    "RADEONSTAY_DATABASE_PATH": "runtime/radeonstay.db",
                    "RADEONSTAY_ISOLATED_DEMO": "1",
                    "RADEONSTAY_DEMO_RUN_ID": "judge-run-strict",
                },
                clear=True,
            ):
                settings = Settings.from_env(root)

            settings.ensure_runtime_dirs()
            settings.database_path.chmod(0o640)
            with self.assertRaisesRegex(ValueError, "mode 0600"):
                settings.ensure_runtime_dirs()

            settings.database_path.chmod(0o600)
            wal_path = Path(f"{settings.database_path}-wal")
            wal_path.symlink_to(settings.database_path)
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                settings.ensure_runtime_dirs()
            wal_path.unlink()
            wal_path.mkdir()
            with self.assertRaisesRegex(ValueError, "regular file"):
                settings.ensure_runtime_dirs()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {
                    "RADEONSTAY_DATABASE_PATH": "runtime/radeonstay.db",
                    "RADEONSTAY_ISOLATED_DEMO": "1",
                    "RADEONSTAY_DEMO_RUN_ID": "judge-run-orphan",
                },
                clear=True,
            ):
                settings = Settings.from_env(root)
            settings.database_path.parent.mkdir(mode=0o700)
            orphaned_wal = Path(f"{settings.database_path}-wal")
            orphaned_wal.write_bytes(b"orphaned")
            orphaned_wal.chmod(0o600)

            with self.assertRaisesRegex(ValueError, "orphaned isolated SQLite"):
                settings.ensure_runtime_dirs()

    def test_custom_isolated_settings_cannot_bypass_database_run_binding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {}, clear=True):
                settings = replace(
                    Settings.from_env(root),
                    audit_secret="a" * 32,
                    identity_secret="b" * 32,
                    isolated_demo=True,
                    demo_run_id="judge-run-custom",
                    runtime_instance_path=root / "runtime" / "instance.json",
                    database_path=root / "runtime" / "radeonstay.db",
                )

            self.assertFalse(settings.isolated_database_run_bound)
            with self.assertRaisesRegex(ValueError, "exact demo run ID"):
                settings.validate_runtime_security()
            with self.assertRaisesRegex(ValueError, "exact demo run ID"):
                settings.ensure_runtime_dirs()

    def test_isolated_competition_demo_forbids_deterministic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {}, clear=True):
                settings = replace(
                    Settings.from_env(root),
                    audit_secret="a" * 32,
                    identity_secret="b" * 32,
                    deterministic_mode=True,
                    isolated_demo=True,
                    demo_run_id="judge-real-model-only",
                    database_path=(
                        root
                        / "runtime"
                        / "radeonstay-judge-real-model-only.db"
                    ),
                )

            with self.assertRaisesRegex(ValueError, "forbids deterministic fallback"):
                settings.validate_runtime_security()

    def test_isolated_database_creation_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {
                    "RADEONSTAY_DATABASE_PATH": "runtime/radeonstay.db",
                    "RADEONSTAY_ISOLATED_DEMO": "1",
                    "RADEONSTAY_DEMO_RUN_ID": "judge-run-race",
                },
                clear=True,
            ):
                settings = Settings.from_env(root)

            with patch(
                "radeonstay.config.os.open",
                side_effect=FileExistsError,
            ) as open_mock, self.assertRaisesRegex(ValueError, "exclusive creation"):
                settings.ensure_runtime_dirs()
            self.assertTrue(open_mock.call_args.args[1] & os.O_EXCL)

    def test_isolated_demo_readiness_requires_eligible_runtime_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {}, clear=True):
                settings = replace(
                    Settings.from_env(Path(directory)),
                    isolated_demo=True,
                    demo_run_id="judge-run-proof",
                    runtime_proof_path=None,
                    database_path=(
                        Path(directory)
                        / "runtime"
                        / "radeonstay-judge-run-proof.db"
                    ),
                )
            proof = load_runtime_proof(settings)
            self.assertTrue(settings.runtime_proof_required)
            self.assertTrue(settings.runtime_instance_required)
            self.assertTrue(proof["required"])
            self.assertFalse(proof["evidence_eligible"])

            health = {
                "ok": True,
                "inventory": {"ok": True},
                "policy_chunks": 1,
                "tools": ["hotel.quote_stay"],
                "runtime_proof": proof,
            }
            with patch(
                "radeonstay.main.readiness_report",
                return_value=health,
            ), patch.object(
                Settings,
                "runtime_security_report",
                return_value={"ok": True},
            ):
                preflight = build_startup_preflight(settings, object())

            self.assertFalse(preflight["ok"])
            self.assertFalse(preflight["checks"]["runtime_proof"]["ok"])
            self.assertFalse(preflight["checks"]["demo_isolation"]["ok"])

    def test_isolated_demo_runtime_proof_must_match_the_unique_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof_path = root / "proof.json"
            proof_path.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = replace(
                    Settings.from_env(root),
                    isolated_demo=True,
                    demo_run_id="judge-run-current",
                    runtime_proof_path=proof_path,
                    runtime_instance_path=root / "runtime-instance.json",
                    database_path=(
                        root / "runtime" / "radeonstay-judge-run-current.db"
                    ),
                )
            health = {
                "ok": True,
                "inventory": {"ok": True},
                "policy_chunks": 1,
                "tools": ["hotel.quote_stay"],
                "runtime_proof": {
                    "required": True,
                    "evidence_eligible": True,
                    "process_binding_valid": True,
                    "run_id": "judge-run-stale",
                },
            }
            with patch(
                "radeonstay.main.readiness_report",
                return_value=health,
            ), patch.object(
                Settings,
                "runtime_security_report",
                return_value={"ok": True},
            ):
                stale = build_startup_preflight(settings, object())
                health["runtime_proof"]["run_id"] = "judge-run-current"
                current = build_startup_preflight(settings, object())

            self.assertFalse(stale["ok"])
            self.assertFalse(
                stale["checks"]["demo_isolation"]["runtime_proof_run_match"]
            )
            self.assertTrue(current["ok"])
            self.assertTrue(
                current["checks"]["demo_isolation"]["runtime_proof_run_match"]
            )
            self.assertTrue(
                current["checks"]["demo_isolation"]["database_run_match"]
            )

    def test_radeon_cloud_free_requires_explicit_bonus_mode_and_private_key(
        self,
    ) -> None:
        environment = {
            "RADEONSTAY_INFERENCE_PROVIDER": "radeon_cloud_free",
            "RADEONSTAY_RADEON_CLOUD_BASE_URL": (
                "https://developer.amd.com.cn/radeon/api/v1"
            ),
            "RADEONSTAY_RADEON_CLOUD_MODEL": "Qwen3.6-35B-A3B",
            "RADEONSTAY_RADEON_CLOUD_API_KEY": "secret-cloud-key-1234567890",
            "RADEONSTAY_AUDIT_SECRET": "a" * 32,
            "RADEONSTAY_IDENTITY_SECRET": "b" * 32,
        }
        with patch.dict(os.environ, environment, clear=True):
            disabled = Settings.from_env(Path.cwd())
            with self.assertRaisesRegex(ValueError, "BONUS_DEMO"):
                disabled.validate_runtime_security()

        environment["RADEONSTAY_BONUS_DEMO"] = "1"
        with patch.dict(os.environ, environment, clear=True):
            enabled = Settings.from_env(Path.cwd())
            enabled.validate_runtime_security()

        self.assertTrue(enabled.uses_radeon_cloud_free)
        self.assertFalse(enabled.local_only)
        self.assertNotIn("secret-cloud-key", repr(enabled))

        invalid_mode = replace(
            enabled,
            radeon_cloud_structured_mode="yaml",
        )
        with self.assertRaisesRegex(ValueError, "STRUCTURED_MODE"):
            invalid_mode.validate_runtime_security()

    def test_radeon_cloud_free_rejects_endpoint_drift_and_local_proof_mix(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RADEONSTAY_INFERENCE_PROVIDER": "radeon_cloud_free",
                "RADEONSTAY_RADEON_CLOUD_BASE_URL": "https://example.test/v1",
                "RADEONSTAY_RADEON_CLOUD_API_KEY": "secret-cloud-key-1234567890",
                "RADEONSTAY_BONUS_DEMO": "1",
                "RADEONSTAY_AUDIT_SECRET": "a" * 32,
                "RADEONSTAY_IDENTITY_SECRET": "b" * 32,
            },
            clear=True,
        ):
            wrong_host = Settings.from_env(Path.cwd())
            with self.assertRaisesRegex(ValueError, "allow-listed"):
                wrong_host.validate_runtime_security()

        valid = replace(
            wrong_host,
            radeon_cloud_base_url=(
                "https://developer.amd.com.cn/radeon/api/v1"
            ),
            isolated_demo=True,
        )
        with self.assertRaisesRegex(ValueError, "isolated-demo"):
            valid.validate_runtime_security()

    def test_memory_database_sentinel_survives_environment_loading(self) -> None:
        with patch.dict(
            os.environ,
            {"RADEONSTAY_DATABASE_PATH": ":memory:"},
            clear=True,
        ):
            settings = Settings.from_env(Path.cwd())

        self.assertTrue(settings.uses_in_memory_database)
        self.assertEqual(str(settings.database_path), ":memory:")


if __name__ == "__main__":
    unittest.main()
