import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "run_pi05_libero_action_steps_confirmation_rocm.py"
SPEC = importlib.util.spec_from_file_location("pi05_action_steps_confirmation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def fixtures():
    config = {
        "protocol_id": "pi05-libero-action-steps-confirmation-v1",
        "phase": "confirmation",
        "units": 400,
        "development_protocol": "pi05-libero-action-steps-full-development-v1",
        "benchmark_manifest_protocol": "pi05-libero-public-benchmark-v2",
        "benchmark_manifest_canonical_sha256": "manifest",
    }
    manifest = {
        "protocol_id": "pi05-libero-public-benchmark-v2",
        "manifest_sha256": "manifest",
        "benchmark": {"action_chunk_size": 50},
    }
    development = {
        "protocol_id": "pi05-libero-action-steps-full-development-v1",
        "selection": {
            "status": "candidate_frozen",
            "selected_action_steps": 8,
            "candidate_strictly_better": True,
            "confirmation_may_start": True,
        },
    }
    return config, manifest, development


class PI05ActionStepsConfirmationTests(unittest.TestCase):
    def test_requires_development_frozen_candidate(self) -> None:
        config, manifest, development = fixtures()
        self.assertEqual(MODULE.validate_inputs(config, manifest, development), 8)
        development["selection"]["status"] = "control_retained"
        with self.assertRaisesRegex(ValueError, "did not freeze"):
            MODULE.validate_inputs(config, manifest, development)

    def test_higher_rate_is_not_automatically_statistical_superiority(self) -> None:
        keys = [("suite", index, 0) for index in range(400)]
        baseline = {key: index < 385 for index, key in enumerate(keys)}
        candidate = dict(baseline)
        candidate[keys[385]] = True

        claims = MODULE.build_claims(baseline, candidate)

        self.assertTrue(claims["candidate_strictly_higher_than_local_pi05"])
        self.assertFalse(claims["paired_local_superiority_at_alpha_0_05"])
        self.assertFalse(claims["pi06_superiority_claim_permitted"])


if __name__ == "__main__":
    unittest.main()
