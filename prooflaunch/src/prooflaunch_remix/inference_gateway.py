from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse

from .tokenfactory import (
    TOKEN_FACTORY_API_KEY_ENV,
    TOKEN_FACTORY_PROVIDER,
    TokenFactoryCallError,
    TokenFactoryClient,
    TokenFactoryConfigurationError,
    TokenFactoryHttpResponse,
    TokenFactoryResult,
    TokenFactoryTransport,
    UrllibTokenFactoryTransport,
)


GATEWAY_SCHEMA = "ProofLaunchResilientInferenceGatewayV1"
THIRD_PARTY_CONFIG_SCHEMA = "ProofLaunchThirdPartyFallbackConfigV1"
OFFICIAL_FINE_TUNING_PARITY_CONTRACT = (
    "radeon-official-finetuning-extreme-v1"
)


class InferenceScope(str, Enum):
    TRAINING_DATA = "training_data"
    TEACHER_DISTILLATION = "teacher_distillation"
    EVALUATION = "evaluation"
    DEVELOPMENT_AGENT = "development_agent"
    DEVELOPMENT_CORE = "development_core"
    COMPETITION_CORE = "competition_core"


THIRD_PARTY_ALLOWED_SCOPES = frozenset(
    {
        InferenceScope.TRAINING_DATA,
        InferenceScope.TEACHER_DISTILLATION,
        InferenceScope.EVALUATION,
        InferenceScope.DEVELOPMENT_AGENT,
        InferenceScope.DEVELOPMENT_CORE,
    }
)


class InferenceGatewayError(RuntimeError):
    pass


class InferenceGatewayPolicyError(InferenceGatewayError):
    pass


class InferenceGatewayCallError(InferenceGatewayError):
    def __init__(self, message: str, receipt: Mapping[str, object]) -> None:
        super().__init__(message)
        self.receipt = dict(receipt)


@dataclass(frozen=True)
class ThirdPartyProviderSpec:
    provider: str
    base_url: str
    model: str
    api_key_env: str
    data_processing_approved: bool
    license_reviewed: bool
    maximum_call_cost_usd: float
    quality_contract: str = OFFICIAL_FINE_TUNING_PARITY_CONTRACT
    allowed_scopes: tuple[InferenceScope, ...] = tuple(THIRD_PARTY_ALLOWED_SCOPES)
    service_tier: str = "default"
    capabilities: tuple[str, ...] = ("text",)

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def validate(self) -> None:
        if not self.provider.strip() or self.provider == TOKEN_FACTORY_PROVIDER:
            raise InferenceGatewayPolicyError(
                "third-party provider must have a distinct non-empty identity"
            )
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise InferenceGatewayPolicyError(
                "third-party API base URL must be public HTTPS"
            )
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if (
            parsed.hostname.lower() == "localhost"
            or (
                address is not None
                and (
                    address.is_private
                    or address.is_loopback
                    or address.is_link_local
                    or address.is_reserved
                )
            )
        ):
            raise InferenceGatewayPolicyError(
                "local and private third-party API endpoints are forbidden"
            )
        if not self.model.strip() or not self.api_key_env.strip():
            raise InferenceGatewayPolicyError(
                "third-party model and key environment variable are required"
            )
        if not self.data_processing_approved or not self.license_reviewed:
            raise InferenceGatewayPolicyError(
                "data-processing and license review must be explicitly approved"
            )
        if (
            not math.isfinite(self.maximum_call_cost_usd)
            or self.maximum_call_cost_usd <= 0
        ):
            raise InferenceGatewayPolicyError(
                "a positive finite per-call spend cap is mandatory"
            )
        if self.quality_contract != OFFICIAL_FINE_TUNING_PARITY_CONTRACT:
            raise InferenceGatewayPolicyError(
                "third-party routes must accept the official fine-tuning parity contract"
            )
        if self.service_tier not in {"default", "priority"}:
            raise InferenceGatewayPolicyError(
                "service_tier must be default or priority"
            )
        if not self.capabilities or any(
            item not in {"text", "vision", "tool_calling", "long_context"}
            for item in self.capabilities
        ):
            raise InferenceGatewayPolicyError(
                "third-party capabilities contain an unsupported value"
            )
        scopes = set(self.allowed_scopes)
        if not scopes or not scopes <= THIRD_PARTY_ALLOWED_SCOPES:
            raise InferenceGatewayPolicyError(
                "third-party routes cannot enter the competition core"
            )


@dataclass(frozen=True)
class GatewayResult:
    provider: str
    model: str
    route: str
    content: str
    response_id: str | None
    finish_reason: str | None
    usage: Mapping[str, object]
    receipt: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


OLLAMA_LOCAL_ALLOWED_SCOPES = frozenset(
    {
        InferenceScope.EVALUATION,
        InferenceScope.DEVELOPMENT_AGENT,
        InferenceScope.DEVELOPMENT_CORE,
    }
)


@dataclass(frozen=True)
class OllamaLocalSpec:
    model: str
    digest: str
    base_url: str = "http://127.0.0.1:11434"
    maximum_output_tokens: int = 2048

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise InferenceGatewayPolicyError(
                "Ollama local inference must remain on loopback HTTP"
            )
        if not self.model.strip():
            raise InferenceGatewayPolicyError("Ollama local model identity is required")
        if len(self.digest) != 64 or any(char not in "0123456789abcdef" for char in self.digest):
            raise InferenceGatewayPolicyError("Ollama local model digest must be SHA-256")
        if not 1 <= self.maximum_output_tokens <= 8192:
            raise InferenceGatewayPolicyError(
                "Ollama maximum_output_tokens must be in [1, 8192]"
            )


