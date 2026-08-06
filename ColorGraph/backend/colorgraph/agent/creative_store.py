from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from colorgraph.agent.creative_contracts import (
    SHA256_PATTERN,
    AgentRunManifest,
    AgentState,
    SignedAgentAsset,
    TechnicalBaseline,
    canonical_sha256,
)
from colorgraph.agent.creative_runtime import AgentRunLedger


class StoredRunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    manifest: AgentRunManifest
    sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_digest(self) -> StoredRunManifest:
        if self.sha256 != canonical_sha256(self.manifest):
            raise ValueError("stored run manifest SHA-256 mismatch")
        return self


def _safe_component(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    digest = canonical_sha256({"value": value})[:12]
    return f"{label[:48] or 'asset'}-{digest}"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


class CreativeAssetStore:
    """Filesystem persistence for immutable signed agent assets."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def run_dir(self, project_id: str, run_id: str) -> Path:
        return self.root / _safe_component(project_id) / _safe_component(run_id)

    @staticmethod
    def _write_immutable(path: Path, content: str) -> Path:
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"refusing to overwrite immutable agent asset {path.name}")
            return path
        _atomic_write(path, content)
        return path

    def save_baseline(
        self,
        project_id: str,
        run_id: str,
        baseline: SignedAgentAsset,
    ) -> Path:
        if baseline.project_id != project_id:
            raise ValueError("baseline project does not match the store path")
        path = self.run_dir(project_id, run_id) / "baseline.json"
        return self._write_immutable(
            path,
            baseline.model_dump_json(indent=2),
        )

    def save_asset(
        self,
        project_id: str,
        run_id: str,
        *,
        sequence: int,
        stage: AgentState,
        asset: SignedAgentAsset,
    ) -> Path:
        if sequence < 0:
            raise ValueError("agent asset sequence must be non-negative")
        if asset.project_id != project_id:
            raise ValueError("agent asset project does not match the store path")
        suffix = asset.asset_id.rsplit("_", 1)[-1]
        path = (
            self.run_dir(project_id, run_id)
            / "assets"
            / f"{sequence:03d}-{stage.value}-{suffix}.json"
        )
        return self._write_immutable(
            path,
            asset.model_dump_json(indent=2),
        )

    def save_failure_case(
        self,
        project_id: str,
        run_id: str,
        *,
        sequence: int,
        asset: SignedAgentAsset,
    ) -> Path:
        if asset.project_id != project_id:
            raise ValueError("failure case project does not match the store path")
        suffix = asset.asset_id.rsplit("_", 1)[-1]
        path = self.run_dir(project_id, run_id) / "failures" / f"{sequence:03d}-{suffix}.json"
        return self._write_immutable(
            path,
            asset.model_dump_json(indent=2),
        )

    def save_manifest(self, manifest: AgentRunManifest) -> Path:
        stored = StoredRunManifest(
            manifest=manifest,
            sha256=canonical_sha256(manifest),
        )
        path = self.run_dir(manifest.project_id, manifest.run_id) / "manifest.json"
        _atomic_write(path, stored.model_dump_json(indent=2))
        return path

    def persist_ledger(self, ledger: AgentRunLedger) -> Path:
        self.save_baseline(
            ledger.project_id,
            ledger.run_id,
            ledger.technical_baseline,
        )
        for sequence, (stage, asset) in enumerate(ledger.assets):
            self.save_asset(
                ledger.project_id,
                ledger.run_id,
                sequence=sequence,
                stage=stage,
                asset=asset,
            )
        for sequence, asset in enumerate(ledger.failure_cases):
            self.save_failure_case(
                ledger.project_id,
                ledger.run_id,
                sequence=sequence,
                asset=asset,
            )
        return self.save_manifest(ledger.manifest())

    def load_baseline(
        self,
        project_id: str,
        run_id: str,
    ) -> SignedAgentAsset:
        path = self.run_dir(project_id, run_id) / "baseline.json"
        asset = SignedAgentAsset.model_validate_json(path.read_text(encoding="utf-8"))
        if asset.project_id != project_id:
            raise ValueError("stored baseline project mismatch")
        return asset

    def load_assets(
        self,
        project_id: str,
        run_id: str,
    ) -> list[SignedAgentAsset]:
        directory = self.run_dir(project_id, run_id) / "assets"
        if not directory.exists():
            return []
        assets = [
            SignedAgentAsset.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]
        if any(asset.project_id != project_id for asset in assets):
            raise ValueError("stored agent asset project mismatch")
        return assets

    def load_manifest(
        self,
        project_id: str,
        run_id: str,
    ) -> AgentRunManifest:
        path = self.run_dir(project_id, run_id) / "manifest.json"
        stored = StoredRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if stored.manifest.project_id != project_id or stored.manifest.run_id != run_id:
            raise ValueError("stored run manifest identity mismatch")
        return stored.manifest

    def verify_run(
        self,
        project_id: str,
        run_id: str,
    ) -> AgentRunManifest:
        baseline = self.load_baseline(project_id, run_id)
        assets = self.load_assets(project_id, run_id)
        manifest = self.load_manifest(project_id, run_id)
        if not isinstance(baseline.payload, TechnicalBaseline):
            raise ValueError("stored baseline has the wrong payload type")
        if manifest.graph_digest != baseline.payload.graph_digest:
            raise ValueError("manifest graph digest differs from baseline")
        expected = [
            (
                entry.asset_id,
                entry.asset_sha256,
            )
            for entry in manifest.assets
        ]
        actual = [
            (
                asset.asset_id,
                asset.sha256,
            )
            for asset in assets
        ]
        if actual != expected:
            raise ValueError("stored agent assets do not match the run manifest")
        return manifest
