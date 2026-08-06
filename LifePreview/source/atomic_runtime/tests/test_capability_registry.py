from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from atomic_runtime import (
    CAPABILITY_ENTRY_POINT_GROUP,
    CapabilityCollisionError,
    CapabilityDiscoveryError,
    CapabilityKey,
    CapabilityNotFoundError,
    CapabilityPlugin,
    CapabilityRegistration,
    CapabilityRegistry,
    InvalidCapabilityError,
    RegistryFrozenError,
    RegistryNotFrozenError,
    SafeErrorMapper,
    UpcasterDigestMismatchError,
    UpcasterRegistry,
    UpcasterSnapshotCollisionError,
    UnboundCapabilityError,
    discover_and_register,
    discover_capability_plugins,
)
from shared_contracts import (
    CacheMode,
    CachePolicy,
    DeterminismClass,
    ImplementationManifest,
    InfrastructureRetryPolicy,
    OperationSpec,
    ReplayClass,
    ResourceClass,
    ResourceRequirement,
    SchemaRevision,
    TimeoutPolicy,
    build_implementation_digest,
    build_operation_spec_digest,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _registration(
    label: str = "one",
    *,
    upcaster_digest: str | None = None,
) -> CapabilityRegistration:
    manifest_values = {
        "manifest_schema_version": SchemaRevision(),
        "replay_class": ReplayClass.REPLAYABLE,
        "code_image_digest": _digest(f"{label}:image"),
        "adapter_digest": _digest(f"{label}:adapter"),
        "upcaster_digest": (
            upcaster_digest or UpcasterRegistry().registry_digest()
        ),
    }
    manifest = ImplementationManifest(
        **manifest_values,
        implementation_digest=build_implementation_digest(**manifest_values),
    )
    spec_values = {
        "op_type": f"test.{label}",
        "op_version": SchemaRevision(),
        "input_schema_version": SchemaRevision(),
        "output_schema_version": SchemaRevision(),
        "resource_class": ResourceClass.CPU,
        "determinism_class": DeterminismClass.DETERMINISTIC,
        "cache_policy": CachePolicy(mode=CacheMode.INPUT_DIGEST),
        "timeout_policy": TimeoutPolicy(
            execution_timeout_seconds=30,
            heartbeat_timeout_seconds=5,
        ),
        "infrastructure_retry_policy": InfrastructureRetryPolicy(),
        "implementation_entrypoint": "test_capability_registry:_registration",
    }
    spec = OperationSpec(
        **spec_values,
        spec_digest=build_operation_spec_digest(**spec_values),
    )
    return CapabilityRegistration(
        spec=spec,
        implementation_manifest=manifest,
        error_mapper=SafeErrorMapper(),
    )


def _gpu_spec() -> tuple[OperationSpec, ResourceRequirement]:
    requirement = ResourceRequirement(
        device_type="cuda",
        minimum_vram_mb=1000,
        target_vram_mb=2000,
        model_digest=_digest("gpu:model"),
        workflow_digest=_digest("gpu:workflow"),
        custom_node_environment_digest=_digest("gpu:nodes"),
        estimated_duration_seconds=10,
    )
    spec_values = {
        "op_type": "test.gpu",
        "op_version": SchemaRevision(),
        "input_schema_version": SchemaRevision(),
        "output_schema_version": SchemaRevision(),
        "resource_class": ResourceClass.LOCAL_GPU,
        "resource_requirement": requirement,
        "determinism_class": DeterminismClass.SEEDED,
        "cache_policy": CachePolicy(),
        "timeout_policy": TimeoutPolicy(
            execution_timeout_seconds=30,
            heartbeat_timeout_seconds=5,
        ),
        "infrastructure_retry_policy": InfrastructureRetryPolicy(),
        "implementation_entrypoint": "test_capability_registry:_registration",
    }
    return (
        OperationSpec(
            **spec_values,
            spec_digest=build_operation_spec_digest(**spec_values),
        ),
        requirement,
    )


def _gpu_manifest(**overrides: object) -> ImplementationManifest:
    _spec, requirement = _gpu_spec()
    values = {
        "manifest_schema_version": SchemaRevision(),
        "replay_class": ReplayClass.REPLAYABLE,
        "code_image_digest": _digest("gpu:image"),
        "adapter_digest": _digest("gpu:adapter"),
        "comfy_workflow_digest": requirement.workflow_digest,
        "custom_node_set_digest": requirement.custom_node_environment_digest,
        "model_weight_digests": (requirement.model_digest,),
        "upcaster_digest": UpcasterRegistry().registry_digest(),
        **overrides,
    }
    return ImplementationManifest(
        **values,
        implementation_digest=build_implementation_digest(**values),
    )


def test_registry_requires_exact_four_part_key_and_freezes() -> None:
    registration = _registration()
    registry = CapabilityRegistry()
    registry.register(registration)
    with pytest.raises(RegistryNotFrozenError):
        registry.resolve(registration.key)
    registry.freeze()

    resolved = registry.resolve(registration.key)
    assert resolved == registration
    assert resolved.is_bound
    assert (
        registry.resolve(
            op_type=registration.spec.op_type,
            op_version=registration.spec.op_version,
            spec_digest=registration.spec.spec_digest,
            implementation_digest=(
                registration.implementation_manifest.implementation_digest
            ),
        )
        == registration
    )
    with pytest.raises(TypeError, match="all four"):
        registry.resolve(
            op_type=registration.spec.op_type,
            op_version=registration.spec.op_version,
        )
    with pytest.raises(RegistryFrozenError):
        registry.register(_registration("two"))
    with pytest.raises(TypeError):
        registry.registrations[registration.key] = registration

    missing = CapabilityKey(
        op_type="test.missing",
        op_version=SchemaRevision(),
        spec_digest="e" * 64,
        implementation_digest="f" * 64,
    )
    with pytest.raises(CapabilityNotFoundError) as caught:
        registry.resolve(missing)
    assert caught.value.requested == missing
    assert caught.value.available == (registration.key,)


def test_registration_and_plugin_are_immutable_and_reject_collisions() -> None:
    registration = _registration()
    plugin = CapabilityPlugin("tests", (registration,))
    with pytest.raises(FrozenInstanceError):
        registration.spec = registration.spec  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plugin.name = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError, match="immutable"):
        registration.error_mapper._unknown = object()  # type: ignore[attr-defined]
    with pytest.raises(InvalidCapabilityError, match="collision"):
        CapabilityPlugin("bad", (registration, registration))
    with pytest.raises(UnboundCapabilityError):
        registration.build_executor(object())


