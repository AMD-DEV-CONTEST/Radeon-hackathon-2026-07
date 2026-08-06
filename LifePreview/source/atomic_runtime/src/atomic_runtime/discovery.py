from __future__ import annotations

import importlib.metadata
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any

from .capabilities import CapabilityPlugin
from .registry import CapabilityRegistry
from .upcasting import UpcasterRegistry, UpcasterSnapshot


CAPABILITY_ENTRY_POINT_GROUP = "douyin.atomic_runtime.capabilities"


class CapabilityDiscoveryError(RuntimeError):
    pass


def _normalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


@dataclass(frozen=True, slots=True)
class _EntryPointIdentity:
    distribution: str | None
    name: str
    value: str

    @property
    def display_name(self) -> str:
        if self.distribution:
            return f"{self.distribution}:{self.name}"
        return self.name


def _identity(entrypoint: Any) -> _EntryPointIdentity:
    distribution = getattr(entrypoint, "dist", None)
    distribution_name = getattr(distribution, "name", None)
    return _EntryPointIdentity(
        distribution=(
            _normalize_distribution_name(str(distribution_name))
            if distribution_name
            else None
        ),
        name=str(entrypoint.name),
        value=str(entrypoint.value),
    )


def _select_entry_points(entry_points: Any | None) -> tuple[Any, ...]:
    available = (
        importlib.metadata.entry_points() if entry_points is None else entry_points
    )
    if hasattr(available, "select"):
        selected = available.select(group=CAPABILITY_ENTRY_POINT_GROUP)
    elif isinstance(available, dict):  # Python 3.9 compatibility for test doubles
        selected = available.get(CAPABILITY_ENTRY_POINT_GROUP, ())
    else:
        selected = (
            entrypoint
            for entrypoint in available
            if getattr(entrypoint, "group", None) == CAPABILITY_ENTRY_POINT_GROUP
        )
    return tuple(
        sorted(
            selected,
            key=lambda entrypoint: (
                _identity(entrypoint).distribution or "",
                _identity(entrypoint).name,
                _identity(entrypoint).value,
            ),
        )
    )


def _is_allowed(
    identity: _EntryPointIdentity,
    allowlist: frozenset[str],
) -> bool:
    if identity.distribution is not None:
        return (
            identity.distribution in allowlist
            or f"{identity.distribution}:{identity.name}" in allowlist
        )
    # importlib.metadata always supplies a distribution. Supporting the name
    # alone keeps small, distribution-less EntryPoint test doubles practical.
    return _normalize_distribution_name(identity.name) in allowlist


def discover_capability_plugins(
    *,
    allowlist: Collection[str],
    entry_points: Any | None = None,
) -> tuple[CapabilityPlugin, ...]:
    """Load one allowlisted plugin set without returning partial success."""

    normalized_allowlist = frozenset(
        (
            f"{_normalize_distribution_name(value.partition(':')[0])}:"
            f"{value.partition(':')[2]}"
            if ":" in value
            else _normalize_distribution_name(value)
        )
        for value in allowlist
    )
    if not normalized_allowlist:
        raise CapabilityDiscoveryError("capability distribution allowlist is empty")

    selected = _select_entry_points(entry_points)
    identities = tuple(_identity(entrypoint) for entrypoint in selected)
    denied = tuple(
        identity.display_name
        for identity in identities
        if not _is_allowed(identity, normalized_allowlist)
    )
    if denied:
        # Crucially, no entrypoint has been imported yet.
        raise CapabilityDiscoveryError(
            "unallowlisted capability entry points present: " + ", ".join(denied)
        )
    missing = tuple(
        allowed
        for allowed in sorted(normalized_allowlist)
        if not any(
            _is_allowed(identity, frozenset((allowed,)))
            for identity in identities
        )
    )
    if missing:
        raise CapabilityDiscoveryError(
            "allowlisted capability entry points are missing: " + ", ".join(missing)
        )

    loaded: list[CapabilityPlugin] = []
    try:
        for entrypoint in selected:
            value = entrypoint.load()
            plugin = value() if callable(value) else value
            if not isinstance(plugin, CapabilityPlugin):
                raise TypeError("entrypoint did not return CapabilityPlugin")
            loaded.append(plugin)
    except Exception as exc:
        # Loaded plugin objects are local only; caller and registry see nothing.
        raise CapabilityDiscoveryError(
            "capability plugin set could not be loaded atomically"
        ) from exc

    names = tuple(plugin.name for plugin in loaded)
    if len(names) != len(set(names)):
        raise CapabilityDiscoveryError("capability plugin names collide")
    return tuple(loaded)


def discover_and_register(
    registry: CapabilityRegistry,
    *,
    allowlist: Collection[str],
    entry_points: Any | None = None,
    freeze: bool = True,
    upcasters: UpcasterRegistry | UpcasterSnapshot | Iterable[UpcasterSnapshot] | None = None,
) -> tuple[CapabilityPlugin, ...]:
    """Discover, transactionally register, and normally freeze one plugin set."""

    plugins = discover_capability_plugins(
        allowlist=allowlist,
        entry_points=entry_points,
    )
    if freeze:
        registry.register_plugins_and_freeze(plugins, upcasters=upcasters)
    else:
        registry.register_plugins(plugins)
    return plugins
