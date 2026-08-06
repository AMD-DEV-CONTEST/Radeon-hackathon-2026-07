"""Conservative taint propagation across derived data."""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import Field

from buildguard.schemas.common import StrictSchema
from buildguard.security.advanced.trust_labels import (
    TRUSTED_CONTROL_LABELS,
    LabeledData,
    Provenance,
    TrustLabel,
)

_UNTRUSTED_PRECEDENCE = (
    TrustLabel.UNTRUSTED_OCR,
    TrustLabel.UNTRUSTED_DOCUMENT,
    TrustLabel.UNTRUSTED_TOOL_OUTPUT,
    TrustLabel.UNTRUSTED_MODEL_OUTPUT,
)


class TaintTrace(StrictSchema):
    value: Any
    labels: list[TrustLabel] = Field(min_length=1)
    provenance: list[Provenance] = Field(min_length=1)
    sensitive: bool = False

    @property
    def trusted_for_control(self) -> bool:
        return all(label in TRUSTED_CONTROL_LABELS for label in self.labels)


def trace(data: LabeledData) -> TaintTrace:
    return TaintTrace(
        value=data.value,
        labels=[data.label],
        provenance=[data.provenance],
        sensitive=data.sensitive,
    )


def propagate_taint(value: Any, *sources: LabeledData | TaintTrace) -> TaintTrace:
    if not sources:
        raise ValueError("Taint propagation requires at least one labeled source")
    labels: list[TrustLabel] = []
    origins: list[Provenance] = []
    sensitive = False
    for source in sources:
        source_labels = [source.label] if isinstance(source, LabeledData) else source.labels
        source_origins = (
            [source.provenance] if isinstance(source, LabeledData) else source.provenance
        )
        for label in source_labels:
            if label not in labels:
                labels.append(label)
        for origin in source_origins:
            if origin not in origins:
                origins.append(origin)
        sensitive = sensitive or source.sensitive
    return TaintTrace(
        value=value,
        labels=sorted(labels, key=lambda item: item.value),
        provenance=origins,
        sensitive=sensitive,
    )


def dominant_label(source: LabeledData | TaintTrace) -> TrustLabel:
    labels = [source.label] if isinstance(source, LabeledData) else source.labels
    for label in _UNTRUSTED_PRECEDENCE:
        if label in labels:
            return label
    if TrustLabel.TRUSTED_CONFIRMATION in labels:
        return TrustLabel.TRUSTED_CONFIRMATION
    if TrustLabel.TRUSTED_POLICY in labels:
        return TrustLabel.TRUSTED_POLICY
    return TrustLabel.TRUSTED_USER_INSTRUCTION


def derived_labeled_data(
    value: Any,
    *sources: LabeledData | TaintTrace,
) -> LabeledData:
    combined = propagate_taint(value, *sources)
    origin_material = "|".join(
        f"{item.source_kind}:{item.source_id}" for item in combined.provenance
    )
    digest = hashlib.sha256(origin_material.encode()).hexdigest()
    return LabeledData(
        value=value,
        label=dominant_label(combined),
        provenance=Provenance(
            source_id=digest,
            source_kind="derived",
            checksum=digest,
        ),
        sensitive=combined.sensitive,
    )

