import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from privateops.agent import PrivateOpsAgent
from privateops.provider_runtime import ProviderConfiguration, RuntimeProviderManager


class ProviderConfigurationTests(unittest.TestCase):
    def test_configuration_requires_mode_endpoint_and_model(self):
        for payload, message in [
            ({"mode": "", "endpoint": "https://example.com/v1/chat/completions", "model": "model", "api_key": "key"}, "mode"),
            ({"mode": "remote", "endpoint": "", "model": "model", "api_key": "key"}, "endpoint"),
            ({"mode": "remote", "endpoint": "https://example.com/v1/chat/completions", "model": "", "api_key": "key"}, "Model"),
        ]:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, message):
                    ProviderConfiguration.from_payload(payload)

    def test_local_configuration_accepts_empty_key(self):
        configuration = ProviderConfiguration.from_payload(
            {
                "mode": "rocm-local",
                "endpoint": "http://127.0.0.1:8000/v1/chat/completions",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "api_key": "",
            }
        )

        self.assertEqual(configuration.mode, "rocm-local")
        self.assertFalse(configuration.allow_remote)
        self.assertEqual(configuration.api_key, "")

    def test_remote_configuration_requires_key(self):
        with self.assertRaisesRegex(ValueError, "API key"):
            ProviderConfiguration.from_payload(
                {
                    "mode": "remote",
                    "endpoint": "https://example.com/v1/chat/completions",
                    "model": "DeepSeek-V4-Flash",
                    "api_key": "",
                }
            )

    def test_local_configuration_rejects_remote_endpoint(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            ProviderConfiguration.from_payload(
                {
                    "mode": "rocm-local",
                    "endpoint": "https://example.com/v1/chat/completions",
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "api_key": "",
                }
            )

    def test_configuration_rejects_non_http_endpoint(self):
        with self.assertRaisesRegex(ValueError, "absolute HTTP URL"):
            ProviderConfiguration.from_payload(
                {"mode": "remote", "endpoint": "file:///tmp/model", "model": "model", "api_key": "key"}
            )


class RuntimeProviderManagerTests(unittest.TestCase):
    def _manager(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        knowledge = root / "knowledge"
        knowledge.mkdir()
        agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)
        return agent, RuntimeProviderManager(agent)

    @patch("privateops.provider_runtime.OpenAICompatibleProvider.complete", return_value="OK")
    def test_test_uses_temporary_provider_without_mutating_agent(self, complete):
        agent, manager = self._manager()
        original = agent.provider

        result = manager.test(
            {
                "mode": "remote",
                "endpoint": "https://developer.amd.com.cn/radeon/api/v1/chat/completions",
                "model": "DeepSeek-V4-Flash",
                "api_key": "secret-for-test",
            }
        )

        self.assertIs(agent.provider, original)
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "DeepSeek-V4-Flash")
        self.assertEqual(result["runtime_mode"], "amd-cloud-api")
        self.assertFalse(result["competition_eligible"])
        self.assertGreaterEqual(result["latency_ms"], 0)
        self.assertNotIn("secret-for-test", str(result))
        complete.assert_called_once()

    def test_apply_remote_provider_updates_safe_status_without_returning_key(self):
        agent, manager = self._manager()

        result = manager.apply(
            {
                "mode": "remote",
                "endpoint": "https://developer.amd.com.cn/radeon/api/v1/chat/completions",
                "model": "DeepSeek-V4-Flash",
                "api_key": "secret-for-test",
            }
        )

        self.assertEqual(result["runtime_mode"], "amd-cloud-api")
        self.assertFalse(result["competition_eligible"])
        self.assertEqual(result["model_name"], "DeepSeek-V4-Flash")
        self.assertNotIn("secret-for-test", str(result))
        self.assertEqual(agent.provider.api_key, "secret-for-test")
        self.assertNotIn("api_key", agent.status())

    def test_apply_loopback_provider_is_reported_as_rocm_local(self):
        agent, manager = self._manager()

        result = manager.apply(
            {
                "mode": "rocm-local",
                "endpoint": "http://127.0.0.1:8000/v1/chat/completions",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "api_key": "",
            }
        )

        self.assertEqual(result["runtime_mode"], "rocm-local")
        self.assertTrue(result["competition_eligible"])
        self.assertEqual(agent.provider.name, "openai-compatible-rocm")
        self.assertEqual(agent.status()["core_inference_location"], "same-instance loopback")

    def test_invalid_apply_keeps_current_provider(self):
        agent, manager = self._manager()
        original = agent.provider

        with self.assertRaises(ValueError):
            manager.apply({"mode": "remote", "endpoint": "not-a-url", "model": "model", "api_key": "key"})

        self.assertIs(agent.provider, original)


if __name__ == "__main__":
    unittest.main()
