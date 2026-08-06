"""OpenAI-compatible localhost vLLM adapter and deterministic test fake."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import ValidationError

from .models import (
    InvalidModelOutput,
    M2SemanticRoleAssignment,
    M2SemanticRoleProposal,
    M2SemanticRoleResult,
    M3LedgerProposal,
    M3LedgerResult,
    M4MapProposal,
    M4MapResult,
    ModelMetadata,
    ModelRequest,
    ModelResult,
    ModelTimedOut,
    ModelUnavailable,
    RelationDiscoveryProposal,
    RelationDiscoveryResult,
    StructuredProposal,
    ToolCallProposal,
)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ModelClient(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResult:
        """Return an untrusted structured proposal without executing tools."""

    async def generate_m2_roles(self, request: ModelRequest) -> M2SemanticRoleResult:
        """Return untrusted M2 semantic-role assignments without side effects."""

    async def generate_m3_ledger(self, request: ModelRequest) -> M3LedgerResult:
        """Return an untrusted M3 ledger proposal without executing tools."""

    async def generate_m4_map(self, request: ModelRequest) -> M4MapResult:
        """Return an untrusted M4 insight/boundary proposal without executing tools."""

    async def generate_relation_discovery(
        self, request: ModelRequest
    ) -> RelationDiscoveryResult:
        """Compare the supplied graphs in one batch, proposing identifiers only."""


def require_loopback_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("core model endpoint must be an http loopback address")
    if parsed.username or parsed.password:
        raise ValueError("model endpoint must not embed credentials")
    return base_url.rstrip("/")


class LocalVLLMClient:
    def __init__(self, *, base_url: str, model_id: str, api_key: str = "EMPTY") -> None:
        self.base_url = require_loopback_base_url(base_url)
        self.model_id = model_id
        self.api_key = api_key

    async def generate(self, request: ModelRequest) -> ModelResult:
        body, elapsed_ms = await self._post_structured_request(
            request,
            schema_name="structured_proposal_v1",
        )
        return self.parse_response(body, elapsed_ms=elapsed_ms)

    async def generate_m2_roles(self, request: ModelRequest) -> M2SemanticRoleResult:
        body, elapsed_ms = await self._post_structured_request(
            request,
            schema_name="m2_semantic_role_proposal_v1",
        )
        try:
            message = body["choices"][0]["message"]
            if message.get("tool_calls"):
                raise InvalidModelOutput("M2 semantic-role extraction must not propose tool calls")
            content = message.get("content")
            content_object = json.loads(content) if isinstance(content, str) else content
            proposal = M2SemanticRoleProposal.model_validate(content_object)
            metadata = self._metadata(body, elapsed_ms=elapsed_ms)
        except InvalidModelOutput:
            raise
        except (
            AttributeError,
            IndexError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise InvalidModelOutput(
                "local M2 semantic-role output failed structured validation"
            ) from exc
        return M2SemanticRoleResult(proposal=proposal, metadata=metadata)

    async def generate_m3_ledger(self, request: ModelRequest) -> M3LedgerResult:
        body, elapsed_ms = await self._post_structured_request(
            request, schema_name="m3_ledger_proposal_v1"
        )
        try:
            message = body["choices"][0]["message"]
            content = message.get("content") or "{}"
            value = json.loads(content) if isinstance(content, str) else content
            calls = message.get("tool_calls") or []
            proposals = list(value.get("tool_call_proposals", []))
            for call in calls:
                function = call["function"]
                arguments = function.get("arguments", {})
                proposals.append(
                    {
                        "name": function["name"],
                        "arguments": json.loads(arguments)
                        if isinstance(arguments, str)
                        else arguments,
                        "requested_reason": "Model proposed a tool during M3 generation.",
                        "permission_granted": False,
                    }
                )
            value["tool_call_proposals"] = proposals
            return M3LedgerResult(
                proposal=M3LedgerProposal.model_validate(value),
                metadata=self._metadata(body, elapsed_ms=elapsed_ms),
            )
        except (
            AttributeError,
            IndexError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise InvalidModelOutput("local M3 output failed structured validation") from exc

    async def generate_m4_map(self, request: ModelRequest) -> M4MapResult:
        body, elapsed_ms = await self._post_structured_request(
            request, schema_name="m4_map_proposal_v1"
        )
        try:
            message = body["choices"][0]["message"]
            content = message.get("content") or "{}"
            value = json.loads(content) if isinstance(content, str) else content
            calls = message.get("tool_calls") or []
            proposals = list(value.get("tool_call_proposals", []))
            for call in calls:
                function = call["function"]
                arguments = function.get("arguments", {})
                proposals.append(
                    {
                        "name": function["name"],
                        "arguments": json.loads(arguments)
                        if isinstance(arguments, str)
                        else arguments,
                        "requested_reason": "Model proposed a tool during M4 generation.",
                        "permission_granted": False,
                    }
                )
            value["tool_call_proposals"] = proposals
            return M4MapResult(
                proposal=M4MapProposal.model_validate(value),
                metadata=self._metadata(body, elapsed_ms=elapsed_ms),
            )
        except (
            AttributeError,
            IndexError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise InvalidModelOutput("local M4 output failed structured validation") from exc

    async def generate_relation_discovery(
        self, request: ModelRequest
    ) -> RelationDiscoveryResult:
        body, elapsed_ms = await self._post_structured_request(
            request, schema_name="relation_discovery_proposal_v1"
        )
        try:
            message = body["choices"][0]["message"]
            if message.get("tool_calls"):
                # The model's contribution is judging correspondence among the
                # graphs it was handed. A tool call means it tried to choose its
                # own scope, and the Runtime cannot validate identifiers against
                # projections it never supplied.
                raise InvalidModelOutput("relation discovery must not propose tool calls")
            content = message.get("content") or "{}"
            value = json.loads(content) if isinstance(content, str) else content
            return RelationDiscoveryResult(
                proposal=RelationDiscoveryProposal.model_validate(value),
                metadata=self._metadata(body, elapsed_ms=elapsed_ms),
            )
        except InvalidModelOutput:
            raise
        except (
            AttributeError,
            IndexError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise InvalidModelOutput(
                "local relation discovery output failed structured validation"
            ) from exc

    async def _post_structured_request(
        self,
        request: ModelRequest,
        *,
        schema_name: str,
    ) -> tuple[dict, int]:
        started = time.monotonic()
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": request.system_policy},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "stage": request.stage,
                            "canonical_context": request.canonical_context,
                            "source_excerpts": [
                                excerpt.model_dump(mode="json")
                                for excerpt in request.source_excerpts
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "max_tokens": request.max_output_tokens,
            "temperature": 0,
            # Qwen3.5's default chat template opens a reasoning block.  The
            # application contracts require a bounded JSON result, not a long
            # hidden chain of thought, and the default thinking path can
            # exhaust the request timeout before emitting the schema object.
            # This is request-local serving configuration; Runtime validation
            # and every permission boundary remain unchanged.
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": request.output_schema,
                    "strict": True,
                },
            },
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = "auto"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=request.timeout_seconds,
            ) as client:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ModelTimedOut("local model request timed out") from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable("local model endpoint is unavailable") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise InvalidModelOutput("local model response body is not valid JSON") from exc

        elapsed_ms = round((time.monotonic() - started) * 1000)
        if not isinstance(body, dict):
            raise InvalidModelOutput("local model response body must be an object")
        return body, elapsed_ms

    def parse_response(self, body: dict, *, elapsed_ms: int) -> ModelResult:
        """Validate content and retain only bounded metadata, never raw response text."""

        try:
            message = body["choices"][0]["message"]
            content = message.get("content") or "{}"
            content_object = json.loads(content) if isinstance(content, str) else content
            tool_calls = message.get("tool_calls") or []
            parsed_tools = []
            for call in tool_calls:
                function = call["function"]
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                parsed_tools.append(
                    ToolCallProposal(
                        name=function["name"],
                        arguments=arguments,
                        requested_reason="Model requested a local application tool.",
                    )
                )
            if not content_object and parsed_tools:
                content_object = {"summary": "Model proposed one or more local application tools."}
            if parsed_tools:
                existing = content_object.get("tool_call_proposals", [])
                content_object["tool_call_proposals"] = [*existing, *parsed_tools]
            proposal = StructuredProposal.model_validate(content_object)
            metadata = self._metadata(body, elapsed_ms=elapsed_ms)
        except (
            AttributeError,
            IndexError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise InvalidModelOutput("local model output failed structured validation") from exc
        return ModelResult(proposal=proposal, metadata=metadata)

    def _metadata(self, body: dict, *, elapsed_ms: int) -> ModelMetadata:
        usage = body.get("usage") or {}
        return ModelMetadata(
            server_kind="vllm",
            server_base_url=self.base_url,
            model_id=body.get("model") or self.model_id,
            response_id=body.get("id"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            elapsed_ms=elapsed_ms,
            received_at=datetime.now(UTC),
        )


class FakeModelClient:
    """Deterministic substitute for contract tests; it never performs I/O."""

    def __init__(
        self,
        proposal: StructuredProposal | None = None,
        *,
        m2_role_proposal: M2SemanticRoleProposal | None = None,
        m3_ledger_proposal: M3LedgerProposal | None = None,
        m4_map_proposal: M4MapProposal | None = None,
        relation_proposal: RelationDiscoveryProposal | None = None,
    ) -> None:
        self.proposal = proposal or StructuredProposal(
            summary="No source content was supplied; request user input.",
            questions=[
                {
                    "question": "请先提供一段具体经历。",
                    "why_it_matters": "没有来源内容时不能生成事实。",
                }
            ],
        )
        self.m2_role_proposal = m2_role_proposal
        self.m3_ledger_proposal = m3_ledger_proposal
        self.m4_map_proposal = m4_map_proposal
        self.relation_proposal = relation_proposal

    async def generate(self, request: ModelRequest) -> ModelResult:
        return ModelResult(
            proposal=self.proposal.model_copy(deep=True),
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/fake",
                model_id="deterministic-contract-fake",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )

    async def generate_m2_roles(self, request: ModelRequest) -> M2SemanticRoleResult:
        proposal = self.m2_role_proposal
        if proposal is None:
            statement_ids = request.canonical_context.get("statement_ids")
            if not isinstance(statement_ids, list) or not statement_ids:
                raise InvalidModelOutput("M2 fake requires canonical statement_ids")
            proposal = M2SemanticRoleProposal(
                assignments=[
                    M2SemanticRoleAssignment(
                        statement_id=UUID(str(statement_id)),
                        roles=[],
                        reasoning="The deterministic test fixture proposes no role.",
                    )
                    for statement_id in statement_ids
                ]
            )
        return M2SemanticRoleResult(
            proposal=proposal.model_copy(deep=True),
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/fake",
                model_id="deterministic-contract-fake",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )

    async def generate_m3_ledger(self, request: ModelRequest) -> M3LedgerResult:
        if self.m3_ledger_proposal is None:
            raise InvalidModelOutput("M3 fake requires an explicit ledger proposal")
        return M3LedgerResult(
            proposal=self.m3_ledger_proposal.model_copy(deep=True),
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/fake",
                model_id="deterministic-contract-fake",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )

    async def generate_relation_discovery(
        self, request: ModelRequest
    ) -> RelationDiscoveryResult:
        if self.relation_proposal is None:
            raise InvalidModelOutput("discovery fake requires an explicit proposal")
        return RelationDiscoveryResult(
            proposal=self.relation_proposal.model_copy(deep=True),
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/fake",
                model_id="deterministic-contract-fake",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )

    async def generate_m4_map(self, request: ModelRequest) -> M4MapResult:
        if self.m4_map_proposal is None:
            raise InvalidModelOutput("M4 fake requires an explicit map proposal")
        return M4MapResult(
            proposal=self.m4_map_proposal.model_copy(deep=True),
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/fake",
                model_id="deterministic-contract-fake",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )
