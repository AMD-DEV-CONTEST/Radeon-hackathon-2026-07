from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prooflaunch_remix.inference_gateway import (
    OFFICIAL_FINE_TUNING_PARITY_CONTRACT,
    InferenceGatewayCallError,
    InferenceGatewayPolicyError,
    InferenceScope,
    OllamaLocalClient,
    OllamaLocalSpec,
    OpenAICompatibleThirdPartyClient,
    ResilientInferenceGateway,
    THIRD_PARTY_CONFIG_SCHEMA,
    ThirdPartyProviderSpec,
    load_third_party_provider_specs,
)
from prooflaunch_remix.gtm_text_challenger import (
    build_text_challenger_receipt,
    validate_text_candidate,
)
from prooflaunch_remix.tokenfactory import (
    TOKEN_FACTORY_PUBLIC_MODELS,
    TokenFactoryClient,
    TokenFactoryHttpResponse,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, **request):
        self.calls.append(request)
        return self.responses.pop(0)


class FakeOllamaTransport:
    def __init__(self, inventory, responses):
        self.inventory = inventory
        self.responses = list(responses)
        self.calls = []

    def get_json(self, **request):
        self.calls.append(("GET", request))
        return self.inventory

    def post_json(self, **request):
        self.calls.append(("POST", request))
        return self.responses.pop(0)


def response(status, payload=None):
    return TokenFactoryHttpResponse(
        status=status,
        headers={},
        body=(
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else b""
        ),
    )


def third_party_spec(**overrides):
    values = {
        "provider": "approved_vendor",
        "base_url": "https://inference.example.com/v1",
        "model": "quality-model",
        "api_key_env": "TEST_THIRD_PARTY_API_KEY",
        "data_processing_approved": True,
        "license_reviewed": True,
        "maximum_call_cost_usd": 0.25,
    }
    values.update(overrides)
    return ThirdPartyProviderSpec(**values)


