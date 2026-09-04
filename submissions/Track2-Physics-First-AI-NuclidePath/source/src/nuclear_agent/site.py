"""Site/source characterization agent for the supported Cs-137 groundwater scenario."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class SiteValidationError(ValueError):
    """Raised when site/source context is invalid or unsupported."""


@dataclass(frozen=True)
class SiteContext:
    site_id: str
    event_type: str
    radionuclide: str
    release_pathway: str
    source_description: str
    data_provenance: str
    data_classification: str
    mineralogy: str | None = None
    clay_fraction: float | None = None
    ph: float | None = None
    cec_cmol_kg: float | None = None
    ionic_composition_available: bool = False
    site_specific_kd_available: bool = False

    _REQUIRED = frozenset(
        {
            "site_id",
            "event_type",
            "radionuclide",
            "release_pathway",
            "source_description",
            "data_provenance",
            "data_classification",
        }
    )
    _FIELDS = _REQUIRED | frozenset(
        {
            "mineralogy",
            "clay_fraction",
            "ph",
            "cec_cmol_kg",
            "ionic_composition_available",
            "site_specific_kd_available",
        }
    )
    _PROVENANCE = frozenset(
        {"site-measured", "user-provided", "literature-default", "demonstration"}
    )
    _CLASSIFICATIONS = frozenset({"public", "internal", "sensitive"})

    def __post_init__(self) -> None:
        for name in self._REQUIRED:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SiteValidationError(f"{name} must be a non-empty string")
        if self.radionuclide != "Cs-137":
            raise SiteValidationError("current physics tool supports Cs-137 only")
        if self.release_pathway != "groundwater":
            raise SiteValidationError("current physics tool supports groundwater pathway only")
        if self.data_provenance not in self._PROVENANCE:
            raise SiteValidationError(
                f"data_provenance must be one of {sorted(self._PROVENANCE)}"
            )
        if self.data_classification not in self._CLASSIFICATIONS:
            raise SiteValidationError(
                f"data_classification must be one of {sorted(self._CLASSIFICATIONS)}"
            )
        if self.clay_fraction is not None and not 0.0 <= self.clay_fraction <= 1.0:
            raise SiteValidationError("clay_fraction must be in [0, 1]")
        if self.ph is not None and not 0.0 <= self.ph <= 14.0:
            raise SiteValidationError("ph must be in [0, 14]")
        if self.cec_cmol_kg is not None and self.cec_cmol_kg < 0:
            raise SiteValidationError("cec_cmol_kg must be >= 0")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SiteContext":
        unknown = set(payload) - cls._FIELDS
        if unknown:
            raise SiteValidationError(f"unknown site field: {sorted(unknown)[0]}")
        missing = cls._REQUIRED - set(payload)
        if missing:
            raise SiteValidationError(f"missing site field: {sorted(missing)[0]}")
        for boolean_name in (
            "ionic_composition_available",
            "site_specific_kd_available",
        ):
            value = payload.get(boolean_name, False)
            if not isinstance(value, bool):
                raise SiteValidationError(f"{boolean_name} must be boolean")
        try:
            return cls(
                site_id=str(payload["site_id"]),
                event_type=str(payload["event_type"]),
                radionuclide=str(payload["radionuclide"]),
                release_pathway=str(payload["release_pathway"]),
                source_description=str(payload["source_description"]),
                data_provenance=str(payload["data_provenance"]),
                data_classification=str(payload["data_classification"]),
                mineralogy=(
                    None
                    if payload.get("mineralogy") is None
                    else str(payload["mineralogy"])
                ),
                clay_fraction=(
                    None
                    if payload.get("clay_fraction") is None
                    else float(payload["clay_fraction"])
                ),
                ph=None if payload.get("ph") is None else float(payload["ph"]),
                cec_cmol_kg=(
                    None
                    if payload.get("cec_cmol_kg") is None
                    else float(payload["cec_cmol_kg"])
                ),
                ionic_composition_available=payload.get(
                    "ionic_composition_available", False
                ),
                site_specific_kd_available=payload.get(
                    "site_specific_kd_available", False
                ),
            )
        except (TypeError, ValueError) as exc:
            raise SiteValidationError(f"invalid site value: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "event_type": self.event_type,
            "radionuclide": self.radionuclide,
            "release_pathway": self.release_pathway,
            "source_description": self.source_description,
            "data_provenance": self.data_provenance,
            "data_classification": self.data_classification,
            "mineralogy": self.mineralogy,
            "clay_fraction": self.clay_fraction,
            "ph": self.ph,
            "cec_cmol_kg": self.cec_cmol_kg,
            "ionic_composition_available": self.ionic_composition_available,
            "site_specific_kd_available": self.site_specific_kd_available,
        }


@dataclass(frozen=True)
class SiteAssessment:
    site_id: str
    normalized_context: dict[str, Any]
    missing_critical_data: tuple[str, ...]
    screening_only: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "normalized_context": dict(self.normalized_context),
            "missing_critical_data": list(self.missing_critical_data),
            "screening_only": self.screening_only,
            "warnings": list(self.warnings),
        }


class SiteAgent:
    """Validates site metadata and exposes limitations without inventing data."""

    def assess(self, payload: Mapping[str, Any]) -> SiteAssessment:
        context = SiteContext.from_dict(payload)
        missing: list[str] = []
        if not context.site_specific_kd_available:
            missing.append("site_specific_kd")
        if not context.mineralogy:
            missing.append("mineralogy")
        if context.clay_fraction is None:
            missing.append("clay_fraction")
        if context.ph is None:
            missing.append("ph")
        if context.cec_cmol_kg is None:
            missing.append("cec")
        if not context.ionic_composition_available:
            missing.append("ionic_composition")

        screening_only = bool(missing) or context.data_provenance != "site-measured"
        warnings = []
        if screening_only:
            warnings.append(
                "Site characterization is incomplete or non-site-specific; results are screening-only"
            )
        if context.data_provenance == "demonstration":
            warnings.append("Site and event metadata are explicitly demonstrative")
        return SiteAssessment(
            site_id=context.site_id,
            normalized_context=context.to_dict(),
            missing_critical_data=tuple(missing),
            screening_only=screening_only,
            warnings=tuple(warnings),
        )