def test_registration_revalidates_constructed_self_digests() -> None:
    valid = _registration()
    bad_spec = valid.spec.model_copy(update={"spec_digest": "0" * 64})
    with pytest.raises(InvalidCapabilityError, match="spec validation"):
        CapabilityRegistration(
            spec=bad_spec,
            implementation_manifest=valid.implementation_manifest,
            error_mapper=SafeErrorMapper(),
        )
    bad_manifest = valid.implementation_manifest.model_copy(
        update={"implementation_digest": "0" * 64}
    )
    with pytest.raises(InvalidCapabilityError, match="manifest validation"):
        CapabilityRegistration(
            spec=valid.spec,
            implementation_manifest=bad_manifest,
            error_mapper=SafeErrorMapper(),
        )


@pytest.mark.parametrize(
    "manifest",
    [
        _gpu_manifest(comfy_workflow_digest=_digest("different-workflow")),
        _gpu_manifest(custom_node_set_digest=_digest("different-nodes")),
        _gpu_manifest(model_weight_digests=(_digest("different-model"),)),
        _gpu_manifest(
            replay_class=ReplayClass.IDENTIFIABLE_ONLY,
            provider_identity="local-provider",
        ),
    ],
)
def test_local_gpu_registration_rejects_spec_manifest_identity_mismatch(
    manifest: ImplementationManifest,
) -> None:
    spec, _requirement = _gpu_spec()
    with pytest.raises(InvalidCapabilityError, match="local GPU"):
        CapabilityRegistration(
            spec=spec,
            implementation_manifest=manifest,
        )

def test_registry_transaction_does_not_partially_commit_on_collision() -> None:
    first = _registration("first")
    second = _registration("second")
    registry = CapabilityRegistry()
    registry.register(first)
    with pytest.raises(CapabilityCollisionError):
        registry.register_all((second, first))
    assert tuple(registry.registrations) == (first.key,)


