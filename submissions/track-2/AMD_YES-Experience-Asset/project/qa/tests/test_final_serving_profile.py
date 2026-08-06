import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class FinalServingProfileTests(unittest.TestCase):
    def test_p1_is_local_and_differs_from_s0_only_by_prefix_cache(self) -> None:
        profile = json.loads(
            (ROOT / "config/serving/final-p1-prefix-cache.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(profile["profile_id"], "P1-prefix-cache")
        self.assertEqual(profile["status"], "SELECTED_FOR_FINAL_LAUNCH")
        self.assertEqual(profile["model"]["served_model_name"], "Qwen3.5-9B")
        self.assertEqual(profile["server"]["host"], "127.0.0.1")
        self.assertEqual(profile["server"]["max_model_len"], 20000)
        self.assertEqual(profile["server"]["max_num_seqs"], 2)
        self.assertEqual(profile["server"]["cli_args"], ["--enable-prefix-caching"])
        self.assertEqual(profile["rollback"]["profile_id"], "S0")

    def test_final_wrapper_keeps_p1_default_and_s0_rollback(self) -> None:
        wrapper = (ROOT / "scripts/serve_final_vllm.sh").read_text(encoding="utf-8")

        self.assertIn('PROFILE="${SERVING_PROFILE:-P1-prefix-cache}"', wrapper)
        self.assertIn("P1-prefix-cache)", wrapper)
        self.assertIn("PROFILE_ARGS=(--enable-prefix-caching)", wrapper)
        self.assertIn("S0)", wrapper)
        self.assertIn('HOST="${VLLM_HOST:-127.0.0.1}"', wrapper)
        self.assertIn("verify_model_snapshot.py", wrapper)

    def test_final_installer_and_wrapper_share_the_frozen_runtime(self) -> None:
        installer = (ROOT / "scripts/install_vllm_qwen35_rocm721.sh").read_text(
            encoding="utf-8"
        )
        wrapper = (ROOT / "scripts/serve_final_vllm.sh").read_text(encoding="utf-8")
        pin = (ROOT / "config/runtime/vllm-rocm721-qwen35.env").read_text(
            encoding="utf-8"
        )

        expected_venv = 'VENV="${VLLM_VENV:-$ROOT/venvs/vllm-026-qwen35}"'
        self.assertIn(expected_venv, installer)
        self.assertIn(expected_venv, wrapper)
        self.assertRegex(pin, r"(?m)^VLLM_EXPECTED_VERSION=0\.26\.0\+rocm723$")
        self.assertRegex(pin, r"(?m)^VLLM_WHEEL_SHA256=[0-9a-f]{64}$")
        self.assertNotIn("Qwen2.5", installer)


if __name__ == "__main__":
    unittest.main()
