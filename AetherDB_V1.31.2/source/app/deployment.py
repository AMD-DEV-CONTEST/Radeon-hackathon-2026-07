"""Deployment-mode and capability contracts.

Only local desktop and competition-local authority are enabled in V1.31.2.
Hosted bridge and full server deployment remain explicit, fail-closed
reservations until their account and synchronization models are implemented.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class DeploymentMode(str, Enum):
    LOCAL_DESKTOP = "local_desktop"
    COMPETITION_LOCAL = "competition_local"
    HOSTED_BRIDGE = "hosted_bridge"
    FULL_SERVER_DEPLOYMENT = "full_server_deployment"


class DeploymentStage(str, Enum):
    ENABLED = "enabled"
    PLANNED = "planned"


class PublicationStatus(str, Enum):
    PRIVATE = "private"
    SELECTED = "selected"
    PUBLISHED = "published"
    OUTDATED = "outdated"
    WITHDRAWN = "withdrawn"


class SyncDirection(str, Enum):
    LOCAL_TO_CLOUD_PUBLISH = "local_to_cloud_publish"


class EffectiveRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    AUTHOR = "author"
    READER = "reader"


class Capability(str, Enum):
    READ_CONTENT = "read_content"
    WRITE_CONTENT = "write_content"
    EXECUTE_CREATION_ASSISTANCE = "execute_creation_assistance"
    MANAGE_MODELS = "manage_models"
    MANAGE_MODEL_PACKAGES = "manage_model_packages"
    MANAGE_OLLAMA = "manage_ollama"
    MANAGE_VECTOR_INDEX = "manage_vector_index"
    MANAGE_BACKUPS = "manage_backups"
    MANAGE_DATABASES = "manage_databases"
    MANAGE_IMPORTS = "manage_imports"
    DELETE_ENTITIES = "delete_entities"
    DELETE_CHAPTERS = "delete_chapters"
    DELETE_BOOKS = "delete_books"
    DELETE_DATABASES = "delete_databases"
    MANAGE_TRANSLATIONS = "manage_translations"
    MANAGE_MEDIA = "manage_media"
    MANAGE_TEMPORAL = "manage_temporal"
    MANAGE_SECURITY = "manage_security"
    MANAGE_SYSTEM = "manage_system"


@dataclass(frozen=True)
class DeploymentProfile:
    mode: DeploymentMode
    enabled: bool
    authority: str
    stage: DeploymentStage


@dataclass(frozen=True)
class EffectivePrincipal:
    credential_role: str
    deployment_mode: DeploymentMode
    effective_role: EffectiveRole
    capabilities: frozenset[Capability]

    def has(self, capability: Capability | str) -> bool:
        requested = capability if isinstance(capability, Capability) else Capability(capability)
        return requested in self.capabilities

    def public_capabilities(self) -> list[str]:
        return sorted(capability.value for capability in self.capabilities)


class DeploymentConfigurationError(RuntimeError):
    pass


class DeploymentModeNotEnabled(RuntimeError):
    def __init__(self, mode: DeploymentMode):
        super().__init__(f"Deployment mode is not enabled: {mode.value}")
        self.mode = mode


DEPLOYMENT_PROFILES = {
    DeploymentMode.LOCAL_DESKTOP: DeploymentProfile(
        mode=DeploymentMode.LOCAL_DESKTOP,
        enabled=True,
        authority="local",
        stage=DeploymentStage.ENABLED,
    ),
    DeploymentMode.COMPETITION_LOCAL: DeploymentProfile(
        mode=DeploymentMode.COMPETITION_LOCAL,
        enabled=True,
        authority="local",
        stage=DeploymentStage.ENABLED,
    ),
    DeploymentMode.HOSTED_BRIDGE: DeploymentProfile(
        mode=DeploymentMode.HOSTED_BRIDGE,
        enabled=False,
        authority="local",
        stage=DeploymentStage.PLANNED,
    ),
    DeploymentMode.FULL_SERVER_DEPLOYMENT: DeploymentProfile(
        mode=DeploymentMode.FULL_SERVER_DEPLOYMENT,
        enabled=False,
        authority="server",
        stage=DeploymentStage.PLANNED,
    ),
}

OWNER_CAPABILITIES = frozenset(Capability)
ROLE_CAPABILITIES = {
    EffectiveRole.ADMIN: OWNER_CAPABILITIES,
    EffectiveRole.AUTHOR: frozenset(
        {
            Capability.READ_CONTENT,
            Capability.WRITE_CONTENT,
            Capability.EXECUTE_CREATION_ASSISTANCE,
            Capability.MANAGE_IMPORTS,
            Capability.MANAGE_TRANSLATIONS,
            Capability.MANAGE_MEDIA,
            Capability.MANAGE_TEMPORAL,
        }
    ),
    EffectiveRole.READER: frozenset({Capability.READ_CONTENT}),
}


def get_deployment_mode(environment: Mapping[str, str] | None = None) -> DeploymentMode:
    env = os.environ if environment is None else environment
    explicit = str(env.get("AETHERDB_DEPLOYMENT_MODE", "")).strip().lower()
    if explicit:
        try:
            return DeploymentMode(explicit)
        except ValueError as exc:
            raise DeploymentConfigurationError(
                "AETHERDB_DEPLOYMENT_MODE is not a supported product deployment mode"
            ) from exc

    execution_mode = str(env.get("AETHERDB_EXECUTION_MODE", "")).strip().lower()
    if execution_mode == "competition":
        return DeploymentMode.COMPETITION_LOCAL
    return DeploymentMode.LOCAL_DESKTOP


def get_deployment_profile(
    mode: DeploymentMode | None = None,
    environment: Mapping[str, str] | None = None,
) -> DeploymentProfile:
    resolved = mode or get_deployment_mode(environment)
    return DEPLOYMENT_PROFILES[resolved]


def principal_for_credential_role(
    credential_role: str,
    *,
    mode: DeploymentMode | None = None,
    environment: Mapping[str, str] | None = None,
) -> EffectivePrincipal:
    profile = get_deployment_profile(mode, environment)
    if not profile.enabled:
        raise DeploymentModeNotEnabled(profile.mode)

    if profile.mode in {
        DeploymentMode.LOCAL_DESKTOP,
        DeploymentMode.COMPETITION_LOCAL,
    }:
        return EffectivePrincipal(
            credential_role=credential_role,
            deployment_mode=profile.mode,
            effective_role=EffectiveRole.OWNER,
            capabilities=OWNER_CAPABILITIES,
        )

    role_map = {
        "admin": EffectiveRole.ADMIN,
        "user": EffectiveRole.AUTHOR,
        "author": EffectiveRole.AUTHOR,
        "reader": EffectiveRole.READER,
    }
    effective_role = role_map.get(credential_role)
    if effective_role is None:
        raise ValueError("Unsupported credential role")
    return EffectivePrincipal(
        credential_role=credential_role,
        deployment_mode=profile.mode,
        effective_role=effective_role,
        capabilities=ROLE_CAPABILITIES[effective_role],
    )