class ResilientInferenceGatewayTests(unittest.TestCase):
    def _official(self, transport):
        return TokenFactoryClient(
            api_key="official-secret",
            transport=transport,
            sleep=lambda _: None,
            now=lambda: "2026-07-30T00:00:00+00:00",
        )

    def test_official_success_never_calls_third_party(self) -> None:
        official_transport = FakeTransport(
            [
                response(
                    200,
                    {
                        "id": "official",
                        "choices": [
                            {
                                "message": {"content": "official result"},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                )
            ]
        )
        third_transport = FakeTransport([])
        with patch.dict(
            os.environ,
            {"TEST_THIRD_PARTY_API_KEY": "third-secret"},
            clear=False,
        ):
            third = OpenAICompatibleThirdPartyClient(
                third_party_spec(),
                transport=third_transport,
            )
            gateway = ResilientInferenceGateway(
                official_client=self._official(official_transport),
                third_party_clients=(third,),
                now=lambda: 1.0,
            )
            result = gateway.complete(
                [{"role": "user", "content": "brief"}],
                scope=InferenceScope.DEVELOPMENT_CORE,
                purpose="GTM agent planning",
            )
        self.assertEqual(result.route, "official_tokenfactory")
        self.assertEqual(third_transport.calls, [])

    def test_three_official_502s_enable_audited_third_party_fallback(self) -> None:
        official_transport = FakeTransport(
            [response(502) for _ in range(len(TOKEN_FACTORY_PUBLIC_MODELS) * 2)]
        )
        third_transport = FakeTransport(
            [
                response(
                    200,
                    {
                        "id": "fallback",
                        "choices": [
                            {
                                "message": {"content": "fallback result"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"total_tokens": 9},
                    },
                )
            ]
        )
        with patch.dict(
            os.environ,
            {"TEST_THIRD_PARTY_API_KEY": "third-secret"},
            clear=False,
        ):
            third = OpenAICompatibleThirdPartyClient(
                third_party_spec(),
                transport=third_transport,
            )
            gateway = ResilientInferenceGateway(
                official_client=self._official(official_transport),
                third_party_clients=(third,),
                now=lambda: 2.0,
            )
            result = gateway.complete(
                [{"role": "user", "content": "private brief"}],
                scope=InferenceScope.TEACHER_DISTILLATION,
                purpose="distill official-grade GTM behavior",
            )
        self.assertEqual(result.route, "third_party_fallback")
        self.assertEqual(result.provider, "approved_vendor")
        self.assertEqual(
            result.receipt["quality_contract"],
            OFFICIAL_FINE_TUNING_PARITY_CONTRACT,
        )
        self.assertFalse(result.receipt["competition_core_eligible"])
        serialized = json.dumps(result.receipt, sort_keys=True)
        self.assertNotIn("official-secret", serialized)
        self.assertNotIn("third-secret", serialized)
        self.assertNotIn("private brief", serialized)

    def test_competition_core_rejects_every_online_provider(self) -> None:
        gateway = ResilientInferenceGateway(
            official_client=self._official(FakeTransport([])),
        )
        with self.assertRaises(InferenceGatewayPolicyError):
            gateway.complete(
                [{"role": "user", "content": "brief"}],
                scope=InferenceScope.COMPETITION_CORE,
                purpose="forbidden online contest execution",
            )

    def test_auth_failure_does_not_hide_behind_third_party(self) -> None:
        official_transport = FakeTransport([response(401)])
        with patch.dict(
            os.environ,
            {"TEST_THIRD_PARTY_API_KEY": "third-secret"},
            clear=False,
        ):
            third = OpenAICompatibleThirdPartyClient(
                third_party_spec(),
                transport=FakeTransport([]),
            )
            gateway = ResilientInferenceGateway(
                official_client=self._official(official_transport),
                third_party_clients=(third,),
            )
            with self.assertRaises(InferenceGatewayCallError) as captured:
                gateway.complete(
                    [{"role": "user", "content": "brief"}],
                    scope=InferenceScope.DEVELOPMENT_AGENT,
                    purpose="must expose official auth failure",
                )
        self.assertEqual(
            captured.exception.receipt["third_party_attempts"],
            [],
        )


    def test_missing_fallback_key_is_a_visible_blocked_attempt(self) -> None:
        official_transport = FakeTransport(
            [response(502) for _ in range(len(TOKEN_FACTORY_PUBLIC_MODELS) * 2)]
        )
        with patch.dict(os.environ, {}, clear=True):
            third = OpenAICompatibleThirdPartyClient(
                third_party_spec(),
                transport=FakeTransport([]),
            )
            gateway = ResilientInferenceGateway(
                official_client=self._official(official_transport),
                third_party_clients=(third,),
            )
            with self.assertRaises(InferenceGatewayCallError) as captured:
                gateway.complete(
                    [{"role": "user", "content": "brief"}],
                    scope=InferenceScope.DEVELOPMENT_CORE,
                    purpose="visible unavailable fallback",
                )
        attempts = captured.exception.receipt["third_party_attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["error_code"], "missing_credential")
        self.assertEqual(
            attempts[0]["credential"]["source"],
            "TEST_THIRD_PARTY_API_KEY",
        )

    def test_unreviewed_or_unbounded_third_party_provider_is_rejected(self) -> None:
        invalid_specs = (
            third_party_spec(data_processing_approved=False),
            third_party_spec(license_reviewed=False),
            third_party_spec(maximum_call_cost_usd=float("inf")),
            third_party_spec(base_url="http://localhost:8000/v1"),
            third_party_spec(
                quality_contract="weaker-contract",
            ),
            third_party_spec(
                allowed_scopes=(InferenceScope.COMPETITION_CORE,),
            ),
        )
        for spec in invalid_specs:
            with self.subTest(spec=spec):
                with self.assertRaises(InferenceGatewayPolicyError):
                    spec.validate()

    def test_fireworks_example_loads_four_official_quality_routes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        specs = load_third_party_provider_specs(
            root / "config/fireworks-fallback.example.json"
        )
        self.assertEqual(len(specs), 4)
        self.assertEqual(
            specs[0].model,
            "accounts/fireworks/models/kimi-k2p6",
        )
        self.assertIn("vision", specs[0].capabilities)
        self.assertTrue(
            all(
                spec.quality_contract
                == OFFICIAL_FINE_TUNING_PARITY_CONTRACT
                for spec in specs
            )
        )
        self.assertTrue(
            all(
                InferenceScope.COMPETITION_CORE not in spec.allowed_scopes
                for spec in specs
            )
        )

    def test_config_loader_rejects_wrong_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "providers.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": f"{THIRD_PARTY_CONFIG_SCHEMA}-wrong",
                        "providers": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(InferenceGatewayPolicyError):
                load_third_party_provider_specs(path)


class OllamaLocalGatewayTests(unittest.TestCase):
    DIGEST = "a" * 64

    def client(
        self,
        *,
        digest: str | None = None,
        content: str = '{"draft":"bounded"}',
    ) -> OllamaLocalClient:
        transport = FakeOllamaTransport(
            response(
                200,
                {
                    "models": [
                        {
                            "name": "qwen2.5-coder:1.5b",
                            "model": "qwen2.5-coder:1.5b",
                            "digest": digest or self.DIGEST,
                        }
                    ]
                },
            ),
            [
                response(
                    200,
                    {
                        "message": {"content": content},
                        "done_reason": "stop",
                        "prompt_eval_count": 12,
                        "eval_count": 6,
                    },
                )
            ],
        )
        return OllamaLocalClient(
            OllamaLocalSpec("qwen2.5-coder:1.5b", self.DIGEST),
            transport=transport,
        )

    def test_digest_pinned_local_completion_is_auditable_without_prompt_persistence(self) -> None:
        result = self.client().complete(
            [{"role": "user", "content": "private first-party brief"}],
            scope=InferenceScope.DEVELOPMENT_CORE,
            purpose="bounded local creative challenger",
            max_tokens=256,
            temperature=0,
            timeout_seconds=30,
        )
        self.assertEqual(result.route, "local_ollama")
        self.assertEqual(result.content, '{"draft":"bounded"}')
        self.assertEqual(result.receipt["model_digest"], self.DIGEST)
        self.assertFalse(result.receipt["competition_core_eligible"])
        self.assertFalse(result.receipt["radeon_local_inference"])
        serialized = json.dumps(result.receipt, sort_keys=True)
        self.assertNotIn("private first-party brief", serialized)
        self.assertNotIn('{"draft":"bounded"}', serialized)

    def test_missing_pinned_digest_fails_closed_without_download(self) -> None:
        with self.assertRaises(InferenceGatewayCallError) as captured:
            self.client(digest="b" * 64).complete(
                [{"role": "user", "content": "brief"}],
                scope=InferenceScope.DEVELOPMENT_CORE,
                purpose="bounded local creative challenger",
                max_tokens=256,
                temperature=0,
                timeout_seconds=30,
            )
        self.assertEqual(
            captured.exception.receipt["error_code"],
            "pinned_model_not_installed",
        )
        self.assertFalse(captured.exception.receipt["network_download_performed"])

    def test_local_apple_route_cannot_be_presented_as_competition_core(self) -> None:
        with self.assertRaises(InferenceGatewayPolicyError):
            self.client().complete(
                [{"role": "user", "content": "brief"}],
                scope=InferenceScope.COMPETITION_CORE,
                purpose="forbidden contest claim",
                max_tokens=256,
                temperature=0,
                timeout_seconds=30,
            )

    def test_gtm_challenger_uses_one_call_with_closed_json_schema_decoding(self) -> None:
        client = self.client()
        contract = {
            "schema": "ProofLaunchTextCreativeCandidateV1",
            "territory_id": "decision_xray",
            "strategy_id": "strategy-1",
            "proof_claim_id": "claim-1",
            "factual_claims": ["Approved proof."],
            "channels": [
                {
                    "channel": "linkedin_organic",
                    "native_format": "LinkedIn text post",
                    "cta": "Review the evidence.",
                    "disclosure": "draft_pending_human_review",
                },
                {
                    "channel": "partner_communities",
                    "native_format": "partner community discussion",
                    "cta": "Review the evidence.",
                    "disclosure": "draft_pending_human_review",
                },
            ],
        }
        result = client.complete(
            [
                {"role": "system", "content": "Return JSON."},
                {
                    "role": "user",
                    "content": json.dumps({"output_contract": contract}),
                },
            ],
            scope=InferenceScope.DEVELOPMENT_CORE,
            purpose="evidence_bound_gtm_text_creative_challenger",
            max_tokens=1400,
            temperature=0,
            timeout_seconds=30,
        )
        transport = client._transport
        payload = transport.calls[-1][1]["payload"]
        self.assertIsInstance(payload["format"], dict)
        self.assertFalse(payload["format"]["additionalProperties"])
        self.assertEqual(
            payload["format"]["properties"]["territory_id"]["const"],
            "decision_xray",
        )
        self.assertEqual(
            payload["format"]["properties"]["channels"]["prefixItems"][0]
            ["properties"]["body"]["prefixItems"][0]["const"],
            "Approved proof.",
        )
        self.assertEqual(payload["options"]["num_predict"], 768)
        self.assertEqual(result.receipt["requested_max_tokens"], 1400)
        self.assertEqual(result.receipt["effective_max_tokens"], 768)
        self.assertFalse(result.receipt["creative_scaffold_field_lock_applied"])
        self.assertEqual(
            result.receipt["creative_model_role"],
            "unconstrained_by_creative_scaffold",
        )

    def test_governance_judge_uses_closed_binary_schema(self) -> None:
        client = self.client(content='{"pass":false,"reason_code":"failed_check_present"}')
        result = client.complete(
            [
                {"role": "system", "content": "Return the binary result."},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "all_checks_satisfied": False,
                            "failed_check_ids": ["workspace_safety"],
                        }
                    ),
                },
            ],
            scope=InferenceScope.EVALUATION,
            purpose="gtm-governance-closure-binary-v1",
            max_tokens=64,
            temperature=0,
            timeout_seconds=30,
        )
        payload = client._transport.calls[-1][1]["payload"]
        self.assertEqual(payload["format"]["properties"]["pass"]["type"], "boolean")
        self.assertEqual(
            payload["format"]["properties"]["reason_code"]["enum"],
            ["all_checks_pass", "failed_check_present"],
        )
        self.assertFalse(payload["format"]["additionalProperties"])
        self.assertEqual(result.content, '{"pass":false,"reason_code":"failed_check_present"}')

    def test_craft_reviewer_uses_closed_identity_and_decision_schema(self) -> None:
        review = {
            "schema": "ProofLaunchGTMCraftAdvisoryReviewV1",
            "work_order_id": "review-platform",
            "territory_id": "decision_xray",
            "strategy_id": "strategy-1",
            "candidate_content_sha256": "b" * 64,
            "decision": "pass",
            "blocking_findings": [],
            "repair_instructions": [],
        }
        client = self.client(content=json.dumps(review))
        result = client.complete(
            [
                {"role": "system", "content": "Review independently."},
                {
                    "role": "user",
                    "content": json.dumps({"output_contract": review}),
                },
            ],
            scope=InferenceScope.DEVELOPMENT_CORE,
            purpose="independent_gtm_craft_advisory_review",
            max_tokens=700,
            temperature=0,
            timeout_seconds=30,
        )
        payload = client._transport.calls[-1][1]["payload"]
        self.assertEqual(
            payload["format"]["properties"]["work_order_id"]["const"],
            "review-platform",
        )
        self.assertEqual(
            payload["format"]["properties"]["decision"]["enum"],
            ["pass", "revise", "block"],
        )
        self.assertFalse(payload["format"]["additionalProperties"])
        self.assertEqual(result.content, json.dumps(review))

    def test_local_gtm_normalization_only_inserts_exact_approved_proof(self) -> None:
        raw_candidate = {
            "channels": [
                {"hook": "Question", "body": ["Block A", "3 outcomes"], "cta": "Act"},
                {"hook": "Question", "body": ["Block A", "3 outcomes"], "cta": "Act"},
            ]
        }
        client = self.client(content=json.dumps(raw_candidate))
        result = client.complete(
            [
                {"role": "system", "content": "Return JSON."},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "context": {"approved_proof": "Approved proof."},
                            "output_contract": {
                                "schema": "ProofLaunchTextCreativeCandidateV1",
                                "territory_id": "decision_xray",
                                "strategy_id": "strategy-1",
                                "proof_claim_id": "claim-1",
                                "factual_claims": ["Approved proof."],
                                "channels": [
                                    {
                                        "channel": "linkedin_organic",
                                        "native_format": "LinkedIn text post",
                                        "cta": "Act",
                                        "disclosure": "draft_pending_human_review",
                                    },
                                    {
                                        "channel": "partner_communities",
                                        "native_format": "partner community discussion",
                                        "cta": "Act",
                                        "disclosure": "draft_pending_human_review",
                                    },
                                ],
                            },
                        }
                    ),
                },
            ],
            scope=InferenceScope.DEVELOPMENT_CORE,
            purpose="evidence_bound_gtm_text_creative_challenger",
            max_tokens=256,
            temperature=0,
            timeout_seconds=30,
        )
        normalized = json.loads(result.content)
        self.assertEqual(normalized["channels"][0]["body"][0], "Approved proof.")
        self.assertEqual(normalized["channels"][1]["body"][0], "Approved proof.")
        self.assertEqual(
            normalized["channels"][0]["hook"], normalized["channels"][1]["hook"]
        )
        self.assertNotIn("3 outcomes", normalized["channels"][0]["body"])
        self.assertNotIn("3 outcomes", normalized["channels"][1]["body"])
        self.assertEqual(
            result.receipt["deterministic_contract_normalization_count"], 4
        )
        self.assertNotIn(
            "add_channel_native_distinction",
            json.dumps(result.receipt["deterministic_contract_normalizations"]),
        )
        self.assertNotEqual(
            result.receipt["raw_response_sha256"],
            result.receipt["normalized_response_sha256"],
        )

    def test_full_gtm_plan_uses_96_token_nucleus_and_preserves_portfolio_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        plan = json.loads(
            (
                root
                / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/text-creative-challenger-plan.json"
            ).read_text(encoding="utf-8")
        )
        candidates = []
        for request in plan["requests"]:
            nucleus = {
                "schema": "ProofLaunchLocalGTMCreativeNucleusV1",
                "territory_id": request["territory_id"],
                "opening_variant": "evidence_gap",
                "participation_variant": "mark_boundary",
                "relay_variant": "decision_card",
                "tone_variant": "calm_forensic",
            }
            client = self.client(content=json.dumps(nucleus))
            result = client.complete(
                request["messages"],
                scope=InferenceScope.DEVELOPMENT_CORE,
                purpose=request["purpose"],
                max_tokens=request["maximum_output_tokens"],
                temperature=request["temperature"],
                timeout_seconds=30,
            )
            payload = client._transport.calls[-1][1]["payload"]
            self.assertEqual(payload["options"]["num_predict"], 96)
            self.assertEqual(
                payload["format"]["properties"]["opening_variant"]["enum"],
                ["unresolved_condition", "evidence_gap", "peer_challenge"],
            )
            self.assertEqual(
                result.receipt["creative_model_role"],
                "bounded_local_creative_nucleus_selector",
            )
            self.assertTrue(
                result.receipt["creative_nucleus_compilation_applied"]
            )
            self.assertEqual(
                result.receipt["deterministic_contract_normalization_count"],
                5,
            )
            candidates.append(
                validate_text_candidate(
                    result.content,
                    plan,
                    territory_id=request["territory_id"],
                )
            )
        receipt = build_text_challenger_receipt(plan, candidates)
        self.assertTrue(receipt["creative_quality_gate"]["passed"])
        self.assertEqual(receipt["creative_quality_gate"]["candidate_gate_count"], 3)

    def test_invalid_local_creative_nucleus_fails_closed_before_candidate_use(self) -> None:
        root = Path(__file__).resolve().parents[1]
        plan = json.loads(
            (
                root
                / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/text-creative-challenger-plan.json"
            ).read_text(encoding="utf-8")
        )
        request = plan["requests"][0]
        invalid_nucleus = {
            "schema": "ProofLaunchLocalGTMCreativeNucleusV1",
            "territory_id": request["territory_id"],
            "opening_variant": "invent_a_claim",
            "participation_variant": "mark_boundary",
            "relay_variant": "decision_card",
            "tone_variant": "calm_forensic",
        }
        client = self.client(content=json.dumps(invalid_nucleus))
        with self.assertRaises(InferenceGatewayCallError) as captured:
            client.complete(
                request["messages"],
                scope=InferenceScope.DEVELOPMENT_CORE,
                purpose=request["purpose"],
                max_tokens=request["maximum_output_tokens"],
                temperature=request["temperature"],
                timeout_seconds=30,
            )
        self.assertEqual(
            captured.exception.receipt["error_code"],
            "local_creative_nucleus_compile_failed",
        )
        self.assertNotIn("invent_a_claim", json.dumps(captured.exception.receipt))


if __name__ == "__main__":
    unittest.main()
