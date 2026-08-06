"""Forward-only AMD deployment control plane.

``AmdAiDeploymentService`` coordinates durable installation intent, immutable
recipes, placement realization, capability-owned projections, and the private
runtime gate.  It is intentionally absent from every inference request path:
LLM, Embedding, and OCR adapters resolve only their exact runtime key.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Session

from ..storage.models import AmdComponentGenerationRow, AmdInstallationRow, AmdTargetEnrollmentRow
from ..storage.repositories.amd_installations import AmdInstallationRepository
from .compatibility import CompatibilityDecision, CompatibilityPlanner
from .manifests import (
    ExecutionProfileManifest,
    ExecutionProfilePlacement,
    ManifestCapability,
    ManifestCatalog,
)
from .participants import AmdComponentParticipant, AmdParticipantError, AmdProjectionStatus
from .placement import (
    AmdExecutionSession,
    AmdMaterializationCancelledError,
    AmdPlacementError,
    AmdRuntimeKey,
)
from .progress import AmdProgressMilestone, AmdProgressSink, report_progress
from .reconcile import AmdExecutionLocation, AmdGenerationMaterialization, AmdPlacementController
from .runtime import (
    AmdRuntimeBusyError,
    AmdRuntimeDirectory,
    AmdRuntimeError,
    AmdRuntimeRetiringError,
    AmdRuntimeUnavailableError,
)
from .status import AmdComponentStatus, AmdInstallationCondition, AmdInstallationStatus


class AmdDeploymentError(RuntimeError):
    """A bounded deployment-control-plane failure safe for UI projection."""

    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class AmdDeploymentNotFoundError(AmdDeploymentError):
    def __init__(self) -> None:
        super().__init__("AMD installation was not found.", error_code="amd_installation_not_found")


class AmdDeploymentPlacementError(AmdDeploymentError):
    def __init__(self) -> None:
        super().__init__("The selected AMD placement is unavailable.", error_code="amd_placement_unavailable")


class AmdDeploymentProfileError(AmdDeploymentError):
    def __init__(self) -> None:
        super().__init__("The selected AMD profile is unavailable.", error_code="amd_profile_unavailable")


@dataclass(frozen=True, slots=True)
class AmdRetirementRequest:
    """Immediate acknowledgement of a durably committed Remove request.

    This is intentionally not an installation status.  A status read may wait
    behind an active long-running materialization, whereas this acknowledgement
    is returned only after desired absence has committed locally.
    """

    installation_id: str
    phase: str


@dataclass(slots=True)
class _MaterializationControl:
    """Volatile revocation signal owned by one in-flight materialization."""

    cancellation: threading.Event
    finished: threading.Event


@dataclass(frozen=True, slots=True)
class _RetirementCancellationPlan:
    """In-memory exact work needed after durable retirement has committed."""

    installation_id: str
    placement: AmdPlacementController
    location: AmdExecutionLocation
    profile: ExecutionProfileManifest
    generations: tuple[AmdGenerationMaterialization, ...]


_RETIRE_CANCELLATION_ATTEMPTS = 3
_RETIRE_CANCELLATION_RETRY_SECONDS = 0.25
_SHUTDOWN_QUIESCE_SECONDS = 8.0


@dataclass(frozen=True, slots=True)
class AmdInstallationSpec:
    """Immutable user intent for one Local or pre-enrolled Private deployment."""

    installation_id: str
    placement: str
    profile_digest: str
    target_id: str | None = None
    local_wsl_distribution: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.installation_id, "Installation ID")
        if self.placement not in {"local_linux", "local_wsl", "private_ssh"}:
            raise ValueError("AMD installation placement is unsupported.")
        _require_digest(self.profile_digest)
        if self.placement == "private_ssh" and not self.target_id:
            raise ValueError("Private SSH AMD installation requires an enrolled target.")
        if self.placement == "private_ssh" and self.local_wsl_distribution is not None:
            raise ValueError("Private SSH AMD installation cannot include a WSL distribution.")
        if self.placement == "local_wsl" and self.target_id is not None:
            raise ValueError("Local WSL AMD installation cannot include an SSH target.")
        if self.placement == "local_wsl" and self.local_wsl_distribution is None:
            raise ValueError("Local WSL AMD installation requires a distribution.")
        if self.placement == "local_linux" and (
            self.target_id is not None or self.local_wsl_distribution is not None
        ):
            raise ValueError("Local Linux AMD installation cannot include a target reference.")
        # The location constructor applies the shared target-shape validation
        # used by all operation controllers.
        AmdExecutionLocation(
            placement_kind=self.placement,
            private_target_id=self.target_id,
            local_wsl_distribution=self.local_wsl_distribution,
        )

    @property
    def location(self) -> AmdExecutionLocation:
        return AmdExecutionLocation(
            placement_kind=self.placement,
            private_target_id=self.target_id,
            local_wsl_distribution=self.local_wsl_distribution,
        )


@dataclass(frozen=True, slots=True)
class AmdPrivateTargetSpec:
    """Enrollment record with opaque local credential/trust references."""

    target_id: str
    host: str
    user: str
    port: int
    pinned_host_key: str
    identity_file_reference: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.target_id, "Target ID"),
            (self.host, "Target host"),
            (self.user, "Target user"),
            (self.pinned_host_key, "Pinned host key reference"),
            (self.identity_file_reference, "Identity-file reference"),
        ):
            _require_identifier(value, label)
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("Target SSH port is invalid.")


@dataclass(frozen=True, slots=True)
class AmdPrivateInstallationEnrollment:
    """Read-only durable identity needed by the guided Private SSH surface.

    Endpoint fields are user-authored enrollment facts, but they stay out of
    representations so accidental diagnostics cannot disclose them.
    """

    installation_id: str
    target_id: str
    host: str = field(repr=False)
    user: str = field(repr=False)
    port: int = field(repr=False)
    desired_presence: bool
    lifecycle_state: str

    def __post_init__(self) -> None:
        _require_identifier(self.installation_id, "Installation ID")
        _require_identifier(self.target_id, "Target ID")
        _require_identifier(self.host, "Target host")
        _require_identifier(self.user, "Target user")
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("Target SSH port is invalid.")


@dataclass(frozen=True, slots=True)
class AmdPrivateTargetEnrollment:
    """One reusable durable Private SSH target, independent of deployments."""

    target_id: str
    host: str = field(repr=False)
    user: str = field(repr=False)
    port: int = field(repr=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.target_id, "Target ID"),
            (self.host, "Target host"),
            (self.user, "Target user"),
        ):
            _require_identifier(value, label)
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("Target SSH port is invalid.")


@dataclass(frozen=True, slots=True)
class AmdInstallationInventoryItem:
    """Minimal durable lifecycle identity for restart/removal discovery."""

    installation_id: str
    placement: str
    desired_presence: bool
    lifecycle_state: str
    target_id: str | None = field(default=None, repr=False)
    local_wsl_distribution: str | None = field(default=None, repr=False)


class AmdAiDeploymentService:
    """Deep Radeon facade for AMD desired-state reconciliation.

    The service is deliberately synchronous and command-oriented.  UI workers
    own scheduling/cancellation, while each public command performs only a
    forward reconcile.  No prior settings snapshot is retained, no compensation
    is attempted, and capability selection is never changed.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        catalog: ManifestCatalog,
        placements: Mapping[str, AmdPlacementController],
        participants: Mapping[ManifestCapability, AmdComponentParticipant],
        runtime_directory: AmdRuntimeDirectory,
        repository: AmdInstallationRepository | None = None,
        new_installation_placements: frozenset[str] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._catalog = catalog
        self._planner = CompatibilityPlanner(catalog)
        self._placements = dict(placements)
        self._participants = dict(participants)
        self._runtime_directory = runtime_directory
        self._repository = repository or AmdInstallationRepository()
        self._new_installation_placements = (
            frozenset(self._placements)
            if new_installation_placements is None
            else frozenset(new_installation_placements)
        )
        if not self._new_installation_placements.issubset(self._placements):
            raise ValueError("AMD new-installation placement policy is invalid.")
        self._lock = threading.RLock()
        self._operation_gates_lock = threading.Lock()
        self._operation_gates: dict[tuple[str, str], threading.RLock] = {}
        # A reconcile can legitimately spend minutes provisioning a target.
        # Shutdown must not wait for that command lock before fencing access to
        # app-owned settings and storage, so volatile state has its own short
        # critical section.
        self._state_lock = threading.RLock()
        self._sessions: dict[str, AmdExecutionSession] = {}
        self._live_keys: set[AmdRuntimeKey] = set()
        self._compatibility_issues: dict[str, tuple[str, ...]] = {}
        self._target_observation_errors: dict[str, str] = {}
        self._materialization_controls: dict[str, _MaterializationControl] = {}
        self._retirement_cancellation_active: set[str] = set()
        self._retirement_workers: set[threading.Thread] = set()
        self._closed = False
        for capability in ManifestCapability:
            if capability not in self._participants:
                raise ValueError(f"AMD deployment is missing the {capability.value} capability participant.")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    @contextmanager
    def _database_session(self):
        """Fence one short storage operation against application shutdown."""

        with self._state_lock:
            self._require_open()
            with self._session_factory() as session:
                yield session

    def close(self) -> None:
        """Fence new work, revoke in-flight materialization, then close sessions.

        Desired presence remains durable.  Shutdown does not reinterpret a
        normal install as Remove, but it must not leave an unpublished session
        alive after the application has disposed its settings or SQLite owners.
        """

        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            controls = tuple(self._materialization_controls.values())
            for control in controls:
                control.cancellation.set()
            workers = tuple(self._retirement_workers)

        # Materialization is allowed a bounded opportunity to observe its
        # in-memory revocation.  A blocked target command may outlive desktop
        # shutdown, but its worker owns and closes any as-yet-unpublished
        # session in `_materialize_and_project`'s finalizer.
        remaining = _SHUTDOWN_QUIESCE_SECONDS
        for control in controls:
            if remaining <= 0:
                break
            started = datetime.now(UTC)
            control.finished.wait(remaining)
            remaining -= max(0.0, (datetime.now(UTC) - started).total_seconds())
        for worker in workers:
            if remaining <= 0 or worker is threading.current_thread():
                break
            started = datetime.now(UTC)
            worker.join(remaining)
            remaining -= max(0.0, (datetime.now(UTC) - started).total_seconds())

        with self._state_lock:
            sessions = tuple(self._sessions.items())
            live_keys = tuple(self._live_keys)
            self._sessions.clear()
            self._live_keys.clear()
            self._compatibility_issues.clear()
            self._target_observation_errors.clear()
            self._materialization_controls.clear()
            self._retirement_cancellation_active.clear()
            self._retirement_workers.clear()
        for installation_id, session in sessions:
            for key in live_keys:
                if key.installation_id != installation_id:
                    continue
                try:
                    self._runtime_directory.clear_binding(
                        key,
                        incarnation=session.incarnation,
                    )
                except AmdRuntimeError:
                    pass
            try:
                session.close()
            except Exception:
                # A session owns its exact remote/local cleanup and must be
                # reconciled again later.  Shutdown cannot replay or guess.
                pass

    def enroll_private_target(self, spec: AmdPrivateTargetSpec) -> str:
        self._require_open()
        self._require_deployable_placement("private_ssh")
        with self._lock, self._database_session() as session:
            row = AmdTargetEnrollmentRow(
                id=spec.target_id,
                host=spec.host,
                user=spec.user,
                port=spec.port,
                pinned_host_key=spec.pinned_host_key,
                identity_file_reference=spec.identity_file_reference,
            )
            self._repository.create_target(session, row)
            session.commit()
        return spec.target_id

    def ensure_private_install(
        self,
        *,
        target: AmdPrivateTargetSpec,
        installation: AmdInstallationSpec,
    ) -> AmdInstallationStatus:
        """Exact-ensure one Private target and installation, then reconcile.

        Target and installation rows share one SQLite transaction.  A retry
        with the exact same immutable intent re-enters reconcile; a reused ID
        with different facts is rejected instead of overwritten.
        """

        self.ensure_private_install_intent(
            target=target,
            installation=installation,
        )
        return self.reconcile(installation.installation_id)

    def ensure_private_install_intent(
        self,
        *,
        target: AmdPrivateTargetSpec,
        installation: AmdInstallationSpec,
    ) -> None:
        """Persist one exact Private target/installation checkpoint only.

        This local transaction intentionally precedes the SettingsStore
        security checkpoint in the guided command.  If the process stops
        between authorities, the installation identity remains discoverable
        and the same command can continue forward after restart.
        """

        self._require_open()
        self._require_deployable_placement("private_ssh")
        if (
            installation.placement != "private_ssh"
            or installation.target_id != target.target_id
        ):
            raise AmdDeploymentError(
                "Private AMD installation intent is inconsistent.",
                error_code="amd_request_invalid",
            )
        profile = self._profile(installation.profile_digest)
        self._require_current_profile_for_spec(profile, installation)
        with self._lock, self._database_session() as session:
            existing_target = self._repository.get_target(session, target.target_id)
            if existing_target is None:
                self._repository.create_target(
                    session,
                    AmdTargetEnrollmentRow(
                        id=target.target_id,
                        host=target.host,
                        user=target.user,
                        port=target.port,
                        pinned_host_key=target.pinned_host_key,
                        identity_file_reference=target.identity_file_reference,
                    ),
                )
            elif not _target_matches(existing_target, target):
                raise AmdDeploymentError(
                    "Private AMD target identity conflicts with its existing enrollment.",
                    error_code="amd_target_conflict",
                )

            existing_installation = self._repository.get_installation(
                session,
                installation.installation_id,
            )
            if existing_installation is None:
                self._require_location_capability_available(
                    session,
                    spec=installation,
                    profile=profile,
                )
                self._repository.create_installation(
                    session,
                    AmdInstallationRow(
                        id=installation.installation_id,
                        placement=installation.placement,
                        target_id=installation.target_id,
                        local_wsl_distribution=installation.local_wsl_distribution,
                        profile_id=profile.profile_id,
                        profile_digest=installation.profile_digest,
                    ),
                )
            elif not _installation_matches(existing_installation, installation, profile):
                raise AmdDeploymentError(
                    "AMD installation identity conflicts with its existing intent.",
                    error_code="amd_installation_conflict",
                )
            elif (
                not existing_installation.desired_presence
                or existing_installation.lifecycle_state != "active"
            ):
                raise AmdDeploymentError(
                    "A retiring AMD installation cannot be reactivated.",
                    error_code="amd_installation_retiring",
                )
            session.commit()

    def prepare(
        self,
        spec: AmdInstallationSpec,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        """Persist one immutable installation intent, then reconcile forward."""

        self._require_open()
        self._require_deployable_placement(spec.placement)
        profile = self._profile(spec.profile_digest)
        self._require_current_profile_for_spec(profile, spec)
        with self._lock, self._database_session() as session:
            self._require_location_capability_available(session, spec=spec, profile=profile)
            row = AmdInstallationRow(
                id=spec.installation_id,
                placement=spec.placement,
                target_id=spec.target_id,
                local_wsl_distribution=spec.local_wsl_distribution,
                profile_id=profile.profile_id,
                profile_digest=spec.profile_digest,
            )
            self._repository.create_installation(session, row)
            session.commit()
        return self.reconcile(spec.installation_id, progress=progress)

    install = prepare

    def prepare_upgrade(self, installation_id: str, *, new_profile_digest: str) -> AmdInstallationStatus:
        """Create a new desired installation instead of rebinding selected G1."""

        self._require_open()
        with self._lock, self._database_session() as session:
            existing = self._require_installation(session, installation_id)
            self._require_deployable_placement(existing.placement)
            if not existing.desired_presence or existing.lifecycle_state != "active":
                raise AmdDeploymentError(
                    "A retired AMD installation cannot be upgraded.",
                    error_code="amd_installation_retiring",
                )
            upgrade_id = f"amd-{uuid4().hex}"
            spec = AmdInstallationSpec(
                installation_id=upgrade_id,
                placement=existing.placement,
                target_id=existing.target_id,
                local_wsl_distribution=existing.local_wsl_distribution,
                profile_digest=new_profile_digest,
            )
        return self.prepare(spec)

    def repair(
        self,
        installation_id: str,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        """Forget only the current volatile session, then reconcile desired state."""

        self._require_open()
        initial = self._read_installation(installation_id)
        with self._operation_gate(self._location_for_installation(initial)):
            installation = self._read_installation(installation_id)
            self._require_deployable_placement(installation.placement)
            self._drop_session(installation_id)
            return self.reconcile(installation_id, progress=progress)

    def resume(
        self,
        installation_id: str,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        return self.reconcile(installation_id, progress=progress)

    def request_retirement(self, installation_id: str) -> AmdRetirementRequest:
        """Commit Remove without waiting for an active materialization lock.

        Desired absence is the only durable authority needed before target-side
        cancellation is allowed.  The target action is delegated to an
        in-memory worker because trusted SSH/session setup may take longer than
        an interactive Remove acknowledgement.  That worker is explicit
        retirement work, never ordinary reconciliation.
        """

        self._require_open()
        installation: AmdInstallationRow
        rows: tuple[AmdComponentGenerationRow, ...]
        phase = "retirement_requested"
        with self._database_session() as session:
            current = self._require_installation(session, installation_id)
            if current.lifecycle_state == "removed":
                return AmdRetirementRequest(installation_id=installation_id, phase="already_removed")
            if current.lifecycle_state == "active":
                installation = self._repository.request_retirement(
                    session,
                    installation_id=installation_id,
                    expected_revision=current.revision,
                    now=_now(),
                )
                session.commit()
            elif current.lifecycle_state == "retiring" and not current.desired_presence:
                installation = current
                phase = "retirement_already_requested"
            else:
                raise AmdDeploymentError(
                    "AMD installation cannot be removed from its current lifecycle state.",
                    error_code="amd_installation_retirement_unavailable",
                )
            rows = tuple(self._repository.list_generations(session, installation_id=installation_id))

        # Signal the currently materializing controller before any target
        # session setup.  The durable-state/checkpoint handshake handles both
        # orders of the race: a worker that registers later observes retiring,
        # while an existing worker receives this event immediately.
        self._signal_materialization_cancellation(installation_id)
        plan = self._retirement_cancellation_plan(installation, rows)
        if plan is not None:
            self._start_retirement_cancellation(plan)
        else:
            self._start_retirement_reconcile(installation_id)
        return AmdRetirementRequest(installation_id=installation_id, phase=phase)

    def reconcile(
        self,
        installation_id: str,
        *,
        progress: AmdProgressSink | None = None,
    ) -> AmdInstallationStatus:
        """Move one installation toward its durable desired state, never backward."""

        self._require_open()
        initial = self._read_installation(installation_id)
        with self._operation_gate(self._location_for_installation(initial)):
            # Re-read after obtaining the location gate.  A concurrent Remove
            # may have committed desired absence while this command waited.
            installation = self._read_installation(installation_id)
            if not installation.desired_presence or installation.lifecycle_state == "retiring":
                return self._reconcile_retirement(installation_id)
            if installation.lifecycle_state == "removed":
                return self.status(installation_id)
            self._require_deployable_placement(installation.placement)

            profile = self._profile_for_installation(installation)
            placement = self._placement(installation.placement)
            report_progress(
                progress,
                AmdProgressMilestone.TARGET_INSPECTION_STARTED,
            )
            try:
                decision = self._planner.plan_profile(
                    profile.manifest_digest,
                    placement.observe(
                        profile=profile,
                        location=self._location_for_installation(installation),
                    ),
                )
            except AmdPlacementError as exc:
                self._set_admission_result(
                    installation_id,
                    target_observation_error_code=_bounded_error_code(
                        exc.error_code,
                        fallback="amd_target_observation_failed",
                    ),
                )
                return self.status(installation_id)
            except Exception:
                self._set_admission_result(
                    installation_id,
                    target_observation_error_code="amd_target_observation_failed",
                )
                return self.status(installation_id)
            self._set_admission_result(
                installation_id,
                compatibility_issues=_decision_issue_codes(decision),
            )
            if not decision.supported:
                return self.status(installation_id)
            report_progress(progress, AmdProgressMilestone.TARGET_COMPATIBLE)

            generations = self._ensure_generations(installation, profile)
            if self._retirement_is_committed(installation_id):
                return self._reconcile_retirement(installation_id)
            if self._materialize_and_project(
                installation,
                profile,
                placement,
                generations,
                progress=progress,
            ):
                return self._reconcile_retirement(installation_id)
            if self._retirement_is_committed(installation_id):
                return self._reconcile_retirement(installation_id)
            status = self.status(installation_id)
            if status.profile_usable:
                report_progress(progress, AmdProgressMilestone.OPERATIONAL)
            return status

    def retire(
        self,
        installation_id: str,
        *,
        drain_timeout_seconds: float | None = 0.0,
    ) -> AmdInstallationStatus:
        """Commit desired absence and advance retirement without selection rewrite."""

        self._require_open()
        if drain_timeout_seconds is not None and drain_timeout_seconds < 0:
            raise ValueError("AMD retirement drain timeout cannot be negative.")
        request = self.request_retirement(installation_id)
        if request.phase == "already_removed":
            return self.status(installation_id)
        initial = self._read_installation(installation_id)
        with self._operation_gate(self._location_for_installation(initial)):
            return self._reconcile_retirement(
                installation_id,
                drain_timeout_seconds=drain_timeout_seconds,
            )

    def status(self, installation_id: str) -> AmdInstallationStatus:
        """Return a read-only projection; it never reconnects or changes state."""

        with self._lock, self._state_lock:
            self._require_open()
            installation = self._read_installation(installation_id)
            rows = tuple(self._list_generations(installation.id))
            try:
                profile = self._profile_for_installation(installation)
            except AmdDeploymentProfileError:
                # A committed retirement may outlive the bundled catalog that
                # originally described it.  That missing metadata cannot
                # authorize a guessed placement path, but it must not make the
                # durable absence invisible to the user either.
                if not installation.desired_presence or installation.lifecycle_state == "removed":
                    return self._retirement_metadata_unavailable_status(installation, rows)
                raise
            generation_by_digest = {row.manifest_digest: row for row in rows}
            components: list[AmdComponentStatus] = []
            for manifest in self._catalog.profile_components(profile):
                row = generation_by_digest.get(manifest.manifest_digest)
                status = AmdProjectionStatus(False, False, False)
                key: AmdRuntimeKey | None = None
                if row is not None:
                    status = self._participants[manifest.capability].status(
                        installation_id=installation.id,
                        component_generation_id=row.id,
                    )
                    key = AmdRuntimeKey(installation.id, row.id)
                components.append(
                    AmdComponentStatus(
                        capability=manifest.capability,
                        generation_id=row.id if row is not None else None,
                        manifest_digest=manifest.manifest_digest,
                        lifecycle_state=row.lifecycle_state if row is not None else "absent",
                        phase=row.phase if row is not None else "planned",
                        error_code=row.error_code if row is not None else None,
                        projected=status.exists,
                        projection_retiring=status.retiring,
                        selected=status.selected,
                        live=self._is_live_key(key) if key is not None else False,
                    )
                )
            ordered_components = tuple(sorted(components, key=lambda component: component.capability.value))
            compatibility_issues, target_observation_error_code = (
                self._admission_result_for(installation.id)
            )
            return AmdInstallationStatus(
                installation_id=installation.id,
                placement=installation.placement,
                profile_id=installation.profile_id,
                profile_digest=installation.profile_digest,
                desired_presence=installation.desired_presence,
                lifecycle_state=installation.lifecycle_state,
                condition=_derive_condition(
                    installation=installation,
                    components=ordered_components,
                    compatibility_issues=compatibility_issues,
                    target_observation_error_code=target_observation_error_code,
                ),
                target_observation_error_code=target_observation_error_code,
                compatibility_issues=compatibility_issues,
                components=ordered_components,
            )

    def has_installation(self, installation_id: str) -> bool:
        """Return whether one durable installation identity exists, without I/O."""

        self._require_open()
        _require_identifier(installation_id, "Installation ID")
        with self._database_session() as session:
            return self._repository.get_installation(session, installation_id) is not None

    def private_installations(self) -> tuple[AmdPrivateInstallationEnrollment, ...]:
        """Return durable Private SSH identities without live target access."""

        self._require_open()
        with self._database_session() as session:
            rows = tuple(
                row
                for row in self._repository.list_installations(session)
                if row.placement == "private_ssh"
            )
            enrollments: list[AmdPrivateInstallationEnrollment] = []
            for row in rows:
                if row.target_id is None:
                    raise AmdDeploymentError(
                        "Private AMD installation target identity is unavailable.",
                        error_code="amd_installation_inventory_invalid",
                    )
                target = self._repository.get_target(session, row.target_id)
                if target is None:
                    raise AmdDeploymentError(
                        "Private AMD installation target enrollment is unavailable.",
                        error_code="amd_installation_inventory_invalid",
                    )
                enrollments.append(
                    AmdPrivateInstallationEnrollment(
                        installation_id=row.id,
                        target_id=target.id,
                        host=target.host,
                        user=target.user,
                        port=target.port,
                        desired_presence=row.desired_presence,
                        lifecycle_state=row.lifecycle_state,
                    )
                )
        return tuple(enrollments)

    def private_targets(self) -> tuple[AmdPrivateTargetEnrollment, ...]:
        """Return reusable target enrollments even when every install is removed."""

        self._require_open()
        with self._database_session() as session:
            rows = tuple(self._repository.list_targets(session))
        try:
            return tuple(
                AmdPrivateTargetEnrollment(
                    target_id=row.id,
                    host=row.host,
                    user=row.user,
                    port=row.port,
                )
                for row in rows
            )
        except (TypeError, ValueError) as exc:
            raise AmdDeploymentError(
                "Private AMD target enrollment is invalid.",
                error_code="amd_ssh_target_invalid",
            ) from exc

    def private_target(self, target_id: str) -> AmdPrivateTargetSpec:
        """Resolve one durable Private SSH enrollment without target I/O."""

        self._require_open()
        _require_identifier(target_id, "Target ID")
        with self._database_session() as session:
            row = self._repository.get_target(session, target_id)
        if row is None:
            raise AmdDeploymentError(
                "Private AMD target enrollment was not found.",
                error_code="amd_ssh_target_not_found",
            )
        try:
            return AmdPrivateTargetSpec(
                target_id=row.id,
                host=row.host,
                user=row.user,
                port=row.port,
                pinned_host_key=row.pinned_host_key,
                identity_file_reference=row.identity_file_reference,
            )
        except (TypeError, ValueError) as exc:
            raise AmdDeploymentError(
                "Private AMD target enrollment is invalid.",
                error_code="amd_ssh_target_invalid",
            ) from exc

    def installations(self) -> tuple[AmdInstallationInventoryItem, ...]:
        """Return durable lifecycle identities without placement or target I/O."""

        self._require_open()
        with self._database_session() as session:
            rows = tuple(self._repository.list_installations(session))
        return tuple(
            AmdInstallationInventoryItem(
                installation_id=row.id,
                placement=row.placement,
                desired_presence=row.desired_presence,
                lifecycle_state=row.lifecycle_state,
                target_id=row.target_id,
                local_wsl_distribution=row.local_wsl_distribution,
            )
            for row in rows
        )

    def _ensure_generations(
        self,
        installation: AmdInstallationRow,
        profile: ExecutionProfileManifest,
    ) -> tuple[AmdComponentGenerationRow, ...]:
        # Generation creation and the active-state check share one short local
        # transaction.  Remove uses the same state fence, so it cannot commit
        # between a successful admission check and a new generation row.
        with self._database_session() as session:
            current = self._require_installation(session, installation.id)
            if not current.desired_presence or current.lifecycle_state != "active":
                return ()
            existing = {
                row.manifest_digest: row
                for row in self._repository.list_generations(session, installation_id=installation.id)
            }
            rows: list[AmdComponentGenerationRow] = []
            for manifest in self._catalog.profile_components(profile):
                row = existing.get(manifest.manifest_digest)
                if row is None:
                    row = self._repository.create_generation(
                        session,
                        AmdComponentGenerationRow(
                            id=f"amdgen-{uuid4().hex}",
                            installation_id=installation.id,
                            capability=manifest.capability.value,
                            manifest_digest=manifest.manifest_digest,
                        ),
                    )
                if row.capability != manifest.capability.value:
                    raise AmdDeploymentProfileError()
                if row.lifecycle_state in {"failed", "blocked"}:
                    row = self._repository.transition_generation(
                        session,
                        generation_id=row.id,
                        expected_revision=row.revision,
                        next_state="staging",
                        phase="reconciling",
                        now=_now(),
                    )
                rows.append(row)
            session.commit()
            return tuple(rows)

    def _materialize_and_project(
        self,
        installation: AmdInstallationRow,
        profile: ExecutionProfileManifest,
        placement: AmdPlacementController,
        rows: tuple[AmdComponentGenerationRow, ...],
        *,
        progress: AmdProgressSink | None,
    ) -> bool:
        """Materialize forward, or report that committed retirement won.

        The caller already owns ``_lock``.  The transient control is deliberately
        separate from durable lifecycle: it only gives the active placement a
        prompt way to observe a Remove request; the installation row remains the
        authority for every decision after this method returns.
        """

        materializations = self._generation_materializations(profile, rows)
        session = self._session_for(installation.id)
        unpublished_session: AmdExecutionSession | None = None
        if session is not None and any(row.phase == "reconciling" for row in rows):
            # A failed/blocked generation was intentionally moved forward to a
            # fresh staging attempt.  Reuse would make its new attestation
            # ambiguous, so discard only volatile realization state and let the
            # placement build a new controller incarnation.
            self._drop_session(installation.id)
            session = None
        newly_materialized = session is None
        control = self._begin_materialization_control(installation.id) if newly_materialized else None
        try:
            if session is None:
                if self._retirement_is_committed(installation.id):
                    control.cancellation.set()
                    return True
                try:
                    session = placement.materialize(
                        installation_id=installation.id,
                        location=self._location_for_installation(installation),
                        profile=profile,
                        generations=materializations,
                        cancellation=control.cancellation,
                        progress=progress,
                    )
                except AmdMaterializationCancelledError:
                    if self._retirement_is_committed(installation.id):
                        return True
                    if self._is_open():
                        for row in rows:
                            self._mark_materialization_failure(row.id)
                    return False
                except AmdPlacementError as exc:
                    if not self._is_open():
                        return False
                    if self._retirement_is_committed(installation.id):
                        return True
                    for row in rows:
                        self._mark_materialization_failure(
                            row.id,
                            error_code=_bounded_error_code(
                                exc.error_code,
                                fallback="materialization_failed",
                            ),
                        )
                    return False
                except Exception:
                    if not self._is_open():
                        return False
                    if self._retirement_is_committed(installation.id):
                        return True
                    for row in rows:
                        self._mark_materialization_failure(row.id)
                    return False
                unpublished_session = session
                if self._retirement_is_committed(installation.id):
                    self._close_unpublished_session(session)
                    unpublished_session = None
                    return True
                if not self._remember_session(installation.id, session):
                    self._close_unpublished_session(session)
                    unpublished_session = None
                    return False
                unpublished_session = None

            for generation in materializations:
                if self._retirement_is_committed(installation.id):
                    return True
                row = self._read_generation(generation.generation_id)
                if row.lifecycle_state in {"retiring", "removal_blocked", "removed"}:
                    return True
                key = AmdRuntimeKey(installation.id, row.id)
                try:
                    attestation: str | None = None
                    if newly_materialized:
                        report_progress(
                            progress,
                            AmdProgressMilestone.SELF_TEST_STARTED,
                            generation.capability,
                        )
                        attestation = placement.self_test(session=session, generation=generation)
                        report_progress(
                            progress,
                            AmdProgressMilestone.SELF_TEST_PASSED,
                            generation.capability,
                        )
                        if self._retirement_is_committed(installation.id):
                            return True
                    report_progress(
                        progress,
                        AmdProgressMilestone.PROVIDER_REGISTRATION_STARTED,
                        generation.capability,
                    )
                    if not self._publish_generation_projection(
                        installation=installation,
                        generation=generation,
                        row=row,
                        key=key,
                        session=session,
                        attestation=attestation,
                        newly_materialized=newly_materialized,
                    ):
                        return True
                    report_progress(
                        progress,
                        AmdProgressMilestone.PROVIDER_REGISTERED,
                        generation.capability,
                    )
                except AmdParticipantError:
                    if not self._is_open():
                        return False
                    if self._retirement_is_committed(installation.id):
                        return True
                    self._mark_projection_blocked(row.id)
                except AmdPlacementError as exc:
                    if not self._is_open():
                        return False
                    if self._retirement_is_committed(installation.id):
                        return True
                    self._mark_materialization_failure(
                        row.id,
                        error_code=_bounded_error_code(
                            exc.error_code,
                            fallback="materialization_failed",
                        ),
                    )
                except Exception:
                    if not self._is_open():
                        return False
                    if self._retirement_is_committed(installation.id):
                        return True
                    self._mark_materialization_failure(row.id)
            return self._retirement_is_committed(installation.id)
        finally:
            if unpublished_session is not None:
                self._close_unpublished_session(unpublished_session)
            if control is not None:
                self._finish_materialization_control(installation.id, control)

    def _publish_generation_projection(
        self,
        *,
        installation: AmdInstallationRow,
        generation: AmdGenerationMaterialization,
        row: AmdComponentGenerationRow,
        key: AmdRuntimeKey,
        session: AmdExecutionSession,
        attestation: str | None,
        newly_materialized: bool,
    ) -> bool:
        """Publish one capability only while durable desired presence remains active."""

        # The state fence serializes this last check with request_retirement's
        # commit.  A Remove that has already won cannot receive a new binding or
        # settings projection; a Remove that waits behind this short section is
        # handled by the subsequent retirement reconcile.
        with self._state_lock:
            self._require_open()
            if not self._installation_is_active_locked(installation.id):
                return False
            current = self._read_generation(row.id)
            if current.lifecycle_state not in {"staging", "verified", "registered"}:
                return False
            if newly_materialized:
                if attestation is None:
                    raise AmdDeploymentError(
                        "AMD runtime verification was missing.",
                        error_code="amd_attestation_missing",
                    )
                self._runtime_directory.activate(key, session.incarnation)
                self._runtime_directory.publish_binding(
                    key,
                    incarnation=session.incarnation,
                    binding=session.resolve_binding(key),
                    binding_resolver=session.resolve_binding,
                )
                self._add_live_key(key)
                if current.lifecycle_state == "staging":
                    current = self._transition_generation(
                        current.id,
                        next_state="verified",
                        phase="verified",
                        attestation_reference=attestation,
                    )
            participant = self._participants[generation.capability]
            participant.ensure(
                installation_id=installation.id,
                component_generation_id=current.id,
                manifest=generation.manifest,
            )
            if current.lifecycle_state == "verified":
                self._transition_generation(
                    current.id,
                    next_state="registered",
                    phase="registered",
                )
            return True

    def _begin_materialization_control(self, installation_id: str) -> _MaterializationControl:
        """Register the volatile cancellation handle before placement I/O begins."""

        with self._state_lock:
            self._require_open()
            if installation_id in self._materialization_controls:
                raise AmdDeploymentError(
                    "AMD installation already has an active materialization.",
                    error_code="amd_materialization_in_progress",
                )
            control = _MaterializationControl(
                cancellation=threading.Event(),
                finished=threading.Event(),
            )
            self._materialization_controls[installation_id] = control
        try:
            if self._retirement_is_committed(installation_id):
                control.cancellation.set()
        except Exception:
            self._finish_materialization_control(installation_id, control)
            raise
        return control

    def _finish_materialization_control(
        self,
        installation_id: str,
        control: _MaterializationControl,
    ) -> None:
        with self._state_lock:
            control.finished.set()
            if self._materialization_controls.get(installation_id) is control:
                self._materialization_controls.pop(installation_id, None)

    def _signal_materialization_cancellation(self, installation_id: str) -> None:
        with self._state_lock:
            control = self._materialization_controls.get(installation_id)
            if control is not None:
                control.cancellation.set()

    def _retirement_is_committed(self, installation_id: str) -> bool:
        with self._database_session() as session:
            installation = self._require_installation(session, installation_id)
            return not installation.desired_presence or installation.lifecycle_state in {"retiring", "removed"}

    def _installation_is_active_locked(self, installation_id: str) -> bool:
        """Read desired presence while the short projection/Remove fence is held."""

        with self._session_factory() as session:
            installation = self._require_installation(session, installation_id)
            return installation.desired_presence and installation.lifecycle_state == "active"

    def _retirement_cancellation_plan(
        self,
        installation: AmdInstallationRow,
        rows: tuple[AmdComponentGenerationRow, ...],
    ) -> _RetirementCancellationPlan | None:
        if installation.desired_presence or installation.lifecycle_state != "retiring" or not rows:
            return None
        try:
            profile = self._profile_for_installation(installation)
            return _RetirementCancellationPlan(
                installation_id=installation.id,
                placement=self._placement(installation.placement),
                location=self._location_for_installation(installation),
                profile=profile,
                generations=self._generation_materializations(profile, rows),
            )
        except AmdDeploymentError:
            # Desired absence has already committed.  A malformed or omitted
            # local catalog cannot safely authorize target operations; later
            # retirement stays visibly blocked rather than guessing paths.
            return None

    def _start_retirement_cancellation(self, plan: _RetirementCancellationPlan) -> None:
        with self._state_lock:
            if self._closed or plan.installation_id in self._retirement_cancellation_active:
                return
            self._retirement_cancellation_active.add(plan.installation_id)
        worker = threading.Thread(
            target=self._run_retirement_cancellation,
            args=(plan,),
            name=f"xenix-amd-retire-{plan.installation_id}",
            daemon=True,
        )
        with self._state_lock:
            if self._closed:
                self._retirement_cancellation_active.discard(plan.installation_id)
                return
            self._retirement_workers.add(worker)
        try:
            worker.start()
        except RuntimeError:
            with self._state_lock:
                self._retirement_cancellation_active.discard(plan.installation_id)
                self._retirement_workers.discard(worker)

    def _start_retirement_reconcile(self, installation_id: str) -> None:
        """Schedule explicit retirement when no target provisioning receipt exists."""

        with self._state_lock:
            if self._closed or installation_id in self._retirement_cancellation_active:
                return
            self._retirement_cancellation_active.add(installation_id)
        worker = threading.Thread(
            target=self._run_retirement_reconcile,
            args=(installation_id,),
            name=f"xenix-amd-retire-{installation_id}",
            daemon=True,
        )
        with self._state_lock:
            if self._closed:
                self._retirement_cancellation_active.discard(installation_id)
                return
            self._retirement_workers.add(worker)
        try:
            worker.start()
        except RuntimeError:
            with self._state_lock:
                self._retirement_cancellation_active.discard(installation_id)
                self._retirement_workers.discard(worker)

    def _run_retirement_cancellation(self, plan: _RetirementCancellationPlan) -> None:
        """Perform explicit bounded target cancellation, then serialized cleanup."""

        try:
            for attempt in range(_RETIRE_CANCELLATION_ATTEMPTS):
                if not self._is_open():
                    return
                session: AmdExecutionSession | None = None
                cancelled = True
                try:
                    session = plan.placement.open_retirement_session(
                        installation_id=plan.installation_id,
                        location=plan.location,
                        profile=plan.profile,
                        generations=plan.generations,
                    )
                    for generation in plan.generations:
                        try:
                            plan.placement.cancel_generation_provisioning(
                                session=session,
                                installation_id=plan.installation_id,
                                profile=plan.profile,
                                generation=generation,
                            )
                        except Exception:
                            cancelled = False
                except Exception:
                    cancelled = False
                finally:
                    if session is not None:
                        try:
                            session.close()
                        except Exception:
                            cancelled = False
                if cancelled:
                    break
                if attempt + 1 < _RETIRE_CANCELLATION_ATTEMPTS:
                    threading.Event().wait(_RETIRE_CANCELLATION_RETRY_SECONDS)

            # The location gate keeps this explicit Remove work ordered after
            # any forward materialization on the same Linux target.  Once the
            # latter exits, the worker re-reads durable desired absence and
            # completes normal retirement.
            if not self._is_open():
                return
            with self._operation_gate(plan.location):
                if self._is_open() and self._retirement_is_committed(plan.installation_id):
                    # This daemon is the explicit Remove completion path.  A
                    # request permit may outlive the acknowledgement, so it
                    # waits for the runtime directory's drain notification
                    # instead of returning once with a permanent RETIRING row.
                    self._reconcile_retirement(plan.installation_id, drain_timeout_seconds=None)
        except AmdDeploymentError:
            # Desired absence remains durable.  Expected metadata/store failures
            # must surface as a bounded blocked projection, never as an
            # uncaught daemon-thread exception that looks like a completed
            # retirement request.
            pass
        finally:
            with self._state_lock:
                self._retirement_cancellation_active.discard(plan.installation_id)
                self._retirement_workers.discard(threading.current_thread())

    def _run_retirement_reconcile(self, installation_id: str) -> None:
        try:
            if not self._is_open():
                return
            installation = self._read_installation(installation_id)
            with self._operation_gate(self._location_for_installation(installation)):
                if self._is_open() and self._retirement_is_committed(installation_id):
                    self._reconcile_retirement(installation_id, drain_timeout_seconds=None)
        except AmdDeploymentError:
            # See the equivalent explicit-cancellation path above.  A later
            # Remove command may retry retirement after the bounded metadata
            # blocker has been repaired.
            pass
        finally:
            with self._state_lock:
                self._retirement_cancellation_active.discard(installation_id)
                self._retirement_workers.discard(threading.current_thread())

    @staticmethod
    def _close_unpublished_session(session: AmdExecutionSession) -> None:
        try:
            session.close()
        except Exception:
            # The committed retirement path retains its own exact cleanup fence.
            pass

    def _reconcile_retirement(
        self,
        installation_id: str,
        *,
        drain_timeout_seconds: float | None = 0.0,
    ) -> AmdInstallationStatus:
        installation = self._read_installation(installation_id)
        if installation.lifecycle_state == "removed":
            return self.status(installation_id)
        rows = self._list_generations(installation_id)
        if not rows or all(row.lifecycle_state == "removed" for row in rows):
            # A component reaches ``removed`` only after its participant and
            # exact placement cleanup have completed.  The aggregate marker is
            # therefore safe to advance without reloading an old profile.
            self._drop_session(installation_id)
            with self._database_session() as session_db:
                current = self._require_installation(session_db, installation_id)
                if current.lifecycle_state != "removed":
                    self._repository.mark_removed(
                        session_db,
                        installation_id=installation_id,
                        expected_revision=current.revision,
                        now=_now(),
                    )
                    session_db.commit()
            return self.status(installation_id)
        try:
            profile = self._profile_for_installation(installation)
            placement = self._placement(installation.placement)
            materializations = {
                materialization.generation_id: materialization
                for materialization in self._generation_materializations(profile, tuple(rows))
            }
        except (AmdDeploymentProfileError, AmdDeploymentPlacementError):
            return self._retirement_metadata_unavailable_status(installation, tuple(rows))
        session = self._session_for(installation_id)
        if any(row.lifecycle_state != "removed" for row in rows) and session is None:
            # A process restart intentionally loses the volatile runtime
            # incarnation and endpoint.  Retirement nevertheless must prove
            # and clean the physical generation instead of declaring it gone
            # merely because that old session is no longer in memory.
            try:
                session = placement.open_retirement_session(
                    installation_id=installation.id,
                    location=self._location_for_installation(installation),
                    profile=profile,
                    generations=tuple(materializations.values()),
                )
            except Exception:
                self._mark_retirement_control_blocked(tuple(rows))
                return self.status(installation_id)
            if not self._remember_session(installation_id, session):
                try:
                    session.close()
                except Exception:
                    pass
                return self.status(installation_id)
        all_removed = True
        for row in rows:
            if row.lifecycle_state == "removed":
                continue
            all_removed = False
            self._retire_generation(
                installation=installation,
                row=row,
                session=session,
                placement=placement,
                profile=profile,
                materialization=materializations[row.id],
                drain_timeout_seconds=drain_timeout_seconds,
            )

        rows = self._list_generations(installation_id)
        if rows and not all(row.lifecycle_state == "removed" for row in rows):
            return self.status(installation_id)
        if all_removed or all(row.lifecycle_state == "removed" for row in rows):
            self._drop_session(installation_id)
            with self._database_session() as session_db:
                current = self._require_installation(session_db, installation_id)
                if current.lifecycle_state != "removed":
                    self._repository.mark_removed(
                        session_db,
                        installation_id=installation_id,
                        expected_revision=current.revision,
                        now=_now(),
                    )
                    session_db.commit()
        return self.status(installation_id)

    def _mark_retirement_control_blocked(
        self,
        rows: tuple[AmdComponentGenerationRow, ...],
    ) -> None:
        """Expose failed trusted cleanup-session setup as retryable blocked state."""

        for row in rows:
            current = self._read_generation(row.id)
            if current.lifecycle_state == "removed":
                continue
            if current.lifecycle_state not in {"retiring", "removal_blocked"}:
                current = self._transition_generation(
                    current.id,
                    next_state="retiring",
                    phase="retiring",
                )
            if current.lifecycle_state == "retiring":
                self._transition_generation(
                    current.id,
                    next_state="removal_blocked",
                    phase="removal_blocked",
                    error_code="physical_cleanup_blocked",
                )

    def _retirement_metadata_unavailable_status(
        self,
        installation: AmdInstallationRow,
        rows: tuple[AmdComponentGenerationRow, ...],
    ) -> AmdInstallationStatus:
        """Project desired absence without reconstructing unavailable metadata.

        This is intentionally a constrained failure projection.  It derives no
        target paths, opens no placement, and does not ask capability owners to
        interpret a historical manifest.  The row's immutable capability and
        digest are sufficient to tell the user which retirement is blocked.
        """

        components: list[AmdComponentStatus] = []
        for row in rows:
            try:
                capability = ManifestCapability(row.capability)
            except ValueError:
                # Storage validation prevents this for supported releases, but
                # fail closed if a damaged historical row is ever encountered.
                continue
            components.append(
                AmdComponentStatus(
                    capability=capability,
                    generation_id=row.id,
                    manifest_digest=row.manifest_digest,
                    lifecycle_state=row.lifecycle_state,
                    phase=row.phase,
                    error_code=row.error_code,
                    projected=False,
                    projection_retiring=False,
                    selected=False,
                    live=False,
                )
            )
        ordered_components = tuple(sorted(components, key=lambda component: component.capability.value))
        condition = (
            AmdInstallationCondition.REMOVED
            if installation.lifecycle_state == "removed"
            else AmdInstallationCondition.REMOVAL_BLOCKED
        )
        return AmdInstallationStatus(
            installation_id=installation.id,
            placement=installation.placement,
            profile_id=installation.profile_id,
            profile_digest=installation.profile_digest,
            desired_presence=installation.desired_presence,
            lifecycle_state=installation.lifecycle_state,
            condition=condition,
            target_observation_error_code=None,
            compatibility_issues=("retirement_metadata_unavailable",),
            components=ordered_components,
        )

    def _retire_generation(
        self,
        *,
        installation: AmdInstallationRow,
        row: AmdComponentGenerationRow,
        session: AmdExecutionSession | None,
        placement: AmdPlacementController,
        profile: ExecutionProfileManifest,
        materialization: AmdGenerationMaterialization,
        drain_timeout_seconds: float,
    ) -> None:
        key = AmdRuntimeKey(installation.id, row.id)
        current = self._read_generation(row.id)
        if current.lifecycle_state == "removal_blocked":
            current = self._transition_generation(
                current.id,
                next_state="retiring",
                phase="retiring",
            )
        if current.lifecycle_state not in {"retiring", "removed"}:
            try:
                self._runtime_directory.retire(
                    key,
                    commit_retiring=lambda: self._transition_generation(
                        current.id,
                        next_state="retiring",
                        phase="retiring",
                    ),
                )
            except AmdRuntimeUnavailableError:
                self._transition_generation(current.id, next_state="retiring", phase="retiring")
            except AmdRuntimeRetiringError:
                pass
            except AmdRuntimeError:
                return
            self._discard_live_key(key)

        try:
            if not self._runtime_directory.wait_for_drain(key, drain_timeout_seconds):
                return
        except AmdRuntimeUnavailableError:
            pass
        except AmdRuntimeError:
            return

        participant = self._participants[ManifestCapability(current.capability)]
        try:
            with self._state_lock:
                self._require_open()
                participant.mark_retiring(
                    installation_id=installation.id,
                    component_generation_id=current.id,
                )
                participant.remove(
                    installation_id=installation.id,
                    component_generation_id=current.id,
                )
        except AmdParticipantError:
            if not self._is_open():
                return
            latest = self._read_generation(current.id)
            if latest.lifecycle_state == "retiring":
                self._transition_generation(
                    latest.id,
                    next_state="removal_blocked",
                    phase="removal_blocked",
                    error_code="provider_removal_blocked",
                )
            return

        if session is None:
            # No in-memory session is never proof that a remote/local process
            # has disappeared.  Keep durable retirement open until a placement
            # can establish a fresh trusted control session and fence cleanup.
            return

        try:
            placement.retire_generation(
                session=session,
                installation_id=installation.id,
                profile=profile,
                generation=materialization,
            )
        except Exception:
            if not self._is_open():
                return
            latest = self._read_generation(current.id)
            if latest.lifecycle_state == "retiring":
                self._transition_generation(
                    latest.id,
                    next_state="removal_blocked",
                    phase="removal_blocked",
                    error_code="physical_cleanup_blocked",
                )
            return

        # A composite session is stopped and cleaned by the placement only
        # after the settings projection has no blocker.  Forget the exact
        # in-memory slot afterwards; a restart legitimately has no slot.
        try:
            self._runtime_directory.remove_retired(key, incarnation=session.incarnation)
        except AmdRuntimeUnavailableError:
            pass
        except AmdRuntimeBusyError:
            return
        except AmdRuntimeError:
            return
        latest = self._read_generation(current.id)
        if latest.lifecycle_state == "retiring":
            self._transition_generation(latest.id, next_state="removed", phase="removed")

    def _mark_materialization_failure(
        self,
        generation_id: str,
        *,
        error_code: str = "materialization_failed",
    ) -> None:
        row = self._read_generation(generation_id)
        if row.lifecycle_state in {"staging", "verified", "registered"}:
            self._transition_generation(
                row.id,
                next_state="failed",
                phase="materialization_failed",
                error_code=_bounded_error_code(
                    error_code,
                    fallback="materialization_failed",
                ),
            )

    def _mark_projection_blocked(self, generation_id: str) -> None:
        row = self._read_generation(generation_id)
        if row.lifecycle_state in {"verified", "registered"}:
            self._transition_generation(
                row.id,
                next_state="blocked",
                phase="projection_blocked",
                error_code="provider_projection_blocked",
            )

    def _transition_generation(
        self,
        generation_id: str,
        *,
        next_state: str,
        phase: str,
        error_code: str | None = None,
        attestation_reference: str | None = None,
    ) -> AmdComponentGenerationRow:
        with self._database_session() as session:
            row = self._require_generation(session, generation_id)
            if row.lifecycle_state == next_state:
                return row
            updated = self._repository.transition_generation(
                session,
                generation_id=generation_id,
                expected_revision=row.revision,
                next_state=next_state,
                phase=phase,
                error_code=error_code,
                attestation_reference=attestation_reference,
                now=_now(),
            )
            session.commit()
            return updated

    def _drop_session(self, installation_id: str) -> None:
        with self._state_lock:
            session = self._sessions.pop(installation_id, None)
            keys = tuple(
                key for key in self._live_keys if key.installation_id == installation_id
            )
            for key in keys:
                self._live_keys.discard(key)
        if session is None:
            return
        for key in keys:
            try:
                self._runtime_directory.clear_binding(
                    key,
                    incarnation=session.incarnation,
                )
            except AmdRuntimeError:
                pass
        try:
            session.close()
        except Exception:
            pass

    def _session_for(self, installation_id: str) -> AmdExecutionSession | None:
        with self._state_lock:
            self._require_open()
            return self._sessions.get(installation_id)

    def _remember_session(
        self,
        installation_id: str,
        session: AmdExecutionSession,
    ) -> bool:
        """Publish a session only while the app still owns its dependencies."""

        with self._state_lock:
            if self._closed:
                return False
            self._sessions[installation_id] = session
            return True

    def _set_admission_result(
        self,
        installation_id: str,
        *,
        compatibility_issues: tuple[str, ...] = (),
        target_observation_error_code: str | None = None,
    ) -> None:
        with self._state_lock:
            self._require_open()
            self._compatibility_issues[installation_id] = compatibility_issues
            if target_observation_error_code is None:
                self._target_observation_errors.pop(installation_id, None)
            else:
                self._target_observation_errors[installation_id] = (
                    target_observation_error_code
                )

    def _admission_result_for(
        self,
        installation_id: str,
    ) -> tuple[tuple[str, ...], str | None]:
        with self._state_lock:
            self._require_open()
            return (
                self._compatibility_issues.get(installation_id, ()),
                self._target_observation_errors.get(installation_id),
            )

    def _add_live_key(self, key: AmdRuntimeKey) -> None:
        with self._state_lock:
            self._require_open()
            self._live_keys.add(key)

    def _discard_live_key(self, key: AmdRuntimeKey) -> None:
        with self._state_lock:
            self._live_keys.discard(key)

    def _is_live_key(self, key: AmdRuntimeKey) -> bool:
        with self._state_lock:
            self._require_open()
            return key in self._live_keys

    def _is_open(self) -> bool:
        with self._state_lock:
            return not self._closed

    def _read_installation(self, installation_id: str) -> AmdInstallationRow:
        with self._database_session() as session:
            return self._require_installation(session, installation_id)

    def _read_generation(self, generation_id: str) -> AmdComponentGenerationRow:
        with self._database_session() as session:
            return self._require_generation(session, generation_id)

    def _list_generations(self, installation_id: str) -> list[AmdComponentGenerationRow]:
        with self._database_session() as session:
            return self._repository.list_generations(session, installation_id=installation_id)

    def _generation_materializations(
        self,
        profile: ExecutionProfileManifest,
        rows: tuple[AmdComponentGenerationRow, ...],
    ) -> tuple[AmdGenerationMaterialization, ...]:
        manifests = {manifest.manifest_digest: manifest for manifest in self._catalog.profile_components(profile)}
        try:
            return tuple(
                AmdGenerationMaterialization(
                    capability=ManifestCapability(row.capability),
                    generation_id=row.id,
                    manifest=manifests[row.manifest_digest],
                )
                for row in rows
            )
        except (KeyError, ValueError) as exc:
            raise AmdDeploymentProfileError() from exc

    def _profile(self, digest: str) -> ExecutionProfileManifest:
        try:
            return self._catalog.profile(digest)
        except Exception as exc:
            raise AmdDeploymentProfileError() from exc

    def _profile_for_installation(self, installation: AmdInstallationRow) -> ExecutionProfileManifest:
        profile = self._profile(installation.profile_digest)
        if profile.profile_id != installation.profile_id:
            raise AmdDeploymentProfileError()
        return profile

    def _require_current_profile_for_spec(
        self,
        profile: ExecutionProfileManifest,
        spec: AmdInstallationSpec,
    ) -> ManifestCapability:
        """Admit only one explicit capability for the selected location kind."""

        try:
            expected_placement = ExecutionProfilePlacement(spec.placement)
            components = self._catalog.profile_components(profile)
        except (TypeError, ValueError):
            raise AmdDeploymentProfileError() from None
        if profile.placement is not expected_placement or len(components) != 1:
            raise AmdDeploymentProfileError()
        return components[0].capability

    def _require_location_capability_available(
        self,
        session: Session,
        *,
        spec: AmdInstallationSpec,
        profile: ExecutionProfileManifest,
    ) -> None:
        """Prevent duplicate exact component ownership at one Linux location."""

        self._require_current_profile_for_spec(profile, spec)
        selected_component_digests = {
            component.manifest_digest for component in self._catalog.profile_components(profile)
        }
        location = spec.location
        for existing in self._repository.list_installations(session):
            if existing.id == spec.installation_id or existing.lifecycle_state == "removed":
                continue
            try:
                existing_location = self._location_for_installation(existing)
            except AmdDeploymentPlacementError:
                # A malformed historical record on the same surface cannot be
                # safely ignored when admitting a new process owner.
                if existing.placement == spec.placement:
                    raise AmdDeploymentError(
                        "AMD execution location is already occupied by an invalid record.",
                        error_code="amd_location_conflict",
                    ) from None
                continue
            if existing_location != location:
                continue
            try:
                existing_profile = self._profile_for_installation(existing)
                existing_component_digests = {
                    component.manifest_digest
                    for component in self._catalog.profile_components(existing_profile)
                }
            except AmdDeploymentProfileError:
                # The target-side cleanup contract for an unknown historical
                # profile is intentionally unavailable.  Do not start a new
                # process that could collide with its retained ownership.
                raise AmdDeploymentError(
                    "AMD execution location is occupied by an unavailable historical profile.",
                    error_code="amd_location_conflict",
                ) from None
            if selected_component_digests & existing_component_digests:
                raise AmdDeploymentError(
                    "This exact Radeon component is already installed at the selected location.",
                    error_code="amd_component_already_installed",
                )

    def _placement(self, placement_kind: str) -> AmdPlacementController:
        placement = self._placements.get(placement_kind)
        if placement is None or placement.placement_kind != placement_kind:
            raise AmdDeploymentPlacementError()
        return placement

    @staticmethod
    def _location_for_installation(installation: AmdInstallationRow) -> AmdExecutionLocation:
        """Reconstruct the typed operation input from the durable row only."""

        try:
            return AmdExecutionLocation(
                placement_kind=installation.placement,
                private_target_id=installation.target_id,
                local_wsl_distribution=installation.local_wsl_distribution,
            )
        except (TypeError, ValueError) as exc:
            raise AmdDeploymentPlacementError() from exc

    @contextmanager
    def _operation_gate(self, location: AmdExecutionLocation):
        """Serialize capacity observation and target work for one location.

        This is intentionally narrower than the control-plane metadata mutex:
        different Linux targets may reconcile independently, but capabilities
        sharing a target observe capacity and materialize in a stable order.
        The durable desired-state checks inside the gate remain authoritative.
        """

        if not isinstance(location, AmdExecutionLocation):
            raise AmdDeploymentPlacementError()
        with self._operation_gates_lock:
            gate = self._operation_gates.get(location.operation_key)
            if gate is None:
                gate = threading.RLock()
                self._operation_gates[location.operation_key] = gate
        with gate:
            yield

    def _require_open(self) -> None:
        with self._state_lock:
            if self._closed:
                raise AmdDeploymentError(
                    "AMD deployment service is closed.",
                    error_code="amd_deployment_closed",
                )

    def _require_deployable_placement(self, placement: str) -> None:
        """Allow forward work only for placements owned by this edition."""

        if placement not in self._new_installation_placements:
            raise AmdDeploymentError(
                "This AMD placement is available for safe cleanup only.",
                error_code="amd_placement_unavailable",
            )

    def _require_installation(self, session: Session, installation_id: str) -> AmdInstallationRow:
        row = self._repository.get_installation(session, installation_id)
        if row is None:
            raise AmdDeploymentNotFoundError()
        return row

    def _require_generation(self, session: Session, generation_id: str) -> AmdComponentGenerationRow:
        row = self._repository.get_generation(session, generation_id)
        if row is None:
            raise AmdDeploymentError(
                "AMD component generation was not found.",
                error_code="amd_generation_not_found",
            )
        return row


def _target_matches(
    row: AmdTargetEnrollmentRow,
    spec: AmdPrivateTargetSpec,
) -> bool:
    return (
        row.id == spec.target_id
        and row.host == spec.host
        and row.user == spec.user
        and row.port == spec.port
        and row.pinned_host_key == spec.pinned_host_key
        and row.identity_file_reference == spec.identity_file_reference
    )


def _installation_matches(
    row: AmdInstallationRow,
    spec: AmdInstallationSpec,
    profile: ExecutionProfileManifest,
) -> bool:
    return (
        row.id == spec.installation_id
        and row.placement == spec.placement
        and row.target_id == spec.target_id
        and row.local_wsl_distribution == spec.local_wsl_distribution
        and row.profile_id == profile.profile_id
        and row.profile_digest == spec.profile_digest
    )


def _derive_condition(
    *,
    installation: AmdInstallationRow,
    components: tuple[AmdComponentStatus, ...],
    compatibility_issues: tuple[str, ...],
    target_observation_error_code: str | None,
) -> AmdInstallationCondition:
    if installation.lifecycle_state == "removed":
        return AmdInstallationCondition.REMOVED
    if not installation.desired_presence or installation.lifecycle_state == "retiring":
        if any(component.lifecycle_state == "removal_blocked" for component in components):
            return AmdInstallationCondition.REMOVAL_BLOCKED
        return AmdInstallationCondition.RETIRING
    if target_observation_error_code is not None:
        if not components or all(component.generation_id is None for component in components):
            return AmdInstallationCondition.NOT_MATERIALIZED
        return AmdInstallationCondition.DEGRADED
    if compatibility_issues:
        return AmdInstallationCondition.INCOMPATIBLE
    if not components or all(component.generation_id is None for component in components):
        return AmdInstallationCondition.NOT_MATERIALIZED
    if all(component.operational for component in components):
        return AmdInstallationCondition.OPERATIONAL
    if any(component.lifecycle_state in {"failed", "blocked"} for component in components):
        return AmdInstallationCondition.DEGRADED
    return AmdInstallationCondition.INSTALLING


def _decision_issue_codes(decision: CompatibilityDecision) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            f"amd_compatibility_{issue.reason.value}"
            for issue in decision.issues
        )
    )


def _bounded_error_code(value: object, *, fallback: str) -> str:
    if (
        isinstance(value, str)
        and 1 <= len(value) <= 120
        and all(character.isascii() and (character.islower() or character.isdigit() or character == "_") for character in value)
    ):
        return value
    return fallback


def _now() -> datetime:
    return datetime.now(UTC)


def _require_identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or value != value.strip()
        or any(character.isspace() or ord(character) < 0x21 for character in value)
    ):
        raise ValueError(f"{label} is invalid.")


def _require_digest(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("AMD profile digest is invalid.")


__all__ = [
    "AmdAiDeploymentService",
    "AmdDeploymentError",
    "AmdDeploymentNotFoundError",
    "AmdDeploymentPlacementError",
    "AmdDeploymentProfileError",
    "AmdInstallationInventoryItem",
    "AmdInstallationSpec",
    "AmdPrivateInstallationEnrollment",
    "AmdPrivateTargetEnrollment",
    "AmdPrivateTargetSpec",
    "AmdRetirementRequest",
]
