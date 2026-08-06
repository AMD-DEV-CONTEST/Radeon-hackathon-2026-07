from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from prooflaunch_remix.tokenfactory import TokenFactoryHttpResponse


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_v10_frontier_free_api_sprint",
    ROOT / "scripts/run_v10_frontier_free_api_sprint.py",
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def candidate(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": "groq-test-free",
        "provider": "groq",
        "api_model": "openai/gpt-oss-20b",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "access_class": "zero_cost_rate_limited",
        "maximum_call_cost_usd": 0.0,
    }
    row.update(overrides)
    return row


class FakeTransport:
    def __init__(self, response: TokenFactoryHttpResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post_json(self, **kwargs: object) -> TokenFactoryHttpResponse:
        self.calls.append(dict(kwargs))
        return self.response


class FrontierFreeApiRunnerTests(unittest.TestCase):
    def test_http_failure_is_recorded_without_crashing_or_persisting_key(self) -> None:
        transport = FakeTransport(TokenFactoryHttpResponse(429, {}, b"rate limited"))
        observation, receipt = RUNNER._call(
            candidate(),
            "schema",
            "Synthetic public brief",
            api_key="secret-that-must-not-appear",
            timeout_seconds=1,
            transport=transport,
        )
        self.assertIsNone(observation)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["error_code"], "http_429")
        self.assertNotIn("secret-that-must-not-appear", repr(receipt))

    def test_non_zero_cost_candidate_is_rejected_before_transport(self) -> None:
        transport = FakeTransport(TokenFactoryHttpResponse(200, {}, b"{}"))
        with self.assertRaisesRegex(RuntimeError, "non-zero-cost"):
            RUNNER._call(
                candidate(access_class="developer_credits", maximum_call_cost_usd=0.1),
                "schema",
                "Synthetic public brief",
                api_key="secret",
                timeout_seconds=1,
                transport=transport,
            )
        self.assertEqual(transport.calls, [])

    def test_positive_call_cost_is_rejected_before_transport(self) -> None:
        transport = FakeTransport(TokenFactoryHttpResponse(200, {}, b"{}"))
        with self.assertRaisesRegex(RuntimeError, "exact zero"):
            RUNNER._call(
                candidate(maximum_call_cost_usd=0.000001),
                "schema",
                "Synthetic public brief",
                api_key="secret",
                timeout_seconds=1,
                transport=transport,
            )
        self.assertEqual(transport.calls, [])

    def test_cloudflare_account_id_is_validated_before_transport(self) -> None:
        transport = FakeTransport(TokenFactoryHttpResponse(200, {}, b"{}"))
        route = candidate(
            provider="cloudflare_workers_ai",
            endpoint=(
                "https://api.cloudflare.com/client/v4/accounts/"
                "{CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions"
            ),
        )
        with patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID": "../bad"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "invalid format"):
                RUNNER._call(
                    route,
                    "schema",
                    "Synthetic public brief",
                    api_key="secret",
                    timeout_seconds=1,
                    transport=transport,
                )
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
