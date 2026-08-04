from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from policyseal.domain.models import DisclosureRevision, DocumentRegion, PolicyDecision


@dataclass(frozen=True, slots=True)
class EvidencePackage:
    data: bytes
    sha256: str


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def build_evidence_package(
    revision: DisclosureRevision,
    regions: tuple[DocumentRegion, ...],
    decisions: tuple[PolicyDecision, ...],
    *,
    template_root: Path,
) -> EvidencePackage:
    locations = {region.id: region.location for region in regions}
    decision_rows = [
        {
            "location": locations[decision.region_id],
            "category": decision.category.value,
            "action": decision.action.value,
            "rule_ids": list(decision.rule_ids),
            "evidence_ids": list(decision.evidence_ids),
            "reason_code": decision.reason_code,
            "transform": decision.transform,
        }
        for decision in decisions
    ]
    manifest = {
        "schema_version": "1.0",
        "revision_id": revision.id,
        "task_id": revision.task_id,
        "revision_number": revision.revision_number,
        "status": revision.status.value,
        "context": {
            "recipient": revision.context.recipient.value,
            "organization": revision.context.organization,
            "purpose": revision.context.purpose.value,
            "channel": revision.context.channel.value,
            "classification": revision.context.classification.value,
            "policy_version": revision.context.policy_version,
        },
        "source_sha256": revision.source_sha256,
        "output_sha256": revision.output_sha256,
        "policy_sha256": revision.policy_sha256,
        "decision_manifest_sha256": revision.decision_manifest_sha256,
        "decisions": decision_rows,
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("ascii")
    environment = Environment(
        loader=FileSystemLoader(template_root),
        autoescape=select_autoescape(("html", "xml")),
    )
    report_bytes = environment.get_template("decision-report.html.j2").render(
        revision=revision,
        decisions=decision_rows,
    ).encode("utf-8")
    checksums = (
        f"{hashlib.sha256(report_bytes).hexdigest()}  decision-report.html\n"
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
    ).encode("ascii")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr(_zip_info("decision-report.html"), report_bytes)
        package.writestr(_zip_info("manifest.json"), manifest_bytes)
        package.writestr(_zip_info("checksums.txt"), checksums)
    data = buffer.getvalue()
    return EvidencePackage(data, hashlib.sha256(data).hexdigest())
