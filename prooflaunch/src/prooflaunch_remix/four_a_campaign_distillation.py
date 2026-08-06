from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence
from urllib.parse import urlparse


class CorpusPartition(str, Enum):
    RESEARCH_REFERENCE = "research_reference"
    SEALED_EVALUATION = "sealed_evaluation"
    TRAINING_CANDIDATE = "training_candidate"


class AssertionKind(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    HYPOTHESIS = "hypothesis"


REQUIRED_DISTILLATION_LAYERS = (
    "business_problem",
    "audience_job",
    "evidence_and_tension",
    "strategy_choice",
    "big_idea_mechanism",
    "brand_role",
    "channel_system",
    "experience_or_tool_mechanism",
    "craft_grammar",
    "production_constraints",
    "measurement_design",
    "reported_outcomes",
    "failure_modes",
    "counterfactuals",
    "transferable_principles",
    "non_transferable_specifics",
)


@dataclass(frozen=True)
class AgencyReference:
    agency_id: str
    display_name: str
    city: str
    country: str
    rank: int
    points: float
    ranking_source_id: str

    def audit(self) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.agency_id or not self.display_name:
            failures.append("agency identity is incomplete")
        if self.rank < 1:
            failures.append(f"{self.agency_id}: rank must be positive")
        if not math.isfinite(self.points) or self.points <= 0:
            failures.append(f"{self.agency_id}: points must be positive")
        if not self.ranking_source_id:
            failures.append(f"{self.agency_id}: ranking source is missing")
        return tuple(failures)


@dataclass(frozen=True)
class CampaignSource:
    source_id: str
    url: str
    publisher: str
    retrieved_at: str
    locator: str
    snapshot_sha256: str
    snapshot_kind: str
    raw_asset_stored: bool = False

    def audit(self) -> tuple[str, ...]:
        failures: list[str] = []
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.netloc:
            failures.append(f"{self.source_id}: source URL must be HTTPS")
        if len(self.snapshot_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.snapshot_sha256
        ):
            failures.append(f"{self.source_id}: invalid snapshot digest")
        if self.snapshot_kind not in {
            "metadata_transcription",
            "licensed_local_snapshot",
            "owned_primary_record",
        }:
            failures.append(f"{self.source_id}: invalid snapshot kind")
        if not self.locator.strip() or not self.publisher.strip():
            failures.append(f"{self.source_id}: publisher/locator missing")
        if self.raw_asset_stored and self.snapshot_kind == "metadata_transcription":
            failures.append(
                f"{self.source_id}: metadata transcription cannot contain raw assets"
            )
        return tuple(failures)


@dataclass(frozen=True)
class LayerAssertion:
    text: str
    kind: AssertionKind
    source_ids: tuple[str, ...]
    confidence: float

    def audit(self, known_sources: set[str]) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.text.strip():
            failures.append("empty layer assertion")
        if not 0.0 <= self.confidence <= 1.0:
            failures.append("layer assertion confidence outside [0,1]")
        if self.kind == AssertionKind.OBSERVED and not self.source_ids:
            failures.append("observed assertion has no source")
        unknown = set(self.source_ids) - known_sources
        if unknown:
            failures.append(
                "layer assertion cites unknown sources: " + ", ".join(sorted(unknown))
            )
        return tuple(failures)


@dataclass(frozen=True)
class CampaignDistillationCase:
    case_id: str
    agency_id: str
    title: str
    brand: str
    year: int
    annual_id: str
    channels: tuple[str, ...]
    partition: CorpusPartition
    source_ids: tuple[str, ...]
    layers: Mapping[str, LayerAssertion]
    contains_raw_campaign_asset: bool = False
    sealed_eval_overlap: bool = False

    @property
    def identity_sha256(self) -> str:
        identity = (
            f"{self.agency_id}\x1f{self.title.casefold()}\x1f"
            f"{self.brand.casefold()}\x1f{self.year}"
        ).encode("utf-8")
        return hashlib.sha256(identity).hexdigest()

    def audit(
        self,
        known_agencies: set[str],
        sources: Mapping[str, CampaignSource],
    ) -> tuple[str, ...]:
        failures: list[str] = []
        if self.agency_id not in known_agencies:
            failures.append(f"{self.case_id}: unknown agency")
        if not self.case_id or not self.title or not self.brand:
            failures.append(f"{self.case_id}: incomplete case identity")
        if self.year < 1990 or self.year > 2100:
            failures.append(f"{self.case_id}: implausible year")
        if len(set(self.source_ids)) < 2:
            failures.append(f"{self.case_id}: fewer than two source locators")
        missing_sources = set(self.source_ids) - set(sources)
        if missing_sources:
            failures.append(
                f"{self.case_id}: unknown case sources "
                + ", ".join(sorted(missing_sources))
            )
        if self.contains_raw_campaign_asset:
            failures.append(f"{self.case_id}: raw campaign asset embedded")
        if self.partition == CorpusPartition.TRAINING_CANDIDATE:
            if self.sealed_eval_overlap:
                failures.append(f"{self.case_id}: sealed evaluation contamination")
            if any(
                sources[source_id].snapshot_kind == "metadata_transcription"
                for source_id in self.source_ids
                if source_id in sources
            ):
                failures.append(
                    f"{self.case_id}: public metadata cannot authorize training"
                )

        if self.layers:
            missing_layers = set(REQUIRED_DISTILLATION_LAYERS) - set(self.layers)
            extra_layers = set(self.layers) - set(REQUIRED_DISTILLATION_LAYERS)
            if missing_layers:
                failures.append(
                    f"{self.case_id}: missing layers "
                    + ", ".join(sorted(missing_layers))
                )
            if extra_layers:
                failures.append(
                    f"{self.case_id}: unknown layers "
                    + ", ".join(sorted(extra_layers))
                )
            for layer_name, assertion in self.layers.items():
                for failure in assertion.audit(set(sources)):
                    failures.append(f"{self.case_id}/{layer_name}: {failure}")
        return tuple(failures)


@dataclass(frozen=True)
class FourACampaignDistillationContract:
    required_agencies: int = 10
    minimum_cases_per_agency: int = 30
    minimum_total_cases: int = 300
    minimum_channels_per_agency: int = 5
    minimum_source_locators_per_case: int = 2
    minimum_fully_distilled_rate: float = 1.0
    minimum_observed_layer_source_coverage: float = 1.0
    maximum_identity_duplicate_count: int = 0
    maximum_sealed_eval_overlap_count: int = 0
    schema: str = "ProofLaunchFourACampaignDistillationContractV1"

    def to_dict(self) -> dict:
        return asdict(self)

    def evaluate(
        self,
        agencies: Sequence[AgencyReference],
        sources: Sequence[CampaignSource],
        cases: Sequence[CampaignDistillationCase],
    ) -> "FourACampaignDistillationAudit":
        failures: list[str] = []
        agency_map = {agency.agency_id: agency for agency in agencies}
        source_map = {source.source_id: source for source in sources}
        if len(agency_map) != len(agencies):
            failures.append("duplicate agency IDs")
        if len(source_map) != len(sources):
            failures.append("duplicate source IDs")
        for agency in agencies:
            failures.extend(agency.audit())
            if agency.ranking_source_id not in source_map:
                failures.append(f"{agency.agency_id}: ranking source unavailable")
        for source in sources:
            failures.extend(source.audit())
        for case in cases:
            failures.extend(case.audit(set(agency_map), source_map))

        if len(agency_map) != self.required_agencies:
            failures.append(
                f"agency cohort {len(agency_map)} != {self.required_agencies}"
            )
        if len(cases) < self.minimum_total_cases:
            failures.append(
                f"campaign case count {len(cases)} < {self.minimum_total_cases}"
            )

        case_counts = {agency_id: 0 for agency_id in agency_map}
        channel_sets = {agency_id: set() for agency_id in agency_map}
        for case in cases:
            if case.agency_id in case_counts:
                case_counts[case.agency_id] += 1
                channel_sets[case.agency_id].update(case.channels)
        for agency_id in agency_map:
            if case_counts[agency_id] < self.minimum_cases_per_agency:
                failures.append(
                    f"{agency_id}: {case_counts[agency_id]} cases "
                    f"< {self.minimum_cases_per_agency}"
                )
            if len(channel_sets[agency_id]) < self.minimum_channels_per_agency:
                failures.append(
                    f"{agency_id}: {len(channel_sets[agency_id])} channels "
                    f"< {self.minimum_channels_per_agency}"
                )

        identities = [case.identity_sha256 for case in cases]
        duplicate_count = len(identities) - len(set(identities))
        if duplicate_count > self.maximum_identity_duplicate_count:
            failures.append(f"identity duplicate count {duplicate_count} > 0")
        overlap_count = sum(case.sealed_eval_overlap for case in cases)
        if overlap_count > self.maximum_sealed_eval_overlap_count:
            failures.append(f"sealed evaluation overlap count {overlap_count} > 0")

        fully_distilled = sum(
            set(case.layers) == set(REQUIRED_DISTILLATION_LAYERS)
            for case in cases
        )
        fully_distilled_rate = fully_distilled / len(cases) if cases else 0.0
        if fully_distilled_rate < self.minimum_fully_distilled_rate:
            failures.append(
                f"fully distilled rate {fully_distilled_rate:.6f} < "
                f"{self.minimum_fully_distilled_rate:.6f}"
            )

        observed = [
            assertion
            for case in cases
            for assertion in case.layers.values()
            if assertion.kind == AssertionKind.OBSERVED
        ]
        sourced_observed = sum(bool(item.source_ids) for item in observed)
        source_coverage = sourced_observed / len(observed) if observed else 0.0
        if source_coverage < self.minimum_observed_layer_source_coverage:
            failures.append(
                f"observed layer source coverage {source_coverage:.6f} < 1.0"
            )

        research_ready = (
            bool(cases)
            and duplicate_count == 0
            and overlap_count == 0
            and not any(case.contains_raw_campaign_asset for case in cases)
        )
        training_candidate_count = sum(
            case.partition == CorpusPartition.TRAINING_CANDIDATE for case in cases
        )
        return FourACampaignDistillationAudit(
            passed=not failures,
            failures=tuple(dict.fromkeys(failures)),
            agency_count=len(agency_map),
            case_count=len(cases),
            fully_distilled_count=fully_distilled,
            agency_case_counts=case_counts,
            agency_channel_counts={
                agency_id: len(channels)
                for agency_id, channels in channel_sets.items()
            },
            fully_distilled_rate=fully_distilled_rate,
            observed_layer_source_coverage=source_coverage,
            identity_duplicate_count=duplicate_count,
            sealed_eval_overlap_count=overlap_count,
            research_reference_ready=research_ready,
            training_candidate_count=training_candidate_count,
        )


@dataclass(frozen=True)
class FourACampaignDistillationAudit:
    passed: bool
    failures: tuple[str, ...]
    agency_count: int
    case_count: int
    fully_distilled_count: int
    agency_case_counts: Mapping[str, int]
    agency_channel_counts: Mapping[str, int]
    fully_distilled_rate: float
    observed_layer_source_coverage: float
    identity_duplicate_count: int
    sealed_eval_overlap_count: int
    research_reference_ready: bool
    training_candidate_count: int
    schema: str = "ProofLaunchFourACampaignDistillationAuditV1"