def test_registry_freeze_binds_every_manifest_to_retained_upcaster_snapshot() -> None:
    missing = _registration("missing", upcaster_digest="f" * 64)
    registry = CapabilityRegistry()
    with pytest.raises(
        UpcasterDigestMismatchError,
        match="unavailable upcaster snapshots",
    ):
        registry.register_plugins_and_freeze(
            (CapabilityPlugin("missing", (missing,)),)
        )
    assert not registry.registrations
    assert not registry.is_frozen

    upcasters = UpcasterRegistry()
    historical = upcasters.snapshot()
    upcasters.register(
        "test.current:input",
        SchemaRevision(major=1, minor=0),
        SchemaRevision(major=1, minor=1),
        lambda payload: payload,
        implementation_digest="e" * 64,
    )
    current = upcasters.freeze()
    registrations = (
        _registration("historical", upcaster_digest=historical.digest),
        _registration("current", upcaster_digest=current.digest),
    )
    registry.register_plugins_and_freeze(
        (CapabilityPlugin("bound", registrations),),
        upcasters=upcasters,
    )
    assert registry.resolve_upcaster_snapshot(historical.digest) is historical
    assert registry.resolve_upcaster_snapshot(current.digest) is current


def test_upcaster_snapshot_digest_collision_is_rejected() -> None:
    snapshots = []
    for marker in ("first", "second"):
        upcasters = UpcasterRegistry()
        upcasters.register(
            "same-contract",
            SchemaRevision(major=1, minor=0),
            SchemaRevision(major=1, minor=1),
            lambda payload, marker=marker: {**payload, "marker": marker},
            implementation_digest="c" * 64,
        )
        snapshots.append(upcasters.freeze())
    assert snapshots[0].digest == snapshots[1].digest
    registry = CapabilityRegistry()
    registry.retain_upcaster_snapshot(snapshots[0])
    with pytest.raises(UpcasterSnapshotCollisionError):
        registry.retain_upcaster_snapshot(snapshots[1])


class _FakeEntryPoint:
    group = CAPABILITY_ENTRY_POINT_GROUP

    def __init__(self, distribution: str, name: str, value: object) -> None:
        self.dist = SimpleNamespace(name=distribution)
        self.name = name
        self.value = f"{distribution}:{name}"
        self._value = value
        self.loaded = False

    def load(self) -> object:
        self.loaded = True
        return self._value


def test_discovery_checks_complete_allowlist_before_importing_any_plugin() -> None:
    allowed = _FakeEntryPoint(
        "allowed-package",
        "allowed",
        lambda: CapabilityPlugin("allowed", (_registration("allowed"),)),
    )
    denied = _FakeEntryPoint(
        "untrusted-package",
        "denied",
        lambda: CapabilityPlugin("denied", (_registration("denied"),)),
    )
    with pytest.raises(CapabilityDiscoveryError, match="unallowlisted"):
        discover_capability_plugins(
            allowlist={"allowed-package"},
            entry_points=(allowed, denied),
        )
    assert not allowed.loaded
    assert not denied.loaded


def test_discovery_and_registry_commit_are_all_or_nothing() -> None:
    good = _FakeEntryPoint(
        "good-package",
        "good",
        lambda: CapabilityPlugin("good", (_registration("good"),)),
    )

    def fail() -> CapabilityPlugin:
        raise RuntimeError("secret plugin failure")

    bad = _FakeEntryPoint("bad-package", "bad", fail)
    registry = CapabilityRegistry()
    with pytest.raises(CapabilityDiscoveryError, match="atomically"):
        discover_and_register(
            registry,
            allowlist={"good-package", "bad-package"},
            entry_points=(good, bad),
        )
    assert not registry.registrations
    assert not registry.is_frozen


def test_allowlist_requires_every_expected_distribution() -> None:
    only = _FakeEntryPoint(
        "present-package",
        "present",
        lambda: CapabilityPlugin("present", (_registration("present"),)),
    )
    with pytest.raises(CapabilityDiscoveryError, match="missing"):
        discover_capability_plugins(
            allowlist={"present-package", "missing-package"},
            entry_points=(only,),
        )
    assert not only.loaded
