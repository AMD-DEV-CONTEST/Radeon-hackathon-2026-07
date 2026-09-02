from __future__ import annotations

import json
from typing import Any

from corpus.programbench.batch001_live_manifest_metadata_lookup import (
    Batch001LiveManifestLookupConfig,
    ProgramBenchBatch001LiveManifestLookupCampaign,
)
from corpus.programbench.batch001_live_manifest_metadata_record import (
    verify_live_manifest_metadata_record,
)
from corpus.programbench.safe_registry_manifest_client import (
    SafeRegistryManifestClient,
    is_broad_search_request,
    parse_image_reference,
)
from corpus.programbench.safe_registry_manifest_record import verify_safe_registry_manifest_record


class FixtureTransport:
    def __init__(
        self,
        manifest_status: int = 200,
        *,
        digest: str = "sha256:" + "a" * 64,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self.manifest_status = manifest_status
        self.digest = digest
        self.manifest = manifest or {
            "schemaVersion": 2,
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        }
        self.urls: list[str] = []

    def get_json(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        self.urls.append(url)
        return 200, {}, {"token": "fixture-token"}

    def get_bytes(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, dict[str, str], bytes]:
        self.urls.append(url)
        if self.manifest_status == 429:
            return 429, {}, b'{"errors":[{"code":"TOOMANYREQUESTS"}]}'
        if self.manifest_status == 404:
            return 404, {}, b'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}'
        return (
            self.manifest_status,
            {"Docker-Content-Digest": self.digest},
            json.dumps(self.manifest).encode("utf-8"),
        )


def _campaign(
    client: SafeRegistryManifestClient | None = None, *, live_lookup: bool = True
) -> ProgramBenchBatch001LiveManifestLookupCampaign:
    return ProgramBenchBatch001LiveManifestLookupCampaign(
        Batch001LiveManifestLookupConfig(
            write_records=False, live_lookup=live_lookup, client=client
        )
    )


def test_safe_registry_client_fixture_success_with_digest_header() -> None:
    transport = FixtureTransport()
    result = SafeRegistryManifestClient(transport=transport).lookup(
        "programbench/example_1776_tool.1234567:task_cleanroom"
    )

    assert result["status"] == "REGISTRY_MANIFEST_METADATA_FOUND"
    assert result["digest"] == "sha256:" + "a" * 64
    assert result["digest_source"] == "Docker-Content-Digest"
    assert result["metadata_only"] is True
    assert result["cache_ready"] is False
    assert result["executable"] is False
    assert result["training_eligible"] is False
    assert all("/blobs/" not in url for url in transport.urls)


def test_safe_registry_client_fixture_manifest_list_platforms() -> None:
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
        "manifests": [
            {
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "digest": "sha256:" + "b" * 64,
                "platform": {"os": "linux", "architecture": "amd64"},
            }
        ],
    }
    result = SafeRegistryManifestClient(transport=FixtureTransport(manifest=manifest)).lookup(
        "programbench/example_1776_tool.1234567:task_cleanroom"
    )

    assert result["status"] == "REGISTRY_MANIFEST_METADATA_FOUND"
    assert result["media_type"] == "application/vnd.docker.distribution.manifest.list.v2+json"
    assert result["platforms"][0]["architecture"] == "amd64"


def test_safe_registry_client_not_found_and_rate_limited() -> None:
    not_found = SafeRegistryManifestClient(transport=FixtureTransport(manifest_status=404)).lookup(
        "programbench/missing_1776_tool.1234567:task_cleanroom"
    )
    limited = SafeRegistryManifestClient(transport=FixtureTransport(manifest_status=429)).lookup(
        "programbench/limited_1776_tool.1234567:task_cleanroom"
    )

    assert not_found["status"] == "REGISTRY_MANIFEST_METADATA_NOT_FOUND"
    assert limited["status"] == "REGISTRY_MANIFEST_LOOKUP_RATE_LIMITED"
    assert not_found["digest"] == ""


def test_safe_registry_client_blocks_latest_missing_tag_search_and_unadmitted_provider() -> None:
    latest = SafeRegistryManifestClient().lookup("programbench/example_1776_tool.1234567:latest")
    missing_tag = SafeRegistryManifestClient().lookup("programbench/example_1776_tool.1234567")
    broad = SafeRegistryManifestClient().lookup("programbench/*:task_cleanroom")
    unadmitted = SafeRegistryManifestClient(provider="unknown").lookup(
        "programbench/example_1776_tool.1234567:task_cleanroom"
    )

    assert latest["status"] == "REGISTRY_MANIFEST_LOOKUP_BLOCKED_LATEST_TAG"
    assert missing_tag["status"] == "REGISTRY_MANIFEST_LOOKUP_BLOCKED_BROAD_SEARCH"
    assert broad["status"] == "REGISTRY_MANIFEST_LOOKUP_BLOCKED_BROAD_SEARCH"
    assert unadmitted["status"] == "REGISTRY_MANIFEST_LOOKUP_BLOCKED_UNADMITTED_PROVIDER"
    assert is_broad_search_request("programbench/*:task_cleanroom") is True
    assert (
        parse_image_reference("programbench/example_1776_tool.1234567:task_cleanroom")["tag"]
        == "task_cleanroom"
    )


def test_safe_registry_manifest_client_lock_record_is_closed() -> None:
    record = _campaign().safe_registry_manifest_client()

    assert record["status"] == "SAFE_REGISTRY_MANIFEST_CLIENT_WRITTEN"
    assert verify_safe_registry_manifest_record(record)
    assert record["uses_docker_cli"] is False
    assert record["downloads_layers"] is False
    assert record["authorization"]["docker_pull_authorized"] is False
    assert record["authorization"]["executable"] is False


def test_batch001_live_manifest_lookup_with_found_fixture_admits_metadata_only() -> None:
    client = SafeRegistryManifestClient(transport=FixtureTransport())
    records = _campaign(client).run_all()

    lookup = records["lookup"]
    admission = records["admission"]
    state = records["state"]
    import_plan = records["import_plan"]

    assert lookup["status"] == "BATCH001_LIVE_MANIFEST_LOOKUP_COMPLETED"
    assert lookup["summary"]["targets_attempted"] == 10
    assert lookup["summary"]["manifests_found"] == 10
    assert admission["summary"]["digests_admitted_metadata_only"] == 10
    assert all(
        row["cache_ready"] is False and row["executable"] is False
        for row in admission["admissions"]
    )
    assert state["summary"]["artifact_import_and_scan_required"] == 10
    assert import_plan["summary"]["plans_written"] == 10
    assert records["final"]["summary"]["training_rows_written"] is False
    assert verify_live_manifest_metadata_record(records["final"])


def test_batch001_live_manifest_lookup_with_not_found_keeps_operator_metadata_required() -> None:
    client = SafeRegistryManifestClient(transport=FixtureTransport(manifest_status=404))
    records = _campaign(client).run_all()

    assert records["lookup"]["status"] == "BATCH001_LIVE_MANIFEST_LOOKUP_ALL_NOT_FOUND"
    assert records["admission"]["status"] == "BATCH001_METADATA_DIGEST_ADMISSION_NONE"
    assert records["state"]["summary"]["operator_metadata_still_required"] == 10
    assert records["metadata_requests"]["summary"]["packets_written"] == 10
    assert all(
        packet["template_only"] is True for packet in records["metadata_requests"]["packets"]
    )
    assert all(
        packet["authorizes_execution"] is False
        for packet in records["metadata_requests"]["packets"]
    )


def test_batch001_live_manifest_lookup_disabled_blocks_without_network_or_digest() -> None:
    records = _campaign(live_lookup=False).run_all()

    assert records["lookup"]["status"] == "BATCH001_LIVE_MANIFEST_LOOKUP_BLOCKED_NETWORK_DISABLED"
    assert records["lookup"]["summary"]["blocked_network_disabled"] == 10
    assert records["lookup"]["summary"]["manifests_found"] == 0
    assert records["admission"]["summary"]["digests_admitted_metadata_only"] == 0
    assert records["final"]["summary"]["still_need_operator_metadata"] == 10
    assert records["final"]["summary"]["execution_performed"] is False
    assert records["final"]["summary"]["training_rows_written"] is False
