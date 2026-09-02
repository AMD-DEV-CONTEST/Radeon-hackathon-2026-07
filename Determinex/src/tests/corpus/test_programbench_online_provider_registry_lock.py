from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.legacy_recovery.artifact_discovery_provider_registry import (  # noqa: E402
    DiscoveryProviderRegistry,
    ProviderDecisionStatus,
)


def _registry(tmp_path: Path) -> DiscoveryProviderRegistry:
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "name": "docker_hub_official",
                        "type": "docker_hub",
                        "allowed_queries": ["official_namespace", "exact_image_reference"],
                        "requires_digest": True,
                        "allows_broad_search": False,
                    },
                    {
                        "name": "ghcr_exact",
                        "type": "ghcr",
                        "allowed_queries": ["exact_owner_repo"],
                        "requires_digest": True,
                        "allows_broad_search": False,
                    },
                    {
                        "name": "github_release_metadata",
                        "type": "github_release",
                        "allowed_queries": ["exact_owner_repo"],
                        "requires_revision": True,
                        "allows_broad_search": False,
                    },
                    {
                        "name": "huggingface_explicit",
                        "type": "huggingface",
                        "allowed_queries": ["explicit_repo_reference"],
                        "requires_revision": True,
                        "allows_broad_search": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return DiscoveryProviderRegistry(path)


def test_docker_hub_official_exact_image_allowed(tmp_path):
    decision = _registry(tmp_path).validate_request(
        "docker_hub_official",
        {"query_type": "official_namespace", "image": "library/debian"},
    )

    assert decision.status == ProviderDecisionStatus.PROVIDER_ALLOWED.value


def test_broad_search_rejected(tmp_path):
    decision = _registry(tmp_path).validate_request(
        "docker_hub_official",
        {"query_type": "official_namespace", "query": "best programbench image"},
    )

    assert decision.status == ProviderDecisionStatus.PROVIDER_REJECTED.value
    assert decision.reason == "broad_search_disabled"


def test_ghcr_requires_exact_owner_repo(tmp_path):
    decision = _registry(tmp_path).validate_request(
        "ghcr_exact",
        {"query_type": "exact_owner_repo", "owner": "rcoh"},
    )

    assert decision.status == ProviderDecisionStatus.PROVIDER_NEEDS_EXACT_REFERENCE.value
    assert decision.reason == "exact_owner_repo_required"


def test_ghcr_exact_owner_repo_allowed(tmp_path):
    decision = _registry(tmp_path).validate_request(
        "ghcr_exact",
        {"query_type": "exact_owner_repo", "owner": "rcoh", "repo": "angle-grinder"},
    )

    assert decision.status == ProviderDecisionStatus.PROVIDER_ALLOWED.value


def test_huggingface_requires_explicit_repo(tmp_path):
    decision = _registry(tmp_path).validate_request(
        "huggingface_explicit",
        {"query_type": "explicit_repo_reference"},
    )

    assert decision.status == ProviderDecisionStatus.PROVIDER_NEEDS_EXACT_REFERENCE.value
    assert decision.reason == "explicit_hf_repo_required"


def test_unknown_provider_rejected(tmp_path):
    decision = _registry(tmp_path).validate_request(
        "search_everywhere",
        {"query_type": "broad"},
    )

    assert decision.status == ProviderDecisionStatus.PROVIDER_REJECTED.value
    assert decision.reason == "provider_not_registered"


def test_non_allowlisted_query_type_rejected(tmp_path):
    decision = _registry(tmp_path).validate_request(
        "github_release_metadata",
        {"query_type": "keyword_search", "owner": "rcoh", "repo": "angle-grinder"},
    )

    assert decision.status == ProviderDecisionStatus.PROVIDER_NEEDS_EXACT_REFERENCE.value
    assert decision.reason == "query_type_not_allowlisted"
