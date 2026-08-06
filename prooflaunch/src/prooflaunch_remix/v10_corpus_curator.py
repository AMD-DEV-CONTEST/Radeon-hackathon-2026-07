from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable, Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_supply_chain import LicensedSource


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CorpusTaxon(str, Enum):
    PHYSICAL_PRODUCT = "physical_product"
    AI_AGENT = "ai_agent"
    EVIDENCE = "evidence"
    STRATEGY = "strategy"
    CREATIVE = "creative"
    COPY = "copy"
    ART = "art"
    CHANNEL = "channel"
    COMPLIANCE = "compliance"
    AUDIT = "audit"
    REPAIR = "repair"
    TOOL_TRAJECTORY = "tool_trajectory"


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    SCREEN = "screen"
    TRAJECTORY = "trajectory"


class GTMArtifactKind(str, Enum):
    PRODUCT_FACT = "product_fact"
    CAPABILITY_LIMIT = "capability_limit"
    CLAIM_RISK = "claim_risk"
    ICP = "icp"
    JTBD = "jtbd"
    MARKET_TENSION = "market_tension"
    CATEGORY_CONVENTION = "category_convention"
    SMP = "smp"
    RTB = "rtb"
    OFFER = "offer"
    BIG_IDEA = "big_idea"
    KEY_VISUAL_BRIEF = "key_visual_brief"
    COPY_SYSTEM = "copy_system"
    CHANNEL_SYSTEM = "channel_system"
    STORYBOARD = "storyboard"
    AUDIT_FINDING = "audit_finding"
    REPAIR_ACTION = "repair_action"


class ReviewDisposition(str, Enum):
    GOLD_POSITIVE = "gold_positive"
    REMOVE = "remove"
    REPAIR = "repair"
    REPLAY = "replay"


@dataclass(frozen=True)
class CorpusSample:
    sample_id: str
    taxon: CorpusTaxon
    modality: Modality
    source_id: str
    source_revision: str
    source_sha256: str
    product_entity_id: str
    repository_entity_id: str
    captured_at: str
    content: str
    template_id: str
    language: str
    synthetic: bool
    success: bool
    trajectory_steps: int
    concept_tags: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "sample_id",
            "source_id",
            "source_revision",
            "product_entity_id",
            "repository_entity_id",
            "captured_at",
            "content",
            "template_id",
            "language",
        ):
            if not str(getattr(self, field_name)).strip():
                raise V10ContractError(f"{field_name} is required")
        if len(self.source_sha256) != 64:
            raise V10ContractError("source_sha256 must be a SHA-256")
        if self.trajectory_steps < 0:
            raise V10ContractError("trajectory_steps cannot be negative")
        try:
            datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise V10ContractError("captured_at must be ISO-8601") from error


@dataclass(frozen=True)
class GroundedGTMArtifact:
    kind: GTMArtifactKind
    value: str
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    observed: bool
    confidence: float

    def __post_init__(self) -> None:
        if not self.value.strip() or not self.source_ids:
            raise V10ContractError("GTM artifact requires value and sources")
        if not 0.0 <= self.confidence <= 1.0:
            raise V10ContractError("artifact confidence must be in [0,1]")
        if self.observed and not self.evidence_ids:
            raise V10ContractError("observed artifact requires evidence")


@dataclass(frozen=True)
class GTMArtifactBundle:
    bundle_id: str
    artifacts: tuple[GroundedGTMArtifact, ...]

    def __post_init__(self) -> None:
        kinds = [item.kind for item in self.artifacts]
        if set(kinds) != set(GTMArtifactKind) or len(kinds) != len(set(kinds)):
            raise V10ContractError(
                "GTM artifact bundle must contain every kind exactly once"
            )


def build_grounded_gtm_bundle(
    bundle_id: str,
    source_ids: Sequence[str],
    evidence_ids: Sequence[str],
    values: Mapping[GTMArtifactKind, str],
) -> GTMArtifactBundle:
    if set(values) != set(GTMArtifactKind):
        raise V10ContractError("all seventeen GTM artifact values are required")
    return GTMArtifactBundle(
        bundle_id=bundle_id,
        artifacts=tuple(
            GroundedGTMArtifact(
                kind=kind,
                value=values[kind],
                source_ids=tuple(source_ids),
                evidence_ids=tuple(evidence_ids),
                observed=kind
                in {
                    GTMArtifactKind.PRODUCT_FACT,
                    GTMArtifactKind.CAPABILITY_LIMIT,
                    GTMArtifactKind.CLAIM_RISK,
                },
                confidence=1.0
                if kind
                in {
                    GTMArtifactKind.PRODUCT_FACT,
                    GTMArtifactKind.CAPABILITY_LIMIT,
                    GTMArtifactKind.CLAIM_RISK,
                }
                else 0.7,
            )
            for kind in GTMArtifactKind
        ),
    )


