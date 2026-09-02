from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from shared_contracts import (
    ImplementationManifest,
    OperationRequest,
    OperationSpec,
    SchemaRevision,
)

from .upcasting import UpcasterRegistry, UpcasterSnapshot


class CompatibilityIssueCode(StrEnum):
    OP_TYPE_MISMATCH = "op_type_mismatch"
    OP_VERSION_INCOMPATIBLE = "op_version_incompatible"
    SPEC_DIGEST_MISMATCH = "spec_digest_mismatch"
    INPUT_SCHEMA_INCOMPATIBLE = "input_schema_incompatible"
    OUTPUT_SCHEMA_INCOMPATIBLE = "output_schema_incompatible"


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    code: CompatibilityIssueCode
    message: str
    requested: object | None = None
    available: object | None = None


@dataclass(frozen=True, slots=True)
class CompatibilityOperationKey:
    op_type: str
    op_version: SchemaRevision
    spec_digest: str
    implementation_digest: str | None


@dataclass(frozen=True, slots=True)
class UpcastEndpoint:
    contract_name: str
    source_revision: SchemaRevision
    target_revision: SchemaRevision


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    compatible: bool
    issues: tuple[CompatibilityIssue, ...]
    input_upcast_required: bool
    requested_key: CompatibilityOperationKey | None = None
    available_key: CompatibilityOperationKey | None = None
    input_upcast_endpoint: UpcastEndpoint | None = None

    def require_compatible(self) -> None:
        if not self.compatible:
            raise IncompatibleOperationError(self)


class IncompatibleOperationError(ValueError):
    def __init__(self, report: CompatibilityReport) -> None:
        self.report = report
        super().__init__("; ".join(issue.message for issue in report.issues))


def revision_satisfies(
    available: SchemaRevision,
    required: SchemaRevision,
) -> bool:
    """Whether a strict reader can consume the exact available wire schema."""

    return available == required


def check_request_compatibility(
    spec: OperationSpec,
    request: OperationRequest,
    *,
    upcasters: UpcasterRegistry | UpcasterSnapshot | None = None,
    implementation_manifest: ImplementationManifest | None = None,
) -> CompatibilityReport:
    issues: list[CompatibilityIssue] = []
    if spec.op_type != request.op_type:
        issues.append(
            CompatibilityIssue(
                CompatibilityIssueCode.OP_TYPE_MISMATCH,
                f"requested {request.op_type}, available {spec.op_type}",
                requested=request.op_type,
                available=spec.op_type,
            )
        )
    if spec.op_version != request.op_version:
        issues.append(
            CompatibilityIssue(
                CompatibilityIssueCode.OP_VERSION_INCOMPATIBLE,
                "operation revision must match the immutable registered spec exactly",
                requested=request.op_version,
                available=spec.op_version,
            )
        )
    if spec.spec_digest != request.operation_spec_digest:
        issues.append(
            CompatibilityIssue(
                CompatibilityIssueCode.SPEC_DIGEST_MISMATCH,
                "operation spec digest does not match the requested immutable spec",
                requested=request.operation_spec_digest,
                available=spec.spec_digest,
            )
        )

    input_upcast_required = request.input_schema_version != spec.input_schema_version
    input_upcast_endpoint = (
        UpcastEndpoint(
            contract_name=f"{request.op_type}:input",
            source_revision=request.input_schema_version,
            target_revision=spec.input_schema_version,
        )
        if input_upcast_required
        else None
    )
    if input_upcast_required:
        contract_name = input_upcast_endpoint.contract_name
        can_upcast = (
            upcasters is not None
            and upcasters.can_upcast(
                contract_name,
                request.input_schema_version,
                spec.input_schema_version,
            )
        )
        if not can_upcast:
            issues.append(
                CompatibilityIssue(
                    CompatibilityIssueCode.INPUT_SCHEMA_INCOMPATIBLE,
                    "input schema differs and no complete sequential upcaster exists",
                    requested=input_upcast_endpoint.source_revision,
                    available=input_upcast_endpoint.target_revision,
                )
            )

    if not revision_satisfies(
        spec.output_schema_version,
        request.required_output_schema_version,
    ):
        issues.append(
            CompatibilityIssue(
                CompatibilityIssueCode.OUTPUT_SCHEMA_INCOMPATIBLE,
                "available output schema cannot satisfy the required reader",
                requested=request.required_output_schema_version,
                available=spec.output_schema_version,
            )
        )
    return CompatibilityReport(
        compatible=not issues,
        issues=tuple(issues),
        input_upcast_required=input_upcast_required,
        requested_key=CompatibilityOperationKey(
            op_type=request.op_type,
            op_version=request.op_version,
            spec_digest=request.operation_spec_digest,
            implementation_digest=request.implementation_digest,
        ),
        available_key=CompatibilityOperationKey(
            op_type=spec.op_type,
            op_version=spec.op_version,
            spec_digest=spec.spec_digest,
            implementation_digest=(
                implementation_manifest.implementation_digest
                if implementation_manifest is not None
                else None
            ),
        ),
        input_upcast_endpoint=input_upcast_endpoint,
    )
