from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from .v10_contracts import V10ContractError
from .v10_supply_chain import stable_sha256


APPROVED_LICENSES = frozenset(
    {"Apache-2.0", "CC0-1.0", "MIT", "OFL-1.1"}
)
EXPECTED_SOURCE_COUNT = 2_000
MAX_PROVIDER_SHARE = 0.40


@dataclass(frozen=True)
class SourceBundleRecord:
    source_id: str
    provider: str
    upstream_asset_id: str
    kind: str
    title: str
    asset_url: str
    evidence_url: str
    license_id: str
    license_url: str
    revision: str
    digest_algorithm: str
    upstream_digest: str
    media_type: str
    attribution: str
    training_allowed: bool
    trademark_hold: bool
    source_observed_at: str

    def __post_init__(self) -> None:
        strings = (
            self.source_id,
            self.provider,
            self.upstream_asset_id,
            self.kind,
            self.title,
            self.license_id,
            self.revision,
            self.digest_algorithm,
            self.upstream_digest,
            self.media_type,
            self.attribution,
            self.source_observed_at,
        )
        if not all(value.strip() for value in strings):
            raise V10ContractError("source-bundle record identity is incomplete")
        for label, locator in (
            ("asset", self.asset_url),
            ("evidence", self.evidence_url),
            ("license", self.license_url),
        ):
            parsed = urlparse(locator)
            if parsed.scheme != "https" or not parsed.hostname:
                raise V10ContractError(f"{label} locator must be public HTTPS")
        if self.training_allowed and self.license_id not in APPROVED_LICENSES:
            raise V10ContractError("training record has no approved license")
        if self.training_allowed and self.trademark_hold:
            raise V10ContractError("trademark-held record cannot enter training")

    @property
    def identity_sha256(self) -> str:
        return stable_sha256(asdict(self))


def validate_source_bundle(
    records: tuple[SourceBundleRecord, ...],
) -> dict[str, object]:
    if len(records) != EXPECTED_SOURCE_COUNT:
        raise V10ContractError(
            f"source bundle must contain exactly {EXPECTED_SOURCE_COUNT} records"
        )
    source_ids = [record.source_id for record in records]
    upstream_ids = [
        f"{record.provider}:{record.upstream_asset_id}" for record in records
    ]
    if len(source_ids) != len(set(source_ids)):
        raise V10ContractError("source bundle IDs are not unique")
    if len(upstream_ids) != len(set(upstream_ids)):
        raise V10ContractError("upstream provider/asset identities are not unique")
    provider_counts = Counter(record.provider for record in records)
    maximum = max(provider_counts.values())
    if maximum / len(records) > MAX_PROVIDER_SHARE:
        raise V10ContractError("one provider exceeds the frozen 40% cap")
    if len(provider_counts) < 5:
        raise V10ContractError("source bundle requires at least five providers")
    kind_counts = Counter(record.kind for record in records)
    required_kinds = {"museum_visual", "hardware", "software", "font", "audio", "video"}
    if not required_kinds <= set(kind_counts):
        raise V10ContractError("source bundle misses required material families")
    training_count = sum(record.training_allowed for record in records)
    if training_count / len(records) < 0.99:
        raise V10ContractError("fewer than 99% of bundle records are training-admitted")
    if any(
        record.training_allowed and record.trademark_hold for record in records
    ):
        raise V10ContractError("a trademark-held record entered training")
    record_hashes = [record.identity_sha256 for record in records]
    return {
        "schema": "ProofLaunchAgencySourceBundleV2",
        "source_count": len(records),
        "provider_counts": dict(sorted(provider_counts.items())),
        "kind_counts": dict(sorted(kind_counts.items())),
        "training_admitted_count": training_count,
        "reference_only_count": len(records) - training_count,
        "unique_source_ids": len(set(source_ids)),
        "unique_upstream_identities": len(set(upstream_ids)),
        "maximum_provider_share": maximum / len(records),
        "source_bundle_2000_complete": True,
        "agency_corpus_v2_frozen": False,
        "raw_asset_bytes_vendored": 0,
        "content_sha256": stable_sha256(record_hashes),
        "truth_boundary": (
            "This proves a 2,000-record rights-and-provenance source bundle. It "
            "does not prove 15M CPT tokens, 15,000 SFT episodes, human gold review, "
            "model training, or Agency Corpus V2 freeze."
        ),
    }
