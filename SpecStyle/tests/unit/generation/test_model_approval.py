"""MODEL-SUPPLY-001 independent approval and graph binding contract."""

from __future__ import annotations

import hashlib
import os
import copy
import pickle
from pathlib import Path

import pytest

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation import model_approval
from specstyle.generation.model_approval import (
    LicenseApproval,
    VerifiedComponent,
    VerifiedPipelineSupply,
    verify_pipeline_supply,
)
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry
from specstyle.generation.pipeline_factory import PipelineFactory
from specstyle.generation.weight_manifest import (
    ModelLoadEntrypoint,
    WeightFile,
    WeightManifest,
    manifest_sha256,
)


REVISION = "b" * 40


def _sha(data: bytes) -> Sha256:
    return Sha256(hashlib.sha256(data).hexdigest())


def _manifest(model_id: str, role: str, folder: str) -> WeightManifest:
    data = f"{model_id}-safe".encode()
    entrypoint = ModelLoadEntrypoint("diffusers_pretrained", "pipeline")
    payloads = {"pipeline/model.safetensors": data}
    if role == "ip_adapter":
        entrypoint = ModelLoadEntrypoint(
            "diffusers_ip_adapter", "pipeline", "model.safetensors"
        )
        payloads.update(
            {
                "pipeline/image_encoder/config.json": b"{}",
                "pipeline/image_encoder/model.safetensors": b"encoder",
            }
        )
    return WeightManifest(
        model_id,
        role,
        REVISION,
        folder,
        entrypoint,
        tuple(
            WeightFile(path, len(content), _sha(content))
            for path, content in payloads.items()
        ),
        Sha256("0" * 64),
    ).with_computed_root()


def _prepare_supply(tmp_path: Path, roots: tuple[str, str, str] = ("base", "ip", "cn")):
    manifests = (
        _manifest("base", "base", roots[0]),
        _manifest("ip", "ip_adapter", roots[1]),
        _manifest("cn", "controlnet", roots[2]),
    )
    descriptors = tuple(
        ModelDescriptor(
            manifest.model_id,
            manifest.role,
            manifest.revision,
            manifest.root_sha256,
            "Apache-2.0",
            "APPROVED",
            "sdxl",
        )
        for manifest in manifests
    )
    registry = ModelRegistry(descriptors)
    graph = PipelineFactory(registry, tmp_path).build_production("base", "ip", "cn")
    approvals = tuple(
        LicenseApproval(
            manifest.model_id,
            manifest.revision,
            manifest_sha256(manifest),
            "Apache-2.0",
            "https://licenses.example/approval",
        )
        for manifest in manifests
    )
    for manifest in manifests:
        for item in manifest.files:
            path = tmp_path / manifest.relative_root / item.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            content = {
                "pipeline/image_encoder/config.json": b"{}",
                "pipeline/image_encoder/model.safetensors": b"encoder",
            }.get(item.relative_path, f"{manifest.model_id}-safe".encode())
            path.write_bytes(content)
    return graph, manifests, approvals


