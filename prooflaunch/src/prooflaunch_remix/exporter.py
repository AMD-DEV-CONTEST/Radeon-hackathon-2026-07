from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from .contracts import CampaignState, ReleaseDecision, Stage
from .files import atomic_write_text
from .ledger import EvidenceLedger, canonical_json


class VerifiedCampaignExporter:
    """Exports only audited files and records content-addressed provenance."""

    def export(self, state: CampaignState) -> list[str]:
        if state.stage is not Stage.AWAITING_RELEASE:
            raise RuntimeError("export is only allowed from awaiting_release")
        if state.release_blockers:
            raise RuntimeError("cannot export assets with release blockers")
        approval = state.release_approval
        if (
            approval is None
            or approval.decision is not ReleaseDecision.APPROVE
            or not approval.integrity_valid
            or approval.run_id != state.run_id
        ):
            raise RuntimeError("valid content-bound approval is required for export")
        ledger_path = state.output_path / "evidence-ledger.jsonl"
        if not EvidenceLedger.verify(ledger_path):
            raise RuntimeError("evidence ledger verification failed")
        try:
            ledger_events = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
            ]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("evidence ledger reload failed") from exc
        if not ledger_events or any(
            event.get("run_id") != state.run_id for event in ledger_events
        ):
            raise RuntimeError("evidence ledger run identity mismatch")
        last_event = ledger_events[-1]
        if (
            last_event.get("kind") != "release_approved"
            or last_event.get("stage") != Stage.AWAITING_RELEASE.value
            or last_event.get("payload", {}).get("approval")
            != approval.serializable()
        ):
            raise RuntimeError("ledger does not contain this release approval")

        files: list[dict[str, object]] = []
        captured_files: list[tuple[str, bytes]] = []
        file_hashes: dict[str, str] = {}
        output_root = state.output_path.resolve()
        for asset in state.assets:
            for role, raw_path in state.release_file_paths(asset):
                path = Path(str(raw_path)).resolve()
                if not path.is_file():
                    raise FileNotFoundError(f"missing {role} file for {asset.id}: {path}")
                try:
                    path.relative_to(output_root)
                except ValueError as exc:
                    raise RuntimeError(
                        f"{role} file for {asset.id} escapes the campaign directory"
                    ) from exc
                payload = path.read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                file_hashes[state.release_file_hash_key(asset.id, role)] = digest
                archive_name = f"assets/{asset.id}/{role}-{path.name}"
                captured_files.append((archive_name, payload))
                files.append(
                    {
                        "asset_id": asset.id,
                        "role": role,
                        "name": path.name,
                        "archive_name": archive_name,
                        "bytes": len(payload),
                        "sha256": digest,
                    }
                )
        snapshot_digest = state.preview_digest(file_hashes=file_hashes)
        if not (
            snapshot_digest
            == state.prepared_preview_digest
            == approval.preview_digest
        ):
            raise RuntimeError("approved preview bytes changed before export")

        manifest = {
            "schema": "ProofLaunchCampaignPackV1",
            "run_id": state.run_id,
            "status": "release_approved",
            "platform": state.request.platform,
            "market": state.request.market,
            "repair_rounds": state.repair_count,
            "ledger_verified_before_export": True,
            "release_approval": approval.serializable(),
            "preview_digest": snapshot_digest,
            "files": files,
            "truth_boundary": (
                "Asset hashes prove pipeline integrity; they do not prove campaign "
                "performance or Radeon execution."
            ),
        }
        manifest_path = state.output_path / "campaign-pack.json"
        atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        archive_path = state.output_path / "campaign-pack.zip"
        temporary_archive = archive_path.with_name(f".{archive_path.name}.tmp")
        try:
            with zipfile.ZipFile(
                temporary_archive,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                self._write_bytes(
                    archive,
                    "campaign-pack.json",
                    canonical_json(manifest).encode("utf-8"),
                )
                for archive_name, payload in sorted(captured_files):
                    self._write_bytes(archive, archive_name, payload)
            temporary_archive.replace(archive_path)
        finally:
            temporary_archive.unlink(missing_ok=True)
        return [str(manifest_path), str(archive_path)]

    @staticmethod
    def _write_bytes(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
        info = zipfile.ZipInfo(name, date_time=(2026, 7, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, payload)
