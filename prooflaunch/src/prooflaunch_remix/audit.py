from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops

from .contracts import AuditFinding, CampaignState, CreativeAsset, Severity
from .files import sha256_file
from .visual_semantics import SemanticScorer


def _intersects(first: Iterable[int], second: Iterable[int]) -> bool:
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1


class FourGateReleaseAuditor:
    """Mechanical claim, identity, typography, and platform-safe-zone gates."""

    def __init__(
        self,
        *,
        min_contrast: float = 4.5,
        min_font_ratio: float = 0.035,
        max_identity_mismatch: float = 0.001,
        semantic_scorer: SemanticScorer | None = None,
    ) -> None:
        self.min_contrast = min_contrast
        self.min_font_ratio = min_font_ratio
        self.max_identity_mismatch = max_identity_mismatch
        self.semantic_scorer = semantic_scorer

    def audit(self, state: CampaignState) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        approved = {claim.id: claim for claim in state.claims if claim.approved}
        for asset in state.assets:
            findings.extend(self._claim_gate(asset, approved))
            findings.extend(self._identity_gate(asset))
            findings.extend(self._typography_gate(asset))
            findings.extend(self._safe_zone_gate(asset))
            findings.extend(self._semantic_gate(state, asset))
        return findings

    @staticmethod
    def _finding(
        asset: CreativeAsset,
        category: str,
        message: str,
        repair_action: str,
        evidence: dict,
        *,
        severity: Severity = Severity.ERROR,
    ) -> AuditFinding:
        return AuditFinding(
            id=f"AUD-{asset.id}-{category}",
            category=category,
            severity=severity,
            message=message,
            asset_id=asset.id,
            repair_action=repair_action,
            evidence=evidence,
        )

    def _claim_gate(self, asset: CreativeAsset, approved: dict) -> list[AuditFinding]:
        claim_ids = tuple(asset.metadata.get("claim_ids", ()))
        rendered = tuple(asset.metadata.get("rendered_claims", ()))
        expected = tuple(approved[item].text for item in claim_ids if item in approved)
        if not claim_ids or len(expected) != len(claim_ids) or rendered != expected:
            return [
                self._finding(
                    asset,
                    "claim_grounding",
                    "Visible claim text is not an exact approved source span.",
                    "restore_exact_approved_claim",
                    {
                        "claim_ids": claim_ids,
                        "expected": expected,
                        "rendered": rendered,
                    },
                    severity=Severity.CRITICAL,
                )
            ]
        return []

    def _semantic_gate(
        self, state: CampaignState, asset: CreativeAsset
    ) -> list[AuditFinding]:
        if self.semantic_scorer is None:
            return []
        score = self.semantic_scorer.score(
            image_path=asset.path,
            product_name=state.request.product_name,
        )
        asset.metadata["semantic_score"] = {
            "passed": score.passed,
            "model_ref": score.model_ref,
            "positive_probability": score.positive_probability,
            "strongest_negative_probability": score.strongest_negative_probability,
            "margin": score.margin,
            "labels": list(score.labels),
            "probabilities": list(score.probabilities),
            "limitations": list(score.limitations),
        }
        if score.passed:
            return []
        return [
            self._finding(
                asset,
                "visual_semantics",
                "Local vision-language scorer did not confirm a single clear product.",
                "regenerate_background_and_reaudit",
                asset.metadata["semantic_score"],
                severity=Severity.ERROR,
            )
        ]

    def _identity_gate(self, asset: CreativeAsset) -> list[AuditFinding]:
        metadata = asset.metadata
        source = Path(str(metadata.get("product_source_path", "")))
        layer = Path(str(metadata.get("product_layer_path", "")))
        output = Path(asset.path)
        expected_source = metadata.get("product_source_sha256")
        expected_layer = metadata.get("product_layer_sha256")
        evidence = {
            "source_exists": source.is_file(),
            "layer_exists": layer.is_file(),
            "asset_exists": output.is_file(),
        }
        if not all(evidence.values()):
            return [
                self._finding(
                    asset,
                    "product_identity",
                    "Product source, protected layer, or final asset is missing.",
                    "regenerate_from_immutable_source",
                    evidence,
                    severity=Severity.CRITICAL,
                )
            ]
        actual_source = sha256_file(source)
        actual_layer = sha256_file(layer)
        evidence.update(
            {
                "expected_source_sha256": expected_source,
                "actual_source_sha256": actual_source,
                "expected_layer_sha256": expected_layer,
                "actual_layer_sha256": actual_layer,
            }
        )
        if actual_source != expected_source or actual_layer != expected_layer:
            return [
                self._finding(
                    asset,
                    "product_identity",
                    "Protected product provenance hash does not match.",
                    "regenerate_from_immutable_source",
                    evidence,
                    severity=Severity.CRITICAL,
                )
            ]
        mismatch = self._opaque_product_mismatch(layer, output)
        evidence["opaque_pixel_mismatch_ratio"] = mismatch
        if mismatch > self.max_identity_mismatch:
            return [
                self._finding(
                    asset,
                    "product_identity",
                    "Final asset altered opaque pixels in the protected product layer.",
                    "regenerate_from_immutable_source",
                    evidence,
                    severity=Severity.CRITICAL,
                )
            ]
        return []

    @staticmethod
    def _opaque_product_mismatch(layer_path: Path, output_path: Path) -> float:
        with Image.open(layer_path) as layer_source:
            layer = layer_source.convert("RGBA")
        with Image.open(output_path) as output_source:
            output = output_source.convert("RGBA")
        if layer.size != output.size:
            return 1.0
        alpha = layer.getchannel("A")
        # Only alpha=255 pixels are expected to remain byte-identical after
        # compositing. Anti-aliased 1..254 edge pixels must blend with the
        # background and therefore cannot be compared to the uncomposited RGB.
        opaque = alpha.point(lambda value: 255 if value == 255 else 0)
        opaque_count = opaque.width * opaque.height - opaque.histogram()[0]
        if opaque_count == 0:
            return 1.0
        difference = ImageChops.difference(layer.convert("RGB"), output.convert("RGB"))
        difference_mask = difference.convert("L").point(lambda value: 255 if value else 0)
        mismatch_mask = ImageChops.multiply(difference_mask, opaque)
        mismatches = (
            mismatch_mask.width * mismatch_mask.height - mismatch_mask.histogram()[0]
        )
        return mismatches / opaque_count

    def _typography_gate(self, asset: CreativeAsset) -> list[AuditFinding]:
        metadata = asset.metadata
        width, height = metadata.get("canvas_size", [0, 0])
        min_font = max(12, round(min(width, height) * self.min_font_ratio))
        actual_font = int(metadata.get("headline_font_px", 0))
        contrast = float(metadata.get("text_contrast_ratio", 0))
        overflow = bool(metadata.get("text_overflow", True))
        if contrast < self.min_contrast or actual_font < min_font or overflow:
            return [
                self._finding(
                    asset,
                    "typography",
                    "Typography failed contrast, size, or fit requirements.",
                    "apply_accessible_type_layout",
                    {
                        "contrast_ratio": contrast,
                        "minimum_contrast_ratio": self.min_contrast,
                        "font_px": actual_font,
                        "minimum_font_px": min_font,
                        "overflow": overflow,
                    },
                )
            ]
        return []

    def _safe_zone_gate(self, asset: CreativeAsset) -> list[AuditFinding]:
        width, height = asset.metadata.get("canvas_size", [0, 0])
        if width <= 0 or height <= 0:
            return [
                self._finding(
                    asset,
                    "platform_safe_zone",
                    "Canvas dimensions are missing.",
                    "apply_platform_safe_layout",
                    {},
                )
            ]
        forbidden = {
            "top": (0, 0, width, round(height * 0.055)),
            "bottom": (0, round(height * 0.89), width, height),
            "action_rail": (round(width * 0.865), 0, width, height),
        }
        boxes = {
            "headline": asset.metadata.get("headline_box", ()),
            "cta": asset.metadata.get("cta_box", ()),
            "product": asset.metadata.get("product_box", ()),
        }
        overlaps = [
            f"{name}:{zone}"
            for name, box in boxes.items()
            if len(box) == 4
            for zone, boundary in forbidden.items()
            if _intersects(box, boundary)
        ]
        if overlaps:
            return [
                self._finding(
                    asset,
                    "platform_safe_zone",
                    "Creative content overlaps a reserved platform region.",
                    "apply_platform_safe_layout",
                    {"overlaps": overlaps, "forbidden": forbidden},
                )
            ]
        return []
