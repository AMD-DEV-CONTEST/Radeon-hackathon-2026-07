from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "tokenfactory_corpus_runner.mjs"


class TokenFactoryOfficialContextTests(unittest.TestCase):
    def test_teacher_stages_receive_the_frozen_official_track_floor(
        self,
    ) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("const SAFE_RPM = 12;", source)
        self.assertIn("const MAX_IN_FLIGHT = 6;", source)
        self.assertIn("const MAX_PIPELINE_BATCHES = SAFE_RPM * 3;", source)
        self.assertIn("runBoundedRateLimited", source)
        self.assertIn('violations.push("upstream_http_error")', source)
        self.assertIn(
            "const MINIMUM_HEALTHY_CHUNK_PASS_RATE = 0.5;",
            source,
        )
        self.assertIn('stoppedReason = "quality_circuit_breaker"', source)
        self.assertIn(
            "Cover every listed ID before expanding any one record",
            source,
        )
        self.assertIn(
            '["Radeon action", "radeon_action"]',
            source,
        )
        self.assertIn(
            '["external blockers", "external_blockers"]',
            source,
        )
        self.assertIn('operation: "rename_key_only"', source)
        self.assertIn("raw_output_sha256", source)
        self.assertIn("output_normalizations", source)
        self.assertIn("priorQualityViolations", source)
        self.assertIn("prior_quality_violations", source)
        self.assertIn("official_failover_from", source)
        self.assertIn('priorQualityViolations.includes(', source)
        self.assertIn('"upstream_http_error"', source)
        self.assertIn("priorRepairHints", source)
        self.assertIn("prior_repair_hints", source)
        self.assertIn("must add exact keys", source)
        self.assertIn("Previous JSON parser error", source)
        self.assertIn("Construct the complete object skeleton", source)
        self.assertIn("emit no backslash characters", source)
        self.assertIn("const requestTemperature", source)
        self.assertIn("Math.max(stage.temperature, 0.20)", source)
        self.assertIn(
            "A prior attempt was rejected by the deterministic validator",
            source,
        )
        self.assertIn(
            "escape every backslash and quote according to RFC 8259",
            source,
        )
        verifier_block = source.split("verifier: {", 1)[1].split(
            "four_a_critic: {",
            1,
        )[0]
        self.assertIn('model: "Qwen3.6-35B-A3B"', verifier_block)
        self.assertIn("maxTokens: 2048", verifier_block)
        self.assertNotIn("MiniCPM5-1B", verifier_block)
        self.assertIn('violations.push("missing_todo_coverage")', source)

        for required in (
            "https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md",
            "https://modelscope.cn/events/299/比赛介绍",
            "2026-08-05 23:59 UTC+8",
            "2026-08-06 23:59 UTC+8",
            "67b26aba27ff24e20b7a42232c86182d0f249a4f",
            "0aff99d7aa46390c614107027487afe4e9399a7e1a28aae7f9bd83effea560e6",
            "75941378bc87da6da15ca2c7e7c22e476acefdebbd0e0b739d3e0aab3629c2d1",
            "at most",
            "three members",
            "40 points workflow integrity",
            "20 innovation/fun",
            "20 practical or social",
            "20 Radeon clarity",
            "At least one key inference must",
            "run locally on Radeon",
        ):
            self.assertIn(required, source)

        self.assertIn("do not invent such requirements", source)
        self.assertIn("KV-cache hits", source)
        self.assertIn(
            "official rules above as the global non-substitutable floor",
            source,
        )
        for required in (
            "all 1,500 TODOs bind",
            "1,100 compute-bearing TODOs",
            "DDP after memory-fit preflight",
            "FSDP2 only as the verified memory fallback",
            "device_map=auto is forbidden for training",
            "torch.cuda.device_count() == 1",
        ):
            self.assertIn(required, source)

        for required in (
            "const FOUR_A_DISTILLATION_CONTEXT",
            "OS26_CE002G",
            "OS26_CE003G",
            "OS26_CE014M",
            "OS26_CE001G",
            "OS26_CE010B",
            "OS26_FI093M",
            "OS26_CE021M",
            "OS26_MI026B",
            "OS26_MI003G",
            "OS26_BE037M",
            "OS26_DM049M",
            "OS26_DM000G",
            "OS26_MI042M",
            "Award status is not causal",
            "Public metadata does not authorize training",
            "four_a_deep_strategy",
            "four_a_deep_craft",
            "four_a_deep_effectiveness",
            "four_a_deep_synthesis",
            "FOUR_A_TRANSFER_REQUIRED_FIELDS",
            "research_reference",
            "four_a_transfer_invalid_admission",
            "four_a_transfer_unbound_reference",
            "four_a_context_sha256",
        ):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
