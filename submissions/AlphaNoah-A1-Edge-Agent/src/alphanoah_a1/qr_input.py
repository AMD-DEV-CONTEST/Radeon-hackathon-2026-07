"""Validated QR-form input adapter for local incident-reporting demos."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .exceptions import InvalidEventInput
from .models import Event
from .runtime import AlphaNoahRuntime

DEFAULT_EVENT_TYPE = "equipment_issue_report"
ALLOWED_FORM_FIELDS = frozenset(
    {
        "asset_id",
        "location",
        "event_type",
        "reporter",
        "description",
        "attachments",
    }
)
ALLOWED_PREFILL_FIELDS = frozenset({"asset_id", "location"})
FIELD_LIMITS = {
    "asset_id": 128,
    "location": 200,
    "event_type": 64,
    "reporter": 128,
    "description": 2000,
    "attachments": 512,
}
MAX_ATTACHMENT_REFERENCES = 5
EVENT_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")


class IncidentReportInputError(ValueError):
    """Raised when a QR incident form does not meet the adapter contract."""


class QRIncidentInputAdapter:
    """Convert a bounded form payload into the existing AlphaNoah Event."""

    source = "qr_incident_report"
    actor = "system:qr-incident-input-adapter"
    raw_input_ref = "local://qr-incident-report/form"
    input_adapter_id = "qr_incident_report_v1"

    def __init__(
        self,
        runtime: AlphaNoahRuntime,
        *,
        trusted_metadata: Mapping[str, Any] | None = None,
    ):
        self.runtime = runtime
        metadata = dict(trusted_metadata or {})
        if any(not isinstance(key, str) for key in metadata):
            raise ValueError("trusted metadata keys must be strings")
        try:
            self.trusted_metadata = json.loads(
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError(
                "trusted metadata must be JSON serializable"
            ) from exc

    def validate_prefill(
        self, query_fields: Mapping[str, object]
    ) -> dict[str, str]:
        unknown = set(query_fields) - ALLOWED_PREFILL_FIELDS
        if unknown:
            raise IncidentReportInputError(
                "Only asset_id and location may be prefilled."
            )
        values = {
            name: self._single_value(query_fields, name)
            for name in ALLOWED_PREFILL_FIELDS
        }
        self._validate_length("asset_id", values["asset_id"])
        self._validate_length("location", values["location"])
        return values

    def validate_form(
        self, form_fields: Mapping[str, object]
    ) -> dict[str, Any]:
        unknown = set(form_fields) - ALLOWED_FORM_FIELDS
        if unknown:
            raise IncidentReportInputError(
                "The form contains unknown or forbidden fields."
            )

        values = {
            name: self._single_value(
                form_fields,
                name,
                DEFAULT_EVENT_TYPE if name == "event_type" else "",
            )
            for name in ALLOWED_FORM_FIELDS
        }
        for name, value in values.items():
            self._validate_length(name, value)

        if not values["description"]:
            raise IncidentReportInputError("description is required.")
        if EVENT_TYPE_PATTERN.fullmatch(values["event_type"]) is None:
            raise IncidentReportInputError(
                "event_type must be a non-empty snake_case string."
            )

        attachment_references = [
            reference.strip()
            for reference in values["attachments"]
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .split("\n")
            if reference.strip()
        ]
        if len(attachment_references) > MAX_ATTACHMENT_REFERENCES:
            raise IncidentReportInputError(
                "Too many attachment references were submitted."
            )

        return {
            "event_type": values["event_type"],
            "asset_id": values["asset_id"],
            "location": values["location"],
            "reporter": values["reporter"],
            "description": values["description"],
            "attachments": attachment_references,
        }

    def submit(self, form_fields: Mapping[str, object]) -> Event:
        validated = self.validate_form(form_fields)
        try:
            return self.runtime.create_event(
                event_type=validated["event_type"],
                source=self.source,
                actor=self.actor,
                raw_input_ref=self.raw_input_ref,
                location=validated["location"],
                asset_id=validated["asset_id"],
                reporter=validated["reporter"],
                description=validated["description"],
                attachments=validated["attachments"],
                metadata={
                    **self.trusted_metadata,
                    "data_classification": "Synthetic demo data",
                    "incident_notice": "Not a real production incident",
                    "input_adapter": self.input_adapter_id,
                },
            )
        except InvalidEventInput as exc:
            raise IncidentReportInputError(
                "The Runtime rejected the incident input."
            ) from exc

    @staticmethod
    def _single_value(
        fields: Mapping[str, object],
        name: str,
        default: str = "",
    ) -> str:
        raw_value = fields.get(name, default)
        if isinstance(raw_value, str):
            return raw_value.strip()
        if (
            isinstance(raw_value, list)
            and len(raw_value) == 1
            and isinstance(raw_value[0], str)
        ):
            return raw_value[0].strip()
        raise IncidentReportInputError(
            f"{name} must be submitted exactly once as text."
        )

    @staticmethod
    def _validate_length(name: str, value: str) -> None:
        if len(value) > FIELD_LIMITS[name]:
            raise IncidentReportInputError(
                f"{name} exceeds the {FIELD_LIMITS[name]} character limit."
            )
