from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ProviderDecisionStatus(str, Enum):
    PROVIDER_ALLOWED = "PROVIDER_ALLOWED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_NEEDS_EXACT_REFERENCE = "PROVIDER_NEEDS_EXACT_REFERENCE"


@dataclass(slots=True)
class DiscoveryProvider:
    name: str
    type: str
    allowed_queries: list[str] = field(default_factory=list)
    requires_digest: bool = False
    requires_revision: bool = False
    allows_broad_search: bool = False


@dataclass(slots=True)
class ProviderDecision:
    status: str
    reason: str
    provider: str = ""


class DiscoveryProviderRegistry:
    def __init__(
        self, path: Path = Path("assurance/config/online_discovery_providers.json")
    ) -> None:
        self.path = path
        self.providers = self._load(path)

    def get(self, name: str) -> DiscoveryProvider | None:
        return self.providers.get(name)

    def validate_request(self, provider_name: str, request: dict[str, Any]) -> ProviderDecision:
        provider = self.get(provider_name)
        if provider is None:
            return ProviderDecision(
                ProviderDecisionStatus.PROVIDER_REJECTED.value,
                "provider_not_registered",
                provider_name,
            )
        if request.get("broad_search") is True or request.get("query"):
            if not provider.allows_broad_search:
                return ProviderDecision(
                    ProviderDecisionStatus.PROVIDER_REJECTED.value,
                    "broad_search_disabled",
                    provider_name,
                )
        query_type = str(request.get("query_type") or "")
        if query_type not in provider.allowed_queries:
            return ProviderDecision(
                ProviderDecisionStatus.PROVIDER_NEEDS_EXACT_REFERENCE.value,
                "query_type_not_allowlisted",
                provider_name,
            )
        if provider.type in {"ghcr", "github_release"} and not _has_exact_owner_repo(request):
            return ProviderDecision(
                ProviderDecisionStatus.PROVIDER_NEEDS_EXACT_REFERENCE.value,
                "exact_owner_repo_required",
                provider_name,
            )
        if provider.type == "huggingface" and not request.get("repo_id"):
            return ProviderDecision(
                ProviderDecisionStatus.PROVIDER_NEEDS_EXACT_REFERENCE.value,
                "explicit_hf_repo_required",
                provider_name,
            )
        if (
            provider.type == "docker_hub"
            and query_type == "official_namespace"
            and not request.get("image")
        ):
            return ProviderDecision(
                ProviderDecisionStatus.PROVIDER_NEEDS_EXACT_REFERENCE.value,
                "exact_image_required",
                provider_name,
            )
        return ProviderDecision(
            ProviderDecisionStatus.PROVIDER_ALLOWED.value, "provider_request_allowed", provider_name
        )

    @staticmethod
    def _load(path: Path) -> dict[str, DiscoveryProvider]:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, DiscoveryProvider] = {}
        for row in data.get("providers") or []:
            if isinstance(row, dict) and row.get("name"):
                provider = DiscoveryProvider(
                    name=str(row.get("name") or ""),
                    type=str(row.get("type") or ""),
                    allowed_queries=[str(item) for item in row.get("allowed_queries") or []],
                    requires_digest=bool(row.get("requires_digest")),
                    requires_revision=bool(row.get("requires_revision")),
                    allows_broad_search=bool(row.get("allows_broad_search")),
                )
                out[provider.name] = provider
        return out


def _has_exact_owner_repo(request: dict[str, Any]) -> bool:
    return bool(request.get("owner") and request.get("repo"))