def normalize_unicode(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(
        character
        for character in normalized
        if character in "\n\t" or unicodedata.category(character) != "Cc"
    )
    return re.sub(r"[ \t]+", " ", normalized).strip()


def detect_language(text: str) -> str:
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return "und"
    cjk = sum("\u3400" <= character <= "\u9fff" for character in letters)
    latin = sum(
        "LATIN" in unicodedata.name(character, "") for character in letters
    )
    if cjk / len(letters) >= 0.25:
        return "zh"
    if latin / len(letters) >= 0.75:
        return "en"
    return "mul"


def template_fingerprint(text: str) -> str:
    normalized = normalize_unicode(text).lower()
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", normalized)
    normalized = re.sub(r"\b[a-f0-9]{16,}\b", "<id>", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return digest_text(normalized)


def _shingles(text: str, width: int = 3) -> set[str]:
    tokens = re.findall(r"\w+", normalize_unicode(text).lower())
    if len(tokens) < width:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[index : index + width]) for index in range(len(tokens) - width + 1)}


def minhash_signature(text: str, seeds: Sequence[int] = tuple(range(32))) -> tuple[int, ...]:
    shingles = _shingles(text)
    if not shingles:
        return tuple(0 for _ in seeds)
    signature = []
    for seed in seeds:
        signature.append(
            min(
                int.from_bytes(
                    hashlib.sha256(f"{seed}:{shingle}".encode()).digest()[:8],
                    "big",
                )
                for shingle in shingles
            )
        )
    return tuple(signature)


def minhash_similarity(left: Sequence[int], right: Sequence[int]) -> float:
    if len(left) != len(right) or not left:
        raise V10ContractError("MinHash signatures must have equal nonzero length")
    return sum(a == b for a, b in zip(left, right, strict=True)) / len(left)


def clean_image_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
    blocked = {
        "gpslatitude",
        "gpslongitude",
        "gpsinfo",
        "serialnumber",
        "ownername",
        "artist",
        "copyright",
        "usercomment",
    }
    return {
        str(key): str(value)
        for key, value in metadata.items()
        if str(key).replace("_", "").lower() not in blocked
    }


def normalize_color_profile(profile: str) -> str:
    if profile.strip().lower() in {"srgb", "iec61966-2.1"}:
        return "sRGB IEC61966-2.1"
    return "convert-to-sRGB IEC61966-2.1"


def perceptual_hash_distance(left: str, right: str) -> int:
    if len(left) != len(right) or any(char not in "0123456789abcdef" for char in left + right):
        raise V10ContractError("pHash values must be equal-length lowercase hex")
    return (int(left, 16) ^ int(right, 16)).bit_count()


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise V10ContractError("embedding vectors must have equal nonzero length")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise V10ContractError("embedding vectors cannot be zero")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def normalize_video_fps(fps: float, allowed: Sequence[float] = (24.0, 25.0, 30.0)) -> float:
    if not math.isfinite(fps) or fps <= 0:
        raise V10ContractError("video FPS must be positive and finite")
    return min(allowed, key=lambda target: abs(target - fps))


def deduplicate_keyframes(frame_hashes: Sequence[str], threshold: int = 4) -> tuple[str, ...]:
    kept: list[str] = []
    for frame_hash in frame_hashes:
        if not kept or all(
            perceptual_hash_distance(frame_hash, prior) > threshold for prior in kept
        ):
            kept.append(frame_hash)
    return tuple(kept)


def normalize_audio_sample_rate(rate: int) -> int:
    if rate <= 0:
        raise V10ContractError("audio sample rate must be positive")
    return 48_000 if rate >= 44_100 else 16_000


def deduplicate_audio(fingerprints: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(fingerprints))


@dataclass(frozen=True)
class AlignmentScore:
    kind: str
    score: float
    evidence_overlap: tuple[str, ...]
    passed: bool


