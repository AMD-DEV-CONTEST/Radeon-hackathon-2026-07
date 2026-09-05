"""Capability recipe controller for the explicit Local WSL2 operation.

The target recipe sequence is intentionally shared with the Private SSH
controller: manifests, launch layouts, self-tests, and exact retirement fences
do not vary by transport.  This module owns the small translation that WSL
needs instead: a typed Local WSL execution location becomes an opaque target,
and bundled shell programs become fixed WSL recipe identifiers.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from uuid import uuid4

from ..compatibility import TargetCompatibilityFacts
from ..manifests import ManifestCapability, ManifestCatalog
from ..placement import AmdExecutionSession, AmdPlacementError, AmdRuntimeKey, LoopbackHttpBinding, RuntimeIncarnation
from ..progress import AmdProgressSink
from ..reconcile import AmdCancellationSignal, AmdExecutionLocation, AmdGenerationMaterialization
from ..remote_supervisor import RemoteGenerationIdentity, RemoteLaunchSpec, RemoteScriptResult
from ..recipes import target_recipe_programs
from .private import PrivateRecipePlacementError, PrivateSshRecipePlacement, _PrivateRecipeSession
from .wsl import (
    WslAmdExecutionSession,
    WslAmdPlacement,
    WslLoopbackVerifier,
    WslPlacementError,
    WslTarget,
    WslTargetRecipe,
)


class LocalWslRecipePlacementError(AmdPlacementError):
    """A bundled Local WSL recipe could not complete safely."""

    error_code = "amd_wsl_recipe_failed"


@dataclass(slots=True)
class _WslRecipeRawSession:
    """Adapt WSL's recipe-ID seam to the shared internal recipe controller."""

    raw: WslAmdExecutionSession
    recipes_by_script: dict[str, WslTargetRecipe]

    @property
    def incarnation(self) -> RuntimeIncarnation:
        return self.raw.incarnation

    @property
    def target_root(self) -> str:
        return self.raw.target_root

    def observe_target_facts(self) -> TargetCompatibilityFacts:
        return self.raw.observe_target_facts().compatibility

    def prepare_recipe_root(self, generation: RemoteGenerationIdentity) -> str:
        return self.raw.prepare_recipe_root(generation)

    def run_generation_recipe(
        self,
        generation: RemoteGenerationIdentity,
        script: str,
        arguments: tuple[str, ...] = (),
        *,
        stdin: bytes | None = None,
        timeout_seconds: float,
    ) -> RemoteScriptResult:
        recipe = self.recipes_by_script.get(script)
        if recipe is None:
            raise LocalWslRecipePlacementError("WSL operation received an unadmitted target recipe.")
        return self.raw.run_generation_recipe(
            generation,
            recipe.recipe_id,
            arguments,
            stdin=stdin,
            timeout_seconds=timeout_seconds,
        )

    def resolve_process_executable(self, command_executable: str) -> str:
        return self.raw.resolve_process_executable(command_executable)

    def allocate_remote_loopback_port(self) -> int:
        return self.raw.allocate_remote_loopback_port()

    def realize(self, spec: RemoteLaunchSpec) -> LoopbackHttpBinding:
        return self.raw.realize(spec)

    def resolve_binding(self, key: AmdRuntimeKey) -> LoopbackHttpBinding:
        return self.raw.resolve_binding(key)

    def cancel_generation_provisioning(self, *, key: AmdRuntimeKey, manifest_digest: str) -> None:
        self.raw.cancel_generation_provisioning(key=key, manifest_digest=manifest_digest)

    def retire_and_cleanup_generation(
        self,
        *,
        key: AmdRuntimeKey,
        manifest_digest: str,
        owned_relative_paths: tuple[str, ...],
    ) -> None:
        self.raw.retire_and_cleanup_generation(
            key=key,
            manifest_digest=manifest_digest,
            owned_relative_paths=owned_relative_paths,
        )

    def close(self) -> None:
        self.raw.close()


class CatalogWslLoopbackVerifier(WslLoopbackVerifier):
    """Prove an authenticated Windows loopback binding against the exact manifest.

    ``RemoteSupervisor`` already verifies the target-side PID, start identity,
    command fingerprint, generation marker, and incarnation.  Acceptance of a
    freshly generated bearer token by the manifest-specific readiness endpoint
    then proves that Windows loopback reaches that exact supervised process;
    merely finding a process on the same port would not pass authentication.
    """

    def __init__(self, catalog: ManifestCatalog) -> None:
        self._catalog = catalog

    def verify(
        self,
        binding: LoopbackHttpBinding,
        generation: RemoteGenerationIdentity,
        *,
        timeout_seconds: float,
    ) -> None:
        if not isinstance(generation, RemoteGenerationIdentity):
            raise LocalWslRecipePlacementError("WSL loopback generation identity is invalid.")
        try:
            manifest = self._catalog.component(generation.manifest_digest)
        except Exception:
            raise LocalWslRecipePlacementError("WSL loopback manifest is unavailable.") from None
        path = (
            f"/v2/models/{manifest.launch.served_model_name}/ready"
            if manifest.capability is ManifestCapability.OCR
            else "/health"
        )
        deadline = time.monotonic() + _require_timeout(timeout_seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LocalWslRecipePlacementError("Windows loopback could not reach the WSL runtime before its deadline.")
            request = urllib.request.Request(
                f"{binding.base_url}{path}",
                method="GET",
                headers={"Authorization": binding.authorization_header()},
            )
            try:
                with urllib.request.urlopen(request, timeout=min(5.0, remaining)) as response:  # noqa: S310
                    if response.status == 200:
                        return
            except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError):
                pass
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))


