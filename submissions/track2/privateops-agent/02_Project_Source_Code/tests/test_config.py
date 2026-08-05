import unittest
from unittest.mock import patch

from privateops.config import Settings, validate_model_endpoint


class ConfigTests(unittest.TestCase):
    def test_rocm_local_accepts_loopback_model_endpoint(self):
        env = {
            "PRIVATEOPS_PROVIDER_MODE": "rocm-local",
            "PRIVATEOPS_MODEL_ENDPOINT": "http://127.0.0.1:8000/v1/chat/completions",
            "PRIVATEOPS_MODEL_NAME": "Qwen/Qwen2.5-7B-Instruct",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.provider_mode, "rocm-local")
        self.assertEqual(settings.model_endpoint, env["PRIVATEOPS_MODEL_ENDPOINT"])
        self.assertEqual(settings.public_status()["model_endpoint"], "http://127.0.0.1:8000/v1/chat/completions")
        self.assertTrue(settings.public_status()["competition_eligible"])

    def test_remote_development_endpoint_is_never_competition_eligible(self):
        env = {
            "PRIVATEOPS_PROVIDER_MODE": "development",
            "PRIVATEOPS_ALLOW_REMOTE_MODEL": "true",
            "PRIVATEOPS_MODEL_ENDPOINT": "https://models.example.com/v1/chat/completions",
        }
        with patch.dict("os.environ", env, clear=True):
            status = Settings.from_env().public_status()

        self.assertFalse(status["competition_eligible"])

    def test_remote_model_endpoint_is_rejected_by_default(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            validate_model_endpoint("https://models.example.com/v1/chat/completions")

    def test_public_status_never_exposes_model_api_key(self):
        env = {
            "PRIVATEOPS_PROVIDER_MODE": "development",
            "PRIVATEOPS_MODEL_API_KEY": "super-secret-value",
        }
        with patch.dict("os.environ", env, clear=True):
            status = Settings.from_env().public_status()

        self.assertNotIn("super-secret-value", str(status))
        self.assertNotIn("model_api_key", status)


if __name__ == "__main__":
    unittest.main()
