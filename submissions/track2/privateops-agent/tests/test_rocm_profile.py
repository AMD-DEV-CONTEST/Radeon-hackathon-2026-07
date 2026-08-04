import unittest

from privateops.rocm_profile import RadeonDeploymentProfile


class RadeonDeploymentProfileTests(unittest.TestCase):
    def test_competition_default_is_loopback_qwen_vllm_profile(self):
        profile = RadeonDeploymentProfile.competition_default()

        self.assertEqual(profile.model_name, "Qwen/Qwen2.5-7B-Instruct")
        self.assertEqual(profile.host, "127.0.0.1")
        self.assertEqual(profile.port, 8000)
        self.assertEqual(profile.max_model_len, 8192)
        self.assertEqual(profile.gpu_memory_utilization, 0.85)
        self.assertEqual(profile.chat_completions_endpoint, "http://127.0.0.1:8000/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
