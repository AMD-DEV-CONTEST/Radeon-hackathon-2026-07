"""Independent approval and supported-API model-supply capabilities.

``_CAPABILITY_SEAL`` is an authenticity tag for supported public APIs, not a
cryptographic secret. It blocks public construction, copying, pickling, random
seal forgery, and accidental misuse. It cannot defend against private module
introspection, ``object.__new__``/``object.__setattr__``, or arbitrary Python
running in the same process; hostile code requires process isolation.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.model_registry import (
    ModelDescriptor,
    ModelRegistry,
    validate_production_license,
)
from specstyle.generation.weight_manifest import (
    WeightManifest,
    _verify_component,
    manifest_sha256,
)

if TYPE_CHECKING:
    from specstyle.generation.pipeline_factory import PipelineGraph

_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_CAPABILITY_SEAL = object()


def _validate_evidence_url(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise DomainError("invalid license approval evidence")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise DomainError("invalid license approval evidence") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
    ):
        raise DomainError("invalid license approval evidence")
    return value


@dataclass(frozen=True, slots=True)
class LicenseApproval:
    model_id: str
    revision: str
    manifest_sha256: Sha256
    license_spdx: str
    evidence_url: str

    def __post_init__(self) -> None:
        if type(self.model_id) is not str or not self.model_id:
            raise DomainError("invalid license approval model")
        if type(self.revision) is not str or _REVISION.fullmatch(self.revision) is None:
            raise DomainError("invalid license approval revision")
        if type(self.manifest_sha256) is not Sha256:
            raise DomainError("invalid license approval digest")
        try:
            validate_production_license(self.license_spdx)
        except DomainError as exc:
            raise DomainError("invalid license approval spdx") from exc
        _validate_evidence_url(self.evidence_url)


@dataclass(frozen=True, slots=True, init=False)
class VerifiedComponent:
    """Supported-API capability for one verified component directory.

    Its seal is an authenticity tag, not a cryptographic secret. Same-process
    code with private introspection or arbitrary object mutation is outside the
    boundary and requires process isolation.
    """

    model_id: str
    role: str
    manifest: WeightManifest
    approval: LicenseApproval
    _fd: int = field(repr=False, compare=False)
    _identity: tuple[int, int] = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("verified components are created only by supply verification")

    def _require_open(self) -> int:
        _validate_verified_component(self, require_open=True, check_fd=True)
        return self._fd

    def borrow_loader_path(self) -> str:
        """Return the Linux fd-borrow path; callers must not retain it past close."""
        return f"/proc/self/fd/{self._require_open()}"

    def close(self) -> None:
        _validate_verified_component(self, require_open=False, check_fd=False)
        fd = self._fd
        if fd >= 0:
            try:
                fd_stat = os.fstat(fd)
                if (fd_stat.st_dev, fd_stat.st_ino) != self._identity:
                    raise InfrastructureError("verified component fd identity changed")
                os.close(fd)
            except OSError as exc:
                raise InfrastructureError("verified component close failed") from exc
            finally:
                object.__setattr__(self, "_fd", -1)

    def __copy__(self) -> VerifiedComponent:
        raise TypeError("verified components cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> VerifiedComponent:
        raise TypeError("verified components cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("verified components cannot be serialized")


@dataclass(frozen=True, slots=True, init=False)
class VerifiedPipelineSupply:
    """Context-managed supported-API capabilities verified under one root fd.

    The seal prevents public construction/copy/pickle/random forgery and
    accidental misuse; it does not resist private introspection or arbitrary
    Python in the same process. Use process isolation for hostile code.
    """

    _models: tuple[VerifiedComponent, ...] = field(repr=False)
    _seal: object = field(repr=False, compare=False)
    _closed: bool = field(repr=False, compare=False)

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("verified supplies are created only by supply verification")

    @property
    def models(self) -> tuple[VerifiedComponent, ...]:
        _validate_verified_supply(self, require_open=True, check_fds=True)
        return self._models

    def borrow_component(self, role: str) -> VerifiedComponent:
        _validate_verified_supply(self, require_open=True, check_fds=True)
        if type(role) is not str:
            raise DomainError("invalid verified component role")
        for component in self._models:
            if component.role == role:
                return component
        raise DomainError("verified component role unavailable")

    def __enter__(self) -> VerifiedPipelineSupply:
        _validate_verified_supply(self, require_open=True, check_fds=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        if exc_type is None:
            self.close()
            return
        try:
            self.close()
        except (DomainError, InfrastructureError):
            pass

    def close(self) -> None:
        _validate_verified_supply(self, require_open=False, check_fds=False)
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        errors: list[InfrastructureError] = []
        for component in self._models:
            try:
                component.close()
            except InfrastructureError as exc:
                errors.append(exc)
        if errors:
            raise InfrastructureError("verified supply close failed") from errors[0]

    def __copy__(self) -> VerifiedPipelineSupply:
        raise TypeError("verified supplies cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> VerifiedPipelineSupply:
        raise TypeError("verified supplies cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("verified supplies cannot be serialized")


def _validate_verified_component(
    component: object, *, require_open: bool, check_fd: bool
) -> None:
    seal = getattr(component, "_seal", None)
    model_id = getattr(component, "model_id", None)
    role = getattr(component, "role", None)
    manifest = getattr(component, "manifest", None)
    approval = getattr(component, "approval", None)
    fd = getattr(component, "_fd", None)
    identity = getattr(component, "_identity", None)
    if (
        type(component) is not VerifiedComponent
        or seal is not _CAPABILITY_SEAL
        or type(model_id) is not str
        or not model_id
        or role not in ("base", "ip_adapter", "controlnet")
        or type(manifest) is not WeightManifest
        or type(approval) is not LicenseApproval
        or type(fd) is not int
        or type(identity) is not tuple
        or len(identity) != 2
        or any(type(part) is not int for part in identity)
        or model_id != manifest.model_id
        or role != manifest.role
        or approval.model_id != manifest.model_id
        or approval.revision != manifest.revision
        or approval.manifest_sha256 != manifest_sha256(manifest)
    ):
        raise DomainError("invalid verified component capability")
    if fd == -1:
        if require_open:
            raise DomainError("verified component is closed")
        return
    if fd < 0:
        raise DomainError("invalid verified component capability")
    if check_fd:
        try:
            fd_stat = os.fstat(fd)
            if (
                not stat.S_ISDIR(fd_stat.st_mode)
                or (
                    fd_stat.st_dev,
                    fd_stat.st_ino,
                )
                != identity
            ):
                raise DomainError("invalid verified component capability")
        except OSError as exc:
            raise DomainError("verified component is closed") from exc


def _validate_verified_supply(
    supply: object, *, require_open: bool, check_fds: bool
) -> None:
    seal = getattr(supply, "_seal", None)
    models = getattr(supply, "_models", None)
    closed = getattr(supply, "_closed", None)
    if (
        type(supply) is not VerifiedPipelineSupply
        or seal is not _CAPABILITY_SEAL
        or type(models) is not tuple
        or len(models) != 3
        or any(type(component) is not VerifiedComponent for component in models)
        or type(closed) is not bool
        or tuple(component.role for component in models)
        != ("base", "ip_adapter", "controlnet")
        or len({component.model_id for component in models}) != 3
    ):
        raise DomainError("invalid verified supply capability")
    if closed:
        if require_open:
            raise DomainError("verified supply is closed")
        return
    for component in models:
        _validate_verified_component(
            component, require_open=require_open, check_fd=check_fds
        )


def _graph_descriptors(graph: object) -> tuple[ModelDescriptor, ...]:
    from specstyle.generation.pipeline_factory import PipelineGraph

    if type(graph) is not PipelineGraph or graph.profile != "production":
        raise DomainError("invalid production pipeline graph")
    descriptors = (graph.base, graph.ip_adapter, graph.controlnet)
    expected_roles = ("base", "ip_adapter", "controlnet")
    if any(type(item) is not ModelDescriptor for item in descriptors):
        raise DomainError("invalid production pipeline graph")
    if tuple(item.role for item in descriptors) != expected_roles:
        raise DomainError("invalid production pipeline roles")
    if len({item.model_id for item in descriptors}) != len(descriptors):
        raise DomainError("duplicate production model")
    return descriptors


def _exact_by_role(
    items: object, cls: type[object], *, label: str
) -> dict[str, object]:
    if type(items) is not tuple:
        raise DomainError(f"invalid {label}")
    result: dict[str, object] = {}
    for item in items:
        if type(item) is not cls or item.role in result:  # type: ignore[attr-defined]
            raise DomainError(f"invalid {label}")
        result[item.role] = item  # type: ignore[attr-defined]
    if set(result) != {"base", "ip_adapter", "controlnet"}:
        raise DomainError(f"invalid {label}")
    return result


def _non_overlapping_component_roots(manifests: tuple[WeightManifest, ...]) -> None:
    roots = tuple(manifest.relative_root for manifest in manifests)
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if (
                left == right
                or left.startswith(f"{right}/")
                or right.startswith(f"{left}/")
            ):
                raise DomainError("overlapping model component roots")


def _close_untransferred_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _approval_for(
    approvals: tuple[LicenseApproval, ...], manifest: WeightManifest
) -> LicenseApproval:
    matches = [
        approval
        for approval in approvals
        if approval.model_id == manifest.model_id
        and approval.revision == manifest.revision
    ]
    if len(matches) != 1:
        raise DomainError("independent license approval missing")
    approval = matches[0]
    if approval.manifest_sha256 != manifest_sha256(manifest):
        raise DomainError("license approval manifest digest mismatch")
    return approval


def verify_pipeline_supply(
    root_fd: int,
    graph: PipelineGraph,
    manifests: tuple[WeightManifest, ...],
    approvals: tuple[LicenseApproval, ...],
) -> VerifiedPipelineSupply:
    """Bind graph pins, manifests and independent approvals before loading locally."""

    def issue_component(
        model_id: str,
        role: str,
        manifest: WeightManifest,
        approval: LicenseApproval,
        fd: int,
    ) -> VerifiedComponent:
        try:
            fd_stat = os.fstat(fd)
        except OSError as exc:
            raise InfrastructureError("model supply component unavailable") from exc
        instance = object.__new__(VerifiedComponent)
        object.__setattr__(instance, "model_id", model_id)
        object.__setattr__(instance, "role", role)
        object.__setattr__(instance, "manifest", manifest)
        object.__setattr__(instance, "approval", approval)
        object.__setattr__(instance, "_fd", fd)
        object.__setattr__(instance, "_identity", (fd_stat.st_dev, fd_stat.st_ino))
        object.__setattr__(instance, "_seal", _CAPABILITY_SEAL)
        _validate_verified_component(instance, require_open=True, check_fd=True)
        return instance

    def issue_supply(
        models: tuple[VerifiedComponent, ...],
    ) -> VerifiedPipelineSupply:
        instance = object.__new__(VerifiedPipelineSupply)
        object.__setattr__(instance, "_models", models)
        object.__setattr__(instance, "_seal", _CAPABILITY_SEAL)
        object.__setattr__(instance, "_closed", False)
        _validate_verified_supply(instance, require_open=True, check_fds=True)
        return instance

    descriptors = _graph_descriptors(graph)
    manifest_by_role = _exact_by_role(
        manifests, WeightManifest, label="weight manifests"
    )
    if (
        type(approvals) is not tuple
        or len(approvals) != 3
        or any(type(item) is not LicenseApproval for item in approvals)
    ):
        raise DomainError("invalid license approvals")
    identities = {(item.model_id, item.revision) for item in approvals}
    if len(identities) != len(approvals):
        raise DomainError("duplicate license approval")
    _non_overlapping_component_roots(manifests)
    retained: list[VerifiedComponent] = []
    directory_identities: set[tuple[int, int]] = set()
    try:
        for descriptor in descriptors:
            ModelRegistry((descriptor,)).require_production(descriptor.model_id)
            manifest = manifest_by_role[descriptor.role]
            if (
                manifest.model_id != descriptor.model_id
                or manifest.revision != descriptor.revision
                or manifest.root_sha256 != descriptor.expected_sha256
                or descriptor.pin.sha256 != descriptor.expected_sha256
            ):
                raise DomainError("model pin and manifest mismatch")
            approval = _approval_for(approvals, manifest)
            if approval.license_spdx != descriptor.license_spdx:
                raise DomainError("license approval mismatch")
            component_fd = _verify_component(root_fd, manifest, keep_open=True)
            if component_fd is None:  # pragma: no cover - internal invariant
                raise InfrastructureError("model supply component unavailable")
            try:
                try:
                    component_stat = os.fstat(component_fd)
                except OSError as exc:
                    raise InfrastructureError(
                        "model supply component unavailable"
                    ) from exc
                identity = (component_stat.st_dev, component_stat.st_ino)
                if identity in directory_identities:
                    raise DomainError("duplicate model component directory identity")
                component = issue_component(
                    descriptor.model_id,
                    descriptor.role,
                    manifest,
                    approval,
                    component_fd,
                )
            except Exception:
                _close_untransferred_fd(component_fd)
                raise
            retained.append(component)
            directory_identities.add(identity)
        return issue_supply(tuple(retained))
    except Exception:
        for component in retained:
            try:
                component.close()
            except InfrastructureError:
                pass
        raise