class LocalWslRecipePlacement(PrivateSshRecipePlacement):
    """Current ``local_wsl`` controller over the shared Linux recipe sequence."""

    placement_kind = "local_wsl"

    def __init__(self, placement: WslAmdPlacement) -> None:
        if not isinstance(placement, WslAmdPlacement):
            raise TypeError("Local WSL recipe placement requires a WSL operation.")
        self._wsl_placement = placement
        self._controller_owner_id = f"amd-controller-{uuid4().hex}"
        recipes = {
            recipe_id: WslTargetRecipe(recipe_id=recipe_id, script=script)
            for recipe_id, script in target_recipe_programs().items()
        }
        self._recipes_by_script = {recipe.script: recipe for recipe in recipes.values()}
        if len(self._recipes_by_script) != len(recipes):
            raise LocalWslRecipePlacementError("WSL target recipe catalogue is ambiguous.")

    def observe(
        self,
        *,
        profile: object,
        location: AmdExecutionLocation,
    ) -> TargetCompatibilityFacts:
        del profile
        session = self._open_location(location)
        try:
            return session.raw.observe_target_facts()
        except WslPlacementError as exc:
            raise LocalWslRecipePlacementError(
                "Local WSL target compatibility facts are unavailable.",
                error_code=exc.error_code,
            ) from None
        finally:
            session.close()

    def materialize(
        self,
        *,
        installation_id: str,
        location: AmdExecutionLocation,
        profile: object,
        generations: tuple[AmdGenerationMaterialization, ...],
        cancellation: AmdCancellationSignal | None = None,
        progress: AmdProgressSink | None = None,
    ) -> AmdExecutionSession:
        del profile
        session = self._open_location(location)
        try:
            for generation in generations:
                self._materialize_generation(session, installation_id, generation, cancellation, progress)
            return session
        except PrivateRecipePlacementError as exc:
            _close_quietly(session)
            raise LocalWslRecipePlacementError("Local WSL AMD provisioning did not complete.", error_code=exc.error_code) from None
        except WslPlacementError as exc:
            _close_quietly(session)
            raise LocalWslRecipePlacementError("Local WSL AMD provisioning did not complete.", error_code=exc.error_code) from None
        except Exception:
            _close_quietly(session)
            raise

    def open_retirement_session(
        self,
        *,
        installation_id: str,
        location: AmdExecutionLocation,
        profile: object,
        generations: tuple[AmdGenerationMaterialization, ...],
    ) -> AmdExecutionSession:
        del installation_id, profile, generations
        return self._open_location(location)

    def self_test(
        self,
        *,
        session: AmdExecutionSession,
        generation: AmdGenerationMaterialization,
    ) -> str:
        try:
            return super().self_test(session=session, generation=generation)
        except PrivateRecipePlacementError as exc:
            raise LocalWslRecipePlacementError("Local WSL AMD self-test did not pass.", error_code=exc.error_code) from None

    def cancel_generation_provisioning(
        self,
        *,
        session: AmdExecutionSession,
        installation_id: str,
        profile: object,
        generation: AmdGenerationMaterialization,
    ) -> None:
        try:
            super().cancel_generation_provisioning(
                session=session,
                installation_id=installation_id,
                profile=profile,
                generation=generation,
            )
        except PrivateRecipePlacementError as exc:
            raise LocalWslRecipePlacementError("Local WSL provisioning could not be cancelled.", error_code=exc.error_code) from None

    def retire_generation(
        self,
        *,
        session: AmdExecutionSession,
        installation_id: str,
        profile: object,
        generation: AmdGenerationMaterialization,
    ) -> None:
        try:
            super().retire_generation(
                session=session,
                installation_id=installation_id,
                profile=profile,
                generation=generation,
            )
        except PrivateRecipePlacementError as exc:
            raise LocalWslRecipePlacementError("Local WSL generation cleanup did not complete.", error_code=exc.error_code) from None

    def _open_location(self, location: AmdExecutionLocation) -> _PrivateRecipeSession:
        target = _target_for_location(location)
        incarnation = RuntimeIncarnation(
            controller_owner_id=self._controller_owner_id,
            incarnation_id=f"amd-incarnation-{uuid4().hex}",
        )
        try:
            raw = self._wsl_placement.open_session(target, incarnation)
        except WslPlacementError as exc:
            raise LocalWslRecipePlacementError(
                "Local WSL target is unavailable.",
                error_code=exc.error_code,
            ) from None
        return _PrivateRecipeSession(
            raw=_WslRecipeRawSession(raw=raw, recipes_by_script=dict(self._recipes_by_script)),
            recipes={},
        )


def _target_for_location(location: AmdExecutionLocation) -> WslTarget:
    if not isinstance(location, AmdExecutionLocation) or location.placement_kind != "local_wsl":
        raise LocalWslRecipePlacementError("Local WSL placement received the wrong execution location.")
    distribution = location.local_wsl_distribution
    if distribution is None:
        raise LocalWslRecipePlacementError("Local WSL distribution is unavailable.")
    digest = hashlib.sha256(distribution.encode("utf-8")).hexdigest()
    return WslTarget(target_id=f"local-wsl-{digest}", distribution=distribution)


def _close_quietly(session: AmdExecutionSession) -> None:
    try:
        session.close()
    except Exception:
        pass


def _require_timeout(value: float) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or not 0 < float(value) <= 1_800:
        raise LocalWslRecipePlacementError("WSL loopback deadline is invalid.")
    return float(value)


__all__ = [
    "CatalogWslLoopbackVerifier",
    "LocalWslRecipePlacement",
    "LocalWslRecipePlacementError",
]