class UrllibOllamaLocalTransport:
    def get_json(self, *, url: str, timeout_seconds: float) -> TokenFactoryHttpResponse:
        request = urllib.request.Request(
            url=url,
            headers={"Accept": "application/json", "User-Agent": "ProofLaunch-LocalGateway/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return TokenFactoryHttpResponse(
                    status=int(response.status),
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return TokenFactoryHttpResponse(
                status=int(error.code),
                headers=dict(error.headers.items()) if error.headers else {},
                body=error.read(),
            )
        except (urllib.error.URLError, TimeoutError):
            return TokenFactoryHttpResponse(status=0, headers={}, body=b"")

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> TokenFactoryHttpResponse:
        try:
            return UrllibTokenFactoryTransport().post_json(
                url=url,
                headers=headers,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            return TokenFactoryHttpResponse(status=0, headers={}, body=b"")


def _ollama_structured_output_format(
    messages: Sequence[Mapping[str, object]], purpose: str
) -> str | dict[str, object]:
    """Compile the closed GTM candidate contract into Ollama's JSON-schema format.

    This is a deterministic decoding constraint, not a repair call. Unknown purposes
    retain the generic JSON-object constraint.
    """

    if purpose == "gtm-governance-closure-binary-v1":
        return {
            "type": "object",
            "properties": {
                "pass": {"type": "boolean"},
                "reason_code": {
                    "type": "string",
                    "enum": ["all_checks_pass", "failed_check_present"],
                },
            },
            "required": ["pass", "reason_code"],
            "additionalProperties": False,
        }
    if purpose == "independent_gtm_craft_advisory_review":
        try:
            user_message = next(
                item for item in reversed(messages) if item.get("role") == "user"
            )
            contract = json.loads(str(user_message["content"]))["output_contract"]
            fixed_fields = (
                "schema",
                "work_order_id",
                "territory_id",
                "strategy_id",
                "candidate_content_sha256",
            )
            properties: dict[str, object] = {
                field: {"type": "string", "const": str(contract[field])}
                for field in fixed_fields
            }
            properties.update(
                {
                    "decision": {
                        "type": "string",
                        "enum": ["pass", "revise", "block"],
                    },
                    "blocking_findings": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "string", "minLength": 1, "maxLength": 600},
                    },
                    "repair_instructions": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "string", "minLength": 1, "maxLength": 600},
                    },
                }
            )
            return {
                "type": "object",
                "additionalProperties": False,
                "required": list(properties),
                "properties": properties,
            }
        except (StopIteration, KeyError, TypeError, json.JSONDecodeError):
            return "json"
    if purpose not in {
        "evidence_bound_gtm_text_creative_challenger",
        "bounded_gtm_craft_repair",
    }:
        return "json"
    try:
        user_message = next(
            item for item in reversed(messages) if item.get("role") == "user"
        )
        prompt = json.loads(str(user_message["content"]))
        contract = prompt["output_contract"]
        if contract.get("schema") == "ProofLaunchLocalGTMCreativeNucleusV1":
            selector_values = {
                "opening_variant": (
                    "unresolved_condition",
                    "evidence_gap",
                    "peer_challenge",
                ),
                "participation_variant": (
                    "mark_boundary",
                    "rewrite_question",
                    "rank_objection",
                ),
                "relay_variant": (
                    "decision_card",
                    "review_checklist",
                    "objection_map",
                ),
                "tone_variant": (
                    "calm_forensic",
                    "direct_peer",
                    "useful_challenge",
                ),
            }
            properties: dict[str, object] = {
                "schema": {
                    "type": "string",
                    "const": "ProofLaunchLocalGTMCreativeNucleusV1",
                },
                "territory_id": {
                    "type": "string",
                    "const": str(contract["territory_id"]),
                },
            }
            properties.update(
                {
                    field: {"type": "string", "enum": list(values)}
                    for field, values in selector_values.items()
                }
            )
            return {
                "type": "object",
                "additionalProperties": False,
                "required": list(properties),
                "properties": properties,
            }
        channels = contract["channels"]
        factual_claims = contract["factual_claims"]
        if (
            contract.get("schema") != "ProofLaunchTextCreativeCandidateV1"
            or not isinstance(channels, list)
            or len(channels) != 2
            or not isinstance(factual_claims, list)
            or len(factual_claims) != 1
        ):
            return "json"
    except (StopIteration, KeyError, TypeError, json.JSONDecodeError):
        return "json"

    def fixed_string(value: object) -> dict[str, object]:
        return {"type": "string", "const": str(value)}

    approved_proof = factual_claims[0]
    channel_schemas = []
    for channel in channels:
        if not isinstance(channel, Mapping):
            return "json"
        fixed_hook = channel.get("hook")
        fixed_body = channel.get("body")
        body_schema: dict[str, object]
        if (
            isinstance(fixed_body, list)
            and 2 <= len(fixed_body) <= 5
            and all(isinstance(item, str) and item for item in fixed_body)
        ):
            body_schema = {
                "type": "array",
                "minItems": len(fixed_body),
                "maxItems": len(fixed_body),
                "prefixItems": [fixed_string(item) for item in fixed_body],
            }
        else:
            body_schema = {
                "type": "array",
                "minItems": 2,
                "maxItems": 5,
                "prefixItems": [fixed_string(approved_proof)],
                "items": {"type": "string", "minLength": 1, "maxLength": 700},
            }
        channel_schemas.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "channel",
                    "native_format",
                    "hook",
                    "body",
                    "cta",
                    "disclosure",
                ],
                "properties": {
                    "channel": fixed_string(channel.get("channel")),
                    "native_format": fixed_string(channel.get("native_format")),
                    "hook": (
                        fixed_string(fixed_hook)
                        if isinstance(fixed_hook, str) and fixed_hook
                        else {"type": "string", "minLength": 1, "maxLength": 300}
                    ),
                    "body": body_schema,
                    "cta": fixed_string(channel.get("cta")),
                    "disclosure": fixed_string(channel.get("disclosure")),
                },
            }
        )
    scalar_fields = (
        "schema",
        "territory_id",
        "strategy_id",
        "proof_claim_id",
    )
    properties: dict[str, object] = {
        field: fixed_string(contract.get(field)) for field in scalar_fields
    }
    for field in (
        "cultural_tension",
        "organizing_idea",
        "participation_mechanism",
        "share_trigger",
        "proof_role",
        "falsifier",
    ):
        fixed_value = contract.get(field)
        properties[field] = (
            fixed_string(fixed_value)
            if isinstance(fixed_value, str) and fixed_value
            else {"type": "string", "minLength": 1, "maxLength": 800}
        )
    properties["factual_claims"] = {
        "type": "array",
        "prefixItems": [fixed_string(approved_proof)],
        "minItems": 1,
        "maxItems": 1,
    }
    properties["channels"] = {
        "type": "array",
        "prefixItems": channel_schemas,
        "minItems": 2,
        "maxItems": 2,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _compact_local_gtm_messages(
    messages: Sequence[Mapping[str, object]], purpose: str
) -> tuple[list[Mapping[str, object]], bool]:
    if purpose != "evidence_bound_gtm_text_creative_challenger":
        return list(messages), False
    try:
        user_message = next(
            item for item in reversed(messages) if item.get("role") == "user"
        )
        prompt = json.loads(str(user_message["content"]))
        context = prompt["context"]
        audience = context["audience"]
        brand = context["brand"]
        territory = prompt["territory"]
        contract = prompt["output_contract"]
        audience_name = str(audience["name"])
        core_problem = str(audience["core_problem"])
        desired_outcome = str(audience["desired_outcome"])
        buying_context = str(audience["buying_context"])
        brand_name = str(brand["name"])
        offer = str(context["offer"])
        territory_id = str(territory["territory_id"])
        scenario_lens = context.get("scenario_lens")
        if not isinstance(scenario_lens, Mapping):
            # Backward-compatible compilation for already sealed plans created
            # before the scenario-lens contract. New plans always carry the
            # explicit four-dimensional lens.
            scenario_lens = {
                "dimensions": {
                    "business_model": {
                        "value": "b2b",
                        "job": "make the multi-person buying decision inspectable"
                    },
                    "lifecycle": {
                        "value": "launch",
                        "job": "earn category entry by sequencing first proof before the launch ask"
                    },
                    "budget": {
                        "value": "zero",
                        "job": "use founder-led, community and earned participation without paid reach"
                    },
                    "industry_risk": {
                        "value": "standard",
                        "job": "keep every assertion inside the approved claim boundary"
                    },
                }
            }
        dimensions = scenario_lens["dimensions"]
        business_model_job = str(dimensions["business_model"]["job"])
        lifecycle_job = str(dimensions["lifecycle"]["job"])
        budget_execution = str(dimensions["budget"]["job"])
        risk_constraint = str(dimensions["industry_risk"]["job"])
        business_model = str(dimensions["business_model"]["value"])
        lifecycle = str(dimensions["lifecycle"]["value"])
        budget = str(dimensions["budget"]["value"])
        industry_risk = str(dimensions["industry_risk"]["value"])
        territory_scaffolds = {
            "decision_xray": {
                "cultural_tension": (
                    f"{audience_name} want to {desired_outcome}. The obstacle is specific: "
                    f"{core_problem}. The buying context is equally specific: {buying_context}."
                ),
                "organizing_idea": (
                    "Decision X-Ray turns the buying decision into an inspectable map of the "
                    f"one proof gap still blocking the next step for {audience_name}."
                ),
                "participation_mechanism": (
                    f"A representative of {audience_name} marks the missing condition that would "
                    "change the decision, then explains why it matters."
                ),
                "share_trigger": (
                    "The marked decision map helps a peer prepare for the same scrutiny without "
                    f"requiring an endorsement of {brand_name}. The context remains: {buying_context}."
                ),
                "proof_role": (
                    "The approved proof is the first layer reviewers inspect before they add "
                    "the unresolved condition, rather than a decorative closing claim."
                ),
                "falsifier": (
                    "Reject Decision X-Ray if reviewers cannot name a more specific next "
                    "question after using the map."
                ),
            },
            "proof_before_promise": {
                "cultural_tension": (
                    f"{audience_name} are asked to trust polished promises while this problem "
                    f"remains unresolved: {core_problem}. The buying context is: {buying_context}."
                ),
                "organizing_idea": (
                    "Proof Before Promise opens with the approved evidence and withholds the "
                    f"{brand_name} offer until reviewers name its limits."
                ),
                "participation_mechanism": (
                    "Reviewers annotate whether the proof resolves their objection before the "
                    f"offer is introduced: {offer}."
                ),
                "share_trigger": (
                    "An annotated evidence card is useful to another decision group because "
                    "the proof and its unresolved limitation remain together."
                ),
                "proof_role": (
                    "The approved proof controls the reveal sequence and earns the right to "
                    f"introduce {brand_name} only after scrutiny."
                ),
                "falsifier": (
                    "Reject Proof Before Promise if leading with evidence does not elicit a "
                    "more specific objection than the existing draft."
                ),
            },
            "voluntary_relay": {
                "cultural_tension": (
                    f"{audience_name} need a useful way to confront this problem: {core_problem}. "
                    f"They do not want to forward another branded pitch. Context: {buying_context}."
                ),
                "organizing_idea": (
                    "The Voluntary Relay Card makes one evidence question portable and useful "
                    f"even when {brand_name} is removed."
                ),
                "participation_mechanism": (
                    "A recipient adapts the decision question, records one limiting condition, "
                    "and passes the revised card to one relevant peer."
                ),
                "share_trigger": (
                    "The card saves a peer preparation effort because the evidence, objection "
                    "and open condition travel together without an endorsement request."
                ),
                "proof_role": (
                    f"The approved proof anchors the reusable card while {brand_name} remains "
                    "secondary to the recipient's decision utility."
                ),
                "falsifier": (
                    "Reject the Voluntary Relay Card if recipients will share it only when this "
                    f"offer remains attached: {offer}."
                ),
            },
        }
        scaffold = territory_scaffolds[territory_id]
        if business_model == "b2c":
            consumer_scaffolds = {
                "decision_xray": {
                    "cultural_tension": (
                        f"{audience_name} encounter this friction in a personal use moment: "
                        f"{core_problem}. Yet the decision is often flattened into a brand claim."
                    ),
                    "organizing_idea": (
                        "Use-Moment Mirror turns the choice into a visible before/after decision "
                        f"that {audience_name} can interpret in their own context."
                    ),
                    "participation_mechanism": (
                        "Each participant chooses the moment where relevance begins or ends, "
                        "then explains the condition behind that choice."
                    ),
                    "share_trigger": (
                        "A personal decision card can help one friend compare a similar use "
                        f"moment without asking them to endorse {brand_name}."
                    ),
                    "proof_role": (
                        "The approved proof anchors the comparison while the participant—not "
                        "the brand—defines whether it applies to their situation."
                    ),
                    "falsifier": (
                        "Reject Use-Moment Mirror if participants cannot name a more precise "
                        "condition for choosing or declining after the comparison."
                    ),
                },
                "proof_before_promise": {
                    "cultural_tension": (
                        f"{audience_name} are surrounded by polished aspiration while this lived "
                        f"problem remains hard to inspect: {core_problem}."
                    ),
                    "organizing_idea": (
                        "Proof-in-the-Moment reveals the approved evidence inside a recognizable "
                        f"use situation and keeps the {brand_name} offer out of frame at first."
                    ),
                    "participation_mechanism": (
                        "A participant marks where the evidence matches their situation, where "
                        "it does not, and only then opens the next-step option."
                    ),
                    "share_trigger": (
                        "The marked use-moment guide is useful to a friend because personal fit "
                        "and the evidence limitation travel together."
                    ),
                    "proof_role": (
                        "The proof earns attention through situated usefulness rather than acting "
                        "as a badge beneath a lifestyle promise."
                    ),
                    "falsifier": (
                        "Reject Proof-in-the-Moment if the situated reveal produces no clearer "
                        "personal-fit question than the original promotional draft."
                    ),
                },
                "voluntary_relay": {
                    "cultural_tension": (
                        f"{audience_name} may want {desired_outcome}, but sharing a branded pitch "
                        "can put their identity and trust with friends at risk."
                    ),
                    "organizing_idea": (
                        "Friend-Adapted Ritual makes one useful action portable, editable and "
                        f"valuable even when {brand_name} is invisible."
                    ),
                    "participation_mechanism": (
                        "One person adapts the ritual to a real use moment, removes what does not "
                        "fit, and offers the revised version to one relevant friend."
                    ),
                    "share_trigger": (
                        "The recipient receives a practical shortcut shaped by someone they know, "
                        "with no endorsement or public-post requirement."
                    ),
                    "proof_role": (
                        "The approved proof protects the ritual's claim boundary while individual "
                        "adaptation creates the reason to relay it."
                    ),
                    "falsifier": (
                        "Reject Friend-Adapted Ritual if people will pass it only when the offer "
                        f"remains attached: {offer}."
                    ),
                },
            }
            scaffold = consumer_scaffolds[territory_id]
        # The weak local decoder chooses only a bounded creative nucleus.  The
        # deterministic compiler then binds the candidate to all four scenario
        # dimensions so a launch/zero-budget/B2B plan cannot silently become the
        # same system as a mature/scaled/B2C plan.
        scaffold["cultural_tension"] = (
            f"{scaffold['cultural_tension']} Business-model job: {business_model_job}. "
            f"Lifecycle job: {lifecycle_job}."
        )
        scaffold["organizing_idea"] = (
            f"{scaffold['organizing_idea']} Execution constraint: {budget_execution}."
        )
        scaffold["proof_role"] = (
            f"{scaffold['proof_role']} Risk constraint: {risk_constraint}."
        )
        channel_scaffolds = {
            "decision_xray": (
                {
                    "hook": (
                        f"{audience_name}: which missing condition would stop this evidence from "
                        "surviving scrutiny?"
                    ),
                    "body": (
                        "Name the unresolved condition in a comment, not a verdict. The strongest "
                        f"question becomes the next evidence card. Buying condition: {buying_context}."
                    ),
                },
                {
                    "hook": (
                        "Bring one disputed claim to the peer roundtable and ask the group to "
                        "mark its weakest decision boundary."
                    ),
                    "body": (
                        "Use the decision map to record the objection that must be resolved before "
                        f"anyone can {offer}. Do not ask participants to recommend {brand_name}."
                    ),
                },
            ),
            "proof_before_promise": (
                {
                    "hook": (
                        "Before another product promise enters the feed, inspect the evidence "
                        f"that {audience_name} are actually allowed to use."
                    ),
                    "body": (
                        "Read the proof first, then comment with the objection it does not resolve; "
                        f"only afterward consider this offer: {offer}."
                    ),
                },
                {
                    "hook": (
                        "Open the partner discussion with the evidence card face up and the offer "
                        "temporarily hidden."
                    ),
                    "body": (
                        f"Start from this buying condition: {buying_context}. Annotate one "
                        f"limitation, then reveal {brand_name} only after the group agrees on the "
                        "unresolved question."
                    ),
                },
            ),
            "voluntary_relay": (
                {
                    "hook": (
                        "Would this decision card still deserve a save or share if the "
                        f"{brand_name} name disappeared?"
                    ),
                    "body": (
                        f"Rewrite one question for {audience_name}, add the limiting condition, "
                        "and pass the card only to a peer who faces the same decision."
                    ),
                },
                {
                    "hook": (
                        "Take the unbranded relay card into the community and challenge one peer "
                        "to improve its decision question."
                    ),
                    "body": (
                        f"Keep the evidence and objection together; attach the offer—{offer}—only "
                        "if the peer asks what produced the card."
                    ),
                },
            ),
        }
        primary_scaffold, secondary_scaffold = channel_scaffolds[territory_id]
        lifecycle_openings = {
            "pre_pmf": {
                "decision_xray": (
                    f"Before {audience_name} scale an assumption, which moment would falsify "
                    f"that this is the problem worth solving: {core_problem}?"
                ),
                "proof_before_promise": (
                    f"Before naming a category, let {audience_name} test the first proof "
                    "against the problem they actually experience."
                ),
                "voluntary_relay": (
                    f"Give {audience_name} a problem-framing card worth correcting before "
                    f"anyone is asked to consider {brand_name}."
                ),
            },
            "launch": {
                "decision_xray": (
                    f"At launch, which missing condition would stop {audience_name} from "
                    "carrying this proof into the next decision?"
                ),
                "proof_before_promise": (
                    f"A launch promise is easy; put the first approved proof in front of "
                    f"{audience_name} and ask where it stops."
                ),
                "voluntary_relay": (
                    f"Would this launch decision object still earn a save or share from "
                    f"{audience_name} with the {brand_name} name removed?"
                ),
            },
            "growth": {
                "decision_xray": (
                    f"Which activation boundary keeps {audience_name} from turning this "
                    "approved proof into a repeatable next step?"
                ),
                "proof_before_promise": (
                    f"Before scaling the offer, show {audience_name} the proof boundary "
                    "that a repeatable growth loop must survive."
                ),
                "voluntary_relay": (
                    f"Turn one verified use condition into a referral object that "
                    f"{audience_name} can improve before relaying."
                ),
            },
            "mature": {
                "decision_xray": (
                    f"Which category default should {audience_name} reopen before renewing "
                    "the familiar decision?"
                ),
                "proof_before_promise": (
                    f"Reactivation starts by showing {audience_name} which old assumption "
                    "the approved proof can—and cannot—reframe."
                ),
                "voluntary_relay": (
                    f"Create a planning ritual that {audience_name} would reuse even if "
                    f"{brand_name} disappeared from the object."
                ),
            },
        }
        secondary_openings = {
            "b2b": {
                "decision_xray": (
                    "Bring one disputed condition into the buying-group working session "
                    "and assign who can verify it."
                ),
                "proof_before_promise": (
                    "Open the committee review with the evidence face up and the offer hidden."
                ),
                "voluntary_relay": (
                    "Hand the unbranded decision object to one informed peer and ask them to improve it."
                ),
            },
            "b2c": {
                "decision_xray": (
                    "Turn one real use moment into a choose-your-boundary prompt, then compare why people chose differently."
                ),
                "proof_before_promise": (
                    "Show the evidence at the moment of use, then let each participant mark where personal relevance ends."
                ),
                "voluntary_relay": (
                    "Invite one person to adapt the utility object for a friend without adding an endorsement."
                ),
            },
        }
        budget_executions = {
            "zero": (
                "Founder-led execution: turn the most useful reply into the next community evidence card; use no paid reach."
            ),
            "small": (
                "Small-budget execution: pair one owned explainer with one micro-creator or community session, then reuse only the answered objection."
            ),
            "scaled": (
                "Scaled execution: sequence one distinctive brand code and one proof spine across channels without changing the claim boundary."
            ),
        }
        risk_executions = {
            "standard": (
                "Keep every assertion inside the approved claim boundary and label the unresolved condition."
            ),
            "high_regulation": (
                "Keep the execution educational: a named specialist reviews the compliance boundary before any release."
            ),
        }
        channel_native_actions = {
            "community_listening": (
                "Run it as a moderated community question; synthesize disagreements instead of counting applause."
            ),
            "creator_community": (
                "Write a creator collaboration brief that asks the creator to recreate and challenge the proof object."
            ),
            "customer_evidence": (
                "Package the proof, limitation and unresolved condition together as one customer evidence card."
            ),
            "customer_email": (
                "Use a plain-text email with one answerable question and treat a reply as research, not conversion proof."
            ),
            "founder_conversations": (
                "Use it in a one-to-one founder interview and record the participant's exact limiting condition."
            ),
            "linkedin_organic": (
                "Structure a LinkedIn text post with the contradiction first, the proof second and one professional question last."
            ),
            "owned_social": (
                "Turn the sequence into an owned social carousel caption: tension, proof, boundary, then the useful action."
            ),
            "partner_communities": (
                "Frame it as a partner community discussion with one verification owner and one unresolved condition."
            ),
            "search_education": (
                "Structure a query-led explainer: answer the search question, show the proof, state its limit and name the next check."
            ),
            "short_video_organic": (
                "Write a vertical short-video sequence with a recognizable opening frame, on-screen proof and a boundary prompt."
            ),
            "paid_search": (
                "Draft a headline and description pair for manual activation; the search-ad draft must lead to the evidence boundary."
            ),
            "paid_social": (
                "Build a paid-social draft as a frame sequence for manual activation: tension, proof object, limitation and next step."
            ),
        }
        primary_scaffold = dict(primary_scaffold)
        secondary_scaffold = dict(secondary_scaffold)
        primary_scaffold["hook"] = lifecycle_openings[lifecycle][territory_id]
        secondary_scaffold["hook"] = secondary_openings[business_model][territory_id]
        execution_suffix = (
            f" {budget_executions[budget]} {risk_executions[industry_risk]}"
        )
        primary_channel_name = str(contract["channels"][0]["channel"])
        secondary_channel_name = str(contract["channels"][1]["channel"])
        primary_scaffold["body"] = (
            f"{primary_scaffold['body']}{execution_suffix} "
            f"{channel_native_actions[primary_channel_name]}"
        )
        secondary_scaffold["body"] = (
            f"{secondary_scaffold['body']}{execution_suffix} "
            f"{channel_native_actions[secondary_channel_name]}"
        )
        compact_contract = dict(contract)
        for field in (
            "cultural_tension",
            "organizing_idea",
            "participation_mechanism",
            "share_trigger",
            "proof_role",
            "falsifier",
        ):
            compact_contract[field] = scaffold[field]
        primary_channel, secondary_channel = contract["channels"]
        compact_contract["channels"] = [
            {
                **dict(primary_channel),
                "hook": primary_scaffold["hook"],
                "body": [
                    context["approved_proof"],
                    primary_scaffold["body"],
                ],
            },
            {
                **dict(secondary_channel),
                "hook": secondary_scaffold["hook"],
                "body": [
                    context["approved_proof"],
                    secondary_scaffold["body"],
                ],
            },
        ]
        nucleus_contract = {
            "schema": "ProofLaunchLocalGTMCreativeNucleusV1",
            "territory_id": territory_id,
            "opening_variant": [
                "unresolved_condition",
                "evidence_gap",
                "peer_challenge",
            ],
            "participation_variant": [
                "mark_boundary",
                "rewrite_question",
                "rank_objection",
            ],
            "relay_variant": [
                "decision_card",
                "review_checklist",
                "objection_map",
            ],
            "tone_variant": [
                "calm_forensic",
                "direct_peer",
                "useful_challenge",
            ],
        }
        compact = {
            "schema": "ProofLaunchLocalGTMCreativeNucleusPromptV1",
            "task": (
                "Select one value for each creative-nucleus field. Return only the "
                "six-field JSON object. Do not write campaign copy."
            ),
            "territory": {
                "territory_id": territory["territory_id"],
                "creative_job": territory["creative_job"],
                "opening_device": territory["opening_device"],
                "participation_device": territory["participation_device"],
            },
            "audience": {
                "name": audience["name"],
                "core_problem": audience["core_problem"],
                "desired_outcome": audience["desired_outcome"],
                "buying_context": audience["buying_context"],
            },
            "brand": {
                "name": brand["name"],
                "purpose": brand["purpose"],
                "customer_promise": brand["customer_promise"],
                "voice_principles": brand["voice_principles"],
            },
            "offer": context["offer"],
            "approved_proof": context["approved_proof"],
            "exact_cta": context["exact_cta"],
            "value_before_ask": context["value_before_ask"],
            "compiler_contract": compact_contract,
            "output_contract": nucleus_contract,
        }
    except (StopIteration, KeyError, TypeError, json.JSONDecodeError):
        return list(messages), False
    return (
        [
            {
                "role": "system",
                "content": (
                    "Return exactly one six-field JSON object. Select only enumerated values. "
                    "Do not generate campaign copy, factual claims, statistics or prose."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    compact,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        ],
        True,
    )


def compact_local_gtm_messages(
    messages: Sequence[Mapping[str, object]], purpose: str
) -> tuple[list[Mapping[str, object]], bool]:
    """Public, side-effect-free entry point for context-preservation evals."""

    return _compact_local_gtm_messages(messages, purpose)


class _LocalCreativeNucleusError(ValueError):
    """A constrained local creative nucleus could not be compiled safely."""


_LOCAL_NUCLEUS_FIELDS = frozenset(
    {
        "schema",
        "territory_id",
        "opening_variant",
        "participation_variant",
        "relay_variant",
        "tone_variant",
    }
)
_LOCAL_NUCLEUS_ALLOWED = {
    "opening_variant": {
        "unresolved_condition",
        "evidence_gap",
        "peer_challenge",
    },
    "participation_variant": {
        "mark_boundary",
        "rewrite_question",
        "rank_objection",
    },
    "relay_variant": {
        "decision_card",
        "review_checklist",
        "objection_map",
    },
    "tone_variant": {
        "calm_forensic",
        "direct_peer",
        "useful_challenge",
    },
}


def _compile_local_gtm_nucleus(
    content: str,
    prompt: Mapping[str, object],
) -> tuple[str, tuple[str, ...]] | None:
    if prompt.get("schema") != "ProofLaunchLocalGTMCreativeNucleusPromptV1":
        return None
    try:
        nucleus = json.loads(content)
        if not isinstance(nucleus, dict) or set(nucleus) != _LOCAL_NUCLEUS_FIELDS:
            raise _LocalCreativeNucleusError(
                "local creative nucleus fields do not match the closed contract"
            )
        if nucleus.get("schema") != "ProofLaunchLocalGTMCreativeNucleusV1":
            raise _LocalCreativeNucleusError("local creative nucleus schema is invalid")
        territory = prompt["territory"]
        if not isinstance(territory, Mapping):
            raise _LocalCreativeNucleusError("local creative territory is invalid")
        territory_id = str(territory["territory_id"])
        if nucleus.get("territory_id") != territory_id:
            raise _LocalCreativeNucleusError(
                "local creative nucleus territory identity drifted"
            )
        for field, allowed in _LOCAL_NUCLEUS_ALLOWED.items():
            if nucleus.get(field) not in allowed:
                raise _LocalCreativeNucleusError(
                    f"local creative nucleus {field} is outside the closed vocabulary"
                )
        compiler_contract = prompt["compiler_contract"]
        if not isinstance(compiler_contract, Mapping):
            raise _LocalCreativeNucleusError(
                "local creative compiler contract is invalid"
            )
        candidate = json.loads(
            json.dumps(compiler_contract, ensure_ascii=False, sort_keys=True)
        )
        if candidate.get("schema") != "ProofLaunchTextCreativeCandidateV1":
            raise _LocalCreativeNucleusError(
                "local creative compiler candidate schema is invalid"
            )
        if candidate.get("territory_id") != territory_id:
            raise _LocalCreativeNucleusError(
                "local creative compiler territory identity drifted"
            )
        channels = candidate.get("channels")
        if not isinstance(channels, list) or len(channels) != 2:
            raise _LocalCreativeNucleusError(
                "local creative compiler channel contract is invalid"
            )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise _LocalCreativeNucleusError(
            "local creative nucleus is not a compilable JSON object"
        ) from error

    opening_phrases = {
        "unresolved_condition": (
            "Opening logic: make the unresolved condition visible before any offer."
        ),
        "evidence_gap": (
            "Opening logic: expose the gap between available proof and the decision still pending."
        ),
        "peer_challenge": (
            "Opening logic: let a relevant peer challenge the weakest decision boundary."
        ),
    }
    participation_phrases = {
        "mark_boundary": (
            "Participant action: mark the boundary where the evidence stops resolving the decision."
        ),
        "rewrite_question": (
            "Participant action: rewrite the decision question so the missing condition is explicit."
        ),
        "rank_objection": (
            "Participant action: rank the unresolved objection before considering the next step."
        ),
    }
    relay_phrases = {
        "decision_card": (
            "Relay object: pass the decision card only when it saves a peer preparation work."
        ),
        "review_checklist": (
            "Relay object: adapt the review checklist before sharing it with one relevant peer."
        ),
        "objection_map": (
            "Relay object: preserve the objection map so the evidence limit travels with it."
        ),
    }
    tone_phrases = {
        "calm_forensic": (
            "Tone logic: inspect first, identify the boundary, and decide only afterward."
        ),
        "direct_peer": (
            "Tone logic: address one informed peer with a precise and answerable challenge."
        ),
        "useful_challenge": (
            "Tone logic: make the challenge useful even when the recipient declines the offer."
        ),
    }
    opening = opening_phrases[str(nucleus["opening_variant"])]
    participation = participation_phrases[str(nucleus["participation_variant"])]
    relay = relay_phrases[str(nucleus["relay_variant"])]
    tone = tone_phrases[str(nucleus["tone_variant"])]

    candidate["cultural_tension"] = f"{candidate['cultural_tension']} {opening}"
    candidate["organizing_idea"] = f"{candidate['organizing_idea']} {tone}"
    candidate["participation_mechanism"] = (
        f"{candidate['participation_mechanism']} {participation}"
    )
    candidate["share_trigger"] = f"{candidate['share_trigger']} {relay}"
    for index, addition in enumerate((participation, relay)):
        channel = channels[index]
        if not isinstance(channel, dict) or not isinstance(channel.get("body"), list):
            raise _LocalCreativeNucleusError(
                "local creative compiler channel body is invalid"
            )
        channel["body"].append(addition)
    compiled = json.dumps(
        candidate,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        compiled,
        (
            "creative_nucleus:compiled_full_candidate",
            f"creative_nucleus:opening_variant={nucleus['opening_variant']}",
            f"creative_nucleus:participation_variant={nucleus['participation_variant']}",
            f"creative_nucleus:relay_variant={nucleus['relay_variant']}",
            f"creative_nucleus:tone_variant={nucleus['tone_variant']}",
        ),
    )


def _normalize_local_gtm_candidate(
    content: str,
    messages: Sequence[Mapping[str, object]],
    purpose: str,
) -> tuple[str, tuple[str, ...]]:
    """Insert only an already-approved proof string omitted by a weak local decoder."""

    if purpose != "evidence_bound_gtm_text_creative_challenger":
        return content, ()
    try:
        user_message = next(
            item for item in reversed(messages) if item.get("role") == "user"
        )
        prompt = json.loads(str(user_message["content"]))
        compiled = _compile_local_gtm_nucleus(content, prompt)
        if compiled is not None:
            return compiled
        context = prompt.get("context")
        approved_proof = str(
            context["approved_proof"]
            if isinstance(context, Mapping)
            else prompt["approved_proof"]
        )
        candidate = json.loads(content)
        channels = candidate["channels"]
        if not isinstance(channels, list) or not approved_proof:
            return content, ()
    except (
        StopIteration,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):
        return content, ()
    changes: list[str] = []
    for index, channel in enumerate(channels):
        if not isinstance(channel, dict):
            continue
        body = channel.get("body")
        if not isinstance(body, list):
            continue
        combined = "\n".join(
            [
                str(channel.get("hook") or ""),
                *(str(item) for item in body),
                str(channel.get("cta") or ""),
            ]
        )
        if approved_proof not in combined and len(body) < 5:
            body.insert(0, approved_proof)
            changes.append(f"channels[{index}].body:insert_exact_approved_proof")
    exact_cta = str(
        context.get("exact_cta")
        if isinstance(context, Mapping)
        else prompt.get("exact_cta")
        or ""
    )
    number_pattern = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?")
    allowed_numbers = set(number_pattern.findall(approved_proof)) | set(
        number_pattern.findall(exact_cta)
    )
    for index, channel in enumerate(channels):
        if not isinstance(channel, dict):
            continue
        hook = str(channel.get("hook") or "")
        if set(number_pattern.findall(hook)) - allowed_numbers:
            channel["hook"] = "What evidence would change your decision?"
            changes.append(f"channels[{index}].hook:remove_unapproved_numeric_claim")
        body = channel.get("body")
        if not isinstance(body, list):
            continue
        safe_body = [
            item
            for item in body
            if not (set(number_pattern.findall(str(item))) - allowed_numbers)
        ]
        removed = len(body) - len(safe_body)
        if removed:
            channel["body"] = safe_body
            body = safe_body
            changes.append(
                f"channels[{index}].body:remove_{removed}_unapproved_numeric_claim_block"
            )
        while len(body) < 2:
            body.append("What evidence would you need before taking the next step?")
            changes.append(f"channels[{index}].body:add_nonclaim_review_prompt")
    if not changes:
        return content, ()
    return (
        json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        tuple(changes),
    )


class OllamaLocalClient:
    """Digest-pinned localhost inference for product development, never contest proof."""

    def __init__(self, spec: OllamaLocalSpec, *, transport: object | None = None) -> None:
        spec.validate()
        self.spec = spec
        self._transport = transport or UrllibOllamaLocalTransport()

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        scope: InferenceScope,
        purpose: str,
        max_tokens: int,
        temperature: float,
        timeout_seconds: float,
        official_models: Sequence[str] | None = None,
        official_retry_rounds: int = 0,
    ) -> GatewayResult:
        del official_models, official_retry_rounds
        if scope not in OLLAMA_LOCAL_ALLOWED_SCOPES:
            raise InferenceGatewayPolicyError(
                f"local Apple/Ollama inference is not approved for {scope.value}"
            )
        if not messages or not purpose.strip():
            raise InferenceGatewayPolicyError("local inference requires messages and purpose")
        if not 1 <= max_tokens <= self.spec.maximum_output_tokens:
            raise InferenceGatewayPolicyError("local inference output budget is out of bounds")
        if not math.isfinite(temperature) or not 0 <= temperature <= 1:
            raise InferenceGatewayPolicyError("local inference temperature must be in [0, 1]")
        if not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 300:
            raise InferenceGatewayPolicyError("local inference timeout must be in [1, 300]")

        request_sha256 = _request_hash(messages)
        effective_messages, prompt_compaction_applied = compact_local_gtm_messages(
            messages,
            purpose,
        )
        local_nucleus_compilation = False
        if prompt_compaction_applied:
            try:
                effective_user = next(
                    item
                    for item in reversed(effective_messages)
                    if item.get("role") == "user"
                )
                effective_prompt = json.loads(str(effective_user["content"]))
                local_nucleus_compilation = (
                    effective_prompt.get("schema")
                    == "ProofLaunchLocalGTMCreativeNucleusPromptV1"
                )
            except (StopIteration, TypeError, json.JSONDecodeError):
                local_nucleus_compilation = False
        effective_max_tokens = (
            min(max_tokens, 96)
            if local_nucleus_compilation
            else min(max_tokens, 768)
            if purpose == "evidence_bound_gtm_text_creative_challenger"
            else max_tokens
        )
        inventory = self._transport.get_json(
            url=f"{self.spec.base_url.rstrip('/')}/api/tags",
            timeout_seconds=timeout_seconds,
        )
        base_receipt: dict[str, object] = {
            "schema": GATEWAY_SCHEMA,
            "route": "local_ollama",
            "provider": "ollama_local",
            "model": self.spec.model,
            "model_digest": self.spec.digest,
            "scope": scope.value,
            "purpose": purpose,
            "request_sha256": request_sha256,
            "effective_prompt_sha256": _request_hash(effective_messages),
            "prompt_compaction_applied": prompt_compaction_applied,
            "prompt_compaction_schema": (
                "ProofLaunchLocalGTMCreativeNucleusPromptV1"
                if local_nucleus_compilation
                else "ProofLaunchLocalGTMCompactPromptV1"
                if prompt_compaction_applied
                else None
            ),
            "creative_scaffold_applied": prompt_compaction_applied,
            "creative_scaffold_schema": (
                "ProofLaunchLocalGTMCreativeNucleusCompilerV1"
                if local_nucleus_compilation
                else "ProofLaunchLocalGTMContextScaffoldV1"
                if prompt_compaction_applied
                else None
            ),
            "creative_scaffold_field_lock_applied": prompt_compaction_applied,
            "creative_model_role": (
                "bounded_local_creative_nucleus_selector"
                if local_nucleus_compilation
                else "schema_constrained_local_assembly"
                if prompt_compaction_applied
                else "unconstrained_by_creative_scaffold"
            ),
            "creative_nucleus_compilation_applied": local_nucleus_compilation,
            "requested_max_tokens": max_tokens,
            "effective_max_tokens": effective_max_tokens,
            "inventory_http_status": inventory.status,
            "localhost_only": True,
            "cloud_api_calls": 0,
            "network_download_performed": False,
            "credential_required": False,
            "competition_core_eligible": False,
            "radeon_local_inference": False,
            "automatic_external_action_enabled": False,
        }
        try:
            inventory_payload = json.loads(inventory.body.decode("utf-8"))
            installed = next(
                row
                for row in inventory_payload.get("models", [])
                if isinstance(row, Mapping)
                and row.get("digest") == self.spec.digest
                and (row.get("name") == self.spec.model or row.get("model") == self.spec.model)
            )
        except (UnicodeDecodeError, json.JSONDecodeError, StopIteration, TypeError, AttributeError):
            base_receipt.update({"status": "blocked", "error_code": "pinned_model_not_installed"})
            raise InferenceGatewayCallError(
                "the digest-pinned local Ollama model is not installed",
                base_receipt,
            )

        payload = {
            "model": str(installed.get("name") or installed.get("model")),
            "messages": effective_messages,
            "format": _ollama_structured_output_format(effective_messages, purpose),
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": effective_max_tokens,
                "seed": 42,
            },
        }
        response = self._transport.post_json(
            url=f"{self.spec.base_url.rstrip('/')}/api/chat",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ProofLaunch-LocalGateway/1.0",
            },
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        receipt = {
            **base_receipt,
            "http_status": response.status,
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        if response.status != 200:
            receipt.update(
                {
                    "status": "blocked",
                    "error_code": "network_error" if response.status == 0 else f"http_{response.status}",
                }
            )
            raise InferenceGatewayCallError("local Ollama inference failed", receipt)
        try:
            decoded = json.loads(response.body.decode("utf-8"))
            content = decoded["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not text")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            receipt.update({"status": "blocked", "error_code": "invalid_response_contract"})
            raise InferenceGatewayCallError(
                "local Ollama returned an invalid response",
                receipt,
            )
        raw_response_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        try:
            content, normalizations = _normalize_local_gtm_candidate(
                content,
                effective_messages,
                purpose,
            )
        except _LocalCreativeNucleusError:
            receipt.update(
                {
                    "raw_response_sha256": raw_response_sha256,
                    "status": "blocked",
                    "error_code": "local_creative_nucleus_compile_failed",
                }
            )
            raise InferenceGatewayCallError(
                "local creative nucleus failed the closed compiler contract",
                receipt,
            )
        receipt.update(
            {
                "raw_response_sha256": raw_response_sha256,
                "normalized_response_sha256": hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest(),
                "deterministic_contract_normalizations": list(normalizations),
                "deterministic_contract_normalization_count": len(normalizations),
            }
        )
        receipt["status"] = "passed"
        return GatewayResult(
            provider="ollama_local",
            model=self.spec.model,
            route="local_ollama",
            content=content,
            response_id=None,
            finish_reason=str(decoded.get("done_reason")) if decoded.get("done_reason") else None,
            usage={
                "prompt_tokens": decoded.get("prompt_eval_count"),
                "completion_tokens": decoded.get("eval_count"),
            },
            receipt=receipt,
        )


def load_third_party_provider_specs(
    path: str | Path,
) -> tuple[ThirdPartyProviderSpec, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != THIRD_PARTY_CONFIG_SCHEMA:
        raise InferenceGatewayPolicyError(
            f"third-party config must use {THIRD_PARTY_CONFIG_SCHEMA}"
        )
    providers = payload.get("providers")
    if not isinstance(providers, list) or not providers:
        raise InferenceGatewayPolicyError(
            "third-party config requires at least one provider"
        )
    specs: list[ThirdPartyProviderSpec] = []
    identities: set[str] = set()
    for item in providers:
        if not isinstance(item, Mapping):
            raise InferenceGatewayPolicyError(
                "third-party provider entry must be an object"
            )
        try:
            spec = ThirdPartyProviderSpec(
                provider=str(item["provider"]),
                base_url=str(item["base_url"]),
                model=str(item["model"]),
                api_key_env=str(item["api_key_env"]),
                data_processing_approved=bool(
                    item["data_processing_approved"]
                ),
                license_reviewed=bool(item["license_reviewed"]),
                maximum_call_cost_usd=float(
                    item["maximum_call_cost_usd"]
                ),
                quality_contract=str(item["quality_contract"]),
                allowed_scopes=tuple(
                    InferenceScope(value)
                    for value in item["allowed_scopes"]
                ),
                service_tier=str(item.get("service_tier", "default")),
                capabilities=tuple(item.get("capabilities", ("text",))),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InferenceGatewayPolicyError(
                "invalid third-party provider configuration"
            ) from error
        spec.validate()
        if spec.provider in identities:
            raise InferenceGatewayPolicyError(
                f"duplicate third-party provider identity: {spec.provider}"
            )
        identities.add(spec.provider)
        specs.append(spec)
    return tuple(specs)


def _request_hash(messages: Sequence[Mapping[str, object]]) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(
            list(messages),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _eligible_official_failure(receipt: Mapping[str, object]) -> bool:
    allowed = {
        "network_error",
        "model_gateway_unavailable",
        "rate_limited",
        "http_500",
        "http_503",
        "http_504",
        "invalid_response_contract",
    }
    attempts = receipt.get("attempts")
    return bool(attempts) and all(
        isinstance(item, Mapping) and item.get("error_code") in allowed
        for item in attempts
    )


class OpenAICompatibleThirdPartyClient:
    def __init__(
        self,
        spec: ThirdPartyProviderSpec,
        *,
        transport: TokenFactoryTransport | None = None,
    ) -> None:
        spec.validate()
        self.spec = spec
        self._transport = transport or UrllibTokenFactoryTransport()

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        scope: InferenceScope,
        purpose: str,
        max_tokens: int,
        temperature: float,
        timeout_seconds: float,
    ) -> GatewayResult:
        if scope not in self.spec.allowed_scopes:
            raise InferenceGatewayPolicyError(
                f"{self.spec.provider} is not approved for {scope.value}"
            )
        api_key = os.environ.get(self.spec.api_key_env)
        if not api_key or not api_key.strip():
            raise InferenceGatewayCallError(
                f"missing {self.spec.api_key_env}",
                {
                    "provider": self.spec.provider,
                    "model": self.spec.model,
                    "endpoint": self.spec.chat_url,
                    "scope": scope.value,
                    "purpose": purpose,
                    "quality_contract": self.spec.quality_contract,
                    "status": "blocked",
                    "error_code": "missing_credential",
                    "credential": {
                        "source": self.spec.api_key_env,
                        "persisted": False,
                        "redacted": True,
                    },
                    "competition_core_eligible": False,
                },
            )
        response = self._transport.post_json(
            url=self.spec.chat_url,
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ProofLaunch-ResilientGateway/1.0",
            },
            payload={
                "model": self.spec.model,
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "service_tier": self.spec.service_tier,
            },
            timeout_seconds=timeout_seconds,
        )
        receipt = {
            "provider": self.spec.provider,
            "model": self.spec.model,
            "endpoint": self.spec.chat_url,
            "scope": scope.value,
            "purpose": purpose,
            "quality_contract": self.spec.quality_contract,
            "service_tier": self.spec.service_tier,
            "capabilities": list(self.spec.capabilities),
            "maximum_call_cost_usd": self.spec.maximum_call_cost_usd,
            "request_sha256": _request_hash(messages),
            "http_status": response.status,
            "credential": {
                "source": self.spec.api_key_env,
                "persisted": False,
                "redacted": True,
            },
            "competition_core_eligible": False,
        }
        if response.status != 200:
            receipt["status"] = "blocked"
            receipt["error_code"] = (
                "network_error"
                if response.status == 0
                else f"http_{response.status}"
            )
            raise InferenceGatewayCallError(
                f"third-party provider {self.spec.provider} failed",
                receipt,
            )
        try:
            payload = json.loads(response.body.decode("utf-8"))
            choice = payload["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not text")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
            receipt.update(
                {"status": "blocked", "error_code": "invalid_response_contract"}
            )
            raise InferenceGatewayCallError(
                f"third-party provider {self.spec.provider} returned an invalid response",
                receipt,
            )
        receipt["status"] = "passed"
        return GatewayResult(
            provider=self.spec.provider,
            model=self.spec.model,
            route="third_party_fallback",
            content=content,
            response_id=(
                str(payload["id"]) if payload.get("id") is not None else None
            ),
            finish_reason=(
                str(choice["finish_reason"])
                if choice.get("finish_reason") is not None
                else None
            ),
            usage=(
                dict(payload["usage"])
                if isinstance(payload.get("usage"), Mapping)
                else {}
            ),
            receipt=receipt,
        )


class ResilientInferenceGateway:
    """Official-first inference with audited, bounded third-party fallback."""

    def __init__(
        self,
        *,
        official_client: TokenFactoryClient,
        third_party_clients: Sequence[OpenAICompatibleThirdPartyClient] = (),
        now: Callable[[], float] = time.time,
    ) -> None:
        self.official_client = official_client
        self.third_party_clients = tuple(third_party_clients)
        self._now = now

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        scope: InferenceScope,
        purpose: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        timeout_seconds: float = 45.0,
        official_models: Sequence[str] | None = None,
        official_retry_rounds: int = 1,
    ) -> GatewayResult:
        if scope is InferenceScope.COMPETITION_CORE:
            raise InferenceGatewayPolicyError(
                "competition core is local Radeon only; online inference is forbidden"
            )
        started_at = self._now()
        official_failure_receipt: Mapping[str, object] | None = None
        try:
            official_arguments: dict[str, object] = {
                "purpose": purpose,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout_seconds": timeout_seconds,
                "retry_rounds": official_retry_rounds,
            }
            if official_models is not None:
                official_arguments["models"] = official_models
            official = self.official_client.complete(
                messages,
                **official_arguments,
            )
            return self._from_official(official, scope, started_at)
        except TokenFactoryConfigurationError:
            raise
        except TokenFactoryCallError as official_error:
            official_failure_receipt = official_error.receipt
            if not _eligible_official_failure(official_error.receipt):
                raise InferenceGatewayCallError(
                    "official Token Factory failed for a non-fallback-eligible reason",
                    {
                        "schema": GATEWAY_SCHEMA,
                        "status": "blocked",
                        "scope": scope.value,
                        "official": official_error.receipt,
                        "third_party_attempts": [],
                    },
                ) from official_error
        if official_failure_receipt is None:
            raise InferenceGatewayError(
                "official failure receipt was not captured"
            )

        failures: list[Mapping[str, object]] = []
        for client in self.third_party_clients:
            try:
                result = client.complete(
                    messages,
                    scope=scope,
                    purpose=purpose,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_seconds=timeout_seconds,
                )
                composite = {
                    "schema": GATEWAY_SCHEMA,
                    "status": "passed",
                    "route": "third_party_fallback",
                    "scope": scope.value,
                    "purpose": purpose,
                    "started_at_epoch": started_at,
                    "completed_at_epoch": self._now(),
                    "official": official_failure_receipt,
                    "third_party_attempts": [*failures, result.receipt],
                    "quality_contract": OFFICIAL_FINE_TUNING_PARITY_CONTRACT,
                    "competition_core_eligible": False,
                }
                return GatewayResult(
                    provider=result.provider,
                    model=result.model,
                    route=result.route,
                    content=result.content,
                    response_id=result.response_id,
                    finish_reason=result.finish_reason,
                    usage=result.usage,
                    receipt=composite,
                )
            except InferenceGatewayCallError as error:
                failures.append(error.receipt)

        raise InferenceGatewayCallError(
            "official Token Factory and every approved third-party fallback failed",
            {
                "schema": GATEWAY_SCHEMA,
                "status": "blocked",
                "scope": scope.value,
                "purpose": purpose,
                "started_at_epoch": started_at,
                "completed_at_epoch": self._now(),
                "official": official_failure_receipt,
                "third_party_attempts": failures,
                "quality_contract": OFFICIAL_FINE_TUNING_PARITY_CONTRACT,
                "competition_core_eligible": False,
            },
        )

    def _from_official(
        self,
        result: TokenFactoryResult,
        scope: InferenceScope,
        started_at: float,
    ) -> GatewayResult:
        receipt = {
            "schema": GATEWAY_SCHEMA,
            "status": "passed",
            "route": "official_tokenfactory",
            "scope": scope.value,
            "started_at_epoch": started_at,
            "completed_at_epoch": self._now(),
            "official": result.receipt,
            "third_party_attempts": [],
            "quality_contract": OFFICIAL_FINE_TUNING_PARITY_CONTRACT,
            "competition_core_eligible": False,
        }
        return GatewayResult(
            provider=result.provider,
            model=result.model,
            route="official_tokenfactory",
            content=result.content,
            response_id=result.response_id,
            finish_reason=result.finish_reason,
            usage=result.usage,
            receipt=receipt,
        )
