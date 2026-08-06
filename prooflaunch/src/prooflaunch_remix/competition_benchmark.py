from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from PIL import Image


MANIFEST_SCHEMA = "ProofLaunchCompetition2XManifestV1"
CASE_RESULT_SCHEMA = "ProofLaunchCompetition2XCaseResultV2"
BASELINE_RESULT_SCHEMA = "ProofLaunchCompetition2XBaselineResultV2"
CASE_GATE_EVIDENCE_SCHEMA = "ProofLaunchCompetition2XCaseGateEvidenceV1"
COMPILED_EVIDENCE_SCHEMA = "ProofLaunchCompetition2XCompiledEvidenceV2"
REQUIRED_RATIOS = ("1:1", "4:5", "9:16")
DEFAULT_SEEDS = (202607, 202608, 202609, 202610, 202611)
ALLOWED_RIGHTS = {"owned", "licensed"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RATER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")


class CompetitionBenchmarkError(RuntimeError):
    pass


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise CompetitionBenchmarkError(f"{field} must be a JSON boolean")
    return value


def _require_int(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CompetitionBenchmarkError(
            f"{field} must be an integer greater than or equal to {minimum}"
        )
    return value


def _require_number(value: object, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompetitionBenchmarkError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise CompetitionBenchmarkError(
            f"{field} must be finite and greater than or equal to {minimum}"
        )
    return number


def _require_sha256(value: object, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise CompetitionBenchmarkError(f"{field} must be a lowercase SHA-256")
    return value


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompetitionBenchmarkError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise CompetitionBenchmarkError(f"{path} must contain one JSON object")
    return value


def _read_jsonl(path: Path) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise CompetitionBenchmarkError(f"cannot read JSONL {path}: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise CompetitionBenchmarkError(
                f"{path}:{line_number} is not valid JSON: {error}"
            ) from error
        if not isinstance(value, dict):
            raise CompetitionBenchmarkError(
                f"{path}:{line_number} must contain one JSON object"
            )
        rows.append(value)
    return tuple(rows)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CompetitionBenchmarkError(f"cannot hash artifact {path}: {error}") from error
    return digest.hexdigest()


def _bound_artifact(
    root: Path,
    locator: object,
    expected_sha256: object,
    field: str,
) -> Path:
    expected = _require_sha256(expected_sha256, f"{field}_sha256")
    if not isinstance(locator, str) or not locator.strip():
        raise CompetitionBenchmarkError(f"{field}_locator must be non-empty")
    relative = Path(locator)
    if relative.is_absolute() or ".." in relative.parts:
        raise CompetitionBenchmarkError(
            f"{field}_locator must be a traversal-free relative path"
        )
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise CompetitionBenchmarkError(f"{field}_locator escapes the evidence root")
    if not resolved.is_file():
        raise CompetitionBenchmarkError(f"{field} artifact does not exist: {locator}")
    actual = _file_sha256(resolved)
    if actual != expected:
        raise CompetitionBenchmarkError(
            f"{field} artifact hash mismatch: expected {expected}, got {actual}"
        )
    return resolved


def image_dhash64(path: Path) -> str:
    try:
        with Image.open(path) as image:
            grayscale = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = list(
                grayscale.get_flattened_data()
                if hasattr(grayscale, "get_flattened_data")
                else grayscale.getdata()
            )
    except (OSError, ValueError) as error:
        raise CompetitionBenchmarkError(
            f"cannot compute perceptual hash for {path}: {error}"
        ) from error
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | (
                1 if pixels[offset + column] > pixels[offset + column + 1] else 0
            )
    return f"{value:016x}"


@dataclass(frozen=True)
class ProductSpec:
    product_id: str
    input_sha256: str
    rights: str
    source_locator: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ProductSpec":
        product_id = value.get("product_id")
        if not isinstance(product_id, str) or not product_id.strip():
            raise CompetitionBenchmarkError("product_id must be a non-empty string")
        input_sha256 = _require_sha256(value.get("input_sha256"), "input_sha256")
        rights = value.get("rights")
        if rights not in ALLOWED_RIGHTS:
            raise CompetitionBenchmarkError(
                f"{product_id}: rights must be owned or licensed"
            )
        source_locator = value.get("source_locator")
        if not isinstance(source_locator, str) or not source_locator.strip():
            raise CompetitionBenchmarkError(
                f"{product_id}: source_locator must be non-empty"
            )
        return cls(
            product_id=product_id.strip(),
            input_sha256=str(input_sha256),
            rights=str(rights),
            source_locator=source_locator.strip(),
        )


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    product_id: str
    aspect_ratio: str
    seed: int
    video_required: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "BenchmarkCase":
        case_id = value.get("case_id")
        product_id = value.get("product_id")
        aspect_ratio = value.get("aspect_ratio")
        if not isinstance(case_id, str) or not case_id:
            raise CompetitionBenchmarkError("case_id must be a non-empty string")
        if not isinstance(product_id, str) or not product_id:
            raise CompetitionBenchmarkError(
                f"{case_id}: product_id must be a non-empty string"
            )
        if aspect_ratio not in REQUIRED_RATIOS:
            raise CompetitionBenchmarkError(
                f"{case_id}: aspect_ratio must be one of {REQUIRED_RATIOS}"
            )
        return cls(
            case_id=case_id,
            product_id=product_id,
            aspect_ratio=str(aspect_ratio),
            seed=_require_int(value.get("seed"), f"{case_id}.seed"),
            video_required=_require_bool(
                value.get("video_required"), f"{case_id}.video_required"
            ),
        )


@dataclass(frozen=True)
class DeclaredBaseline:
    name: str
    version: str
    settings_sha256: str
    source_locator: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "DeclaredBaseline":
        name = value.get("name")
        version = value.get("version")
        source_locator = value.get("source_locator")
        for field, field_value in (
            ("baseline.name", name),
            ("baseline.version", version),
            ("baseline.source_locator", source_locator),
        ):
            if not isinstance(field_value, str) or not field_value.strip():
                raise CompetitionBenchmarkError(f"{field} must be non-empty")
        return cls(
            name=str(name).strip(),
            version=str(version).strip(),
            settings_sha256=str(
                _require_sha256(
                    value.get("settings_sha256"), "baseline.settings_sha256"
                )
            ),
            source_locator=str(source_locator).strip(),
        )


@dataclass(frozen=True)
class FrozenBenchmarkManifest:
    benchmark_id: str
    protocol_sha256: str
    prooflaunch_build_sha256: str
    baseline: DeclaredBaseline
    products: tuple[ProductSpec, ...]
    aspect_ratios: tuple[str, ...]
    seeds: tuple[int, ...]
    cases: tuple[BenchmarkCase, ...]
    manifest_hash: str
    schema: str = MANIFEST_SCHEMA

    def unsigned_dict(self) -> dict:
        return {
            "schema": self.schema,
            "benchmark_id": self.benchmark_id,
            "protocol_sha256": self.protocol_sha256,
            "prooflaunch_build_sha256": self.prooflaunch_build_sha256,
            "baseline": asdict(self.baseline),
            "products": [asdict(item) for item in self.products],
            "aspect_ratios": list(self.aspect_ratios),
            "seeds": list(self.seeds),
            "cases": [asdict(item) for item in self.cases],
        }

    def to_dict(self) -> dict:
        return {**self.unsigned_dict(), "manifest_hash": self.manifest_hash}


def _case_id(benchmark_id: str, product_id: str, ratio: str, seed: int) -> str:
    digest = hashlib.sha256(
        "\0".join((benchmark_id, product_id, ratio, str(seed))).encode("utf-8")
    ).hexdigest()
    return f"PLX-{digest[:24]}"


def build_frozen_manifest(
    *,
    benchmark_id: str,
    protocol_sha256: str,
    prooflaunch_build_sha256: str,
    baseline: DeclaredBaseline,
    products: Sequence[ProductSpec],
    seeds: Sequence[int] = DEFAULT_SEEDS,
) -> FrozenBenchmarkManifest:
    if not isinstance(benchmark_id, str) or not benchmark_id.strip():
        raise CompetitionBenchmarkError("benchmark_id must be a non-empty string")
    protocol_hash = _require_sha256(protocol_sha256, "protocol_sha256")
    build_hash = _require_sha256(
        prooflaunch_build_sha256, "prooflaunch_build_sha256"
    )
    if not isinstance(baseline, DeclaredBaseline):
        raise CompetitionBenchmarkError("baseline must be a DeclaredBaseline")
    if len(products) != 30:
        raise CompetitionBenchmarkError("the frozen benchmark requires exactly 30 products")
    product_ids = [item.product_id for item in products]
    if len(set(product_ids)) != len(product_ids):
        raise CompetitionBenchmarkError("product_id values must be unique")
    input_hashes = [item.input_sha256 for item in products]
    if len(set(input_hashes)) != len(input_hashes):
        raise CompetitionBenchmarkError("each benchmark product needs a unique input hash")
    seed_values = tuple(seeds)
    if len(seed_values) != 5 or len(set(seed_values)) != 5:
        raise CompetitionBenchmarkError("the frozen benchmark requires exactly five seeds")
    if any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seed_values):
        raise CompetitionBenchmarkError("seeds must be unique non-negative integers")

    sorted_products = tuple(sorted(products, key=lambda item: item.product_id))
    cases = tuple(
        BenchmarkCase(
            case_id=_case_id(benchmark_id.strip(), product.product_id, ratio, seed),
            product_id=product.product_id,
            aspect_ratio=ratio,
            seed=seed,
            video_required=ratio == "9:16" and seed == seed_values[0],
        )
        for product in sorted_products
        for ratio in REQUIRED_RATIOS
        for seed in seed_values
    )
    unsigned = {
        "schema": MANIFEST_SCHEMA,
        "benchmark_id": benchmark_id.strip(),
        "protocol_sha256": protocol_hash,
        "prooflaunch_build_sha256": build_hash,
        "baseline": asdict(baseline),
        "products": [asdict(item) for item in sorted_products],
        "aspect_ratios": list(REQUIRED_RATIOS),
        "seeds": list(seed_values),
        "cases": [asdict(item) for item in cases],
    }
    return FrozenBenchmarkManifest(
        benchmark_id=benchmark_id.strip(),
        protocol_sha256=str(protocol_hash),
        prooflaunch_build_sha256=str(build_hash),
        baseline=baseline,
        products=sorted_products,
        aspect_ratios=REQUIRED_RATIOS,
        seeds=seed_values,
        cases=cases,
        manifest_hash=_sha256(unsigned),
    )


def load_frozen_manifest(path: Path) -> FrozenBenchmarkManifest:
    payload = _read_json(path)
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise CompetitionBenchmarkError(f"{path}: unsupported manifest schema")
    benchmark_id = payload.get("benchmark_id")
    protocol_sha256 = payload.get("protocol_sha256")
    prooflaunch_build_sha256 = payload.get("prooflaunch_build_sha256")
    baseline_value = payload.get("baseline")
    products_value = payload.get("products")
    ratios_value = payload.get("aspect_ratios")
    seeds_value = payload.get("seeds")
    cases_value = payload.get("cases")
    if not isinstance(benchmark_id, str):
        raise CompetitionBenchmarkError("benchmark_id must be a string")
    if not isinstance(baseline_value, dict):
        raise CompetitionBenchmarkError("baseline must be an object")
    if not isinstance(products_value, list):
        raise CompetitionBenchmarkError("products must be a list")
    if not isinstance(ratios_value, list) or tuple(ratios_value) != REQUIRED_RATIOS:
        raise CompetitionBenchmarkError(
            f"aspect_ratios must be exactly {REQUIRED_RATIOS}"
        )
    if not isinstance(seeds_value, list):
        raise CompetitionBenchmarkError("seeds must be a list")
    if not isinstance(cases_value, list):
        raise CompetitionBenchmarkError("cases must be a list")
    products = tuple(ProductSpec.from_mapping(item) for item in products_value)
    generated = build_frozen_manifest(
        benchmark_id=benchmark_id,
        protocol_sha256=str(
            _require_sha256(protocol_sha256, "protocol_sha256")
        ),
        prooflaunch_build_sha256=str(
            _require_sha256(
                prooflaunch_build_sha256, "prooflaunch_build_sha256"
            )
        ),
        baseline=DeclaredBaseline.from_mapping(baseline_value),
        products=products,
        seeds=tuple(
            _require_int(seed, "seed")
            for seed in seeds_value
        ),
    )
    supplied_cases = tuple(BenchmarkCase.from_mapping(item) for item in cases_value)
    if supplied_cases != generated.cases:
        raise CompetitionBenchmarkError(
            "manifest cases do not match the deterministic 30×3×5 matrix"
        )
    supplied_hash = payload.get("manifest_hash")
    if supplied_hash != generated.manifest_hash:
        raise CompetitionBenchmarkError("manifest_hash does not match manifest contents")
    return generated


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    completed: bool
    crashed: bool
    repairs: int
    unsupported_claim_count: int
    observation_count: int
    located_observation_count: int
    image_identity_pass: bool
    preencode_video_identity_pass: bool | None
    encoded_video_identity_pass: bool | None
    audio_video_alignment_pass: bool | None
    cross_media_pass: bool
    latency_seconds: float
    peak_vram_gb: float
    output_sha256: str | None
    output_locator: str | None
    video_output_sha256: str | None
    video_output_locator: str | None
    gate_evidence_sha256: str
    gate_evidence_locator: str
    perceptual_hash: str | None
    raw: Mapping[str, object]


@dataclass(frozen=True)
class BaselineResult:
    case_id: str
    completed: bool
    crashed: bool
    output_sha256: str | None
    output_locator: str | None
    raw: Mapping[str, object]


def _optional_gate(value: object, field: str, *, required: bool) -> bool | None:
    if required:
        return _require_bool(value, field)
    if value is not None:
        raise CompetitionBenchmarkError(f"{field} must be null for a still-only case")
    return None


def _load_case_results(
    path: Path,
    manifest: FrozenBenchmarkManifest,
) -> tuple[CaseResult, ...]:
    case_by_id = {case.case_id: case for case in manifest.cases}
    evidence_root = path.parent
    rows = _read_jsonl(path)
    parsed: dict[str, CaseResult] = {}
    for index, row in enumerate(rows, start=1):
        label = f"{path}:{index}"
        if row.get("schema") != CASE_RESULT_SCHEMA:
            raise CompetitionBenchmarkError(f"{label}: unsupported case-result schema")
        if row.get("manifest_hash") != manifest.manifest_hash:
            raise CompetitionBenchmarkError(f"{label}: manifest_hash mismatch")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id not in case_by_id:
            raise CompetitionBenchmarkError(f"{label}: unknown case_id")
        if case_id in parsed:
            raise CompetitionBenchmarkError(f"{label}: duplicate case_id {case_id}")
        case = case_by_id[case_id]
        gate_evidence_sha256 = str(
            _require_sha256(
                row.get("gate_evidence_sha256"),
                f"{case_id}.gate_evidence_sha256",
            )
        )
        gate_evidence_locator = row.get("gate_evidence_locator")
        gate_path = _bound_artifact(
            evidence_root,
            gate_evidence_locator,
            gate_evidence_sha256,
            f"{case_id}.gate_evidence",
        )
        gate = _read_json(gate_path)
        if gate.get("schema") != CASE_GATE_EVIDENCE_SCHEMA:
            raise CompetitionBenchmarkError(
                f"{case_id}: unsupported gate-evidence schema"
            )
        if gate.get("manifest_hash") != manifest.manifest_hash:
            raise CompetitionBenchmarkError(
                f"{case_id}: gate-evidence manifest_hash mismatch"
            )
        if gate.get("case_id") != case_id:
            raise CompetitionBenchmarkError(
                f"{case_id}: gate-evidence case_id mismatch"
            )
        completed = _require_bool(gate.get("completed"), f"{case_id}.completed")
        crashed = _require_bool(gate.get("crashed"), f"{case_id}.crashed")
        if completed and crashed:
            raise CompetitionBenchmarkError(
                f"{case_id}: completed and crashed cannot both be true"
            )
        output_sha256 = _require_sha256(
            row.get("output_sha256"),
            f"{case_id}.output_sha256",
            optional=not completed,
        )
        if not completed and row.get("output_sha256") is not None:
            raise CompetitionBenchmarkError(
                f"{case_id}.output_sha256 must be null when incomplete"
            )
        output_locator = row.get("output_locator")
        if completed:
            output_path = _bound_artifact(
                evidence_root,
                output_locator,
                output_sha256,
                f"{case_id}.output",
            )
            perceptual_hash = image_dhash64(output_path)
        else:
            if output_locator is not None:
                raise CompetitionBenchmarkError(
                    f"{case_id}.output_locator must be null when incomplete"
                )
            perceptual_hash = None
        if gate.get("output_sha256") != output_sha256:
            raise CompetitionBenchmarkError(
                f"{case_id}: gate evidence is not bound to the still output"
            )

        video_output_sha256 = _require_sha256(
            row.get("video_output_sha256"),
            f"{case_id}.video_output_sha256",
            optional=not (case.video_required and completed),
        )
        video_output_locator = row.get("video_output_locator")
        if case.video_required and completed:
            _bound_artifact(
                evidence_root,
                video_output_locator,
                video_output_sha256,
                f"{case_id}.video_output",
            )
        elif (
            row.get("video_output_sha256") is not None
            or video_output_locator is not None
        ):
            raise CompetitionBenchmarkError(
                f"{case_id}: video output fields must be null unless a required "
                "video case completed"
            )
        if gate.get("video_output_sha256") != video_output_sha256:
            raise CompetitionBenchmarkError(
                f"{case_id}: gate evidence is not bound to the video output"
            )

        observation_count = _require_int(
            gate.get("observation_count"), f"{case_id}.observation_count"
        )
        located_count = _require_int(
            gate.get("located_observation_count"),
            f"{case_id}.located_observation_count",
        )
        if located_count > observation_count:
            raise CompetitionBenchmarkError(
                f"{case_id}: located observations exceed total observations"
            )
        parsed[case_id] = CaseResult(
            case_id=case_id,
            completed=completed,
            crashed=crashed,
            repairs=_require_int(gate.get("repairs"), f"{case_id}.repairs"),
            unsupported_claim_count=_require_int(
                gate.get("unsupported_claim_count"),
                f"{case_id}.unsupported_claim_count",
            ),
            observation_count=observation_count,
            located_observation_count=located_count,
            image_identity_pass=_require_bool(
                gate.get("image_identity_pass"), f"{case_id}.image_identity_pass"
            ),
            preencode_video_identity_pass=_optional_gate(
                gate.get("preencode_video_identity_pass"),
                f"{case_id}.preencode_video_identity_pass",
                required=case.video_required,
            ),
            encoded_video_identity_pass=_optional_gate(
                gate.get("encoded_video_identity_pass"),
                f"{case_id}.encoded_video_identity_pass",
                required=case.video_required,
            ),
            audio_video_alignment_pass=_optional_gate(
                gate.get("audio_video_alignment_pass"),
                f"{case_id}.audio_video_alignment_pass",
                required=case.video_required,
            ),
            cross_media_pass=_require_bool(
                gate.get("cross_media_pass"), f"{case_id}.cross_media_pass"
            ),
            latency_seconds=_require_number(
                gate.get("latency_seconds"), f"{case_id}.latency_seconds"
            ),
            peak_vram_gb=_require_number(
                gate.get("peak_vram_gb"), f"{case_id}.peak_vram_gb"
            ),
            output_sha256=output_sha256,
            output_locator=(
                str(output_locator) if output_locator is not None else None
            ),
            video_output_sha256=video_output_sha256,
            video_output_locator=(
                str(video_output_locator)
                if video_output_locator is not None
                else None
            ),
            gate_evidence_sha256=gate_evidence_sha256,
            gate_evidence_locator=str(gate_evidence_locator),
            perceptual_hash=perceptual_hash,
            raw=row,
        )
    missing = sorted(set(case_by_id) - set(parsed))
    if missing:
        raise CompetitionBenchmarkError(
            f"{path}: missing {len(missing)} case results; first missing {missing[0]}"
        )
    return tuple(parsed[case.case_id] for case in manifest.cases)


def _load_baseline_results(
    path: Path,
    manifest: FrozenBenchmarkManifest,
) -> tuple[BaselineResult, ...]:
    expected = {case.case_id for case in manifest.cases}
    evidence_root = path.parent
    rows = _read_jsonl(path)
    parsed: dict[str, BaselineResult] = {}
    for index, row in enumerate(rows, start=1):
        label = f"{path}:{index}"
        if row.get("schema") != BASELINE_RESULT_SCHEMA:
            raise CompetitionBenchmarkError(f"{label}: unsupported baseline schema")
        if row.get("manifest_hash") != manifest.manifest_hash:
            raise CompetitionBenchmarkError(f"{label}: manifest_hash mismatch")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id not in expected:
            raise CompetitionBenchmarkError(f"{label}: unknown case_id")
        if case_id in parsed:
            raise CompetitionBenchmarkError(f"{label}: duplicate case_id {case_id}")
        completed = _require_bool(row.get("completed"), f"{case_id}.completed")
        crashed = _require_bool(row.get("crashed"), f"{case_id}.crashed")
        if completed and crashed:
            raise CompetitionBenchmarkError(
                f"{case_id}: completed and crashed cannot both be true"
            )
        output_sha256 = _require_sha256(
            row.get("output_sha256"),
            f"{case_id}.output_sha256",
            optional=not completed,
        )
        if not completed and row.get("output_sha256") is not None:
            raise CompetitionBenchmarkError(
                f"{case_id}.output_sha256 must be null when incomplete"
            )
        output_locator = row.get("output_locator")
        if completed:
            _bound_artifact(
                evidence_root,
                output_locator,
                output_sha256,
                f"{case_id}.baseline_output",
            )
        elif output_locator is not None:
            raise CompetitionBenchmarkError(
                f"{case_id}.output_locator must be null when incomplete"
            )
        parsed[case_id] = BaselineResult(
            case_id=case_id,
            completed=completed,
            crashed=crashed,
            output_sha256=output_sha256,
            output_locator=(
                str(output_locator) if output_locator is not None else None
            ),
            raw=row,
        )
    missing = sorted(expected - set(parsed))
    if missing:
        raise CompetitionBenchmarkError(
            f"{path}: missing {len(missing)} baseline results; first missing {missing[0]}"
        )
    return tuple(parsed[case.case_id] for case in manifest.cases)


def _parse_csv_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise CompetitionBenchmarkError(f"{field} must be true or false")


def _compile_human_comparisons(
    path: Path,
    manifest: FrozenBenchmarkManifest,
    results: Sequence[CaseResult],
    baseline_results: Sequence[BaselineResult],
) -> tuple[int, int, int, str]:
    expected_fields = (
        "comparison_id",
        "rater_id",
        "case_id",
        "candidate_a_sha256",
        "candidate_b_sha256",
        "winner",
        "blinded",
    )
    proof_by_id = {item.case_id: item for item in results}
    baseline_by_id = {item.case_id: item for item in baseline_results}
    case_by_id = {item.case_id: item for item in manifest.cases}
    comparison_ids: set[str] = set()
    rater_case_pairs: set[tuple[str, str]] = set()
    rater_products: dict[str, set[str]] = {}
    preferred = 0
    comparisons = 0
    normalized_rows: list[dict[str, str]] = []
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as error:
        raise CompetitionBenchmarkError(f"cannot read human CSV {path}: {error}") from error
    with handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != expected_fields:
            raise CompetitionBenchmarkError(
                f"{path}: CSV header must be exactly {','.join(expected_fields)}"
            )
        for line_number, row in enumerate(reader, start=2):
            label = f"{path}:{line_number}"
            comparison_id = row["comparison_id"].strip()
            rater_id = row["rater_id"].strip()
            case_id = row["case_id"].strip()
            if not comparison_id or comparison_id in comparison_ids:
                raise CompetitionBenchmarkError(
                    f"{label}: comparison_id must be non-empty and unique"
                )
            if not RATER_RE.fullmatch(rater_id) or "@" in rater_id:
                raise CompetitionBenchmarkError(
                    f"{label}: rater_id must be a pseudonymous identifier"
                )
            if case_id not in case_by_id:
                raise CompetitionBenchmarkError(f"{label}: unknown case_id")
            pair = (rater_id, case_id)
            if pair in rater_case_pairs:
                raise CompetitionBenchmarkError(
                    f"{label}: duplicate rater/case comparison"
                )
            if not _parse_csv_bool(row["blinded"], f"{label}.blinded"):
                raise CompetitionBenchmarkError(
                    f"{label}: every counted comparison must be blinded"
                )
            winner = row["winner"].strip().lower()
            if winner not in {"candidate_a", "candidate_b", "tie", "neither"}:
                raise CompetitionBenchmarkError(f"{label}: invalid winner")
            proof = proof_by_id[case_id]
            baseline = baseline_by_id[case_id]
            if not proof.completed or not baseline.completed:
                raise CompetitionBenchmarkError(
                    f"{label}: both paired outputs must be completed"
                )
            candidate_a = row["candidate_a_sha256"].strip()
            candidate_b = row["candidate_b_sha256"].strip()
            if not SHA256_RE.fullmatch(candidate_a) or not SHA256_RE.fullmatch(
                candidate_b
            ):
                raise CompetitionBenchmarkError(
                    f"{label}: candidate hashes must be lowercase SHA-256 values"
                )
            expected_hashes = {str(proof.output_sha256), str(baseline.output_sha256)}
            if candidate_a == candidate_b or {candidate_a, candidate_b} != expected_hashes:
                raise CompetitionBenchmarkError(
                    f"{label}: candidate hashes do not match the paired case outputs"
                )
            proof_slot = (
                "candidate_a"
                if candidate_a == proof.output_sha256
                else "candidate_b"
            )
            if winner == proof_slot:
                preferred += 1
            comparisons += 1
            comparison_ids.add(comparison_id)
            rater_case_pairs.add(pair)
            rater_products.setdefault(rater_id, set()).add(
                case_by_id[case_id].product_id
            )
            normalized_rows.append(
                {field: row[field].strip() for field in expected_fields}
            )
    all_products = {item.product_id for item in manifest.products}
    for rater_id, products in rater_products.items():
        missing_products = all_products - products
        if missing_products:
            raise CompetitionBenchmarkError(
                f"{rater_id}: blind review is missing {len(missing_products)} products"
            )
    return preferred, comparisons, len(rater_products), _sha256(normalized_rows)


def _normalized_hamming(left: str, right: str) -> float:
    return (int(left, 16) ^ int(right, 16)).bit_count() / 64.0


def _diversity_pass_rate(
    manifest: FrozenBenchmarkManifest,
    results: Sequence[CaseResult],
) -> tuple[float, int]:
    result_by_id = {item.case_id: item for item in results}
    groups: dict[tuple[str, str], list[CaseResult]] = {}
    for case in manifest.cases:
        groups.setdefault((case.product_id, case.aspect_ratio), []).append(
            result_by_id[case.case_id]
        )
    passed_groups = 0
    for group_results in groups.values():
        if len(group_results) != 5:
            raise CompetitionBenchmarkError("diversity group does not contain five seeds")
        if not all(
            item.completed and item.image_identity_pass and item.perceptual_hash
            for item in group_results
        ):
            continue
        distances = [
            _normalized_hamming(str(left.perceptual_hash), str(right.perceptual_hash))
            for index, left in enumerate(group_results)
            for right in group_results[index + 1 :]
        ]
        median_distance = statistics.median(distances)
        if 0.08 <= median_distance <= 0.45:
            passed_groups += 1
    return passed_groups / len(groups), len(groups)


def _ratio(successes: int, trials: int) -> float:
    return successes / trials if trials else 0.0


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def compile_competition_evidence(
    *,
    manifest_path: Path,
    results_path: Path,
    baseline_results_path: Path,
    human_comparisons_path: Path,
) -> dict:
    manifest = load_frozen_manifest(manifest_path)
    results = _load_case_results(results_path, manifest)
    baseline_results = _load_baseline_results(baseline_results_path, manifest)
    preferred, comparisons, raters, human_hash = _compile_human_comparisons(
        human_comparisons_path,
        manifest,
        results,
        baseline_results,
    )
    cases = len(manifest.cases)
    video_case_ids = {
        item.case_id for item in manifest.cases if item.video_required
    }
    video_results = [item for item in results if item.case_id in video_case_ids]
    total_observations = sum(item.observation_count for item in results)
    total_located = sum(item.located_observation_count for item in results)
    completed = sum(item.completed for item in results)
    baseline_completed = sum(item.completed for item in baseline_results)
    diversity_rate, diversity_groups = _diversity_pass_rate(manifest, results)
    sorted_results = [item.raw for item in results]
    sorted_baseline = [item.raw for item in baseline_results]
    return {
        "schema": COMPILED_EVIDENCE_SCHEMA,
        "benchmark_id": manifest.benchmark_id,
        "manifest_hash": manifest.manifest_hash,
        "protocol_sha256": manifest.protocol_sha256,
        "prooflaunch_build_sha256": manifest.prooflaunch_build_sha256,
        "baseline_name": manifest.baseline.name,
        "baseline_version": manifest.baseline.version,
        "baseline_settings_sha256": manifest.baseline.settings_sha256,
        "case_result_set_hash": _sha256(sorted_results),
        "baseline_result_set_hash": _sha256(sorted_baseline),
        "human_comparison_set_hash": human_hash,
        "product_count": len(manifest.products),
        "aspect_ratio_count": len(manifest.aspect_ratios),
        "seeds_per_product": len(manifest.seeds),
        "benchmark_case_count": cases,
        "video_case_count": sum(item.completed for item in video_results),
        "human_raters": raters,
        "repair_budget_max": max(item.repairs for item in results),
        "unsupported_claim_count": sum(
            item.unsupported_claim_count for item in results
        ),
        "locator_coverage": _ratio(total_located, total_observations),
        "image_identity_pass_rate": _ratio(
            sum(item.completed and item.image_identity_pass for item in results),
            cases,
        ),
        "preencode_video_identity_pass_rate": _ratio(
            sum(
                item.completed and item.preencode_video_identity_pass is True
                for item in video_results
            ),
            len(video_results),
        ),
        "encoded_video_identity_pass_rate": _ratio(
            sum(
                item.completed and item.encoded_video_identity_pass is True
                for item in video_results
            ),
            len(video_results),
        ),
        "audio_video_alignment_pass_rate": _ratio(
            sum(
                item.completed and item.audio_video_alignment_pass is True
                for item in video_results
            ),
            len(video_results),
        ),
        "cross_media_pass_rate": _ratio(
            sum(item.completed and item.cross_media_pass for item in results),
            cases,
        ),
        "completion_rate": _ratio(completed, cases),
        "crash_rate": _ratio(sum(item.crashed for item in results), cases),
        "latency_seconds_p50": _percentile(
            [item.latency_seconds for item in results], 0.50
        ),
        "latency_seconds_p95": _percentile(
            [item.latency_seconds for item in results], 0.95
        ),
        "peak_vram_gb_max": max(item.peak_vram_gb for item in results),
        "seed_diversity_group_count": diversity_groups,
        "seed_diversity_group_pass_rate": diversity_rate,
        "baseline_completion_rate": _ratio(baseline_completed, cases),
        "baseline_completion_rate_gap": _ratio(completed, cases)
        - _ratio(baseline_completed, cases),
        "publish_preferred_count": preferred,
        "publish_comparison_count": comparisons,
    }


def _relative_locator(root: Path, target: Path, field: str) -> str:
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if not resolved_target.is_relative_to(resolved_root):
        raise CompetitionBenchmarkError(
            f"{field} must be stored beneath the result JSONL directory"
        )
    if not resolved_target.is_file():
        raise CompetitionBenchmarkError(f"{field} does not exist: {target}")
    return resolved_target.relative_to(resolved_root).as_posix()


def _verify_partial_case_binding(
    *,
    row: Mapping[str, object],
    case: BenchmarkCase,
    manifest_hash: str,
    evidence_root: Path,
) -> None:
    case_id = case.case_id
    gate_path = _bound_artifact(
        evidence_root,
        row.get("gate_evidence_locator"),
        row.get("gate_evidence_sha256"),
        f"{case_id}.gate_evidence",
    )
    gate = _read_json(gate_path)
    if (
        gate.get("schema") != CASE_GATE_EVIDENCE_SCHEMA
        or gate.get("manifest_hash") != manifest_hash
        or gate.get("case_id") != case_id
    ):
        raise CompetitionBenchmarkError(
            f"{case_id}: existing gate evidence is not bound to this case"
        )
    completed = _require_bool(gate.get("completed"), f"{case_id}.completed")
    crashed = _require_bool(gate.get("crashed"), f"{case_id}.crashed")
    if completed and crashed:
        raise CompetitionBenchmarkError(
            f"{case_id}: completed and crashed cannot both be true"
        )
    if completed:
        _bound_artifact(
            evidence_root,
            row.get("output_locator"),
            row.get("output_sha256"),
            f"{case_id}.output",
        )
    elif row.get("output_locator") is not None or row.get("output_sha256") is not None:
        raise CompetitionBenchmarkError(
            f"{case_id}: incomplete existing row binds a still output"
        )
    if gate.get("output_sha256") != row.get("output_sha256"):
        raise CompetitionBenchmarkError(
            f"{case_id}: existing gate evidence is not bound to the still output"
        )
    if case.video_required and completed:
        _bound_artifact(
            evidence_root,
            row.get("video_output_locator"),
            row.get("video_output_sha256"),
            f"{case_id}.video_output",
        )
    elif (
        row.get("video_output_locator") is not None
        or row.get("video_output_sha256") is not None
    ):
        raise CompetitionBenchmarkError(
            f"{case_id}: existing row binds an unexpected video output"
        )
    if gate.get("video_output_sha256") != row.get("video_output_sha256"):
        raise CompetitionBenchmarkError(
            f"{case_id}: existing gate evidence is not bound to the video output"
        )


class CompetitionCaseJournal:
    """Append-only, resumable journal for the frozen ProofLaunch case matrix."""

    def __init__(self, manifest_path: Path, results_path: Path) -> None:
        self.manifest = load_frozen_manifest(manifest_path)
        self.results_path = results_path
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        self._case_by_id = {case.case_id: case for case in self.manifest.cases}
        self._recorded: set[str] = set()
        if self.results_path.exists():
            for index, row in enumerate(_read_jsonl(self.results_path), start=1):
                case_id = row.get("case_id")
                if row.get("schema") != CASE_RESULT_SCHEMA:
                    raise CompetitionBenchmarkError(
                        f"{self.results_path}:{index}: unsupported case-result schema"
                    )
                if row.get("manifest_hash") != self.manifest.manifest_hash:
                    raise CompetitionBenchmarkError(
                        f"{self.results_path}:{index}: manifest_hash mismatch"
                    )
                if not isinstance(case_id, str) or case_id not in self._case_by_id:
                    raise CompetitionBenchmarkError(
                        f"{self.results_path}:{index}: unknown case_id"
                    )
                if case_id in self._recorded:
                    raise CompetitionBenchmarkError(
                        f"{self.results_path}:{index}: duplicate case_id {case_id}"
                    )
                _verify_partial_case_binding(
                    row=row,
                    case=self._case_by_id[case_id],
                    manifest_hash=self.manifest.manifest_hash,
                    evidence_root=self.results_path.parent,
                )
                self._recorded.add(case_id)

    @property
    def pending_cases(self) -> tuple[BenchmarkCase, ...]:
        return tuple(
            case for case in self.manifest.cases if case.case_id not in self._recorded
        )

    @property
    def recorded_count(self) -> int:
        return len(self._recorded)

    def append(
        self,
        *,
        case_id: str,
        gate_evidence_path: Path,
        output_path: Path | None,
        video_output_path: Path | None = None,
    ) -> Mapping[str, object]:
        if case_id not in self._case_by_id:
            raise CompetitionBenchmarkError(f"unknown case_id {case_id}")
        if case_id in self._recorded:
            raise CompetitionBenchmarkError(f"case_id already recorded: {case_id}")
        case = self._case_by_id[case_id]
        root = self.results_path.parent
        gate = _read_json(gate_evidence_path)
        if gate.get("schema") != CASE_GATE_EVIDENCE_SCHEMA:
            raise CompetitionBenchmarkError("unsupported gate-evidence schema")
        if gate.get("manifest_hash") != self.manifest.manifest_hash:
            raise CompetitionBenchmarkError("gate-evidence manifest_hash mismatch")
        if gate.get("case_id") != case_id:
            raise CompetitionBenchmarkError("gate-evidence case_id mismatch")
        completed = _require_bool(gate.get("completed"), f"{case_id}.completed")
        crashed = _require_bool(gate.get("crashed"), f"{case_id}.crashed")
        if completed and crashed:
            raise CompetitionBenchmarkError(
                f"{case_id}: completed and crashed cannot both be true"
            )
        if completed and output_path is None:
            raise CompetitionBenchmarkError(
                f"{case_id}: a completed case requires an output artifact"
            )
        if not completed and output_path is not None:
            raise CompetitionBenchmarkError(
                f"{case_id}: an incomplete case cannot bind an output artifact"
            )
        if case.video_required and completed and video_output_path is None:
            raise CompetitionBenchmarkError(
                f"{case_id}: a completed video case requires a video artifact"
            )
        if (not case.video_required or not completed) and video_output_path is not None:
            raise CompetitionBenchmarkError(
                f"{case_id}: video artifact is not permitted for this result row"
            )

        output_sha256 = _file_sha256(output_path) if output_path else None
        video_sha256 = (
            _file_sha256(video_output_path) if video_output_path else None
        )
        if gate.get("output_sha256") != output_sha256:
            raise CompetitionBenchmarkError(
                f"{case_id}: gate evidence is not bound to the still output"
            )
        if gate.get("video_output_sha256") != video_sha256:
            raise CompetitionBenchmarkError(
                f"{case_id}: gate evidence is not bound to the video output"
            )
        row: dict[str, object] = {
            "schema": CASE_RESULT_SCHEMA,
            "manifest_hash": self.manifest.manifest_hash,
            "case_id": case_id,
            "gate_evidence_sha256": _file_sha256(gate_evidence_path),
            "gate_evidence_locator": _relative_locator(
                root, gate_evidence_path, "gate_evidence_path"
            ),
            "output_sha256": output_sha256,
            "output_locator": (
                _relative_locator(root, output_path, "output_path")
                if output_path
                else None
            ),
            "video_output_sha256": video_sha256,
            "video_output_locator": (
                _relative_locator(root, video_output_path, "video_output_path")
                if video_output_path
                else None
            ),
        }
        with self.results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._recorded.add(case_id)
        return row


class BaselineCaseJournal:
    """Append-only, resumable journal for the same frozen baseline cases."""

    def __init__(self, manifest_path: Path, results_path: Path) -> None:
        self.manifest = load_frozen_manifest(manifest_path)
        self.results_path = results_path
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        self._case_ids = {case.case_id for case in self.manifest.cases}
        self._recorded: set[str] = set()
        if self.results_path.exists():
            for index, row in enumerate(_read_jsonl(self.results_path), start=1):
                case_id = row.get("case_id")
                if row.get("schema") != BASELINE_RESULT_SCHEMA:
                    raise CompetitionBenchmarkError(
                        f"{self.results_path}:{index}: unsupported baseline schema"
                    )
                if row.get("manifest_hash") != self.manifest.manifest_hash:
                    raise CompetitionBenchmarkError(
                        f"{self.results_path}:{index}: manifest_hash mismatch"
                    )
                if not isinstance(case_id, str) or case_id not in self._case_ids:
                    raise CompetitionBenchmarkError(
                        f"{self.results_path}:{index}: unknown case_id"
                    )
                if case_id in self._recorded:
                    raise CompetitionBenchmarkError(
                        f"{self.results_path}:{index}: duplicate case_id {case_id}"
                    )
                completed = _require_bool(
                    row.get("completed"), f"{case_id}.completed"
                )
                crashed = _require_bool(row.get("crashed"), f"{case_id}.crashed")
                if completed and crashed:
                    raise CompetitionBenchmarkError(
                        f"{case_id}: completed and crashed cannot both be true"
                    )
                if completed:
                    _bound_artifact(
                        self.results_path.parent,
                        row.get("output_locator"),
                        row.get("output_sha256"),
                        f"{case_id}.baseline_output",
                    )
                elif (
                    row.get("output_locator") is not None
                    or row.get("output_sha256") is not None
                ):
                    raise CompetitionBenchmarkError(
                        f"{case_id}: incomplete baseline row binds an output"
                    )
                self._recorded.add(case_id)

    @property
    def pending_cases(self) -> tuple[BenchmarkCase, ...]:
        return tuple(
            case for case in self.manifest.cases if case.case_id not in self._recorded
        )

    def append(
        self,
        *,
        case_id: str,
        completed: bool,
        crashed: bool,
        output_path: Path | None,
    ) -> Mapping[str, object]:
        if case_id not in self._case_ids:
            raise CompetitionBenchmarkError(f"unknown case_id {case_id}")
        if case_id in self._recorded:
            raise CompetitionBenchmarkError(f"case_id already recorded: {case_id}")
        if not isinstance(completed, bool) or not isinstance(crashed, bool):
            raise CompetitionBenchmarkError("completed and crashed must be booleans")
        if completed and crashed:
            raise CompetitionBenchmarkError(
                f"{case_id}: completed and crashed cannot both be true"
            )
        if completed != (output_path is not None):
            raise CompetitionBenchmarkError(
                f"{case_id}: completed must exactly match output artifact presence"
            )
        root = self.results_path.parent
        row: dict[str, object] = {
            "schema": BASELINE_RESULT_SCHEMA,
            "manifest_hash": self.manifest.manifest_hash,
            "case_id": case_id,
            "completed": completed,
            "crashed": crashed,
            "output_sha256": _file_sha256(output_path) if output_path else None,
            "output_locator": (
                _relative_locator(root, output_path, "output_path")
                if output_path
                else None
            ),
        }
        with self.results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._recorded.add(case_id)
        return row


def load_products_csv(path: Path) -> tuple[ProductSpec, ...]:
    expected_fields = ("product_id", "input_sha256", "rights", "source_locator")
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as error:
        raise CompetitionBenchmarkError(f"cannot read products CSV {path}: {error}") from error
    with handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != expected_fields:
            raise CompetitionBenchmarkError(
                f"{path}: CSV header must be exactly {','.join(expected_fields)}"
            )
        return tuple(ProductSpec.from_mapping(row) for row in reader)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows
    )
    path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")
