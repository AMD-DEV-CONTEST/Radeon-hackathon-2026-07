"""Application orchestration for the bounded F03-C demo activation flow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .exceptions import ObjectNotFoundError
from .golden_path import (
    SCENARIO_ASSET_TYPE,
    SCENARIO_EVENT_TYPE,
    SCENARIO_ID,
    RestaurantAirconGoldenPath,
)
from .models import AuditRecord, Decision, Event
from .notifications import Notification
from .responsibility import (
    ResponsibilityAssignment,
    ResponsibilityDirectory,
)
from .runtime import AlphaNoahRuntime

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEMO_RESPONSIBILITY_FILE = (
    REPOSITORY_ROOT / "examples" / "demo_activation_responsibility.json"
)

DEMO_SOURCE = "demo_activation"
DEMO_ACTOR = "adapter:demo-activation"
DEMO_ASSET_ID = "A08-AIRCON"
DEMO_LOCATION = "Restaurant-Private-Room-A08"
DEMO_REPORTER = "synthetic:demo-activation"
DEMO_DATA_CLASSIFICATION = "Synthetic demo data"
DEMO_INCIDENT_NOTICE = "Not a real production incident"


class DemoActivationFailure(Exception):
    """Preserve the persisted Event identity after a partial activation."""

    def __init__(self, event_id: str):
        super().__init__("Demo activation did not complete.")
        self.event_id = event_id


@dataclass(frozen=True, slots=True)
class DemoActivationSnapshot:
    """Internal facts used by the Web projection without changing Runtime."""

    event: Event
    responsibility: ResponsibilityAssignment
    decision: Decision | None
    notification: Notification | None
    audits: tuple[AuditRecord, ...]
    decision_count: int
    notification_count: int
    task_count: int


@dataclass(frozen=True, slots=True)
class DemoActivationResult:
    event_id: str
    replayed: bool


class DemoActivationInputAdapter:
    """Create the one reviewed synthetic Event shape through Runtime."""

    def __init__(self, runtime: AlphaNoahRuntime):
        if not isinstance(runtime, AlphaNoahRuntime):
            raise TypeError("runtime must be AlphaNoahRuntime")
        self.runtime = runtime

    def submit(self, *, description: str, request_id: str) -> Event:
        return self.runtime.create_event(
            source=DEMO_SOURCE,
            actor=DEMO_ACTOR,
            normalized_input={
                "location": DEMO_LOCATION,
                "description": description,
                "data_classification": DEMO_DATA_CLASSIFICATION,
            },
            event_type=SCENARIO_EVENT_TYPE,
            location=DEMO_LOCATION,
            asset_id=DEMO_ASSET_ID,
            reporter=DEMO_REPORTER,
            description=description,
            metadata={
                "asset_type": SCENARIO_ASSET_TYPE,
                "scenario_id": SCENARIO_ID,
                "request_id": request_id,
                "data_classification": DEMO_DATA_CLASSIFICATION,
                "incident_notice": DEMO_INCIDENT_NOTICE,
            },
        )


class DemoActivationApplication:
    """Run one synthetic Event to human review through existing boundaries."""

    def __init__(
        self,
        *,
        application: RestaurantAirconGoldenPath,
        input_adapter: DemoActivationInputAdapter,
        responsibility_directory: ResponsibilityDirectory,
    ):
        if not isinstance(application, RestaurantAirconGoldenPath):
            raise TypeError(
                "application must be RestaurantAirconGoldenPath"
            )
        if not isinstance(input_adapter, DemoActivationInputAdapter):
            raise TypeError(
                "input_adapter must be DemoActivationInputAdapter"
            )
        if not isinstance(
            responsibility_directory,
            ResponsibilityDirectory,
        ):
            raise TypeError(
                "responsibility_directory must be ResponsibilityDirectory"
            )
        if input_adapter.runtime is not application.runtime:
            raise ValueError(
                "input adapter and application must share one Runtime"
            )
        self.application = application
        self.input_adapter = input_adapter
        self.responsibility_directory = responsibility_directory
        self._activation_lock = RLock()
        self._request_events: dict[str, str] = {}

    def activate(
        self,
        *,
        description: str,
        request_id: str,
    ) -> DemoActivationResult:
        """Create at most one Event per request ID in this process."""

        with self._activation_lock:
            existing = self._event_for_request(request_id)
            if existing is not None:
                return DemoActivationResult(
                    event_id=existing.event_id,
                    replayed=True,
                )

            event = self.input_adapter.submit(
                description=description,
                request_id=request_id,
            )
            self._request_events[request_id] = event.event_id
            try:
                summary = self.application.analyze(event.event_id)
                assignment = self.responsibility_directory.resolve(
                    self.application.runtime.store.get_event(event.event_id)
                )
                self.application.runtime.create_notification_for_decision(
                    summary.decision_id,
                    directory=self.responsibility_directory,
                    actor=DEMO_ACTOR,
                )
                self._assert_activation_boundary(
                    event.event_id,
                    assignment,
                )
            except Exception as exc:
                raise DemoActivationFailure(event.event_id) from exc
            return DemoActivationResult(
                event_id=event.event_id,
                replayed=False,
            )

    def get_snapshot(self, event_id: str) -> DemoActivationSnapshot:
        """Reconstruct a read-only projection without invoking a provider."""

        with self._activation_lock:
            event = self.application.runtime.store.get_event(event_id)
            if (
                event.source != DEMO_SOURCE
                or event.metadata.get("scenario_id") != SCENARIO_ID
            ):
                raise ObjectNotFoundError(
                    f"Demo activation Event not found: {event_id}"
                )
            decisions = self.application.runtime.store.list_decisions(
                event.event_id
            )
            notifications = (
                self.application.runtime.store.list_notifications(
                    event.event_id
                )
            )
            decision = decisions[0] if len(decisions) == 1 else None
            notification = (
                notifications[0] if len(notifications) == 1 else None
            )
            task_count = (
                len(
                    self.application.runtime.store.list_tasks(
                        decision.decision_id
                    )
                )
                if decision is not None
                else 0
            )
            return DemoActivationSnapshot(
                event=event,
                responsibility=self.responsibility_directory.resolve(event),
                decision=decision,
                notification=notification,
                audits=tuple(
                    self.application.runtime.store.list_audit(event.trace_id)
                ),
                decision_count=len(decisions),
                notification_count=len(notifications),
                task_count=task_count,
            )

    def _event_for_request(self, request_id: str) -> Event | None:
        event_id = self._request_events.get(request_id)
        if event_id is not None:
            try:
                return self.application.runtime.store.get_event(event_id)
            except ObjectNotFoundError:
                self._request_events.pop(request_id, None)

        matches = [
            event
            for event in self.application.runtime.store.list_events()
            if (
                event.source == DEMO_SOURCE
                and event.metadata.get("scenario_id") == SCENARIO_ID
                and event.metadata.get("request_id") == request_id
            )
        ]
        if not matches:
            return None
        event = matches[0]
        self._request_events[request_id] = event.event_id
        return event

    def _assert_activation_boundary(
        self,
        event_id: str,
        assignment: ResponsibilityAssignment,
    ) -> None:
        snapshot = self.get_snapshot(event_id)
        if snapshot.event.status.value != "PENDING_HUMAN_REVIEW":
            raise RuntimeError("Activation did not stop at human review.")
        if (
            snapshot.decision is None
            or snapshot.decision.status.value
            != "PENDING_HUMAN_REVIEW"
        ):
            raise RuntimeError("Activation Decision is not awaiting review.")
        if snapshot.notification is None:
            raise RuntimeError("Activation notification was not persisted.")
        if snapshot.notification.status.value != "CREATED":
            raise RuntimeError("Activation notification is not pending.")
        if snapshot.notification.recipient_id != assignment.owner_id:
            raise RuntimeError("Activation responsibility is inconsistent.")
        if snapshot.task_count:
            raise RuntimeError("Activation created a Task unexpectedly.")
        if assignment.owner_id == ResponsibilityDirectory.UNASSIGNED.owner_id:
            raise RuntimeError("Synthetic responsibility is unassigned.")


def build_demo_activation_application(
    application: RestaurantAirconGoldenPath,
    *,
    responsibility_file: str | Path = DEFAULT_DEMO_RESPONSIBILITY_FILE,
) -> DemoActivationApplication:
    """Compose the demo adapter over the same application and database."""

    return DemoActivationApplication(
        application=application,
        input_adapter=DemoActivationInputAdapter(application.runtime),
        responsibility_directory=ResponsibilityDirectory.from_file(
            responsibility_file
        ),
    )
