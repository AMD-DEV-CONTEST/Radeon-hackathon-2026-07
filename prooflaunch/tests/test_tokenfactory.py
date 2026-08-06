from __future__ import annotations

import json
import unittest

from prooflaunch_remix.tokenfactory import (
    TOKEN_FACTORY_API_KEY_ENV,
    TOKEN_FACTORY_CHAT_URL,
    TOKEN_FACTORY_PROVIDER,
    TOKEN_FACTORY_PUBLIC_MODELS,
    TokenFactoryCallError,
    TokenFactoryClient,
    TokenFactoryConfigurationError,
    TokenFactoryHttpResponse,
    TokenFactoryQuotaError,
    TokenFactoryQuotaGuard,
    TokenFactoryQuotaPolicy,
    TokenFactoryQuotaSnapshot,
    tokenfactory_policy,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, **request):
        self.calls.append(request)
        return self.responses.pop(0)


def response(status, payload=None, **headers):
    body = (
        json.dumps(payload).encode("utf-8")
        if payload is not None
        else b""
    )
    return TokenFactoryHttpResponse(status, headers, body)


class TokenFactoryTests(unittest.TestCase):
    def test_policy_makes_official_provider_first_and_fallback_bounded(self) -> None:
        policy = tokenfactory_policy()
        self.assertEqual(
            policy["external_inference_priority"],
            [TOKEN_FACTORY_PROVIDER, "approved_third_party_fallback"],
        )
        self.assertEqual(
            policy["official_chat_completions_url"],
            TOKEN_FACTORY_CHAT_URL,
        )
        self.assertEqual(
            policy["other_online_model_apis_allowed"],
            "approved_fallback_only",
        )
        self.assertEqual(policy["competition_core_path"], "local_radeon_only")
        self.assertFalse(policy["secret_persistence_allowed"])
        self.assertEqual(policy["quota"]["daily_budget_usd"], 10.0)
        self.assertEqual(policy["quota"]["daily_reserve_usd"], 0.0001)
        self.assertEqual(policy["quota"]["provider_rpm_limit"], 30)
        self.assertEqual(policy["quota"]["client_rpm_limit"], 24)
        self.assertTrue(
            policy["quota"]["profile_snapshot_required_before_large_batch"]
        )

    def test_missing_key_fails_closed(self) -> None:
        with self.assertRaises(TokenFactoryConfigurationError):
            TokenFactoryClient(api_key="")

    def test_502_fails_over_only_inside_official_model_allowlist(self) -> None:
        transport = FakeTransport(
            [
                response(502, {"detail": "Model gateway is unavailable"}),
                response(
                    200,
                    {
                        "id": "official-response",
                        "choices": [
                            {
                                "message": {"content": "approved"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"total_tokens": 7},
                    },
                    **{"x-request-id": "safe-request-id"},
                ),
            ]
        )
        client = TokenFactoryClient(
            api_key="test-secret-never-persist",
            transport=transport,
            sleep=lambda _: None,
            now=lambda: "2026-07-30T00:00:00+00:00",
        )
        result = client.complete(
            [{"role": "user", "content": "hello"}],
            models=TOKEN_FACTORY_PUBLIC_MODELS[:2],
            purpose="test official failover",
            retry_rounds=0,
        )
        self.assertEqual(result.model, "DeepSeek-V4-Flash")
        self.assertEqual(result.content, "approved")
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(
            all(call["url"] == TOKEN_FACTORY_CHAT_URL for call in transport.calls)
        )
        self.assertEqual(
            [call["payload"]["model"] for call in transport.calls],
            list(TOKEN_FACTORY_PUBLIC_MODELS[:2]),
        )
        self.assertTrue(
            all(
                call["payload"]["chat_template_kwargs"]
                == {"enable_thinking": False}
                for call in transport.calls
            )
        )
        self.assertTrue(
            all(
                call["headers"]["Authorization"]
                == "Bearer test-secret-never-persist"
                for call in transport.calls
            )
        )
        receipt_text = json.dumps(result.receipt, sort_keys=True)
        self.assertNotIn("test-secret-never-persist", receipt_text)
        self.assertNotIn("hello", receipt_text)
        self.assertEqual(
            result.receipt["credential"]["source"],
            TOKEN_FACTORY_API_KEY_ENV,
        )
        self.assertEqual(
            result.receipt["evidence_boundary"],
            "external_advisory_not_local_radeon_execution",
        )

    def test_unknown_provider_model_is_rejected_before_transport(self) -> None:
        transport = FakeTransport([])
        client = TokenFactoryClient(
            api_key="test-secret",
            transport=transport,
        )
        with self.assertRaises(TokenFactoryConfigurationError):
            client.complete(
                [{"role": "user", "content": "hello"}],
                models=("non-tokenfactory-model",),
                purpose="must fail closed",
            )
        self.assertEqual(transport.calls, [])

    def test_all_official_failures_emit_secret_free_blocked_receipt(self) -> None:
        transport = FakeTransport(
            [
                response(502),
                response(502),
                response(502),
            ]
        )
        client = TokenFactoryClient(
            api_key="another-secret-never-persist",
            transport=transport,
            sleep=lambda _: None,
            now=lambda: "2026-07-30T00:00:00+00:00",
        )
        with self.assertRaises(TokenFactoryCallError) as captured:
            client.complete(
                [{"role": "user", "content": "private prompt"}],
                purpose="official availability probe",
                retry_rounds=0,
            )
        receipt = captured.exception.receipt
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["attempt_count"], 3)
        self.assertTrue(
            all(
                attempt["error_code"] == "model_gateway_unavailable"
                for attempt in receipt["attempts"]
            )
        )
        serialized = json.dumps(receipt, sort_keys=True)
        self.assertNotIn("another-secret-never-persist", serialized)
        self.assertNotIn("private prompt", serialized)

    def test_auth_failure_stops_without_model_hammering(self) -> None:
        transport = FakeTransport([response(401)])
        client = TokenFactoryClient(
            api_key="expired-secret",
            transport=transport,
            sleep=lambda _: None,
        )
        with self.assertRaises(TokenFactoryCallError) as captured:
            client.complete(
                [{"role": "user", "content": "hello"}],
                purpose="auth test",
                retry_rounds=1,
            )
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(
            captured.exception.receipt["attempts"][0]["error_code"],
            "authentication_rejected",
        )

    def test_invalid_success_contract_fails_closed(self) -> None:
        transport = FakeTransport([response(200, {"choices": []})])
        client = TokenFactoryClient(
            api_key="test-secret",
            transport=transport,
            sleep=lambda _: None,
        )
        with self.assertRaises(TokenFactoryCallError) as captured:
            client.complete(
                [{"role": "user", "content": "hello"}],
                models=("Qwen3.6-35B-A3B",),
                purpose="contract test",
                retry_rounds=0,
            )
        self.assertEqual(
            captured.exception.receipt["attempts"][0]["error_code"],
            "invalid_response_contract",
        )

    def test_reasoning_only_token_exhaustion_fails_over(self) -> None:
        transport = FakeTransport(
            [
                response(
                    200,
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "",
                                    "reasoning": "internal reasoning omitted",
                                },
                                "finish_reason": "length",
                            }
                        ]
                    },
                ),
                response(
                    200,
                    {
                        "choices": [
                            {
                                "message": {"content": "usable result"},
                                "finish_reason": "stop",
                            }
                        ]
                    },
                ),
            ]
        )
        client = TokenFactoryClient(
            api_key="test-secret",
            transport=transport,
            sleep=lambda _: None,
        )
        result = client.complete(
            [{"role": "user", "content": "hello"}],
            models=TOKEN_FACTORY_PUBLIC_MODELS[:2],
            purpose="reasoning budget contract",
            retry_rounds=0,
        )
        self.assertEqual(result.model, "DeepSeek-V4-Flash")
        self.assertEqual(
            result.receipt["attempts"][0]["error_code"],
            "reasoning_budget_exhausted",
        )
        self.assertTrue(
            result.receipt["attempts"][0]["reasoning_field_present"]
        )
        self.assertNotIn(
            "internal reasoning omitted",
            json.dumps(result.receipt, sort_keys=True),
        )

    def test_token_ceiling_blocks_before_transport(self) -> None:
        transport = FakeTransport([])
        policy = TokenFactoryQuotaPolicy(max_tokens_per_request=512)
        client = TokenFactoryClient(
            api_key="test-secret",
            transport=transport,
            quota_guard=TokenFactoryQuotaGuard(policy),
        )
        with self.assertRaises(TokenFactoryQuotaError):
            client.complete(
                [{"role": "user", "content": "hello"}],
                models=("DeepSeek-V4-Flash",),
                purpose="bounded tokens",
                max_tokens=513,
                retry_rounds=0,
            )
        self.assertEqual(transport.calls, [])

    def test_daily_reserve_blocks_worst_case_batch(self) -> None:
        transport = FakeTransport([])
        snapshot = TokenFactoryQuotaSnapshot(
            used_usd=9.996,
            remaining_usd=0.004,
            tokens_today=292,
            reset_at="2026-07-31T00:00:00Z",
            observed_at="2026-07-30T08:02:15Z",
        )
        client = TokenFactoryClient(
            api_key="test-secret",
            transport=transport,
            quota_guard=TokenFactoryQuotaGuard(snapshot=snapshot),
        )
        with self.assertRaises(TokenFactoryQuotaError):
            client.complete(
                [{"role": "user", "content": "hello"}],
                models=("DeepSeek-V4-Flash",),
                purpose="reserve boundary",
                retry_rounds=0,
                estimated_cost_per_attempt_usd=0.05,
            )
        self.assertEqual(transport.calls, [])

    def test_client_rpm_headroom_blocks_worst_case_batch(self) -> None:
        transport = FakeTransport([])
        policy = TokenFactoryQuotaPolicy(
            provider_rpm_limit=30,
            client_rpm_limit=1,
        )
        client = TokenFactoryClient(
            api_key="test-secret",
            transport=transport,
            quota_guard=TokenFactoryQuotaGuard(
                policy,
                monotonic=lambda: 10.0,
            ),
        )
        with self.assertRaises(TokenFactoryQuotaError):
            client.complete(
                [{"role": "user", "content": "hello"}],
                models=("Qwen3.6-35B-A3B", "DeepSeek-V4-Flash"),
                purpose="RPM headroom",
                retry_rounds=0,
            )
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
