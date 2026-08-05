#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.artifact_provenance import provenance_record, write_provenance_record
from corpus.legacy_recovery.artifact_source_registry import ArtifactSourceRegistry
from corpus.legacy_recovery.artifact_trust_policy import evaluate_artifact_policy

ArtifactSearcher = Callable[[dict[str, Any]], list[dict[str, Any]]]


class OnlineArtifactStatus(str, Enum):
    ONLINE_DISCOVERY_CANDIDATE_FOUND = "ONLINE_DISCOVERY_CANDIDATE_FOUND"
    ONLINE_ARTIFACT_PINNED = "ONLINE_ARTIFACT_PINNED"
    ONLINE_ARTIFACT_REJECTED = "ONLINE_ARTIFACT_REJECTED"
    ONLINE_ARTIFACT_AMBIGUOUS = "ONLINE_ARTIFACT_AMBIGUOUS"
    IMAGE_MISSING = "IMAGE_MISSING"


@dataclass(slots=True)
class OnlineArtifactDiscoveryConfig:
    source_registry_path: Path = Path("assurance/config/artifact_sources.json")
    provenance_root: Path = Path("T:/determinex_artifacts/provenance")
    quarantine_root: Path = Path("T:/determinex_artifacts/quarantine")
    cache_root: Path = Path("T:/determinex_artifacts/cache")
    output_path: Path = Path(
        "assurance/evidence/programbench_online_artifact_discovery_batch_001.json"
    )
    searcher: ArtifactSearcher | None = None
    allow_download: bool = False


@dataclass(slots=True)
class OnlineArtifactDiscoveryResult:
    tool: str
    status: str
    reason: str
    artifact_id: str = ""
    source: str = ""
    resolved_digest: str = ""
    revision: str = ""
    provenance_path: str = ""
    score: int = 0
    rejected_candidates: list[dict[str, str]] = field(default_factory=list)


class OnlineArtifactDiscovery:
    def __init__(self, config: OnlineArtifactDiscoveryConfig) -> None:
        self.config = config
        self.registry = ArtifactSourceRegistry(config.source_registry_path)

    def discover_batch(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        results = [self.discover_for_candidate(candidate) for candidate in candidates]
        counts = _counts(result.status for result in results)
        report = {
            "schema_version": "determinex-online-artifact-discovery-v1",
            "batch_id": "legacy_replay_promotion_batch_001",
            "candidates": len(candidates),
            "online_candidates_found": counts.get(
                OnlineArtifactStatus.ONLINE_DISCOVERY_CANDIDATE_FOUND.value, 0
            ),
            "online_artifacts_pinned": counts.get(
                OnlineArtifactStatus.ONLINE_ARTIFACT_PINNED.value, 0
            ),
            "online_artifacts_rejected": counts.get(
                OnlineArtifactStatus.ONLINE_ARTIFACT_REJECTED.value, 0
            ),
            "online_artifacts_ambiguous": counts.get(
                OnlineArtifactStatus.ONLINE_ARTIFACT_AMBIGUOUS.value, 0
            ),
            "missing": counts.get(OnlineArtifactStatus.IMAGE_MISSING.value, 0),
            "status_counts": counts,
            "results": [asdict(result) for result in results],
            "policy": "Online sources may suggest artifacts. Only pinned, scanned, provenance-recorded artifacts can enter replay hydration.",
        }
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    def discover_for_candidate(self, candidate: dict[str, Any]) -> OnlineArtifactDiscoveryResult:
        tool = str(candidate.get("tool") or "")
        if self.config.searcher is None:
            return OnlineArtifactDiscoveryResult(
                tool, OnlineArtifactStatus.IMAGE_MISSING.value, "online_searcher_not_configured"
            )

        discovered = self.config.searcher(candidate)
        if not discovered:
            return OnlineArtifactDiscoveryResult(
                tool, OnlineArtifactStatus.IMAGE_MISSING.value, "no_online_candidates"
            )

        scored = sorted(
            [(_score(row, candidate), idx, row) for idx, row in enumerate(discovered)],
            key=lambda item: item[0],
        )
        best_score, _idx, best = scored[-1]
        if len(scored) > 1 and scored[-2][0] == best_score:
            return OnlineArtifactDiscoveryResult(
                tool,
                OnlineArtifactStatus.ONLINE_ARTIFACT_AMBIGUOUS.value,
                "multiple_equal_candidates",
                score=best_score,
            )

        source = self.registry.get(str(best.get("source") or ""))
        if source:
            best = dict(best)
            best.setdefault("trust_level", source.trust_level)
        decision = evaluate_artifact_policy(best, source)
        if not decision.allowed:
            return OnlineArtifactDiscoveryResult(
                tool,
                OnlineArtifactStatus.ONLINE_ARTIFACT_REJECTED.value,
                decision.reason,
                artifact_id=str(best.get("artifact_id") or ""),
                source=str(best.get("source") or ""),
                resolved_digest=str(best.get("resolved_digest") or best.get("digest") or ""),
                revision=str(best.get("revision") or ""),
                score=best_score,
                rejected_candidates=[
                    {"artifact_id": str(best.get("artifact_id") or ""), "reason": decision.reason}
                ],
            )

        # Discovery-only lock: no download/execution is performed. Quarantine and
        # cache roots are recorded for the later downloader/hydrator phase.
        record = provenance_record(best, allowed_use=["programbench_replay"])
        path = write_provenance_record(record, self.config.provenance_root)
        return OnlineArtifactDiscoveryResult(
            tool,
            OnlineArtifactStatus.ONLINE_ARTIFACT_PINNED.value,
            "pinned_scanned_provenance_recorded",
            artifact_id=str(best.get("artifact_id") or ""),
            source=str(best.get("source") or ""),
            resolved_digest=str(best.get("resolved_digest") or best.get("digest") or ""),
            revision=str(best.get("revision") or ""),
            provenance_path=str(path),
            score=best_score,
        )


def _score(candidate: dict[str, Any], request: dict[str, Any]) -> int:
    score = 0
    tool = str(request.get("tool") or "").lower()
    artifact_id = str(candidate.get("artifact_id") or "").lower()
    image = str(candidate.get("image") or "").lower()
    repo = str(candidate.get("repo") or "").lower()
    if tool and (tool in artifact_id or tool in image or tool in repo):
        score += 20
    if str(candidate.get("programbench_task_id") or "") == str(
        request.get("programbench_task_id") or ""
    ):
        score += 15
    if str(candidate.get("resolved_digest") or candidate.get("digest") or "").startswith("sha256:"):
        score += 10
    if candidate.get("revision") and candidate.get("revision") not in {"main", "master", "latest"}:
        score += 8
    if candidate.get("license"):
        score += 4
    if (candidate.get("security_scan") or {}).get("policy") == "pass":
        score += 10
    if candidate.get("official_source"):
        score += 6
    return score


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discovery-only ProgramBench artifact candidate resolver."
    )
    parser.add_argument("candidates", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/programbench_online_artifact_discovery_batch_001.json"),
    )
    args = parser.parse_args()
    data = json.loads(args.candidates.read_text(encoding="utf-8"))
    candidates = list(data.get("selected") or data.get("results") or [])
    report = OnlineArtifactDiscovery(
        OnlineArtifactDiscoveryConfig(output_path=args.output)
    ).discover_batch(candidates)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