def test_verify_pipeline_supply_requires_separate_matching_approvals(
    tmp_path: Path,
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with verify_pipeline_supply(root_fd, graph, manifests, approvals) as result:
            assert tuple(item.model_id for item in result.models) == (
                "base",
                "ip",
                "cn",
            )
    finally:
        os.close(root_fd)


def test_verified_supply_closes_component_fds_but_never_the_caller_root(
    tmp_path: Path,
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with verify_pipeline_supply(root_fd, graph, manifests, approvals) as supply:
            component = supply.models[0]
            assert component.borrow_loader_path().startswith("/proc/self/fd/")
        with pytest.raises(DomainError, match="closed"):
            component.borrow_loader_path()
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


def test_verified_capabilities_reject_direct_forgery() -> None:
    with pytest.raises(TypeError):
        VerifiedComponent("base", "base", None, None, 1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        VerifiedPipelineSupply(())


def test_public_api_cannot_wrap_an_arbitrary_directory_fd(tmp_path: Path) -> None:
    arbitrary_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(TypeError):
            VerifiedComponent(arbitrary_fd)
        with pytest.raises(TypeError):
            VerifiedPipelineSupply((arbitrary_fd,))
        assert os.fstat(arbitrary_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(arbitrary_fd)


def test_model_approval_module_exposes_no_capability_mint_helpers() -> None:
    assert not hasattr(model_approval, "_mint_verified_component")
    assert not hasattr(model_approval, "_mint_verified_supply")


def test_supply_closes_retained_fds_when_verification_fails_midway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    retained_fds: list[int] = []
    original = model_approval._verify_component

    def fail_after_first(
        root_fd: int, manifest: WeightManifest, *, keep_open: bool
    ) -> int | None:
        if retained_fds:
            raise DomainError("forced verification failure")
        fd = original(root_fd, manifest, keep_open=keep_open)
        assert fd is not None
        retained_fds.append(fd)
        return fd

    monkeypatch.setattr(model_approval, "_verify_component", fail_after_first)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(DomainError, match="forced"):
            verify_pipeline_supply(root_fd, graph, manifests, approvals)
        with pytest.raises(OSError):
            os.fstat(retained_fds[0])
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


def test_supply_close_continues_when_one_component_fd_is_already_closed(
    tmp_path: Path,
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        supply = verify_pipeline_supply(root_fd, graph, manifests, approvals)
        first, *remaining = supply.models
        os.close(first._fd)
        with pytest.raises(InfrastructureError, match="close"):
            supply.close()
        for component in remaining:
            with pytest.raises(OSError):
                os.fstat(component._fd)
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


def test_supply_exit_preserves_primary_error_while_closing_every_component(
    tmp_path: Path,
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        supply = verify_pipeline_supply(root_fd, graph, manifests, approvals)
        first, *remaining = supply.models
        with pytest.raises(DomainError, match="primary failure"):
            with supply:
                os.close(first._fd)
                raise DomainError("primary failure")
        for component in remaining:
            with pytest.raises(OSError):
                os.fstat(component._fd)
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


def test_component_mint_failure_closes_untransferred_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    opened: list[int] = []
    original_verify = model_approval._verify_component

    def capture_fd(
        root_fd: int, manifest: WeightManifest, *, keep_open: bool
    ) -> int | None:
        fd = original_verify(root_fd, manifest, keep_open=keep_open)
        assert fd is not None
        opened.append(fd)
        return fd

    def fail_mint_validation(
        _component: object, *, require_open: bool, check_fd: bool
    ) -> None:
        assert require_open is True
        assert check_fd is True
        raise DomainError("forced mint failure")

    monkeypatch.setattr(model_approval, "_verify_component", capture_fd)
    monkeypatch.setattr(
        model_approval, "_validate_verified_component", fail_mint_validation
    )
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(DomainError, match="forced mint"):
            verify_pipeline_supply(root_fd, graph, manifests, approvals)
        with pytest.raises(OSError):
            os.fstat(opened[0])
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


@pytest.mark.parametrize(
    "roots",
    [
        ("same", "same", "other"),
        ("a", "a-b", "a/b"),
    ],
)
def test_supply_rejects_equal_or_posix_ancestor_component_roots(
    tmp_path: Path, roots: tuple[str, str, str]
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path, roots)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(DomainError, match="component roots"):
            verify_pipeline_supply(root_fd, graph, manifests, approvals)
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


def test_supply_rejects_duplicate_retained_directory_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    retained: list[int] = []

    def alias_root(root_fd: int, _manifest: WeightManifest, *, keep_open: bool) -> int:
        assert keep_open
        fd = os.dup(root_fd)
        retained.append(fd)
        return fd

    monkeypatch.setattr(model_approval, "_verify_component", alias_root)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(DomainError, match="directory identity"):
            verify_pipeline_supply(root_fd, graph, manifests, approvals)
        for fd in retained:
            with pytest.raises(OSError):
                os.fstat(fd)
        assert os.fstat(root_fd).st_ino == tmp_path.stat().st_ino
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("bad", ["approval", "model", "revision", "digest"])
def test_verify_pipeline_supply_rejects_mismatched_approval(
    tmp_path: Path, bad: str
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    if bad == "approval":
        approvals = approvals[:-1]
    else:
        first = approvals[0]
        approvals = (
            LicenseApproval(
                "other" if bad == "model" else first.model_id,
                "c" * 40 if bad == "revision" else first.revision,
                Sha256("1" * 64) if bad == "digest" else first.manifest_sha256,
                first.license_spdx,
                first.evidence_url,
            ),
            *approvals[1:],
        )
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(DomainError):
            verify_pipeline_supply(root_fd, graph, manifests, approvals)
    finally:
        os.close(root_fd)


def test_verify_pipeline_supply_rejects_status_only_candidate_approval(
    tmp_path: Path,
) -> None:
    graph, manifests, _approvals = _prepare_supply(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(DomainError, match="approval"):
            verify_pipeline_supply(root_fd, graph, manifests, ())
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("status", ["UNKNOWN", "BLOCKED"])
def test_registry_rejects_non_approved_statuses(status: str) -> None:
    descriptor = ModelDescriptor(
        "base", "base", REVISION, Sha256("1" * 64), "MIT", status, "sdxl"
    )
    with pytest.raises(DomainError):
        ModelRegistry((descriptor,)).require_production("base")


def test_registry_rejects_floating_revision_only_at_production_gate() -> None:
    descriptor = ModelDescriptor(
        "base",
        "base",
        "rev-placeholder",
        Sha256("1" * 64),
        "MIT",
        "APPROVED",
        "sdxl",
    )

    with pytest.raises(DomainError, match="full lowercase"):
        ModelRegistry((descriptor,)).require_production("base")


@pytest.mark.parametrize(
    "license_spdx",
    [
        " UNKNOWN ",
        "tBd",
        "Placeholder",
        "MIT OR Apache-2.0",
        "Totally-Made-Up",
    ],
)
def test_license_approval_rejects_reserved_or_unsupported_license_values(
    license_spdx: str,
) -> None:
    with pytest.raises(DomainError, match="license approval spdx"):
        LicenseApproval(
            "base",
            REVISION,
            Sha256("1" * 64),
            license_spdx,
            "https://licenses.example/evidence",
        )


@pytest.mark.parametrize(
    "evidence_url",
    [
        "http://licenses.example/evidence",
        "https:///missing-host",
        "https://user:secret@licenses.example/evidence",
        "https://licenses.example/evidence#fragment",
        "https://licenses.example/ev\x00idence",
    ],
)
def test_license_approval_rejects_untrusted_evidence_urls(evidence_url: str) -> None:
    with pytest.raises(DomainError, match="approval evidence"):
        LicenseApproval(
            "base",
            REVISION,
            Sha256("1" * 64),
            "Apache-2.0",
            evidence_url,
        )


def test_verified_capabilities_reject_copy_pickle_and_closed_borrow(
    tmp_path: Path,
) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        supply = verify_pipeline_supply(root_fd, graph, manifests, approvals)
        component = supply.borrow_component("base")
        for operation in (
            lambda: copy.copy(component),
            lambda: copy.deepcopy(component),
            lambda: pickle.dumps(component),
            lambda: copy.copy(supply),
            lambda: copy.deepcopy(supply),
            lambda: pickle.dumps(supply),
        ):
            with pytest.raises(TypeError):
                operation()
        supply.close()
        supply.close()
        with pytest.raises(DomainError, match="closed"):
            supply.borrow_component("base")
    finally:
        os.close(root_fd)


def test_verified_capability_has_no_externally_callable_create() -> None:
    assert not hasattr(VerifiedComponent, "_create")
    assert not hasattr(VerifiedPipelineSupply, "_create")


def test_verified_capabilities_reject_bogus_identity_seals(tmp_path: Path) -> None:
    graph, manifests, approvals = _prepare_supply(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with verify_pipeline_supply(root_fd, graph, manifests, approvals) as supply:
            genuine = supply.borrow_component("base")
            forged_component = object.__new__(VerifiedComponent)
            for field_name in (
                "model_id",
                "role",
                "manifest",
                "approval",
                "_fd",
                "_identity",
            ):
                object.__setattr__(
                    forged_component, field_name, getattr(genuine, field_name)
                )
            object.__setattr__(forged_component, "_seal", object())
            with pytest.raises(DomainError, match="capability"):
                forged_component.borrow_loader_path()

            forged_supply = object.__new__(VerifiedPipelineSupply)
            object.__setattr__(forged_supply, "_models", supply.models)
            object.__setattr__(forged_supply, "_seal", object())
            object.__setattr__(forged_supply, "_closed", False)
            with pytest.raises(DomainError, match="capability"):
                forged_supply.borrow_component("base")
    finally:
        os.close(root_fd)


@pytest.mark.parametrize("hostile", [{}, {"base": "not-a-manifest"}])
def test_verify_pipeline_supply_rejects_hostile_container_types(
    tmp_path: Path, hostile: object
) -> None:
    graph, _manifests, approvals = _prepare_supply(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(DomainError):
            verify_pipeline_supply(root_fd, graph, hostile, approvals)
    finally:
        os.close(root_fd)
