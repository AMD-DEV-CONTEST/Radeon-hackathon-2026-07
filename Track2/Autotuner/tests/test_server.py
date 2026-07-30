import tempfile
import unittest
from pathlib import Path

from autotuner.config import load_config
from autotuner.server import ServerManager
from autotuner.space import build_candidates


ROOT = Path(__file__).resolve().parents[1]


class ServerTests(unittest.TestCase):
    def test_vllm_command_contains_candidate_controls(self) -> None:
        config = load_config(ROOT / "configs" / "radeon.json")
        candidate = build_candidates(config)[0]
        profile = config.engines[0]
        with tempfile.TemporaryDirectory() as directory:
            manager = ServerManager(
                config, candidate, Path(directory), enable_profile=False
            )
            command = manager._build_command(profile)
        self.assertIn("--max-model-len", command)
        self.assertIn(str(candidate.max_model_len), command)
        self.assertIn("--gpu-memory-utilization", command)


if __name__ == "__main__":
    unittest.main()
