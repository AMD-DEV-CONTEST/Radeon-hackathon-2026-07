import unittest
from pathlib import Path

from autotuner.agent import TuningAgent
from autotuner.config import load_config
from autotuner.space import build_candidates


ROOT = Path(__file__).resolve().parents[1]


class AgentTests(unittest.TestCase):
    def test_heuristic_proposal_is_in_allowed_set(self) -> None:
        config = load_config(ROOT / "configs" / "demo.json")
        candidates = build_candidates(config)
        allowed = candidates[1:30]
        proposal = TuningAgent(config).propose(
            allowed,
            [],
            candidates[0].model,
            allow_local_inference=False,
        )
        self.assertIn(proposal.candidate, allowed)
        self.assertTrue(proposal.hypothesis)


if __name__ == "__main__":
    unittest.main()
