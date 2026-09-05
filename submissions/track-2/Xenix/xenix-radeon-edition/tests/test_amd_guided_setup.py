from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QWidget

from xenix.services.amd.capability_deployment import (
    AmdCapabilityDeploymentAdapter,
    AmdCapabilityDeploymentError,
)
from xenix.services.amd.deployment import (
    AmdAiDeploymentService,
    AmdDeploymentError,
    AmdPrivateTargetSpec,
    AmdRetirementRequest,
)
from xenix.services.amd.guided_capability import (
    AmdCapabilityGuidedDeploymentService,
    AmdLocalWslInstallCommand,
)
from xenix.services.amd.manifests import (
    ExecutionProfilePlacement,
    ManifestAdmission,
    ManifestCapability,
)
from xenix.services.amd.placements.wsl import (
    WslAmdPlacement,
    WslDistributionError,
    WslPlacementError,
    WslTarget,
    WslTargetRecipe,
)
from xenix.services.amd.placements.ssh import (
    OpenSshCommandResult,
    PinnedHostKey,
    PrivateSshAmdPlacement,
    ResolvedSshIdentity,
    SshAmdExecutionSession,
    SshConnectionError,
    SshForwardError,
    SshTargetEnrollment,
)
from xenix.services.amd.profile_catalog import load_product_manifest_catalog
from xenix.services.amd.remote_supervisor import (
    ProtectedRuntimeSecret,
    RemoteGenerationIdentity,
    RemoteLaunchSpec,
    RemoteSupervisorError,
)
from xenix.services.amd.placement import AmdRuntimeKey, LoopbackHttpBinding, RuntimeIncarnation
from xenix.services.amd.participants import AmdEmbeddingParticipant, AmdLlmParticipant, AmdOcrParticipant
from xenix.services.amd.status import (
    AmdComponentStatus,
    AmdInstallationCondition,
    AmdInstallationStatus,
)
from xenix.services.amd.ssh_trust import OpenSshHostTrustProbe
from xenix.services.amd.ssh_security import AmdSshSecurityStore
from xenix.services.settings_store import SettingsStore
from xenix.services.storage.database import create_engine_for_path, create_session_factory
from xenix.services.storage.migrations import bootstrap_current_schema
from xenix.ui.amd_capability_tasks import (
    AmdCapabilityTaskRunner,
    AmdRetirementAcknowledgement,
)
from xenix.ui.amd_setup import AmdCapabilitySetupDialog, AmdRadeonSettingsContribution
from xenix.ui.settings_dialog import SettingsDialogCapabilitySlots


