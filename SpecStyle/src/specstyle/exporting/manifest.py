"""EXP-001A export input models, invariants, routing, and canonical documents.

Frozen by sections 13.1 through 13.10 and 13.12. This module defines the
public input types ``CreditRole``, ``AssetCredit``, ``ExportItem``,
``ExportCohort``, and ``ExportRequest``, plus the package-private
``_PreparedFile``, ``_PreparedExport``, and ``_prepare_export``. All generation
is in memory, with no filesystem, network, environment capture, model call, or
verifier rerun.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.enums import ArtifactStatus
from specstyle.domain.identifiers import JobId, Sha256
from specstyle.errors import DomainError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.environment import (
    EnvironmentSnapshot,
    dump_environment_json,
    hash_environment,
)
from specstyle.observability.hashing import hash_bytes
from specstyle.repair.history import RepairHistory
from specstyle.repair.loop import RepairTerminal
from specstyle.spec.compiled_models import (
    CompiledStyleSpec,
    CompiledVerificationPlan,
    OutputProfile,
)
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import VerificationReport

from specstyle.exporting import qa_report as _qa

CreditRole = Literal["input", "style_reference"]
_OUTPUT_RANK = ("xhs_grid", "talking_head_cover", "background_sequence")
_CONTROL_CHARS = set(range(32)) | {127}
_PROVENANCE_FIELDS = ("source_url", "license", "attribution", "consent")


def _invalid_request() -> None:
    raise DomainError("invalid export request") from None


def _invariant_violation() -> None:
    raise DomainError("export invariant violation") from None


# --------------------------------------------------------------------------- #
# Routing (§13.10)
# --------------------------------------------------------------------------- #


def _leaf(artifact_id: str, sequence_index: int | None, output_profile: str) -> str:
    if output_profile == "background_sequence":
        if type(sequence_index) is not int:
            _invariant_violation()
        return f"{sequence_index:06d}_{artifact_id}.png"
    if sequence_index is not None:
        _invariant_violation()
    return f"{artifact_id}.png"


def _relative_path(
    status: ArtifactStatus,
    output_profile: str,
    input_asset_id: str,
    leaf: str,
) -> str:
    if status is ArtifactStatus.APPROVED:
        return f"approved/{output_profile}/{leaf}"
    if status is ArtifactStatus.REJECTED:
        return f"rejected/{input_asset_id}/{leaf}"
    return f"manual_review/{input_asset_id}/{leaf}"


def _plan_for(
    compiled: CompiledStyleSpec, output_profile: str
) -> CompiledVerificationPlan:
    plans = tuple(
        plan
        for plan in compiled.verification_plans
        if plan.output_profile == output_profile
    )
    if len(plans) != 1:
        _invalid_request()
    return plans[0]


def _all_requests(history: RepairHistory) -> tuple[GenerationRequest, ...]:
    initial = history.initial_attempt.request
    return (initial, *(attempt.request for attempt in history.repair_attempts))


# --------------------------------------------------------------------------- #
# Input models
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AssetCredit:
    asset: AssetRef
    roles: tuple[CreditRole, ...]
    source_url: str | None
    license: str | None
    attribution: str | None
    consent: Literal["not_applicable", "obtained"] | None

    def __post_init__(self) -> None:
        try:
            asset = _qa.rebuild_asset_ref(self.asset)
            roles = self._validate_roles()
            source_url = self._validate_url()
            license_ = self._validate_text(self.license)
            attribution = self._validate_text(self.attribution)
            consent = self._validate_consent()
        except DomainError:
            raise
        except Exception:
            _invalid_request()
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "license", license_)
        object.__setattr__(self, "attribution", attribution)
        object.__setattr__(self, "consent", consent)

    def _validate_roles(self) -> tuple[CreditRole, ...]:
        if type(self.roles) is not tuple or not self.roles:
            _invalid_request()
        rebuilt: list[CreditRole] = []
        for role in self.roles:
            if type(role) is not str or role not in _CREDIT_ROLE_ORDER:
                _invalid_request()
            if role in rebuilt:
                _invalid_request()
            rebuilt.append(role)  # type: ignore[arg-type]
        if rebuilt != [r for r in _CREDIT_ROLE_ORDER if r in rebuilt]:
            _invalid_request()
        return tuple(rebuilt)

    def _validate_text(self, value: object) -> str | None:
        if value is None:
            return None
        if type(value) is not str or not 1 <= len(value) <= 2048:
            _invalid_request()
        if value != value.strip() or any(ord(c) in _CONTROL_CHARS for c in value):
            _invalid_request()
        return value

    def _validate_url(self) -> str | None:
        value = self.source_url
        if value is None:
            return None
        if type(value) is not str or not 1 <= len(value) <= 2083:
            _invalid_request()
        if value != value.strip() or any(c.isspace() for c in value):
            _invalid_request()
        if any(ord(c) in _CONTROL_CHARS for c in value):
            _invalid_request()
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            _invalid_request()
        if parts.username or parts.password or parts.query or parts.fragment:
            _invalid_request()
        return value

    def _validate_consent(self) -> Literal["not_applicable", "obtained"] | None:
        value = self.consent
        if value is None:
            return None
        if type(value) is not str or value not in ("not_applicable", "obtained"):
            _invalid_request()
        return value  # type: ignore[return-value]

    @property
    def identity(self) -> tuple[str, str]:
        return (self.asset.asset_id.value, self.asset.sha256.value)

    @property
    def provenance_status(self) -> str:
        fields = (
            self.source_url,
            self.license,
            self.attribution,
            self.consent,
        )
        non_none = sum(1 for f in fields if f is not None)
        if non_none == 4:
            return "COMPLETE"
        if non_none == 0:
            return "MISSING"
        return "INCOMPLETE"

    @property
    def missing_fields(self) -> list[str]:
        pairs = zip(
            _PROVENANCE_FIELDS,
            (self.source_url, self.license, self.attribution, self.consent),
        )
        return [name for name, value in pairs if value is None]


_CREDIT_ROLE_ORDER = ("input", "style_reference")


@dataclass(frozen=True, slots=True)
class ExportItem:
    history: RepairHistory
    terminal: RepairTerminal
    sequence_index: int | None

    def __post_init__(self) -> None:
        history = _qa.rebuild_repair_history(self.history)
        terminal = _qa.rebuild_repair_terminal(self.terminal)
        if type(self.sequence_index) is bool or (
            self.sequence_index is not None and type(self.sequence_index) is not int
        ):
            _invalid_request()
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "terminal", terminal)


@dataclass(frozen=True, slots=True)
class ExportCohort:
    output_profile: OutputProfile
    final_report: VerificationReport
    items: tuple[ExportItem, ...]

    def __post_init__(self) -> None:
        if (
            type(self.output_profile) is not str
            or self.output_profile not in _OUTPUT_RANK
        ):
            _invalid_request()
        if type(self.items) is not tuple or not self.items:
            _invalid_request()
        items = tuple(
            ExportItem(item.history, item.terminal, item.sequence_index)
            for item in self.items
        )
        final_report = _qa.rebuild_verification_report(self.final_report)
        compiled = _qa.rebuild_compiled_spec(
            items[0].history.current_request.compiled_spec
        )
        plan = _plan_for(compiled, self.output_profile)
        self._validate_cohort(items, final_report, compiled, plan)
        object.__setattr__(self, "output_profile", self.output_profile)
        object.__setattr__(self, "final_report", final_report)
        object.__setattr__(self, "items", items)

    def _validate_cohort(
        self,
        items: tuple[ExportItem, ...],
        final_report: VerificationReport,
        compiled: CompiledStyleSpec,
        plan: CompiledVerificationPlan,
    ) -> None:
        # Item semantic order must match final_report.artifacts; do not call __eq__.
        current_refs = [item.history.current_artifact.ref for item in items]
        if _qa.canonical_material(tuple(current_refs)) != _qa.canonical_material(
            final_report.artifacts
        ):
            _invariant_violation()
        # current_artifact.content supplies bytes for each current reference.
        for item in items:
            artifact = item.history.current_artifact
            if type(artifact) is not GeneratedArtifact:
                _invariant_violation()
            if hash_bytes(artifact.content) != artifact.ref.sha256:
                _invariant_violation()
        # Rules exactly match applicable compiled definitions, regardless of order.
        applicable = plan.applicable_rule_definitions
        if {_qa.canonical_material(rule) for rule in final_report.rules} != {
            _qa.canonical_material(rule) for rule in applicable
        }:
            _invariant_violation()
        # sequence_index per profile + terminal artifact ID == current artifact ID
        self._validate_sequence_and_terminals(items)
        # Replay decide_artifact routing; v1 rejects accepted_with_override=True.
        for item in items:
            decision = item.terminal.artifact_decision
            if decision.accepted_with_override:
                _invariant_violation()
            if decision.repair_stop_reason is None:
                _invariant_violation()
            replayed = decide_artifact(
                final_report,
                item.history.current_target_artifact_id,
                repair_stop_reason=decision.repair_stop_reason,
                accepted_with_override=decision.accepted_with_override,
            )
            if _qa.canonical_material(replayed) != _qa.canonical_material(decision):
                _invariant_violation()

    def _validate_sequence_and_terminals(self, items: tuple[ExportItem, ...]) -> None:
        if self.output_profile == "background_sequence":
            for index, item in enumerate(items):
                if item.sequence_index != index:
                    _invariant_violation()
                if (
                    item.terminal.artifact_decision.artifact_id
                    != item.history.current_target_artifact_id
                ):
                    _invariant_violation()
        else:
            for item in items:
                if item.sequence_index is not None:
                    _invariant_violation()
                if (
                    item.terminal.artifact_decision.artifact_id
                    != item.history.current_target_artifact_id
                ):
                    _invariant_violation()


@dataclass(frozen=True, slots=True)
class ExportRequest:
    cohorts: tuple[ExportCohort, ...]
    environment: EnvironmentSnapshot
    asset_credits: tuple[AssetCredit, ...]

    def __post_init__(self) -> None:
        if (
            type(self.cohorts) is not tuple
            or not self.cohorts
            or type(self.asset_credits) is not tuple
            or not self.asset_credits
        ):
            _invalid_request()
        cohorts = tuple(
            ExportCohort(c.output_profile, c.final_report, c.items)
            for c in self.cohorts
        )
        environment = _qa.rebuild_environment(self.environment)
        credits = tuple(
            AssetCredit(
                c.asset, c.roles, c.source_url, c.license, c.attribution, c.consent
            )
            for c in self.asset_credits
        )
        self._validate_cohort_order(cohorts)
        compiled = _qa.rebuild_compiled_spec(
            cohorts[0].items[0].history.current_request.compiled_spec
        )
        self._validate_request_invariants(cohorts, environment, compiled)
        self._validate_credits(cohorts, credits, compiled)
        object.__setattr__(self, "cohorts", cohorts)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "asset_credits", credits)

    def _validate_cohort_order(self, cohorts: tuple[ExportCohort, ...]) -> None:
        ranks = [_OUTPUT_RANK.index(c.output_profile) for c in cohorts]
        if ranks != sorted(ranks) or len(set(ranks)) != len(ranks):
            _invalid_request()

    def _validate_request_invariants(
        self,
        cohorts: tuple[ExportCohort, ...],
        environment: EnvironmentSnapshot,
        compiled: CompiledStyleSpec,
    ) -> None:
        env_hash = hash_environment(environment)
        job_id: JobId | None = None
        for cohort in cohorts:
            for item in cohort.items:
                for request in _all_requests(item.history):
                    if request.generation_profile != "production":
                        _invalid_request()
                    if request.environment_hash != env_hash:
                        _invalid_request()
                    if job_id is None:
                        job_id = request.job_id
                    elif request.job_id != job_id:
                        _invalid_request()
                    spec = _qa.rebuild_compiled_spec(request.compiled_spec)
                    if _qa.canonical_material(spec) != _qa.canonical_material(compiled):
                        _invalid_request()
                    if spec.compiled_spec_hash != compiled.compiled_spec_hash:
                        _invalid_request()

    def _validate_credits(
        self,
        cohorts: tuple[ExportCohort, ...],
        credits: tuple[AssetCredit, ...],
        compiled: CompiledStyleSpec,
    ) -> None:
        derived = self._derive_credits(cohorts)
        identities = [c.identity for c in credits]
        if identities != sorted(identities):
            _invalid_request()
        if len(set(identities)) != len(identities):
            _invalid_request()
        if set(identities) != set(derived):
            _invalid_request()
        asset_to_shas: dict[str, set[str]] = {}
        for asset_id, sha256 in derived:
            asset_to_shas.setdefault(asset_id, set()).add(sha256)
        if any(len(shas) > 1 for shas in asset_to_shas.values()):
            _invalid_request()
        for credit in credits:
            if credit.roles != derived[credit.identity]:
                _invalid_request()
        self._validate_style_provenance(cohorts, credits, compiled)

    def _derive_credits(
        self, cohorts: tuple[ExportCohort, ...]
    ) -> dict[tuple[str, str], tuple[str, ...]]:
        derived: dict[tuple[str, str], list[str]] = {}
        for cohort in cohorts:
            for item in cohort.items:
                for request in _all_requests(item.history):
                    self._collect(derived, request.source.source, "input")
                    for ref in request.style_references:
                        self._collect(derived, ref, "style_reference")
        return {
            key: tuple(r for r in _CREDIT_ROLE_ORDER if r in roles)
            for key, roles in derived.items()
        }

    @staticmethod
    def _collect(
        derived: dict[tuple[str, str], list[str]], ref: AssetRef, role: str
    ) -> None:
        key = (ref.asset_id.value, ref.sha256.value)
        if role not in derived.setdefault(key, []):
            derived[key].append(role)

    def _validate_style_provenance(
        self,
        cohorts: tuple[ExportCohort, ...],
        credits: tuple[AssetCredit, ...],
        compiled: CompiledStyleSpec | None,
    ) -> None:
        spec = compiled.source_spec  # type: ignore[union-attr]
        references = spec.assets.style_references
        credit_by_identity = {c.identity: c for c in credits}
        for cohort in cohorts:
            for item in cohort.items:
                request = item.history.initial_attempt.request
                refs = request.style_references
                if type(refs) is not tuple or len(refs) != len(references):
                    _invalid_request()
                for index, ref in enumerate(refs):
                    if ref.sha256.value != references[index].asset_sha256:
                        _invalid_request()
                    credit = credit_by_identity.get(
                        (ref.asset_id.value, ref.sha256.value)
                    )
                    if credit is None or "style_reference" not in credit.roles:
                        continue
                    expected = (
                        references[index].source_url,
                        references[index].license,
                        references[index].attribution,
                        references[index].consent,
                    )
                    actual = (
                        credit.source_url,
                        credit.license,
                        credit.attribution,
                        credit.consent,
                    )
                    if expected != actual:
                        _invalid_request()


# --------------------------------------------------------------------------- #
# Prepared export (package-private ABI)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _PreparedFile:
    relative_path: str
    content: bytes
    sha256: Sha256
    size_bytes: int

    def __post_init__(self) -> None:
        if (
            type(self.relative_path) is not str
            or type(self.content) is not bytes
            or type(self.size_bytes) is not int
            or isinstance(self.size_bytes, bool)
        ):
            _invariant_violation()
        if self.sha256 != hash_bytes(self.content) or self.size_bytes != len(
            self.content
        ):
            _invariant_violation()


@dataclass(frozen=True, slots=True)
class _PreparedExport:
    payload_files: tuple[_PreparedFile, ...]
    manifest_file: _PreparedFile
    payload_sha256: Sha256
    bundle_sha256: Sha256

    def __post_init__(self) -> None:
        if type(self.payload_files) is not tuple or not self.payload_files:
            _invariant_violation()
        paths = [f.relative_path for f in self.payload_files]
        if paths != sorted(paths) or len(set(paths)) != len(paths):
            _invariant_violation()
        if any(f.relative_path == _qa.MANIFEST_PATH for f in self.payload_files):
            _invariant_violation()
        if self.manifest_file.relative_path != _qa.MANIFEST_PATH:
            _invariant_violation()


def _style_spec_bytes(compiled: CompiledStyleSpec) -> bytes:
    primitive = compiled.source_spec.model_dump(mode="json", round_trip=True)
    return _qa.canonical_json_bytes(primitive)


def _style_spec_meta(
    compiled: CompiledStyleSpec, prepared_bytes: bytes
) -> dict[str, Any]:
    encoder = compiled.l2_encoder
    return {
        "compiled_spec_sha256": compiled.compiled_spec_hash.value,
        "compiler_pin": _qa.pin_primitive(compiled.compiler_pin),
        "l2_encoder": {
            "distance_function": encoder.distance_function,
            "layer": encoder.layer,
            "pin": _qa.pin_primitive(encoder.pin),
            "preprocessing_version": encoder.preprocessing_version,
        },
        "path": _qa.STYLE_SPEC_PATH,
        "ruleset_pin": _qa.pin_primitive(compiled.ruleset_pin),
        "schema_version": compiled.source_spec.schema_version,
        "sha256": hash_bytes(prepared_bytes).value,
        "spec_id": compiled.source_spec.metadata.spec_id,
    }


def _environment_meta(
    environment: EnvironmentSnapshot, prepared_bytes: bytes
) -> dict[str, Any]:
    return {
        "path": _qa.ENVIRONMENT_PATH,
        "schema_version": environment.schema_version,
        "sha256": hash_bytes(prepared_bytes).value,
    }


def _asset_credits_primitive(credits: tuple[AssetCredit, ...]) -> dict[str, Any]:
    entries = []
    for credit in credits:
        entries.append(
            {
                "asset": _qa.asset_ref_primitive(credit.asset),
                "attribution": credit.attribution,
                "consent": credit.consent,
                "license": credit.license,
                "missing_fields": credit.missing_fields,
                "provenance_status": credit.provenance_status,
                "roles": list(credit.roles),
                "source_url": credit.source_url,
            }
        )
    return {
        "assets": entries,
        "complete": all(c.provenance_status == "COMPLETE" for c in credits),
        "schema_version": _qa.ASSET_CREDITS_SCHEMA_VERSION,
    }


def _cohort_primitive(
    cohort: ExportCohort, compiled: CompiledStyleSpec
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = _plan_for(compiled, cohort.output_profile)
    items = []
    qa_items = []
    for item in cohort.items:
        artifact = item.history.current_artifact
        status = item.terminal.artifact_decision.artifact_status
        input_asset_id = (
            item.history.initial_attempt.request.source.source.asset_id.value
        )
        leaf = _leaf(
            artifact.ref.artifact_id.value, item.sequence_index, cohort.output_profile
        )
        relative_path = _relative_path(
            status, cohort.output_profile, input_asset_id, leaf
        )
        item_primitive = _qa.manifest_item_primitive(
            history=item.history,
            terminal=item.terminal,
            sequence_index=item.sequence_index,
            output_profile=cohort.output_profile,
            plan=plan,
            relative_path=relative_path,
            content_size=len(artifact.content),
            artifact_sha256=artifact.ref.sha256,
        )
        items.append(item_primitive)
        qa_items.append(
            {
                "artifact_id": artifact.ref.artifact_id.value,
                "initial_report": _qa.report_primitive(
                    item.history.initial_attempt.report, plan
                ),
                "repair_reports": [
                    _qa.report_primitive(attempt.report, plan)
                    for attempt in item.history.repair_attempts
                ],
                "sequence_index": item.sequence_index,
            }
        )
    final_report = _qa.report_primitive(cohort.final_report, plan)
    cohort_primitive = {
        "final_report": final_report,
        "items": items,
        "output_profile": cohort.output_profile,
        "verification_plan": _qa.verification_plan_primitive(plan),
    }
    qa_cohort = {
        "final_report": final_report,
        "items": qa_items,
        "output_profile": cohort.output_profile,
        "verification_plan": _qa.verification_plan_primitive(plan),
    }
    return cohort_primitive, qa_cohort


def _prepare_export(request: ExportRequest) -> _PreparedExport:
    """Build canonical documents and payload, manifest, and bundle digests in memory."""
    compiled = _qa.rebuild_compiled_spec(
        request.cohorts[0].items[0].history.current_request.compiled_spec
    )
    job_id = request.cohorts[0].items[0].history.initial_attempt.request.job_id.value

    style_bytes = _style_spec_bytes(compiled)
    environment_bytes = dump_environment_json(request.environment).encode("utf-8")
    credits_primitive = _asset_credits_primitive(request.asset_credits)
    credits_bytes = _qa.canonical_json_bytes(credits_primitive)

    cohort_primitives: list[dict[str, Any]] = []
    qa_cohorts: list[dict[str, Any]] = []
    artifact_files: list[_PreparedFile] = []
    seen_paths: set[str] = set()
    seen_artifact_ids: set[str] = set()
    for cohort in request.cohorts:
        manifest_cohort, qa_cohort = _cohort_primitive(cohort, compiled)
        cohort_primitives.append(manifest_cohort)
        qa_cohorts.append(qa_cohort)
        for item in cohort.items:
            artifact = item.history.current_artifact
            status = item.terminal.artifact_decision.artifact_status
            input_asset_id = (
                item.history.initial_attempt.request.source.source.asset_id.value
            )
            leaf = _leaf(
                artifact.ref.artifact_id.value,
                item.sequence_index,
                cohort.output_profile,
            )
            path = _relative_path(status, cohort.output_profile, input_asset_id, leaf)
            if (
                path in seen_paths
                or artifact.ref.artifact_id.value in seen_artifact_ids
            ):
                _invariant_violation()
            seen_paths.add(path)
            seen_artifact_ids.add(artifact.ref.artifact_id.value)
            artifact_files.append(
                _PreparedFile(
                    path, artifact.content, artifact.ref.sha256, len(artifact.content)
                )
            )

    spec_meta = _style_spec_meta(compiled, style_bytes)
    if spec_meta["sha256"] != hash_bytes(style_bytes).value:
        _invariant_violation()
    environment_meta = _environment_meta(request.environment, environment_bytes)
    if environment_meta["sha256"] != hash_bytes(environment_bytes).value:
        _invariant_violation()

    qa_spec = {
        "compiled_spec_sha256": compiled.compiled_spec_hash.value,
        "schema_version": compiled.source_spec.schema_version,
        "spec_id": compiled.source_spec.metadata.spec_id,
    }
    qa_primitive = _qa.build_qa_report(spec=qa_spec, cohorts=qa_cohorts, job_id=job_id)
    qa_bytes = _qa.canonical_json_bytes(qa_primitive)

    sidecars = [
        _PreparedFile(
            _qa.STYLE_SPEC_PATH, style_bytes, hash_bytes(style_bytes), len(style_bytes)
        ),
        _PreparedFile(
            _qa.ENVIRONMENT_PATH,
            environment_bytes,
            hash_bytes(environment_bytes),
            len(environment_bytes),
        ),
        _PreparedFile(
            _qa.ASSET_CREDITS_PATH,
            credits_bytes,
            hash_bytes(credits_bytes),
            len(credits_bytes),
        ),
        _PreparedFile(
            _qa.QA_REPORT_PATH, qa_bytes, hash_bytes(qa_bytes), len(qa_bytes)
        ),
    ]
    payload_files = tuple(
        sorted(sidecars + artifact_files, key=lambda f: f.relative_path)
    )

    file_entries = [
        _qa.file_entry(f.relative_path, f.sha256, f.size_bytes) for f in payload_files
    ]
    payload_material = {"domain": _qa.PAYLOAD_DOMAIN, "files": file_entries}
    payload_sha256 = hash_bytes(_qa.canonical_json_bytes(payload_material))

    manifest_primitive = {
        "asset_credits": {
            "complete": credits_primitive["complete"],
            "path": _qa.ASSET_CREDITS_PATH,
            "schema_version": _qa.ASSET_CREDITS_SCHEMA_VERSION,
            "sha256": hash_bytes(credits_bytes).value,
        },
        "cohorts": cohort_primitives,
        "environment": environment_meta,
        "files": file_entries,
        "job_id": job_id,
        "payload_sha256": payload_sha256.value,
        "qa_report": {
            "path": _qa.QA_REPORT_PATH,
            "schema_version": _qa.QA_REPORT_SCHEMA_VERSION,
            "sha256": hash_bytes(qa_bytes).value,
        },
        "schema_version": _qa.MANIFEST_SCHEMA_VERSION,
        "style_spec": spec_meta,
    }
    manifest_bytes = _qa.canonical_json_bytes(manifest_primitive)
    manifest_sha256 = hash_bytes(manifest_bytes)
    bundle_material = {
        "domain": _qa.BUNDLE_DOMAIN,
        "manifest_sha256": manifest_sha256.value,
        "payload_sha256": payload_sha256.value,
    }
    bundle_sha256 = hash_bytes(_qa.canonical_json_bytes(bundle_material))

    # Section 13.9 readback: each canonical document must re-dump identically.
    for prepared in (*payload_files,):
        if prepared.relative_path.endswith((".json", ".yaml")):
            _qa.assert_canonical_round_trip(prepared.content)
    _qa.assert_canonical_round_trip(manifest_bytes)

    manifest_file = _PreparedFile(
        _qa.MANIFEST_PATH, manifest_bytes, manifest_sha256, len(manifest_bytes)
    )
    return _PreparedExport(payload_files, manifest_file, payload_sha256, bundle_sha256)