def alignment_score(
    kind: str,
    left_concepts: Iterable[str],
    right_concepts: Iterable[str],
    *,
    threshold: float = 0.5,
) -> AlignmentScore:
    left = {item.strip().lower() for item in left_concepts if item.strip()}
    right = {item.strip().lower() for item in right_concepts if item.strip()}
    union = left | right
    overlap = left & right
    score = len(overlap) / len(union) if union else 0.0
    return AlignmentScore(
        kind=kind,
        score=score,
        evidence_overlap=tuple(sorted(overlap)),
        passed=score >= threshold,
    )


@dataclass(frozen=True)
class SampleScores:
    sample_id: str
    quality: float
    difficulty: float
    novelty: float
    coverage: float
    information: float


def score_sample(
    sample: CorpusSample,
    *,
    alignment: float,
    evidence_coverage: float,
    verifier_confidence: float,
    rarity: float,
    failure_value: float,
) -> SampleScores:
    for value in (alignment, evidence_coverage, verifier_confidence, rarity, failure_value):
        if not 0.0 <= value <= 1.0:
            raise V10ContractError("sample score inputs must be in [0,1]")
    quality = 0.35 * alignment + 0.35 * evidence_coverage + 0.30 * verifier_confidence
    difficulty = min(1.0, 0.12 * math.log2(sample.trajectory_steps + 1) + 0.55 * failure_value)
    novelty = 0.7 * rarity + 0.3 * (1.0 if sample.template_id == "unique" else 0.0)
    coverage = min(1.0, len(set(sample.concept_tags)) / 8.0 + 0.25 * bool(sample.evidence_ids))
    information = 0.32 * quality + 0.24 * difficulty + 0.24 * novelty + 0.20 * coverage
    return SampleScores(
        sample_id=sample.sample_id,
        quality=round(quality, 6),
        difficulty=round(difficulty, 6),
        novelty=round(novelty, 6),
        coverage=round(coverage, 6),
        information=round(information, 6),
    )


@dataclass(frozen=True)
class BatchScores:
    sample_count: int
    diversity: float
    mean_difficulty: float
    information: float


def score_batch(samples: Sequence[CorpusSample], scores: Mapping[str, SampleScores]) -> BatchScores:
    if not samples:
        raise V10ContractError("batch cannot be empty")
    unique_axes = {
        (sample.taxon.value, sample.modality.value, tag)
        for sample in samples
        for tag in sample.concept_tags
    }
    denominator = sum(max(1, len(sample.concept_tags)) for sample in samples)
    diversity = min(1.0, len(unique_axes) / denominator)
    selected = [scores[sample.sample_id] for sample in samples]
    mean_difficulty = sum(item.difficulty for item in selected) / len(selected)
    information = (
        sum(item.information for item in selected) / len(selected)
    ) * (0.7 + 0.3 * diversity)
    return BatchScores(
        sample_count=len(samples),
        diversity=round(diversity, 6),
        mean_difficulty=round(mean_difficulty, 6),
        information=round(information, 6),
    )


@dataclass(frozen=True)
class CuratedReference:
    reference_id: str
    required_taxa: frozenset[CorpusTaxon]
    required_modalities: frozenset[Modality]
    required_concepts: frozenset[str]
    minimum_quality: float


@dataclass(frozen=True)
class SelectionPolicy:
    maximum_source_rate: float = 0.25
    maximum_template_rate: float = 0.20
    maximum_synthetic_rate: float = 0.30
    minimum_physical_rate: float = 0.25
    minimum_visual_rate: float = 0.25
    minimum_failure_rate: float = 0.20
    minimum_long_trajectory_rate: float = 0.15

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not 0.0 <= value <= 1.0:
                raise V10ContractError(f"{name} must be in [0,1]")