@pytest.fixture()
def app(monkeypatch) -> QApplication:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _wait_until(app: QApplication, predicate, timeout_seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    app.processEvents()
    return predicate()


def _status(
    installation_id: str,
    capability: ManifestCapability,
    *,
    condition: AmdInstallationCondition = AmdInstallationCondition.OPERATIONAL,
) -> AmdInstallationStatus:
    component = AmdComponentStatus(
        capability=capability,
        generation_id=f"{installation_id}-{capability.value}",
        manifest_digest="a" * 64,
        lifecycle_state="registered" if condition is AmdInstallationCondition.OPERATIONAL else "staging",
        phase="registered" if condition is AmdInstallationCondition.OPERATIONAL else "prepare",
        error_code=None,
        projected=condition is AmdInstallationCondition.OPERATIONAL,
        projection_retiring=False,
        selected=condition is AmdInstallationCondition.OPERATIONAL,
        live=condition is AmdInstallationCondition.OPERATIONAL,
    )
    return AmdInstallationStatus(
        installation_id=installation_id,
        placement="local_wsl",
        profile_id="profile",
        profile_digest="b" * 64,
        desired_presence=condition is not AmdInstallationCondition.REMOVED,
        lifecycle_state="active",
        condition=condition,
        target_observation_error_code=None,
        compatibility_issues=(),
        components=(component,),
    )


def test_catalog_admits_multiple_chat_options_without_expanding_other_capabilities() -> None:
    catalog = load_product_manifest_catalog()

    for capability in ManifestCapability:
        profiles = [
            profile
            for profile in catalog.profiles
            if profile.placement in {
                ExecutionProfilePlacement.PRIVATE_SSH,
                ExecutionProfilePlacement.LOCAL_WSL,
            }
            and len(catalog.profile_components(profile)) == 1
            and catalog.profile_components(profile)[0].capability is capability
        ]
        expected_placements = {ExecutionProfilePlacement.PRIVATE_SSH}
        if capability is not ManifestCapability.CHAT:
            expected_placements.add(ExecutionProfilePlacement.LOCAL_WSL)
        assert {profile.placement for profile in profiles} == expected_placements
        assert all(profile.admission is ManifestAdmission.ADMITTED for profile in profiles)
        assert all(
            catalog.profile_components(profile)[0].admission is ManifestAdmission.ADMITTED
            for profile in profiles
        )
        adapter = AmdCapabilityDeploymentAdapter(
            capability=capability,
            catalog=catalog,
            deployment=SimpleNamespace(),
        )
        if capability is ManifestCapability.CHAT:
            assert len(adapter.deployment_options("private_ssh")) == 2
            assert adapter.deployment_options("local_wsl") == ()
        else:
            assert len(adapter.deployment_options("private_ssh")) == 1
            assert len(adapter.deployment_options("local_wsl")) == 1
        if capability in {ManifestCapability.EMBEDDING, ManifestCapability.OCR}:
            current = adapter.profile_for("private_ssh")
            assert current.profile_version == "2"
            assert current.compatibility_cell_id == "radeon-cloud-gfx1100-ubuntu-24.04-k106-rocm-7.2.1"

    assert all(profile.placement is not ExecutionProfilePlacement.LEGACY for profile in catalog.profiles)


class _FilteredHostScanner:
    """Model a cloud SSH front door that refuses scanner-only probes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments, *, stdin, timeout_seconds, environment):
        del stdin, timeout_seconds, environment
        command = tuple(arguments)
        self.calls.append(command)
        if command[0] == "ssh-keyscan":
            return OpenSshCommandResult(
                return_code=1,
                stdout=b"",
                stderr=b"scanner connection refused",
            )

        known_hosts_option = next(
            argument
            for argument in command
            if argument.startswith("UserKnownHostsFile=")
        )
        known_hosts = Path(known_hosts_option.split("=", 1)[1])
        known_hosts.write_text(
            "[example.test]:22022 ssh-ed25519 "
            "AAAAC3NzaC1lZDI1NTE5AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=\n",
            encoding="utf-8",
        )
        return OpenSshCommandResult(
            return_code=255,
            stdout=b"",
            stderr=b"authentication unavailable",
        )


def test_host_trust_falls_back_to_ephemeral_unauthenticated_ssh_when_scanner_is_filtered(
    tmp_path: Path,
) -> None:
    runner = _FilteredHostScanner()

    challenge = OpenSshHostTrustProbe(
        temporary_parent=tmp_path,
        process_runner=runner,
    ).discover(host="example.test", port=22022)

    assert challenge.algorithm == "ssh-ed25519"
    assert challenge.fingerprint.startswith("SHA256:")
    assert len(runner.calls) == 2
    assert runner.calls[0][0] == "ssh-keyscan"
    fallback = runner.calls[1]
    assert fallback[:3] == ("ssh", "-F", os.devnull)
    assert "PreferredAuthentications=none" in fallback
    assert "PubkeyAuthentication=no" in fallback
    assert "GSSAPIAuthentication=no" in fallback
    assert "HostbasedAuthentication=no" in fallback
    assert "IdentityAgent=none" in fallback
    assert "IdentitiesOnly=yes" in fallback
    assert "PasswordAuthentication=no" in fallback
    assert "KbdInteractiveAuthentication=no" in fallback
    assert "GlobalKnownHostsFile=none" in fallback
    assert "UpdateHostKeys=no" in fallback
    assert "StrictHostKeyChecking=accept-new" in fallback
    assert "xenix-host-probe@example.test" in fallback
    assert "-i" not in fallback
    assert not tuple(tmp_path.iterdir())


class _SuccessfulPrivateSshRunner:
    def __init__(self) -> None:
        self.configs: list[str] = []
        self._outputs = iter(
            (
                b"xenix-ssh-v1\n",
                b"/home/xenix\n",
                b"xenix-supervisor-v1\n",
            )
        )

    def run(self, arguments, *, stdin, timeout_seconds, environment):
        del stdin, timeout_seconds, environment
        command = tuple(arguments)
        self.configs.append(Path(command[2]).read_text(encoding="utf-8"))
        return OpenSshCommandResult(return_code=0, stdout=next(self._outputs))


def test_private_ssh_uses_bounded_connection_establishment_retries(tmp_path: Path) -> None:
    target_id = "amd-target-11111111111111111111111111111111"
    identity_file = tmp_path / "identity"
    identity_file.write_text("test identity", encoding="utf-8")
    enrollment = SshTargetEnrollment(
        target_id=target_id,
        host="example.test",
        user="xenix",
        port=22022,
        pinned_host_key_reference="pinned-host-key",
        identity_file_reference="identity-file",
    )
    runner = _SuccessfulPrivateSshRunner()
    placement = PrivateSshAmdPlacement(
        target_resolver=SimpleNamespace(resolve_target=lambda _target_id: enrollment),
        credential_resolver=SimpleNamespace(
            resolve_identity=lambda _reference: ResolvedSshIdentity(identity_file)
        ),
        trust_resolver=SimpleNamespace(
            resolve_host_key=lambda _reference: PinnedHostKey(
                key_type="ssh-ed25519",
                key_data=(
                    "AAAAC3NzaC1lZDI1NTE5AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
                ),
            )
        ),
        process_runner=runner,
        temporary_parent=tmp_path,
    )

    session = placement.open_session(
        target_id,
        RuntimeIncarnation("controller", "incarnation"),
    )
    session.close()

    assert len(runner.configs) == 3
    assert all("    ConnectionAttempts 3\n" in config for config in runner.configs)
    assert all("    StrictHostKeyChecking yes\n" in config for config in runner.configs)
    assert all("    IdentitiesOnly yes\n" in config for config in runner.configs)
    assert all("    ProxyCommand none\n" in config for config in runner.configs)
    assert all("    ProxyJump none\n" in config for config in runner.configs)


def test_ssh_security_store_preserves_first_target_when_second_is_saved_after_reload(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    first_target_id = "amd-target-11111111111111111111111111111111"
    second_target_id = "amd-target-22222222222222222222222222222222"
    host_key = PinnedHostKey(
        key_type="ssh-ed25519",
        key_data=(
            "AAAAC3NzaC1lZDI1NTE5AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
        ),
    )

    first_store = SettingsStore(config)
    first_security = AmdSshSecurityStore(first_store)
    first_references = first_security.record(
        target_id=first_target_id,
        identity_file=(tmp_path / "first-identity"),
        host_key=host_key,
    )
    first_security.close()
    first_store.close()

    second_store = SettingsStore(config)
    second_security = AmdSshSecurityStore(second_store)
    second_references = second_security.record(
        target_id=second_target_id,
        identity_file=(tmp_path / "second-identity"),
        host_key=host_key,
    )
    second_security.close()
    second_store.close()

    verification_store = SettingsStore(config)
    verification_security = AmdSshSecurityStore(verification_store)
    try:
        assert verification_security.resolve_identity(first_references[0]).identity_file == (
            tmp_path / "first-identity"
        )
        assert verification_security.resolve_host_key(first_references[1]) == host_key
        assert verification_security.resolve_identity(second_references[0]).identity_file == (
            tmp_path / "second-identity"
        )
        assert verification_security.resolve_host_key(second_references[1]) == host_key
    finally:
        verification_security.close()
        verification_store.close()


class _RetryableIdentitySupervisor:
    def __init__(self, observation: object) -> None:
        self.observation = observation
        self.observe_calls = 0
        self.stopped: list[object] = []

    def observe(self, generation: object) -> object:
        del generation
        self.observe_calls += 1
        if self.observe_calls == 1:
            raise SshConnectionError("transient")
        return self.observation

    def stop(self, observation: object) -> None:
        self.stopped.append(observation)


class _LiveForward:
    def __init__(self) -> None:
        self.is_alive = True
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        self.is_alive = False


def test_transient_identity_probe_keeps_live_forward_for_a_verified_retry() -> None:
    key = AmdRuntimeKey("installation", "generation")
    observation = SimpleNamespace(generation=SimpleNamespace())
    supervisor = _RetryableIdentitySupervisor(observation)
    forward = _LiveForward()
    binding = LoopbackHttpBinding(
        base_url="http://127.0.0.1:43123",
        bearer_token="x" * 24,
    )
    material = SimpleNamespace(close=lambda: None)
    session = SshAmdExecutionSession(
        incarnation=RuntimeIncarnation("controller", "incarnation"),
        transport=SimpleNamespace(),
        supervisor=supervisor,
        material=material,
        token_factory=lambda: "x" * 24,
        target_root="/root/.local/share/Xenix/amd-runtime",
    )
    session._realizations[key] = SimpleNamespace(  # noqa: SLF001
        observation=observation,
        forward=forward,
        binding=binding,
    )

    with pytest.raises(SshForwardError):
        session.resolve_binding(key)

    assert forward.is_alive
    assert forward.close_calls == 0
    assert session.resolve_binding(key) == binding
    assert supervisor.observe_calls == 2
    session.close()
    assert forward.close_calls == 1
    assert supervisor.stopped == [observation]


class _AbsentManagedProjectionSettings:
    def projection_status(self, reference: object) -> SimpleNamespace:
        del reference
        return SimpleNamespace(
            exists=False,
            retiring=False,
            active=False,
            default_selected=False,
            turn_completion_guard_selected=False,
            thread_title_selected=False,
        )

    def mark_managed_provider_retiring(self, reference: object) -> None:
        del reference
        raise AssertionError("an absent projection must not be marked")

    def remove_managed_provider(self, reference: object) -> None:
        del reference
        raise AssertionError("an absent projection must not be removed again")


def test_participant_retirement_treats_an_unpublished_projection_as_already_absent() -> None:
    settings = _AbsentManagedProjectionSettings()

    for participant in (
        AmdLlmParticipant(settings),
        AmdEmbeddingParticipant(settings),
        AmdOcrParticipant(settings),
    ):
        marked = participant.mark_retiring(
            installation_id="failed-installation",
            component_generation_id="unpublished-generation",
        )
        removed = participant.remove(
            installation_id="failed-installation",
            component_generation_id="unpublished-generation",
        )
        assert not marked.exists
        assert not removed.exists


@dataclass
class _AdapterDeployment:
    statuses: dict[str, AmdInstallationStatus]
    calls: list[object]
    targets: tuple[object, ...] = ()

    def prepare(self, spec, *, progress=None):
        self.calls.append(spec)
        status = _status(spec.installation_id, ManifestCapability.CHAT)
        self.statuses[spec.installation_id] = status
        return status

    def ensure_private_install_intent(self, *, target, installation):
        self.calls.append(installation)

    def reconcile(self, installation_id, *, progress=None):
        return self.statuses.get(installation_id, _status(installation_id, ManifestCapability.CHAT))

    def status(self, installation_id):
        try:
            return self.statuses[installation_id]
        except KeyError:
            from xenix.services.amd.deployment import AmdDeploymentNotFoundError

            raise AmdDeploymentNotFoundError() from None

    def installations(self):
        return ()

    def private_installations(self):
        raise AssertionError("target inventory must not depend on installations")

    def private_targets(self):
        return self.targets

    def request_retirement(self, installation_id):
        return AmdRetirementRequest(installation_id, "retirement_requested")

    def retire(self, installation_id, *, drain_timeout_seconds=0.0):
        return self.status(installation_id)


def test_capability_adapter_routes_admitted_profiles_and_isolates_other_capabilities() -> None:
    catalog = load_product_manifest_catalog()
    deployment = _AdapterDeployment({}, [])
    adapter = AmdCapabilityDeploymentAdapter(
        capability=ManifestCapability.CHAT,
        catalog=catalog,
        deployment=deployment,
    )

    assert len(catalog.profile_components(adapter.profile_for("private_ssh"))) == 1
    assert catalog.profile_components(adapter.profile_for("private_ssh"))[0].capability is ManifestCapability.CHAT
    with pytest.raises(AmdCapabilityDeploymentError) as unverified_wsl:
        adapter.profile_for("local_wsl")
    assert unverified_wsl.value.error_code == "amd_capability_profile_unavailable"
    with pytest.raises(AmdCapabilityDeploymentError) as legacy:
        adapter.profile_for("legacy")
    assert legacy.value.error_code == "amd_capability_profile_unavailable"

    private_options = adapter.deployment_options("private_ssh")
    assert [option.model_id for option in private_options] == [
        "Qwen/Qwen3.5-9B",
        "Qwen/Qwen3.5-4B",
    ]
    assert private_options[0].variant == "recommended"
    assert private_options[0].context_limit == 8192
    assert private_options[0].supports_streaming
    assert private_options[0].supports_tool_calls
    assert private_options[0].supports_reasoning
    assert adapter.deployment_options("local_wsl") == ()

    selected = private_options[1]
    target = SimpleNamespace(target_id="target-1")
    adapter.install_private_intent(
        installation_id="qwen-4b",
        target=target,
        option_id=selected.option_id,
    )
    intent = deployment.calls[-1]
    assert intent.profile_digest == adapter.profile_for("private_ssh", selected.option_id).manifest_digest

    deployment.statuses["embedding-install"] = _status(
        "embedding-install", ManifestCapability.EMBEDDING
    )
    with pytest.raises(AmdCapabilityDeploymentError) as mismatch:
        adapter.status("embedding-install")
    assert mismatch.value.error_code == "amd_capability_installation_mismatch"


def test_exact_chat_recipe_is_exclusive_but_different_models_share_one_location(tmp_path: Path) -> None:
    engine = create_engine_for_path(tmp_path / "xenix.db")
    bootstrap_current_schema(engine)
    catalog = load_product_manifest_catalog()
    service = AmdAiDeploymentService(
        session_factory=create_session_factory(engine),
        catalog=catalog,
        placements={"private_ssh": SimpleNamespace(placement_kind="private_ssh")},
        participants={capability: SimpleNamespace(capability=capability) for capability in ManifestCapability},
        runtime_directory=SimpleNamespace(),
    )
    adapter = AmdCapabilityDeploymentAdapter(
        capability=ManifestCapability.CHAT,
        catalog=catalog,
        deployment=service,
    )
    target = AmdPrivateTargetSpec(
        target_id="shared-target",
        host="gpu.example.test",
        user="rocm",
        port=22,
        pinned_host_key="host-key-reference",
        identity_file_reference="identity-reference",
    )
    private_options = adapter.deployment_options("private_ssh")
    qwen_9b = next(option for option in private_options if option.model_id == "Qwen/Qwen3.5-9B")
    qwen_4b = next(option for option in private_options if option.model_id == "Qwen/Qwen3.5-4B")
    try:
        adapter.install_private_intent(
            installation_id="qwen-9b",
            target=target,
            option_id=qwen_9b.option_id,
        )
        adapter.install_private_intent(
            installation_id="qwen-4b",
            target=target,
            option_id=qwen_4b.option_id,
        )

        assert {item.installation_id for item in service.installations()} == {"qwen-9b", "qwen-4b"}

        with pytest.raises(AmdDeploymentError) as duplicate:
            adapter.install_private_intent(
                installation_id="qwen-9b-duplicate",
                target=target,
                option_id=qwen_9b.option_id,
            )
        assert duplicate.value.error_code == "amd_component_already_installed"
        assert {item.installation_id for item in service.installations()} == {"qwen-9b", "qwen-4b"}
    finally:
        service.close()
        engine.dispose()


class _TargetInventorySecurity:
    def contains_target(self, target_id: str) -> bool:
        return target_id == "target-without-installations"


def test_guided_target_inventory_keeps_enrollments_after_all_installations_are_removed() -> None:
    catalog = load_product_manifest_catalog()
    deployment = _AdapterDeployment(
        {},
        [],
        targets=(
            SimpleNamespace(
                target_id="target-without-installations",
                host="gpu.example.test",
                user="rocm",
                port=30401,
            ),
        ),
    )
    adapter = AmdCapabilityDeploymentAdapter(
        capability=ManifestCapability.CHAT,
        catalog=catalog,
        deployment=deployment,
    )
    guided = AmdCapabilityGuidedDeploymentService(
        adapter=adapter,
        deployment=deployment,
        ssh_security=_TargetInventorySecurity(),
        host_trust_probe=object(),
        wsl_operation=WslAmdPlacement(
            process_runner=_WslRunner(stdout=b"Ubuntu\n"),
            loopback_verifier=_LoopbackVerifier(),
        ),
    )

    targets = guided.private_targets()

    assert len(targets) == 1
    assert targets[0].target_id == "target-without-installations"
    assert targets[0].security_enrolled


class _WslRunner:
    def __init__(self, *, stdout: bytes, return_code: int = 0) -> None:
        self.stdout = stdout
        self.return_code = return_code
        self.calls: list[tuple[tuple[str, ...], bytes | None, float]] = []

    def run(self, arguments, *, stdin, timeout_seconds):
        self.calls.append((tuple(arguments), stdin, timeout_seconds))
        return SimpleNamespace(return_code=self.return_code, stdout=self.stdout, stderr=b"hidden")


class _LoopbackVerifier:
    def verify(self, binding, generation, *, timeout_seconds):
        del binding, generation, timeout_seconds


def test_wsl_distribution_listing_is_fixed_and_rejects_shell_text() -> None:
    runner = _WslRunner(stdout=b"Ubuntu\nUbuntu\nDebian\n")
    placement = WslAmdPlacement(process_runner=runner, loopback_verifier=_LoopbackVerifier())

    assert placement.list_distributions() == ("Ubuntu", "Debian")
    assert runner.calls[0][0] == ("wsl.exe", "--list", "--quiet")
    assert runner.calls[0][1] is None

    unsafe = _WslRunner(stdout=b"Ubuntu; touch pwned\n")
    with pytest.raises(WslDistributionError) as error:
        WslAmdPlacement(process_runner=unsafe, loopback_verifier=_LoopbackVerifier()).list_distributions()
    assert error.value.error_code == "amd_wsl_distribution_invalid"


@pytest.mark.parametrize("value", ["-Ubuntu", "Ubuntu;rm", "Ubuntu\nother", "../Ubuntu"])
def test_wsl_target_rejects_untrusted_distribution_names(value: str) -> None:
    with pytest.raises(WslDistributionError):
        WslTarget(target_id="amd-target", distribution=value)


def test_wsl_recipes_and_launch_specs_cannot_become_arbitrary_commands() -> None:
    with pytest.raises(WslPlacementError):
        WslTargetRecipe(recipe_id="recipe", script="")
    with pytest.raises(WslPlacementError):
        WslTargetRecipe(recipe_id="recipe", script="\x00")

    generation = RemoteGenerationIdentity(
        runtime_key=AmdRuntimeKey("install", "generation"),
        manifest_digest="a" * 64,
        incarnation=RuntimeIncarnation("controller", "incarnation"),
    )
    with pytest.raises(RemoteSupervisorError):
        RemoteLaunchSpec(
            generation=generation,
            command=("/opt/run", "0.0.0.0", "18081"),
            remote_loopback_port=18081,
        )
    with pytest.raises(RemoteSupervisorError):
        ProtectedRuntimeSecret("short")


class _GuidedForRunner:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.install_calls = 0

    def install_local_wsl(self, command, *, progress=None):
        del command, progress
        self.install_calls += 1
        self.entered.set()
        assert self.release.wait(3)
        return _status("install-1", ManifestCapability.CHAT)

    def request_retirement(self, installation_id):
        return AmdRetirementRequest(installation_id, "retirement_requested")

    def inventory(self):
        return ()


def test_task_runner_operation_tokens_fence_delivery_and_acknowledge_retirement(app) -> None:
    guided = _GuidedForRunner()
    runner = AmdCapabilityTaskRunner(guided)
    finished: list[object] = []
    acknowledgements: list[AmdRetirementAcknowledgement] = []
    runner.finished.connect(finished.append)
    runner.retirement_acknowledged.connect(acknowledgements.append)
    command = AmdLocalWslInstallCommand("install-1", "Ubuntu")

    operation_id = runner.start_local_wsl_install(command)
    assert operation_id == 1
    assert guided.entered.wait(1)
    assert runner.start_local_wsl_install(command) is None
    assert runner.cancel(operation_id)

    retirement_id = runner.start_retire("install-1")
    assert retirement_id == 2
    assert _wait_until(app, lambda: bool(acknowledgements))
    assert acknowledgements[0].operation_id == retirement_id
    assert acknowledgements[0].acknowledged
    assert acknowledgements[0].request_phase == "retirement_requested"

    guided.release.set()
    assert _wait_until(app, lambda: not runner.active)
    app.processEvents()
    assert finished == []  # cancelled delivery cannot leak a stale result
    runner.shutdown()


class _GuidedForModelDialog:
    def __init__(self) -> None:
        catalog = load_product_manifest_catalog()
        self._adapter = AmdCapabilityDeploymentAdapter(
            capability=ManifestCapability.CHAT,
            catalog=catalog,
            deployment=SimpleNamespace(),
        )

    def deployment_options(self, placement=None):
        return self._adapter.deployment_options(placement)

    def inventory(self):
        return ()

    def private_targets(self):
        return ()

    def local_wsl_distributions(self):
        return ("Ubuntu",)


def test_chat_setup_defaults_to_qwen_and_hides_unverified_wsl_location(app) -> None:
    dialog = AmdCapabilitySetupDialog(
        capability=ManifestCapability.CHAT,
        guided=_GuidedForModelDialog(),
    )
    model_selector = dialog.findChild(QComboBox, "amdCapabilityModelSelector")
    location_selector = dialog.findChild(QComboBox, "amdCapabilityLocationSelector")
    assert model_selector is not None
    assert location_selector is not None
    try:
        assert model_selector.count() == 2
        assert "Qwen3.5-9B" in model_selector.currentText()
        assert "Recommended" in model_selector.currentText()
        assert location_selector.count() == 1
        assert location_selector.currentData() == "private_ssh"
        assert location_selector.findData("local_wsl") == -1
    finally:
        dialog.shutdown()
        dialog.close()


def test_settings_contribution_populates_each_capability_slot(app) -> None:
    parent = QWidget()
    slots = SettingsDialogCapabilitySlots(QFormLayout(), QFormLayout(), QFormLayout())
    composition = SimpleNamespace(capability_guided_deployments={capability: SimpleNamespace(inventory=lambda: ()) for capability in ManifestCapability})
    handle = AmdRadeonSettingsContribution(composition).attach(parent, slots)
    try:
        assert slots.llm.rowCount() == 1
        assert slots.embedding.rowCount() == 1
        assert slots.ocr.rowCount() == 1
        assert parent.findChild(QWidget, "amdRadeonChatControl") is not None
        assert parent.findChild(QWidget, "amdRadeonEmbeddingControl") is not None
        assert parent.findChild(QWidget, "amdRadeonOcrControl") is not None
    finally:
        handle.shutdown()
        parent.deleteLater()
