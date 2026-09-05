"""Capability-scoped Radeon setup controls for the existing Settings cards.

Radeon deployment is deliberately presented beside the capability it enables:
Chat in the LLM card, Embedding in the vector-provider card, and OCR in the
OCR card.  The UI owns no provider selection or endpoint state.  It submits
one explicit capability command to the AMD guided facade and asks Settings to
reload managed provider projections only after the operator closes and opens
Settings again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ..services.amd.manifests import ManifestCapability
from ..services.amd.progress import AmdProgressEvent, AmdProgressMilestone
from .amd_capability_tasks import (
    AmdCapabilityDeploymentOption,
    AmdCapabilityProgressUpdate,
    AmdCapabilityTaskResult,
    AmdCapabilityTaskRunner,
    AmdExistingPrivateSshInstallCommand,
    AmdGuidedCapabilityInstallation,
    AmdGuidedDeploymentError,
    AmdGuidedInputField,
    AmdGuidedPrivateTarget,
    AmdHostTrustTaskResult,
    AmdLocalWslDiscoveryTaskResult,
    AmdLocalWslInstallCommand,
    AmdPrivateSshInstallCommand,
    AmdRetirementAcknowledgement,
    AmdSshHostTrustChallenge,
)

if TYPE_CHECKING:
    from ..services.amd.composition import AmdComposition
    from ..services.amd.guided_capability import AmdCapabilityGuidedDeploymentService
    from .settings_dialog import SettingsDialog, SettingsDialogCapabilitySlots


_PRIVATE_SSH = "private_ssh"
_LOCAL_WSL = "local_wsl"
_CAPABILITIES = (
    ManifestCapability.CHAT,
    ManifestCapability.EMBEDDING,
    ManifestCapability.OCR,
)


@dataclass(slots=True)
class _CapabilityControl:
    """One compact, Settings-owned capability row."""

    label: QLabel
    status: QLabel
    button: QPushButton
    container: QWidget


class AmdRadeonSettingsContribution:
    """Append Radeon setup controls to the three generic capability slots."""

    def __init__(self, composition: AmdComposition) -> None:
        self._composition = composition

    def attach(
        self,
        dialog: SettingsDialog,
        capability_slots: SettingsDialogCapabilitySlots,
    ) -> _AmdRadeonSettingsHandle:
        return _AmdRadeonSettingsHandle(dialog, capability_slots, self._composition)


class _AmdRadeonSettingsHandle(QObject):
    """Own capability rows and their persistent guided dialogs."""

    def __init__(
        self,
        dialog: SettingsDialog,
        capability_slots: SettingsDialogCapabilitySlots,
        composition: AmdComposition,
    ) -> None:
        super().__init__(dialog)
        self._settings_dialog = dialog
        self._composition = composition
        self._shutdown = False
        self._conditions: dict[ManifestCapability, str | None] = {
            capability: None for capability in _CAPABILITIES
        }
        self._provider_projection_signature: tuple[tuple[str, ...], ...] | None = None
        self._controls: dict[ManifestCapability, _CapabilityControl] = {}
        self._dialogs: dict[ManifestCapability, AmdCapabilitySetupDialog] = {}

        slots = {
            ManifestCapability.CHAT: capability_slots.llm,
            ManifestCapability.EMBEDDING: capability_slots.embedding,
            ManifestCapability.OCR: capability_slots.ocr,
        }
        for capability in _CAPABILITIES:
            control = self._create_control(capability, parent=dialog)
            slots[capability].addRow(control.label, control.container)
            self._controls[capability] = control
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        for capability, control in self._controls.items():
            control.label.setText(self.tr("AMD Radeon"))
            control.status.setText(self._control_status_text(capability))
            control.button.setText(
                self.tr("Set up Radeon {capability}...").format(
                    capability=_capability_label(self, capability)
                )
            )
            control.button.setToolTip(
                self.tr("Set up or manage Radeon {capability}").format(
                    capability=_capability_label(self, capability)
                )
            )
        for dialog in tuple(self._dialogs.values()):
            if isValid(dialog):
                dialog.retranslate_ui()

    def prepare_for_settings_show(self) -> None:
        """Refresh Radeon summaries and request a draft-safe provider reload.

        This is intentionally local inventory only: the call neither probes an
        SSH/WSL target nor starts a deployment.  The generic Settings dialog
        remains the only owner that decides whether and when to reload its
        provider fields.
        """

        if self._shutdown:
            return
        snapshots: list[tuple[str, tuple[AmdGuidedCapabilityInstallation, ...]]] = []
        for capability in _CAPABILITIES:
            try:
                inventory = self._composition.capability_guided_deployments[
                    capability
                ].inventory()
            except Exception:
                return
            snapshots.append((capability.value, inventory))

        signature: list[tuple[str, ...]] = []
        for capability, inventory in snapshots:
            typed_capability = ManifestCapability(capability)
            self._set_condition(
                typed_capability,
                _capability_inventory_condition(inventory),
            )
            for installation in inventory:
                for component in installation.status.components:
                    signature.append(
                        (
                            capability,
                            installation.installation_id,
                            installation.lifecycle_state,
                            "present" if installation.desired_presence else "retiring",
                            installation.status.condition.value,
                            component.generation_id or "",
                            component.lifecycle_state,
                            "projected" if component.projected else "unprojected",
                            "projection_retiring"
                            if component.projection_retiring
                            else "projection_active",
                        )
                    )
        current_signature = tuple(sorted(signature))
        if (
            self._provider_projection_signature is not None
            and current_signature != self._provider_projection_signature
        ):
            self._settings_dialog.request_managed_provider_refresh()
        self._provider_projection_signature = current_signature

    def shutdown(self) -> None:
        """Stop UI-only activity before Settings tears down its app services."""

        if self._shutdown:
            return
        self._shutdown = True
        for control in self._controls.values():
            control.button.setEnabled(False)
            control.container.hide()
            control.label.hide()
        for dialog in tuple(self._dialogs.values()):
            if isValid(dialog):
                dialog.shutdown()
                dialog.close()
                dialog.deleteLater()
        self._dialogs.clear()

    def _create_control(
        self,
        capability: ManifestCapability,
        *,
        parent: QWidget,
    ) -> _CapabilityControl:
        label = QLabel(parent=parent)
        label.setObjectName(f"amdRadeon{capability.value.title()}Label")
        container = QWidget(parent=parent)
        container.setObjectName(f"amdRadeon{capability.value.title()}Control")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        status = QLabel(parent=container)
        status.setObjectName(f"amdRadeon{capability.value.title()}Status")
        status.setWordWrap(True)
        button = QPushButton(parent=container)
        button.setObjectName(f"amdRadeon{capability.value.title()}Button")
        button.clicked.connect(
            lambda _checked=False, selected=capability: self._open_dialog(selected)
        )
        layout.addWidget(status, 1)
        layout.addWidget(button)
        return _CapabilityControl(
            label=label,
            status=status,
            button=button,
            container=container,
        )

    def _open_dialog(self, capability: ManifestCapability) -> None:
        if self._shutdown:
            return
        guided = self._composition.capability_guided_deployments[capability]
        dialog = self._dialogs.get(capability)
        if dialog is None or not isValid(dialog):
            dialog = AmdCapabilitySetupDialog(
                capability=capability,
                guided=guided,
                parent=self._settings_dialog,
            )
            dialog.provider_projections_may_have_changed.connect(
                self._settings_dialog.request_managed_provider_refresh
            )
            dialog.status_changed.connect(
                lambda condition, selected=capability: self._set_condition(
                    selected,
                    condition,
                )
            )
            self._dialogs[capability] = dialog
        else:
            dialog.refresh_inventory()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _set_condition(self, capability: ManifestCapability, condition: str) -> None:
        if self._shutdown:
            return
        self._conditions[capability] = condition
        self._controls[capability].status.setText(self._control_status_text(capability))

    def _control_status_text(self, capability: ManifestCapability) -> str:
        condition = self._conditions[capability]
        if condition is None:
            return self.tr("Radeon {capability} is not configured.").format(
                capability=_capability_label(self, capability)
            )
        return self.tr("Radeon {capability}: {condition}").format(
            capability=_capability_label(self, capability),
            condition=_condition_label(self, condition),
        )


class AmdCapabilitySetupDialog(QDialog):
    """Manage one explicit capability at one explicit Linux execution location."""

    provider_projections_may_have_changed = Signal()
    status_changed = Signal(str)

    def __init__(
        self,
        *,
        capability: ManifestCapability,
        guided: AmdCapabilityGuidedDeploymentService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(capability, ManifestCapability):
            raise TypeError("Radeon setup requires one capability.")
        self._capability = capability
        self._guided = guided
        self.setObjectName(f"amd{capability.value.title()}CapabilitySetupDialog")
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setModal(True)
        self.setMinimumWidth(680)

        self._shutdown = False
        self._ui_loading = False
        self._primary_active = False
        self._retirement_active = False
        self._wsl_discovery_active = False
        self._pending_installation_id = _new_installation_id()
        self._pending_target_id = _new_target_id()
        self._inventory: dict[str, AmdGuidedCapabilityInstallation] = {}
        self._private_targets: dict[str, AmdGuidedPrivateTarget] = {}
        self._condition = "not_materialized"
        self._phase = "idle"
        self._error_code: str | None = None
        self._invalid_field: AmdGuidedInputField | None = None
        self._details = ""
        self._activity_sequence = 0
        self._operation_started_at: float | None = None
        self._primary_operation_id: int | None = None
        self._host_trust_operation_id: int | None = None
        self._wsl_discovery_operation_id: int | None = None
        self._retirement_operation_id: int | None = None
        self._display_operation_id: int | None = None
        self._active_installation_id: str | None = None
        self._retiring_installation_id: str | None = None
        self._inventory_refresh_pending = False
        self._pending_inventory_selection_id: str | None = None

        self._runner = AmdCapabilityTaskRunner(guided, parent=self)
        self._deployment_options = self._runner.deployment_options()
        self._deployment_options_by_id = {
            option.option_id: option for option in self._deployment_options
        }
        self._runner.finished.connect(self._finish_operation)
        self._runner.retirement_acknowledged.connect(
            self._finish_retirement_acknowledgement
        )
        self._runner.host_trust_finished.connect(self._finish_host_trust)
        self._runner.local_wsl_discovery_finished.connect(self._finish_wsl_discovery)
        self._runner.progressed.connect(self._append_progress)

        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(30_000)
        self._activity_timer.timeout.connect(self._append_activity_heartbeat)
        self._retirement_poll_timer = QTimer(self)
        self._retirement_poll_timer.setSingleShot(True)
        self._retirement_poll_timer.setInterval(1_500)
        self._retirement_poll_timer.timeout.connect(self.refresh_inventory)

        self._intro_label = QLabel(parent=self)
        self._intro_label.setObjectName("amdCapabilitySetupIntroduction")
        self._intro_label.setWordWrap(True)
        self._installation_label = QLabel(parent=self)
        self._installation_combo = QComboBox(parent=self)
        self._installation_combo.setObjectName("amdCapabilityInstallationSelector")
        self._refresh_inventory_button = QPushButton(parent=self)
        self._refresh_inventory_button.setObjectName("amdCapabilityRefreshInventoryButton")
        self._model_label = QLabel(parent=self)
        self._model_selector = QComboBox(parent=self)
        self._model_selector.setObjectName("amdCapabilityModelSelector")
        self._model_details = QLabel(parent=self)
        self._model_details.setObjectName("amdCapabilityModelDetails")
        self._model_details.setWordWrap(True)
        self._location_label = QLabel(parent=self)
        self._location_selector = QComboBox(parent=self)
        self._location_selector.setObjectName("amdCapabilityLocationSelector")
        available_placements = {option.placement for option in self._deployment_options}
        for placement in (_PRIVATE_SSH, _LOCAL_WSL):
            if placement in available_placements:
                self._location_selector.addItem("", placement)

        self._private_panel = QFrame(parent=self)
        self._private_panel.setObjectName("amdCapabilityPrivateSshPanel")
        self._private_panel.setFrameShape(QFrame.StyledPanel)
        self._private_heading = QLabel(parent=self._private_panel)
        self._private_heading.setObjectName("amdCapabilityPrivateSshHeading")
        self._private_heading.setWordWrap(True)
        self._private_target_label = QLabel(parent=self._private_panel)
        self._private_target_combo = QComboBox(parent=self._private_panel)
        self._private_target_combo.setObjectName("amdCapabilityPrivateTargetSelector")
        self._private_target_hint = QLabel(parent=self._private_panel)
        self._private_target_hint.setObjectName("amdCapabilityPrivateTargetHint")
        self._private_target_hint.setWordWrap(True)
        self._private_credentials_panel = QWidget(parent=self._private_panel)
        self._host_label = QLabel(parent=self._private_credentials_panel)
        self._host_input = QLineEdit(parent=self._private_credentials_panel)
        self._host_input.setObjectName("amdCapabilitySshHostInput")
        self._user_label = QLabel(parent=self._private_credentials_panel)
        self._user_input = QLineEdit(parent=self._private_credentials_panel)
        self._user_input.setObjectName("amdCapabilitySshUserInput")
        self._port_label = QLabel(parent=self._private_credentials_panel)
        self._port_input = QSpinBox(parent=self._private_credentials_panel)
        self._port_input.setObjectName("amdCapabilitySshPortInput")
        self._port_input.setRange(1, 65_535)
        self._port_input.setValue(22)
        self._identity_file_label = QLabel(parent=self._private_credentials_panel)
        self._identity_file_input = QLineEdit(parent=self._private_credentials_panel)
        self._identity_file_input.setObjectName("amdCapabilitySshIdentityInput")
        self._identity_file_browse_button = QPushButton(parent=self._private_credentials_panel)
        self._identity_file_browse_button.setObjectName("amdCapabilitySshIdentityBrowseButton")

        self._wsl_panel = QFrame(parent=self)
        self._wsl_panel.setObjectName("amdCapabilityWslPanel")
        self._wsl_panel.setFrameShape(QFrame.StyledPanel)
        self._wsl_heading = QLabel(parent=self._wsl_panel)
        self._wsl_heading.setObjectName("amdCapabilityWslHeading")
        self._wsl_heading.setWordWrap(True)
        self._wsl_distribution_label = QLabel(parent=self._wsl_panel)
        self._wsl_distribution_combo = QComboBox(parent=self._wsl_panel)
        self._wsl_distribution_combo.setObjectName("amdCapabilityWslDistributionSelector")
        self._wsl_refresh_button = QPushButton(parent=self._wsl_panel)
        self._wsl_refresh_button.setObjectName("amdCapabilityWslRefreshButton")
        self._wsl_hint = QLabel(parent=self._wsl_panel)
        self._wsl_hint.setObjectName("amdCapabilityWslHint")
        self._wsl_hint.setWordWrap(True)

        self._condition_label = QLabel(parent=self)
        self._condition_value = QLabel(parent=self)
        self._condition_value.setObjectName("amdCapabilityCondition")
        self._phase_label = QLabel(parent=self)
        self._phase_value = QLabel(parent=self)
        self._phase_value.setObjectName("amdCapabilityPhase")
        self._support_code_label = QLabel(parent=self)
        self._support_code_value = QLabel(parent=self)
        self._support_code_value.setObjectName("amdCapabilitySupportCode")
        self._support_code_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._details_label = QLabel(parent=self)
        self._details_value = QLabel(parent=self)
        self._details_value.setObjectName("amdCapabilityDetails")
        self._details_value.setWordWrap(True)
        self._details_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._activity_label = QLabel(parent=self)
        self._activity_view = QPlainTextEdit(parent=self)
        self._activity_view.setObjectName("amdCapabilityInstallationActivity")
        self._activity_view.setReadOnly(True)
        self._activity_view.setMaximumBlockCount(1_024)
        self._activity_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._activity_view.setMinimumHeight(180)

        self._install_button = QPushButton(parent=self)
        self._install_button.setObjectName("amdCapabilityInstallButton")
        self._repair_button = QPushButton(parent=self)
        self._repair_button.setObjectName("amdCapabilityRepairButton")
        self._remove_button = QPushButton(parent=self)
        self._remove_button.setObjectName("amdCapabilityRemoveButton")
        self._close_button = QPushButton(parent=self)
        self._close_button.setObjectName("amdCapabilityCloseButton")

        self._build_ui()
        self._wire_events()
        self.retranslate_ui()
        self.refresh_inventory()

    def retranslate_ui(self) -> None:
        capability = _capability_label(self, self._capability)
        self.setWindowTitle(
            self.tr("Set up Radeon {capability}").format(capability=capability)
        )
        self._intro_label.setText(
            self.tr(
                "Deploy only Radeon {capability}. Choose Private SSH for a Linux server, "
                "or This PC (WSL2) for a local Radeon-enabled Linux environment. "
                "Xenix adds the managed provider only after this capability is operational."
            ).format(capability=capability)
        )
        self._installation_label.setText(self.tr("Deployment"))
        self._refresh_inventory_button.setText(self.tr("Refresh"))
        self._model_label.setText(self.tr("LLM model"))
        self._location_label.setText(self.tr("Execution location"))
        self._set_location_item_text(_PRIVATE_SSH, self.tr("Private SSH"))
        self._set_location_item_text(_LOCAL_WSL, self.tr("This PC (WSL2)"))
        self._private_heading.setText(
            self.tr(
                "Use an enrolled Linux server, or enter a new SSH target. Xenix "
                "will show its fingerprint for confirmation before credentials are saved."
            )
        )
        self._private_target_label.setText(self.tr("SSH target"))
        self._host_label.setText(self.tr("Host"))
        self._user_label.setText(self.tr("User"))
        self._port_label.setText(self.tr("Port"))
        self._identity_file_label.setText(self.tr("Private identity file"))
        self._identity_file_browse_button.setText(self.tr("Browse..."))
        self._wsl_heading.setText(
            self.tr(
                "Choose an explicit WSL2 distribution. Xenix checks its ROCm and "
                "Radeon compatibility before installing this capability."
            )
        )
        self._wsl_distribution_label.setText(self.tr("WSL2 distribution"))
        self._wsl_refresh_button.setText(self.tr("Refresh distributions"))
        self._condition_label.setText(self.tr("Condition"))
        self._phase_label.setText(self.tr("Phase"))
        self._support_code_label.setText(self.tr("Support code"))
        self._details_label.setText(self.tr("Details"))
        self._activity_label.setText(self.tr("Installation activity"))
        self._install_button.setText(
            self.tr("Continue setup")
            if self._requires_private_security_setup()
            else self.tr("Install")
        )
        self._repair_button.setText(self.tr("Repair"))
        self._remove_button.setText(self.tr("Remove"))
        self._close_button.setText(self.tr("Close"))
        self._rebuild_installation_selector()
        self._rebuild_private_target_selector()
        self._rebuild_model_selector()
        self._sync_context()
        self._render_state()

    def refresh_inventory(self, *, select_installation_id: str | None = None) -> None:
        """Refresh only durable UI projections; never probe a target on the UI thread."""

        if self._shutdown:
            return
        if self._primary_active or self._retirement_active or self._runner.active:
            self._inventory_refresh_pending = True
            if select_installation_id is not None:
                self._pending_inventory_selection_id = select_installation_id
            return
        self._inventory_refresh_pending = False
        pending_selection = self._pending_inventory_selection_id
        self._pending_inventory_selection_id = None
        selected_id = (
            select_installation_id
            or pending_selection
            or self._selected_installation_id()
        )
        try:
            inventory = self._runner.inventory()
        except Exception as exc:
            self._record_nonblocking_error(_safe_error_code(exc))
            return
        try:
            targets = self._runner.private_targets()
        except Exception as exc:
            targets = ()
            self._record_nonblocking_error(_safe_error_code(exc))
        self._inventory = {
            installation.installation_id: installation for installation in inventory
        }
        if self._retiring_installation_id is not None:
            retiring = self._inventory.get(self._retiring_installation_id)
            if retiring is None or not retiring.desired_presence:
                self._retiring_installation_id = None
        self._private_targets = {target.target_id: target for target in targets}
        self._rebuild_installation_selector(selected_id=selected_id)
        self._rebuild_private_target_selector()
        self._sync_context()
        self._emit_status_condition()
        self._schedule_retirement_poll()

    def _request_inventory_refresh(self, installation_id: str | None = None) -> None:
        """Coalesce local inventory refresh after asynchronous UI work settles."""

        if self._shutdown:
            return
        self._inventory_refresh_pending = True
        if installation_id is not None:
            self._pending_inventory_selection_id = installation_id
        self._flush_pending_inventory_refresh()

    def _flush_pending_inventory_refresh(self) -> None:
        if self._shutdown or not self._inventory_refresh_pending or self._runner.active:
            return
        self.refresh_inventory(
            select_installation_id=self._pending_inventory_selection_id
        )

    def shutdown(self) -> None:
        """Suppress late worker delivery before app-owned AMD services close."""

        if self._shutdown:
            return
        self._shutdown = True
        self._activity_timer.stop()
        self._retirement_poll_timer.stop()
        for signal, slot in (
            (self._runner.finished, self._finish_operation),
            (self._runner.retirement_acknowledged, self._finish_retirement_acknowledgement),
            (self._runner.host_trust_finished, self._finish_host_trust),
            (self._runner.local_wsl_discovery_finished, self._finish_wsl_discovery),
            (self._runner.progressed, self._append_progress),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._runner.shutdown()
        for widget in (
            self._install_button,
            self._repair_button,
            self._remove_button,
            self._close_button,
        ):
            widget.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._shutdown:
            self._activity_timer.stop()
            self._retirement_poll_timer.stop()
            event.accept()
            return
        if self._runner.active:
            event.ignore()
            QMessageBox.information(
                self,
                self.tr("Radeon deployment is active"),
                self.tr(
                    "Wait for the active Radeon operation to finish, or choose Remove "
                    "to request its safe retirement."
                ),
            )
            return
        self._activity_timer.stop()
        self._retirement_poll_timer.stop()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._shutdown:
            self.refresh_inventory()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(self._intro_label)

        selection_form = QFormLayout()
        installation_row = QWidget(parent=self)
        installation_layout = QHBoxLayout(installation_row)
        installation_layout.setContentsMargins(0, 0, 0, 0)
        installation_layout.setSpacing(8)
        installation_layout.addWidget(self._installation_combo, 1)
        installation_layout.addWidget(self._refresh_inventory_button)
        selection_form.addRow(self._installation_label, installation_row)
        selection_form.addRow(self._model_label, self._model_selector)
        selection_form.addRow(self._model_details)
        selection_form.addRow(self._location_label, self._location_selector)
        layout.addLayout(selection_form)

        private_layout = QVBoxLayout(self._private_panel)
        private_layout.setContentsMargins(12, 12, 12, 12)
        private_layout.setSpacing(8)
        private_layout.addWidget(self._private_heading)
        private_form = QFormLayout()
        private_form.addRow(self._private_target_label, self._private_target_combo)
        private_form.addRow(self._private_target_hint)
        private_layout.addLayout(private_form)
        credentials_form = QFormLayout(self._private_credentials_panel)
        credentials_form.setContentsMargins(0, 0, 0, 0)
        credentials_form.addRow(self._host_label, self._host_input)
        credentials_form.addRow(self._user_label, self._user_input)
        credentials_form.addRow(self._port_label, self._port_input)
        identity_row = QWidget(parent=self._private_credentials_panel)
        identity_layout = QHBoxLayout(identity_row)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(8)
        identity_layout.addWidget(self._identity_file_input, 1)
        identity_layout.addWidget(self._identity_file_browse_button)
        credentials_form.addRow(self._identity_file_label, identity_row)
        private_layout.addWidget(self._private_credentials_panel)
        layout.addWidget(self._private_panel)

        wsl_layout = QVBoxLayout(self._wsl_panel)
        wsl_layout.setContentsMargins(12, 12, 12, 12)
        wsl_layout.setSpacing(8)
        wsl_layout.addWidget(self._wsl_heading)
        wsl_form = QFormLayout()
        wsl_row = QWidget(parent=self._wsl_panel)
        wsl_row_layout = QHBoxLayout(wsl_row)
        wsl_row_layout.setContentsMargins(0, 0, 0, 0)
        wsl_row_layout.setSpacing(8)
        wsl_row_layout.addWidget(self._wsl_distribution_combo, 1)
        wsl_row_layout.addWidget(self._wsl_refresh_button)
        wsl_form.addRow(self._wsl_distribution_label, wsl_row)
        wsl_form.addRow(self._wsl_hint)
        wsl_layout.addLayout(wsl_form)
        layout.addWidget(self._wsl_panel)

        status_form = QFormLayout()
        status_form.addRow(self._condition_label, self._condition_value)
        status_form.addRow(self._phase_label, self._phase_value)
        status_form.addRow(self._support_code_label, self._support_code_value)
        status_form.addRow(self._details_label, self._details_value)
        layout.addLayout(status_form)
        layout.addWidget(self._activity_label)
        layout.addWidget(self._activity_view, 1)

        actions = QHBoxLayout()
        actions.addWidget(self._install_button)
        actions.addWidget(self._repair_button)
        actions.addWidget(self._remove_button)
        actions.addStretch(1)
        actions.addWidget(self._close_button)
        layout.addLayout(actions)

    def _wire_events(self) -> None:
        self._installation_combo.currentIndexChanged.connect(self._on_installation_changed)
        self._model_selector.currentIndexChanged.connect(self._on_model_changed)
        self._location_selector.currentIndexChanged.connect(self._on_location_changed)
        self._private_target_combo.currentIndexChanged.connect(self._on_private_target_changed)
        self._refresh_inventory_button.clicked.connect(self.refresh_inventory)
        self._wsl_refresh_button.clicked.connect(self._request_wsl_discovery)
        self._identity_file_browse_button.clicked.connect(self._browse_identity_file)
        self._install_button.clicked.connect(self._start_install)
        self._repair_button.clicked.connect(self._start_repair)
        self._remove_button.clicked.connect(self._start_retire)
        self._close_button.clicked.connect(self.close)

    def _on_installation_changed(self, _index: int) -> None:
        if self._ui_loading or self._shutdown:
            return
        if self._selected_installation_id() is None:
            self._pending_installation_id = _new_installation_id()
            self._pending_target_id = _new_target_id()
        self._sync_context()
        self._emit_status_condition()

    def _on_location_changed(self, _index: int) -> None:
        if self._ui_loading or self._shutdown:
            return
        self._sync_context()
        if self._current_location() == _LOCAL_WSL:
            self._request_wsl_discovery()

    def _on_model_changed(self, _index: int) -> None:
        if self._ui_loading or self._shutdown:
            return
        self._sync_context()

    def _on_private_target_changed(self, _index: int) -> None:
        if self._ui_loading or self._shutdown:
            return
        target = self._selected_private_target()
        if target is not None and not target.security_enrolled:
            self._prefill_incomplete_target(target)
        self._sync_context()

    def _browse_identity_file(self) -> None:
        if self._shutdown or self._runner.active:
            return
        initial = self._identity_file_input.text().strip()
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            self.tr("Choose SSH private identity file"),
            initial,
            self.tr("All files (*)"),
        )
        if selected:
            self._identity_file_input.setText(selected)

    def _request_wsl_discovery(self) -> None:
        if self._shutdown or self._runner.active or self._current_location() != _LOCAL_WSL:
            return
        operation_id = self._runner.start_local_wsl_discovery()
        if operation_id is not None:
            self._wsl_discovery_operation_id = operation_id
            self._wsl_discovery_active = True
            self._begin_primary(
                "wsl_discovery",
                self.tr("Discovering local WSL2 distributions."),
                operation_id=operation_id,
            )

    def _start_install(self) -> None:
        installation = self._current_installation()
        if (
            self._shutdown
            or self._runner.active
            or (installation is not None and not self._requires_private_security_setup())
        ):
            return
        location = self._current_location()
        if location == _PRIVATE_SSH:
            target = self._selected_private_target()
            if target is not None and target.security_enrolled:
                command = AmdExistingPrivateSshInstallCommand(
                    installation_id=self._pending_installation_id,
                    target_id=target.target_id,
                    option_id=self._selected_option_id(),
                )
                operation_id = self._runner.start_existing_private_install(command)
                if operation_id is not None:
                    self._begin_primary(
                        "install",
                        self.tr("Starting installation on the enrolled SSH target."),
                        operation_id=operation_id,
                        installation_id=command.installation_id,
                    )
                return
            command = self._private_install_command(target)
            try:
                self._runner.validate_private_fields(command)
            except AmdGuidedDeploymentError as exc:
                self._show_error(exc.error_code, exc.field)
                return
            operation_id = self._runner.start_host_trust(command)
            if operation_id is not None:
                self._host_trust_operation_id = operation_id
                self._begin_primary(
                    "host_trust",
                    self.tr("Reading the SSH server identity before authentication."),
                    operation_id=operation_id,
                )
            return
        if location == _LOCAL_WSL:
            distribution = str(self._wsl_distribution_combo.currentData() or "")
            if not distribution:
                self._show_error(
                    "amd_wsl_distribution_unavailable",
                    AmdGuidedInputField.WSL_DISTRIBUTION,
                )
                return
            command = AmdLocalWslInstallCommand(
                installation_id=self._pending_installation_id,
                distribution=distribution,
                option_id=self._selected_option_id(),
            )
            operation_id = self._runner.start_local_wsl_install(command)
            if operation_id is not None:
                self._begin_primary(
                    "install",
                    self.tr("Starting installation in the selected WSL2 distribution."),
                    operation_id=operation_id,
                    installation_id=command.installation_id,
                )
            return
        self._show_error("amd_request_invalid", None)

    def _start_repair(self) -> None:
        installation = self._current_installation()
        if (
            self._shutdown
            or installation is None
            or self._runner.active
            or not installation.desired_presence
        ):
            return
        operation_id = self._runner.start_repair(installation.installation_id)
        if operation_id is not None:
            self._begin_primary(
                "repair",
                self.tr("Starting forward repair."),
                operation_id=operation_id,
                installation_id=installation.installation_id,
            )

    def _start_retire(self) -> None:
        installation = self._current_installation()
        installation_id = (
            installation.installation_id
            if installation is not None
            else self._active_installation_id
        )
        if (
            self._shutdown
            or installation_id is None
            or (installation is not None and not installation.desired_presence)
            or self._retirement_active
        ):
            return
        answer = QMessageBox.question(
            self,
            self.tr("Remove Radeon deployment?"),
            self.tr(
                "Remove Radeon {capability} from this location? Xenix will commit the removal "
                "request first, then safely retire the exact managed runtime."
            ).format(capability=_capability_label(self, self._capability)),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer is not QMessageBox.Yes:
            return
        operation_id = self._runner.start_retire(installation_id)
        if operation_id is not None:
            self._retirement_active = True
            self._retirement_operation_id = operation_id
            self._retiring_installation_id = installation_id
            self._display_operation_id = operation_id
            self._activity_timer.stop()
            self._operation_started_at = None
            self._phase = "retirement_requesting"
            self._details = self.tr("Recording the removal request safely.")
            self._append_activity(self._details)
            self._render_state()
            self._emit_status_condition()
            self._sync_context()

    def _finish_host_trust(self, result: object) -> None:
        if not isinstance(result, AmdHostTrustTaskResult):
            return
        if (
            result.operation_id != self._host_trust_operation_id
            or result.operation_id != self._primary_operation_id
        ):
            return
        self._primary_active = False
        self._primary_operation_id = None
        self._host_trust_operation_id = None
        self._stop_activity_timer_when_idle()
        if self._shutdown or result.operation_id != self._display_operation_id:
            self._flush_pending_inventory_refresh()
            return
        if not result.succeeded or result.challenge is None:
            self._show_error(result.error_code or "amd_operation_failed", result.invalid_field)
            return
        self._phase = "host_trust_awaiting"
        self._details = self.tr("Confirm the server fingerprint before enrollment.")
        self._append_activity(self.tr("SSH server identity discovered; confirmation is required."))
        self._render_state()
        if not self._confirm_host_trust(result.challenge):
            self._condition = "not_materialized"
            self._phase = "host_trust_declined"
            self._error_code = None
            self._invalid_field = None
            self._details = self.tr("The SSH server identity was not accepted. No target credentials were saved.")
            self._append_activity(self.tr("SSH server trust was declined."))
            self._render_state()
            self._emit_status_condition()
            self._sync_context()
            return
        operation_id = self._runner.start_private_install(result.command, result.challenge)
        if operation_id is not None:
            self._begin_primary(
                "install",
                self.tr("Server trust accepted. Starting installation."),
                operation_id=operation_id,
                installation_id=result.command.installation_id,
            )

    def _finish_wsl_discovery(self, result: object) -> None:
        if not isinstance(result, AmdLocalWslDiscoveryTaskResult):
            return
        if (
            result.operation_id != self._wsl_discovery_operation_id
            or result.operation_id != self._primary_operation_id
        ):
            return
        self._primary_active = False
        self._primary_operation_id = None
        self._wsl_discovery_operation_id = None
        self._wsl_discovery_active = False
        self._stop_activity_timer_when_idle()
        if self._shutdown or result.operation_id != self._display_operation_id:
            self._flush_pending_inventory_refresh()
            return
        if not result.succeeded:
            self._show_error(result.error_code or "amd_wsl_distribution_unavailable", result.invalid_field)
            return
        previous = str(self._wsl_distribution_combo.currentData() or "")
        self._ui_loading = True
        self._wsl_distribution_combo.clear()
        for distribution in result.distributions:
            self._wsl_distribution_combo.addItem(distribution, distribution)
        index = self._wsl_distribution_combo.findData(previous)
        self._wsl_distribution_combo.setCurrentIndex(index if index >= 0 else -1)
        self._ui_loading = False
        if result.distributions:
            self._details = self.tr("Choose a WSL2 distribution, then install this capability.")
            self._append_activity(self.tr("Local WSL2 distributions were refreshed."))
        else:
            self._details = self.tr("No WSL2 distributions were found on this PC.")
            self._append_activity(self._details)
        self._error_code = None
        self._invalid_field = None
        self._condition = "not_materialized"
        self._phase = "wsl_discovery_completed"
        self._render_state()
        self._emit_status_condition()
        self._sync_context()

    def _finish_operation(self, result: object) -> None:
        if not isinstance(result, AmdCapabilityTaskResult):
            return
        if result.operation_id != self._primary_operation_id:
            return
        self._primary_active = False
        self._primary_operation_id = None
        if result.installation_id == self._active_installation_id:
            self._active_installation_id = None
        self._stop_activity_timer_when_idle()
        if self._shutdown or result.operation_id != self._display_operation_id:
            self._request_inventory_refresh(result.installation_id)
            return
        self._condition = result.condition
        self._phase = result.phase
        if result.succeeded:
            self._error_code = None
            self._invalid_field = None
            self._details = self._success_message(result)
            self._append_activity(self._details)
            self.provider_projections_may_have_changed.emit()
            self._render_state()
            self._request_inventory_refresh(result.installation_id)
            return
        self._show_error(
            result.error_code or "amd_operation_failed",
            result.invalid_field,
            condition=result.condition,
            phase=result.phase,
        )
        self._request_inventory_refresh(result.installation_id)

    def _finish_retirement_acknowledgement(self, result: object) -> None:
        if not isinstance(result, AmdRetirementAcknowledgement):
            return
        if result.operation_id != self._retirement_operation_id:
            return
        self._retirement_active = False
        self._retirement_operation_id = None
        if self._shutdown:
            return
        if result.operation_id != self._display_operation_id:
            self._request_inventory_refresh(result.installation_id)
            return
        if not result.acknowledged:
            self._retiring_installation_id = None
            if self._primary_operation_id is not None:
                self._display_operation_id = self._primary_operation_id
            self._show_error(result.error_code or "amd_operation_failed", result.invalid_field)
            self._request_inventory_refresh(result.installation_id)
            return
        self._condition = (
            "removed" if result.request_phase == "already_removed" else "retiring"
        )
        self._phase = result.request_phase or "retirement_requested"
        self._error_code = None
        self._invalid_field = None
        self._details = self._retirement_acknowledgement_message(result)
        self._append_activity(self._details)
        self.provider_projections_may_have_changed.emit()
        self._render_state()
        self._emit_status_condition()
        self._sync_context()
        self._request_inventory_refresh(result.installation_id)

    def _append_progress(self, update: object) -> None:
        if self._shutdown or not isinstance(update, AmdCapabilityProgressUpdate):
            return
        if (
            update.operation_id != self._primary_operation_id
            or update.operation_id != self._display_operation_id
        ):
            return
        event = update.event
        self._condition = "installing"
        self._phase = event.milestone.value
        self._details = _progress_message(self, event)
        self._append_activity(self._details)
        self._render_state()
        self._emit_status_condition()

    def _append_activity_heartbeat(self) -> None:
        if (
            self._shutdown
            or not self._primary_active
            or self._primary_operation_id != self._display_operation_id
        ):
            return
        elapsed = 0
        if self._operation_started_at is not None:
            elapsed = max(0, int(time.monotonic() - self._operation_started_at))
        self._append_activity(
            self.tr("Still working ({seconds} s): {phase}").format(
                seconds=elapsed,
                phase=_phase_label(self, self._phase),
            )
        )

    def _begin_primary(
        self,
        phase: str,
        details: str,
        *,
        operation_id: int,
        installation_id: str | None = None,
    ) -> None:
        self._primary_active = True
        self._primary_operation_id = operation_id
        self._display_operation_id = operation_id
        if installation_id is not None:
            self._active_installation_id = installation_id
        self._condition = "installing"
        self._phase = phase
        self._error_code = None
        self._invalid_field = None
        self._details = details
        self._operation_started_at = time.monotonic()
        self._activity_timer.start()
        self._append_activity(details)
        self._render_state()
        self._emit_status_condition()
        self._sync_context()

    def _stop_activity_timer_when_idle(self) -> None:
        if not self._primary_active:
            self._activity_timer.stop()
            self._operation_started_at = None
        self._sync_context()

    def _show_error(
        self,
        error_code: str,
        field: AmdGuidedInputField | None,
        *,
        condition: str = "failed",
        phase: str = "failed",
    ) -> None:
        code = _safe_code(error_code)
        self._condition = condition
        self._phase = phase
        self._error_code = code
        self._invalid_field = field
        self._details = _error_message(self, code)
        self._append_activity(self._details)
        self._render_state()
        self._emit_status_condition()
        self._focus_invalid_field(field)
        QMessageBox.warning(
            self,
            self.tr("Radeon setup needs attention"),
            self._details,
        )

    def _record_nonblocking_error(self, error_code: str | None) -> None:
        self._error_code = error_code
        self._details = _error_message(self, error_code)
        self._append_activity(self._details)
        self._render_state()

    def _confirm_host_trust(self, challenge: AmdSshHostTrustChallenge) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(self.tr("Trust this SSH server?"))
        box.setText(
            self.tr("Verify this server fingerprint with the server or cloud owner before continuing.")
        )
        box.setInformativeText(
            self.tr("Algorithm: {algorithm}\nFingerprint: {fingerprint}").format(
                algorithm=challenge.algorithm,
                fingerprint=challenge.fingerprint,
            )
        )
        trust = box.addButton(self.tr("Trust and install"), QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        return box.clickedButton() is trust

    def _sync_context(self) -> None:
        if self._shutdown:
            return
        installation = self._current_installation()
        is_new = installation is None
        location = self._current_location()
        active = self._primary_active or self._retirement_active or self._runner.active
        pending_installation = self._active_installation_id is not None
        self._ui_loading = True
        try:
            if installation is not None:
                self._set_location(location=installation.placement)
                if installation.placement == _PRIVATE_SSH and installation.target_id:
                    self._set_private_target(installation.target_id)
                if installation.placement == _LOCAL_WSL and installation.local_wsl_distribution:
                    self._set_wsl_distribution(installation.local_wsl_distribution)
            self._rebuild_model_selector()
            self._location_selector.setEnabled(is_new and not active)
            self._installation_combo.setEnabled(not active and not self._retirement_active)
            self._refresh_inventory_button.setEnabled(not active and not self._retirement_active)
            model_visible = self._capability is ManifestCapability.CHAT
            self._model_label.setVisible(model_visible)
            self._model_selector.setVisible(model_visible)
            self._model_details.setVisible(model_visible)
            self._model_selector.setEnabled(model_visible and is_new and not active)
            self._model_details.setText(self._model_details_text(self._selected_option()))
            private_visible = location == _PRIVATE_SSH
            wsl_visible = location == _LOCAL_WSL
            self._private_panel.setVisible(private_visible)
            self._wsl_panel.setVisible(wsl_visible)
            target = self._selected_private_target()
            if target is not None and not target.security_enrolled:
                # An existing enrollment is immutable.  A missing local
                # credential checkpoint is recoverable, but it must not turn
                # the saved target identity into a silently edited "new"
                # target.  Only the identity-file checkpoint remains editable.
                self._prefill_incomplete_target(target)
            reusable_target = target is not None and target.security_enrolled
            target_identity_locked = target is not None and not target.security_enrolled
            continuing_private_setup = self._requires_private_security_setup()
            needs_credentials = (
                private_visible
                and (is_new or continuing_private_setup)
                and not reusable_target
            )
            self._private_target_combo.setEnabled(is_new and private_visible and not active)
            self._private_credentials_panel.setVisible(needs_credentials)
            for widget in (
                self._host_input,
                self._user_input,
                self._port_input,
            ):
                widget.setEnabled(
                    needs_credentials and not active and not target_identity_locked
                )
            for widget in (self._identity_file_input, self._identity_file_browse_button):
                widget.setEnabled(needs_credentials and not active)
            self._wsl_distribution_combo.setEnabled(is_new and wsl_visible and not active)
            self._wsl_refresh_button.setEnabled(
                is_new and wsl_visible and not active and not self._wsl_discovery_active
            )
            self._private_target_hint.setText(
                self._private_target_message(target, needs_credentials)
            )
            self._wsl_hint.setText(self._wsl_message(installation))
            installable = is_new or continuing_private_setup
            self._install_button.setVisible(installable)
            self._install_button.setText(
                self.tr("Continue setup")
                if continuing_private_setup
                else self.tr("Install")
            )
            self._repair_button.setVisible(not is_new and not continuing_private_setup)
            self._install_button.setEnabled(
                installable
                and self._selected_option_id() is not None
                and not active
                and not self._retirement_active
            )
            self._repair_button.setEnabled(
                installation is not None
                and installation.desired_presence
                and not active
                and not self._retirement_active
            )
            self._remove_button.setVisible(not is_new or pending_installation)
            self._remove_button.setEnabled(
                (
                    (installation is not None and installation.desired_presence)
                    or (installation is None and pending_installation)
                )
                and not self._retirement_active
                and self._retiring_installation_id is None
            )
            self._close_button.setEnabled(not self._shutdown)
        finally:
            self._ui_loading = False
        if not active:
            self._adopt_inventory_condition(installation)

    def _adopt_inventory_condition(
        self,
        installation: AmdGuidedCapabilityInstallation | None,
    ) -> None:
        if installation is None:
            if self._condition not in {"failed", "installing"}:
                self._condition = "not_materialized"
                self._phase = "idle"
                if self._error_code is None:
                    self._details = self.tr(
                        "Choose an execution location and install only this capability."
                    )
            self._render_state()
            return
        if self._condition != "failed":
            self._condition = installation.status.condition.value
            self._phase = _installation_phase(installation)
            if self._error_code is None:
                self._details = _installation_details(self, installation)
        self._render_state()

    def _private_target_message(
        self,
        target: AmdGuidedPrivateTarget | None,
        needs_credentials: bool,
    ) -> str:
        if not needs_credentials:
            if target is not None:
                return self.tr("The existing trusted SSH target will be reused for this capability.")
            return self.tr("This deployment keeps its existing Private SSH target.")
        if target is not None:
            return self.tr(
                "This target needs its local identity file to be enrolled again. "
                "Its saved host identity is locked; verify the fingerprint before "
                "installation continues."
            )
        return self.tr("Enter a new SSH target. The server public key is confirmed interactively.")

    def _wsl_message(
        self,
        installation: AmdGuidedCapabilityInstallation | None,
    ) -> str:
        if installation is not None and installation.local_wsl_distribution:
            return self.tr("This deployment is bound to its saved WSL2 distribution.")
        if self._wsl_discovery_active:
            return self.tr("Discovering WSL2 distributions without blocking the Settings window.")
        if self._wsl_distribution_combo.count() == 0:
            return self.tr("Refresh distributions to discover local WSL2 targets.")
        return self.tr("The selected distribution is checked before Xenix changes it.")

    def _private_install_command(
        self,
        selected_target: AmdGuidedPrivateTarget | None,
    ) -> AmdPrivateSshInstallCommand:
        installation = self._current_installation()
        existing_target_id = (
            installation.target_id
            if installation is not None
            and installation.placement == _PRIVATE_SSH
            and installation.target_id
            else None
        )
        return AmdPrivateSshInstallCommand(
            installation_id=(
                installation.installation_id
                if installation is not None
                else self._pending_installation_id
            ),
            target_id=(
                selected_target.target_id
                if selected_target is not None
                else existing_target_id or self._pending_target_id
            ),
            host=self._host_input.text().strip(),
            user=self._user_input.text().strip(),
            port=self._port_input.value(),
            identity_file=(
                Path(self._identity_file_input.text().strip())
                if self._identity_file_input.text().strip()
                else None
            ),
            option_id=self._selected_option_id(),
        )

    def _prefill_incomplete_target(self, target: AmdGuidedPrivateTarget) -> None:
        previous_loading = self._ui_loading
        self._ui_loading = True
        try:
            self._host_input.setText(target.host)
            self._user_input.setText(target.user)
            self._port_input.setValue(target.port)
        finally:
            self._ui_loading = previous_loading

    def _rebuild_installation_selector(self, *, selected_id: str | None = None) -> None:
        if self._shutdown:
            return
        selected = selected_id if selected_id is not None else self._selected_installation_id()
        self._ui_loading = True
        self._installation_combo.clear()
        self._installation_combo.addItem(
            self.tr("New Radeon {capability} deployment").format(
                capability=_capability_label(self, self._capability)
            ),
            None,
        )
        for installation in self._inventory.values():
            self._installation_combo.addItem(
                self._installation_label_for(installation),
                installation.installation_id,
            )
        index = self._installation_combo.findData(selected)
        self._installation_combo.setCurrentIndex(index if index >= 0 else 0)
        self._ui_loading = False

    def _rebuild_private_target_selector(self) -> None:
        if self._shutdown:
            return
        selected = str(self._private_target_combo.currentData() or "")
        self._ui_loading = True
        self._private_target_combo.clear()
        self._private_target_combo.addItem(self.tr("Add a new SSH target"), "")
        for target in self._private_targets.values():
            suffix = "" if target.security_enrolled else self.tr(" (needs setup)")
            self._private_target_combo.addItem(
                f"{target.host} · {target.user} · {target.port}{suffix}",
                target.target_id,
            )
        index = self._private_target_combo.findData(selected)
        self._private_target_combo.setCurrentIndex(index if index >= 0 else 0)
        self._ui_loading = False

    def _rebuild_model_selector(self) -> None:
        if self._shutdown:
            return
        installation = self._current_installation()
        selected = (
            installation.option.option_id
            if installation is not None and installation.option is not None
            else self._selected_option_id()
        )
        location = self._current_location()
        previous_loading = self._ui_loading
        self._ui_loading = True
        try:
            self._model_selector.clear()
            for option in self._deployment_options:
                if option.placement != location:
                    continue
                self._model_selector.addItem(self._model_option_label(option), option.option_id)
            index = self._model_selector.findData(selected)
            self._model_selector.setCurrentIndex(index if index >= 0 else (0 if self._model_selector.count() else -1))
        finally:
            self._ui_loading = previous_loading

    def _model_option_label(self, option: AmdCapabilityDeploymentOption) -> str:
        variants = {
            "recommended": self.tr("Recommended"),
            "lightweight": self.tr("Lightweight"),
        }
        variant = variants.get(option.variant)
        return (
            self.tr("{model} — {variant}").format(model=option.display_name, variant=variant)
            if variant
            else option.display_name
        )

    def _model_details_text(self, option: AmdCapabilityDeploymentOption | None) -> str:
        if option is None:
            return self.tr("No verified Radeon model is available for this execution location.")
        facts = [option.model_id, self.tr("License: {license}").format(license=option.license_spdx)]
        if option.context_limit is not None:
            facts.append(
                self.tr("Context: {tokens} tokens").format(tokens=f"{option.context_limit:,}")
            )
        if option.minimum_free_vram_bytes is not None:
            facts.append(
                self.tr("Free VRAM required: {size}").format(
                    size=_format_decimal_gb(option.minimum_free_vram_bytes)
                )
            )
        if option.required_persistent_bytes is not None:
            facts.append(
                self.tr("Storage required: {size}").format(
                    size=_format_decimal_gb(option.required_persistent_bytes)
                )
            )
        capabilities = []
        if option.supports_streaming:
            capabilities.append(self.tr("streaming"))
        if option.supports_tool_calls:
            capabilities.append(self.tr("tool calls"))
        if option.supports_reasoning:
            capabilities.append(self.tr("reasoning"))
        if capabilities:
            facts.append(
                self.tr("Capabilities: {capabilities}").format(
                    capabilities=self.tr(", ").join(capabilities)
                )
            )
        return self.tr(" · ").join(facts)

    def _installation_label_for(
        self,
        installation: AmdGuidedCapabilityInstallation,
    ) -> str:
        location = _location_label(self, installation.placement)
        condition = _condition_label(self, installation.status.condition.value)
        model = installation.option.display_name if installation.option is not None else self.tr("Unknown model")
        return self.tr("{model} · {location} · {condition}").format(
            model=model,
            location=location,
            condition=condition,
        )

    def _set_location(self, *, location: str) -> None:
        index = self._location_selector.findData(location)
        if index >= 0:
            self._location_selector.setCurrentIndex(index)

    def _set_private_target(self, target_id: str) -> None:
        index = self._private_target_combo.findData(target_id)
        if index >= 0:
            self._private_target_combo.setCurrentIndex(index)

    def _set_wsl_distribution(self, distribution: str) -> None:
        index = self._wsl_distribution_combo.findData(distribution)
        if index >= 0:
            self._wsl_distribution_combo.setCurrentIndex(index)
        else:
            self._wsl_distribution_combo.setCurrentIndex(-1)

    def _set_location_item_text(self, location: str, text: str) -> None:
        index = self._location_selector.findData(location)
        if index >= 0:
            self._location_selector.setItemText(index, text)

    def _current_installation(self) -> AmdGuidedCapabilityInstallation | None:
        installation_id = self._selected_installation_id()
        return self._inventory.get(installation_id) if installation_id else None

    def _selected_installation_id(self) -> str | None:
        value = self._installation_combo.currentData()
        return value if isinstance(value, str) and value else None

    def _selected_private_target(self) -> AmdGuidedPrivateTarget | None:
        target_id = self._private_target_combo.currentData()
        return self._private_targets.get(target_id) if isinstance(target_id, str) else None

    def _selected_option(self) -> AmdCapabilityDeploymentOption | None:
        installation = self._current_installation()
        if installation is not None:
            return installation.option
        return self._deployment_options_by_id.get(self._selected_option_id())

    def _selected_option_id(self) -> str | None:
        value = self._model_selector.currentData()
        if isinstance(value, str) and value:
            return value
        location_options = tuple(
            option for option in self._deployment_options if option.placement == self._current_location()
        )
        return location_options[0].option_id if len(location_options) == 1 else None

    def _requires_private_security_setup(self) -> bool:
        installation = self._current_installation()
        if (
            installation is None
            or installation.placement != _PRIVATE_SSH
            or not installation.desired_presence
            or not installation.target_id
        ):
            return False
        target = self._private_targets.get(installation.target_id)
        return target is not None and not target.security_enrolled

    def _current_location(self) -> str:
        installation = self._current_installation()
        if installation is not None:
            return installation.placement
        value = self._location_selector.currentData()
        return str(value) if isinstance(value, str) else _PRIVATE_SSH

    def _render_state(self) -> None:
        self._condition_value.setText(_condition_label(self, self._condition))
        self._phase_value.setText(_phase_label(self, self._phase))
        self._support_code_value.setText(self._error_code or self.tr("None"))
        self._details_value.setText(self._details)

    def _emit_status_condition(self) -> None:
        if self._shutdown:
            return
        if self._retirement_active or self._retiring_installation_id is not None:
            self.status_changed.emit("retiring")
            return
        if self._primary_active:
            self.status_changed.emit("installing")
            return
        installation = self._current_installation()
        if installation is not None:
            self.status_changed.emit(installation.status.condition.value)
            return
        self.status_changed.emit("degraded" if self._condition == "failed" else "not_materialized")

    def _schedule_retirement_poll(self) -> None:
        if self._shutdown:
            return
        if any(
            installation.lifecycle_state == "retiring"
            for installation in self._inventory.values()
        ):
            self._retirement_poll_timer.start()
        else:
            self._retirement_poll_timer.stop()

    def _append_activity(self, message: str) -> None:
        if self._shutdown or not message:
            return
        self._activity_sequence += 1
        timestamp = time.strftime("%H:%M:%S")
        self._activity_view.appendPlainText(
            f"{timestamp}  {self._activity_sequence:03d}  {message}"
        )

    def _focus_invalid_field(self, field: AmdGuidedInputField | None) -> None:
        fields: dict[AmdGuidedInputField, QWidget] = {
            AmdGuidedInputField.HOST: self._host_input,
            AmdGuidedInputField.USER: self._user_input,
            AmdGuidedInputField.PORT: self._port_input,
            AmdGuidedInputField.IDENTITY_FILE: self._identity_file_input,
            AmdGuidedInputField.WSL_DISTRIBUTION: self._wsl_distribution_combo,
        }
        widget = fields.get(field) if field is not None else None
        if widget is not None and widget.isVisible():
            widget.setFocus(Qt.OtherFocusReason)

    def _success_message(self, result: AmdCapabilityTaskResult) -> str:
        return self.tr("Radeon {capability} is operational.").format(
            capability=_capability_label(self, self._capability)
        )

    def _retirement_acknowledgement_message(
        self,
        acknowledgement: AmdRetirementAcknowledgement,
    ) -> str:
        if acknowledgement.request_phase == "already_removed":
            return self.tr("The Radeon deployment has already been removed.")
        return self.tr(
            "Removal is requested. Xenix will continue safe physical cleanup."
        )


def _capability_label(owner: QObject, capability: ManifestCapability) -> str:
    labels = {
        ManifestCapability.CHAT: owner.tr("LLM"),
        ManifestCapability.EMBEDDING: owner.tr("Embedding"),
        ManifestCapability.OCR: owner.tr("OCR"),
    }
    return labels[capability]


def _location_label(owner: QObject, placement: str) -> str:
    labels = {
        _PRIVATE_SSH: owner.tr("Private SSH"),
        _LOCAL_WSL: owner.tr("This PC (WSL2)"),
    }
    return labels.get(placement, owner.tr("Unknown location"))


def _condition_label(owner: QObject, condition: str) -> str:
    labels = {
        "not_materialized": owner.tr("Not installed"),
        "installing": owner.tr("Installing"),
        "degraded": owner.tr("Needs repair"),
        "operational": owner.tr("Operational"),
        "retiring": owner.tr("Removal in progress"),
        "removal_blocked": owner.tr("Removal needs attention"),
        "removed": owner.tr("Removed"),
        "incompatible": owner.tr("Not compatible"),
        "failed": owner.tr("Needs attention"),
        "multiple": owner.tr("Multiple deployment locations"),
    }
    return labels.get(condition, owner.tr("Unknown status"))


def _capability_inventory_condition(
    inventory: tuple[AmdGuidedCapabilityInstallation, ...],
) -> str | None:
    """Summarize a capability without choosing one of several locations."""

    if not inventory:
        return None
    if len(inventory) == 1:
        return inventory[0].status.condition.value
    if any(item.status.condition.value == "removal_blocked" for item in inventory):
        return "removal_blocked"
    if any(item.status.condition.value == "degraded" for item in inventory):
        return "degraded"
    if any(item.status.condition.value == "incompatible" for item in inventory):
        return "incompatible"
    if any(item.status.condition.value == "retiring" for item in inventory):
        return "retiring"
    return "multiple"


def _phase_label(owner: QObject, phase: str) -> str:
    labels = {
        "idle": owner.tr("Ready"),
        "wsl_discovery": owner.tr("Discovering WSL2"),
        "wsl_discovery_completed": owner.tr("WSL2 discovery complete"),
        "host_trust": owner.tr("Reading SSH server identity"),
        "host_trust_awaiting": owner.tr("Waiting for server trust"),
        "host_trust_declined": owner.tr("Server trust declined"),
        "install": owner.tr("Installing"),
        "repair": owner.tr("Repairing"),
        "retirement_requesting": owner.tr("Requesting removal"),
        "retirement_requested": owner.tr("Removal requested"),
        "retirement_already_requested": owner.tr("Removal already requested"),
        "failed": owner.tr("Failed"),
    }
    return labels.get(phase, phase.replace("_", " ").capitalize())


def _progress_message(owner: QObject, event: AmdProgressEvent) -> str:
    messages = {
        AmdProgressMilestone.INPUT_VALIDATED: owner.tr("Input was validated."),
        AmdProgressMilestone.HOST_KEY_DISCOVERY_STARTED: owner.tr(
            "Reading the SSH server public identity."
        ),
        AmdProgressMilestone.HOST_KEY_DISCOVERED: owner.tr(
            "The SSH server presented a supported public key."
        ),
        AmdProgressMilestone.HOST_TRUST_AWAITING: owner.tr(
            "Waiting for explicit SSH server trust."
        ),
        AmdProgressMilestone.HOST_TRUST_ACCEPTED: owner.tr("SSH server trust was accepted."),
        AmdProgressMilestone.INSTALL_INTENT_SAVING: owner.tr(
            "Saving the capability installation intent."
        ),
        AmdProgressMilestone.INSTALL_INTENT_SAVED: owner.tr(
            "The capability installation intent was saved."
        ),
        AmdProgressMilestone.SSH_SECURITY_SAVING: owner.tr(
            "Saving the accepted SSH trust and identity reference."
        ),
        AmdProgressMilestone.SSH_SECURITY_SAVED: owner.tr(
            "SSH security enrollment was saved."
        ),
        AmdProgressMilestone.TARGET_INSPECTION_STARTED: owner.tr(
            "Inspecting Radeon hardware, ROCm, and target capacity."
        ),
        AmdProgressMilestone.TARGET_COMPATIBLE: owner.tr(
            "The Radeon target matches the bundled compatibility profile."
        ),
        AmdProgressMilestone.COMPONENT_PREPARATION_STARTED: owner.tr(
            "Preparing the selected Radeon capability."
        ),
        AmdProgressMilestone.COMPONENT_PREPARED: owner.tr(
            "The selected Radeon capability is prepared."
        ),
        AmdProgressMilestone.RUNTIME_STARTING: owner.tr("Starting the managed runtime."),
        AmdProgressMilestone.RUNTIME_STARTED: owner.tr("The managed runtime started."),
        AmdProgressMilestone.SELF_TEST_STARTED: owner.tr(
            "Running the capability protocol self-test."
        ),
        AmdProgressMilestone.SELF_TEST_PASSED: owner.tr(
            "The capability protocol self-test passed."
        ),
        AmdProgressMilestone.PROVIDER_REGISTRATION_STARTED: owner.tr(
            "Registering the managed provider projection."
        ),
        AmdProgressMilestone.PROVIDER_REGISTERED: owner.tr(
            "The managed provider projection was registered."
        ),
        AmdProgressMilestone.OPERATIONAL: owner.tr("The Radeon capability is operational."),
    }
    return messages[event.milestone]


def _installation_phase(installation: AmdGuidedCapabilityInstallation) -> str:
    components = tuple(installation.status.components)
    if not components:
        return installation.lifecycle_state
    error = next((component for component in components if component.error_code), None)
    component = error or next(
        (candidate for candidate in components if candidate.phase != "registered"),
        components[0],
    )
    return component.phase


def _installation_details(
    owner: QObject,
    installation: AmdGuidedCapabilityInstallation,
) -> str:
    condition = installation.status.condition.value
    if condition == "operational":
        return owner.tr("The managed provider is available after the next Settings reopen.")
    if condition == "retiring":
        return owner.tr("Removal is durably requested and safe physical cleanup continues.")
    if condition == "removal_blocked":
        return owner.tr("Safe removal needs restored target access before it can continue.")
    if condition == "incompatible":
        return owner.tr("The selected location does not satisfy this fixed Radeon profile.")
    if condition == "degraded":
        return owner.tr("This capability needs forward repair.")
    return owner.tr("This capability has not reached operational state.")


def _safe_code(exc: Exception | str | None) -> str | None:
    value = exc if isinstance(exc, str) else getattr(exc, "error_code", None)
    if isinstance(value, str) and value and len(value) <= 128 and value.replace("_", "").isalnum():
        return value
    return None


def _safe_error_code(exc: Exception) -> str | None:
    return _safe_code(exc) or "amd_operation_failed"


def _format_decimal_gb(value: int) -> str:
    return f"{value / 1_000_000_000:.1f} GB"


def _error_message(owner: QObject, error_code: str | None) -> str:
    messages = {
        "amd_ssh_host_required": owner.tr("Enter the SSH host."),
        "amd_ssh_host_invalid": owner.tr(
            "Enter a valid IP address or DNS host name without spaces."
        ),
        "amd_ssh_user_required": owner.tr("Enter the SSH user."),
        "amd_ssh_user_invalid": owner.tr("Enter a valid OpenSSH user name."),
        "amd_ssh_port_invalid": owner.tr("Enter an SSH port between 1 and 65535."),
        "amd_ssh_identity_required": owner.tr(
            "Choose the private identity file used for SSH authentication."
        ),
        "amd_ssh_identity_invalid": owner.tr(
            "Choose an identity file by its absolute local path."
        ),
        "amd_ssh_identity_unavailable": owner.tr(
            "The selected identity file is not available. Choose an existing file."
        ),
        "amd_ssh_host_key_discovery_failed": owner.tr(
            "Xenix could not read a supported public key from the SSH server. "
            "Verify the host, port, and server availability."
        ),
        "amd_ssh_host_key_discovery_invalid": owner.tr(
            "The SSH server returned an invalid or unsupported host identity."
        ),
        "amd_ssh_host_key_discovery_conflict": owner.tr(
            "The SSH server presented conflicting host keys. Stop and verify it with its owner."
        ),
        "amd_ssh_host_trust_challenge_invalid": owner.tr(
            "The server identity changed before enrollment. Start installation again and verify the new fingerprint."
        ),
        "amd_ssh_security_conflict": owner.tr(
            "These SSH security details conflict with the existing enrollment."
        ),
        "amd_ssh_security_capacity_reached": owner.tr(
            "The local SSH target enrollment limit has been reached."
        ),
        "amd_ssh_security_unavailable": owner.tr(
            "Xenix could not save or read the local SSH security record."
        ),
        "amd_ssh_enrollment_incomplete": owner.tr(
            "This target needs its SSH identity and fingerprint confirmation to be completed."
        ),
        "amd_target_conflict": owner.tr(
            "This target identity conflicts with an existing immutable enrollment."
        ),
        "amd_installation_conflict": owner.tr(
            "This installation identity conflicts with an existing deployment."
        ),
        "amd_component_already_installed": owner.tr(
            "This exact Radeon model is already installed at the selected location."
        ),
        "amd_capability_option_required": owner.tr("Choose a Radeon model to install."),
        "amd_capability_option_unavailable": owner.tr(
            "The selected Radeon model is unavailable for this execution location."
        ),
        "amd_capability_installation_mismatch": owner.tr(
            "The selected Radeon deployment belongs to another capability."
        ),
        "amd_location_conflict": owner.tr(
            "The selected execution location is occupied by an incompatible Radeon deployment."
        ),
        "amd_ssh_client_unavailable": owner.tr(
            "Windows OpenSSH is unavailable. Install or enable the OpenSSH client."
        ),
        "amd_ssh_authentication_failed": owner.tr(
            "SSH authentication failed. Verify the SSH user and identity file."
        ),
        "amd_ssh_connection_timeout": owner.tr(
            "The SSH connection timed out. Verify the host, port, and target availability."
        ),
        "amd_ssh_connection_failed": owner.tr(
            "The SSH target reset or rejected the connection. Verify its availability."
        ),
        "amd_ssh_forward_failed": owner.tr(
            "Xenix could not establish the private loopback connection to the managed service."
        ),
        "amd_ssh_target_unavailable": owner.tr(
            "The enrolled SSH target or its local security material is unavailable."
        ),
        "amd_wsl_client_unavailable": owner.tr(
            "Windows Subsystem for Linux is unavailable on this PC."
        ),
        "amd_wsl_distribution_invalid": owner.tr("The selected WSL2 distribution name is invalid."),
        "amd_wsl_distribution_unavailable": owner.tr(
            "Choose an available WSL2 distribution."
        ),
        "amd_wsl_operation_timeout": owner.tr(
            "The WSL2 target operation timed out. Verify the selected distribution."
        ),
        "amd_wsl_operation_failed": owner.tr(
            "Xenix could not operate the selected WSL2 target safely."
        ),
        "amd_wsl_recipe_unavailable": owner.tr(
            "The bundled WSL2 deployment recipe is unavailable."
        ),
        "amd_wsl_recipe_failed": owner.tr(
            "The WSL2 Radeon capability could not be deployed or verified."
        ),
        "amd_target_observation_failed": owner.tr(
            "Xenix could not inspect the Radeon target safely."
        ),
        "amd_private_recipe_failed": owner.tr(
            "The Radeon capability could not be deployed or verified."
        ),
        "materialization_failed": owner.tr("The Radeon capability did not finish deployment."),
        "provider_projection_blocked": owner.tr(
            "Deployment completed, but managed provider registration was blocked."
        ),
        "amd_deployment_degraded": owner.tr("The Radeon capability needs repair."),
        "amd_deployment_incomplete": owner.tr(
            "The Radeon capability has not reached operational state. Choose Repair to continue forward."
        ),
        "amd_not_materialized": owner.tr("The Radeon capability has not been installed."),
        "amd_installation_retiring": owner.tr(
            "This Radeon deployment is being removed and cannot be reactivated."
        ),
        "amd_removal_blocked": owner.tr(
            "Safe physical cleanup is blocked. Restore target access, then retry removal."
        ),
        "physical_cleanup_blocked": owner.tr(
            "Xenix could not establish the trusted control session needed for physical cleanup."
        ),
        "provider_removal_blocked": owner.tr(
            "The managed provider could not be removed safely. Retry removal later."
        ),
        "amd_installation_not_found": owner.tr("The selected Radeon deployment was not found."),
        "amd_profile_catalog_invalid": owner.tr("The bundled Radeon deployment profile is unavailable."),
        "amd_profile_unavailable": owner.tr("The bundled Radeon deployment profile is unavailable."),
        "amd_capability_profile_unavailable": owner.tr(
            "The bundled profile is unavailable for this capability and location."
        ),
        "amd_capability_profile_incomplete": owner.tr(
            "The bundled capability profile catalog is incomplete."
        ),
        "amd_placement_unavailable": owner.tr(
            "This historical Radeon location is available only for safe cleanup."
        ),
        "amd_deployment_closed": owner.tr("AMD deployment is shutting down. Reopen Xenix and try again."),
        "amd_request_invalid": owner.tr("The Radeon request is invalid. Review the displayed fields."),
        "amd_status_invalid": owner.tr("Xenix received an invalid Radeon deployment status."),
        "amd_operation_failed": owner.tr(
            "The Radeon operation could not complete. Use the support code with the diagnostic bundle."
        ),
    }
    if error_code in messages:
        return messages[error_code]
    if error_code and error_code.startswith("amd_compatibility_"):
        return _compatibility_message(owner, error_code)
    return owner.tr(
        "The Radeon operation could not complete. Use the support code with the diagnostic bundle."
    )


def _compatibility_message(owner: QObject, code: str) -> str:
    messages = {
        "amd_compatibility_profile_not_admitted": owner.tr(
            "The bundled Radeon profile is not admitted for product deployment."
        ),
        "amd_compatibility_component_not_admitted": owner.tr(
            "The bundled Radeon component is not admitted."
        ),
        "amd_compatibility_cell_not_admitted": owner.tr(
            "This Radeon software and hardware cell is not admitted."
        ),
        "amd_compatibility_target_kind_mismatch": owner.tr(
            "The selected execution location type is unsupported by this Radeon profile."
        ),
        "amd_compatibility_target_fact_missing": owner.tr(
            "The target did not provide all required compatibility facts."
        ),
        "amd_compatibility_os_name_mismatch": owner.tr("The target operating system is unsupported."),
        "amd_compatibility_os_version_mismatch": owner.tr(
            "The target operating-system version is unsupported."
        ),
        "amd_compatibility_kernel_version_mismatch": owner.tr(
            "The target Linux kernel is unsupported."
        ),
        "amd_compatibility_architecture_mismatch": owner.tr(
            "The target CPU architecture is unsupported."
        ),
        "amd_compatibility_gpu_architecture_mismatch": owner.tr(
            "The Radeon GPU architecture is unsupported."
        ),
        "amd_compatibility_driver_version_mismatch": owner.tr(
            "The AMD GPU driver or WSL runtime is unsupported."
        ),
        "amd_compatibility_rocm_version_mismatch": owner.tr("The ROCm version is unsupported."),
        "amd_compatibility_hip_version_mismatch": owner.tr("The HIP version is unsupported."),
        "amd_compatibility_python_version_mismatch": owner.tr("The target Python version is unsupported."),
        "amd_compatibility_gpu_count_insufficient": owner.tr(
            "The target does not have enough admitted Radeon GPUs."
        ),
        "amd_compatibility_vram_insufficient": owner.tr(
            "The target does not have enough free GPU memory."
        ),
        "amd_compatibility_system_memory_insufficient": owner.tr(
            "The target does not have enough free system memory."
        ),
        "amd_compatibility_persistent_storage_insufficient": owner.tr(
            "The target does not have enough free persistent storage."
        ),
        "amd_compatibility_capacity_requirement_unmeasured": owner.tr(
            "The Radeon profile is missing a required capacity measurement."
        ),
        "amd_compatibility_failed": owner.tr(
            "The target does not satisfy the fixed Radeon deployment profile."
        ),
    }
    return messages.get(
        code,
        owner.tr("The target does not satisfy the fixed Radeon deployment profile."),
    )


def _new_installation_id() -> str:
    return f"amd-installation-{uuid4().hex}"


def _new_target_id() -> str:
    return f"amd-target-{uuid4().hex}"


__all__ = ["AmdCapabilitySetupDialog", "AmdRadeonSettingsContribution"]