@dataclass(frozen=True)
class SelectionResult:
    samples: tuple[CorpusSample, ...]
    batch_scores: BatchScores
    constraints: Mapping[str, bool]
    content_sha256: str


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def select_super_batch(
    candidates: Sequence[CorpusSample],
    scores: Mapping[str, SampleScores],
    reference: CuratedReference,
    policy: SelectionPolicy,
    *,
    batch_size: int,
) -> SelectionResult:
    if batch_size <= 0 or batch_size > len(candidates):
        raise V10ContractError("invalid super-batch size")
    eligible = [
        sample
        for sample in candidates
        if scores[sample.sample_id].quality >= reference.minimum_quality
    ]
    if len(eligible) < batch_size:
        raise V10ContractError("not enough reference-qualified candidates")
    selected: list[CorpusSample] = []
    source_counts: Counter[str] = Counter()
    template_counts: Counter[str] = Counter()
    source_cap = max(1, math.floor(batch_size * policy.maximum_source_rate))
    template_cap = max(1, math.floor(batch_size * policy.maximum_template_rate))
    synthetic_cap = math.floor(batch_size * policy.maximum_synthetic_rate)
    for sample in sorted(
        eligible,
        key=lambda item: (
            -scores[item.sample_id].information,
            item.sample_id,
        ),
    ):
        if source_counts[sample.source_id] + 1 > source_cap:
            continue
        if template_counts[sample.template_id] + 1 > template_cap:
            continue
        if sample.synthetic and sum(item.synthetic for item in selected) + 1 > synthetic_cap:
            continue
        selected.append(sample)
        source_counts[sample.source_id] += 1
        template_counts[sample.template_id] += 1
        if len(selected) == batch_size:
            break
    if len(selected) != batch_size:
        raise V10ContractError("bounded source/template/synthetic caps prevent requested batch")
    total = len(selected)
    constraints = {
        "source_cap": max(source_counts.values()) / total <= policy.maximum_source_rate,
        "template_cap": max(template_counts.values()) / total <= policy.maximum_template_rate,
        "synthetic_cap": _rate(sum(item.synthetic for item in selected), total) <= policy.maximum_synthetic_rate,
        "physical_software_balance": _rate(sum(item.taxon == CorpusTaxon.PHYSICAL_PRODUCT for item in selected), total) >= policy.minimum_physical_rate,
        "text_visual_balance": _rate(sum(item.modality in {Modality.IMAGE, Modality.VIDEO, Modality.SCREEN} for item in selected), total) >= policy.minimum_visual_rate,
        "image_video_balance": any(item.modality == Modality.IMAGE for item in selected) and any(item.modality == Modality.VIDEO for item in selected),
        "strategy_production_balance": any(item.taxon == CorpusTaxon.STRATEGY for item in selected) and any(item.taxon in {CorpusTaxon.ART, CorpusTaxon.CREATIVE} for item in selected),
        "success_failure_balance": _rate(sum(not item.success for item in selected), total) >= policy.minimum_failure_rate,
        "short_long_trajectory_balance": _rate(sum(item.trajectory_steps >= 8 for item in selected), total) >= policy.minimum_long_trajectory_rate and any(0 < item.trajectory_steps <= 3 for item in selected),
        "reference_taxa": reference.required_taxa.issubset({item.taxon for item in selected}),
        "reference_modalities": reference.required_modalities.issubset({item.modality for item in selected}),
        "reference_concepts": reference.required_concepts.issubset({tag for item in selected for tag in item.concept_tags}),
    }
    if not all(constraints.values()):
        raise V10ContractError(
            "selected super-batch misses balance/reference constraints: "
            + ", ".join(key for key, value in constraints.items() if not value)
        )
    batch_scores = score_batch(selected, scores)
    material = {
        "sample_ids": [item.sample_id for item in selected],
        "scores": asdict(batch_scores),
        "constraints": constraints,
    }
    return SelectionResult(
        samples=tuple(selected),
        batch_scores=batch_scores,
        constraints=constraints,
        content_sha256=digest_text(str(sorted(material.items()))),
    )


def grouped_split(
    samples: Sequence[CorpusSample], field: str
) -> dict[str, tuple[CorpusSample, ...]]:
    if field not in {"product_entity_id", "repository_entity_id"}:
        raise V10ContractError("group split field must be product or repository entity")
    partitions: dict[str, list[CorpusSample]] = {"train": [], "validation": [], "test": []}
    group_assignment: dict[str, str] = {}
    for sample in samples:
        group = str(getattr(sample, field))
        bucket = int(digest_text(group)[:8], 16) % 10
        partition = "train" if bucket < 7 else "validation" if bucket < 9 else "test"
        group_assignment.setdefault(group, partition)
        partitions[group_assignment[group]].append(sample)
    return {key: tuple(value) for key, value in partitions.items()}


def temporal_split(
    samples: Sequence[CorpusSample], validation_start: str, test_start: str
) -> dict[str, tuple[CorpusSample, ...]]:
    validation_time = datetime.fromisoformat(validation_start.replace("Z", "+00:00"))
    test_time = datetime.fromisoformat(test_start.replace("Z", "+00:00"))
    if validation_time >= test_time:
        raise V10ContractError("validation must precede test")
    partitions: dict[str, list[CorpusSample]] = {"train": [], "validation": [], "test": []}
    for sample in samples:
        timestamp = datetime.fromisoformat(sample.captured_at.replace("Z", "+00:00"))
        partition = "train" if timestamp < validation_time else "validation" if timestamp < test_time else "test"
        partitions[partition].append(sample)
    return {key: tuple(value) for key, value in partitions.items()}


@dataclass(frozen=True)
class ContaminationFinding:
    sample_id: str
    reference_id: str
    overlap: float
    kind: str


def scan_contamination(
    samples: Sequence[CorpusSample], benchmark_texts: Mapping[str, str], threshold: float = 0.75
) -> tuple[ContaminationFinding, ...]:
    findings: list[ContaminationFinding] = []
    benchmark_signatures = {
        key: minhash_signature(value) for key, value in benchmark_texts.items()
    }
    for sample in samples:
        signature = minhash_signature(sample.content)
        for reference_id, reference in benchmark_signatures.items():
            overlap = minhash_similarity(signature, reference)
            if overlap >= threshold:
                findings.append(
                    ContaminationFinding(sample.sample_id, reference_id, overlap, "benchmark")
                )
    return tuple(findings)


def scan_prompt_leakage(samples: Sequence[CorpusSample], canary_tokens: Sequence[str]) -> tuple[str, ...]:
    leaked = []
    for sample in samples:
        lowered = sample.content.lower()
        if any(token.lower() in lowered for token in canary_tokens):
            leaked.append(sample.sample_id)
    return tuple(leaked)


def deterministic_audit_sample(samples: Sequence[CorpusSample], count: int, seed: str) -> tuple[CorpusSample, ...]:
    if count < 1 or count > len(samples):
        raise V10ContractError("audit count exceeds corpus")
    return tuple(
        sorted(samples, key=lambda item: digest_text(f"{seed}:{item.sample_id}"))[:count]
    )


def krippendorff_alpha_ordinal(ratings: Sequence[Sequence[int]]) -> float:
    pairs: list[tuple[int, int]] = []
    values: list[int] = []
    for unit in ratings:
        clean = [int(value) for value in unit]
        values.extend(clean)
        pairs.extend((clean[i], clean[j]) for i in range(len(clean)) for j in range(i + 1, len(clean)))
    if not pairs or len(values) < 2:
        raise V10ContractError("alpha requires multiple units and raters")
    observed = sum((a - b) ** 2 for a, b in pairs) / len(pairs)
    expected_pairs = [(values[i], values[j]) for i in range(len(values)) for j in range(i + 1, len(values))]
    expected = sum((a - b) ** 2 for a, b in expected_pairs) / len(expected_pairs)
    return 1.0 if expected == 0 else 1.0 - observed / expected


def review_disposition(mean_score: float, difficulty: float) -> ReviewDisposition:
    if not 0.0 <= difficulty <= 1.0 or not 1.0 <= mean_score <= 5.0:
        raise V10ContractError("review values out of bounds")
    if mean_score >= 4.7:
        return ReviewDisposition.GOLD_POSITIVE
    if mean_score < 3.0:
        return ReviewDisposition.REMOVE
    if difficulty >= 0.75:
        return ReviewDisposition.REPLAY
    return ReviewDisposition.REPAIR


def corpus_distribution(samples: Sequence[CorpusSample]) -> dict[str, Mapping[str, int]]:
    return {
        "taxon": dict(sorted(Counter(item.taxon.value for item in samples).items())),
        "modality": dict(sorted(Counter(item.modality.value for item in samples).items())),
        "source": dict(sorted(Counter(item.source_id for item in samples).items())),
        "concept": dict(sorted(Counter(tag for item in samples for tag in item.concept_tags).items())),
    }


def concept_long_tail(samples: Sequence[CorpusSample]) -> tuple[tuple[str, int], ...]:
    counts = Counter(tag for item in samples for tag in item.concept_tags)
    return tuple(sorted(counts.items(), key=lambda item: (item[1], item[0])))


def bind_sources_to_samples(
    samples: Iterable[CorpusSample], sources: Iterable[LicensedSource]
) -> tuple[str, ...]:
    source_map = {source.source_id: source for source in sources}
    failures = []
    for sample in samples:
        source = source_map.get(sample.source_id)
        if source is None:
            failures.append(f"{sample.sample_id}: missing LicensedSource")
        elif sample.source_revision != source.revision or sample.source_sha256 != source.sha256:
            failures.append(f"{sample.sample_id}: source revision/hash mismatch")
    return tuple(failures)
