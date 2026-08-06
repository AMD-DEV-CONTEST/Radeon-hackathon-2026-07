"""Pure validation for authenticated loopback-only component bindings.

The helpers model a binding but deliberately do not create sockets or issue
network requests.  Placement owns actual listeners and forwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_address

from .auth import RuntimeBearerToken
from .errors import LoopbackBindingError


_MIN_SECRET_BYTES = 24


@dataclass(frozen=True, slots=True)
class LoopbackListener:
    """A syntactically validated IP listener that cannot resolve off-host."""

    host: str
    port: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", validate_loopback_host(self.host))
        _validate_port(self.port)

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"


@dataclass(frozen=True, slots=True)
class LoopbackBinding:
    """An authenticated binding whose bearer token is hidden from ``repr``."""

    listener: LoopbackListener
    bearer_token: RuntimeBearerToken | str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.listener, LoopbackListener):
            raise LoopbackBindingError()
        token_value = self.bearer_token.value if isinstance(self.bearer_token, RuntimeBearerToken) else self.bearer_token
        _validate_secret(token_value)
        object.__setattr__(self, "bearer_token", token_value)

    @property
    def base_url(self) -> str:
        return self.listener.base_url

    def authorization_header(self) -> str:
        return f"Bearer {self.bearer_token}"

    def __repr__(self) -> str:
        return "LoopbackBinding(<redacted>)"

    def __str__(self) -> str:
        return "<redacted loopback binding>"


def validate_loopback_host(host: str) -> str:
    """Return a canonical loopback IP address and reject names or public IPs."""

    if not isinstance(host, str) or not host or host != host.strip():
        raise LoopbackBindingError()
    if "%" in host:
        raise LoopbackBindingError()
    try:
        address = ip_address(host)
    except ValueError:
        raise LoopbackBindingError() from None
    if not address.is_loopback:
        raise LoopbackBindingError()
    return str(address)


def validate_loopback_listener(host: str, port: int) -> LoopbackListener:
    """Validate one loopback-only listener address without binding it."""

    return LoopbackListener(host=host, port=port)


def validate_loopback_binding(
    host: str,
    port: int,
    bearer_token: RuntimeBearerToken | str,
) -> LoopbackBinding:
    """Validate a loopback listener and an authentication secret of at least 24 bytes."""

    token_value = bearer_token.value if isinstance(bearer_token, RuntimeBearerToken) else bearer_token
    return LoopbackBinding(
        listener=validate_loopback_listener(host, port),
        bearer_token=token_value,
    )


def _validate_port(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65_535:
        raise LoopbackBindingError()


def _validate_secret(value: object) -> None:
    if not isinstance(value, str):
        raise LoopbackBindingError()
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise LoopbackBindingError() from None
    if (
        len(encoded) < _MIN_SECRET_BYTES
        or any(ord(character) < 0x21 or ord(character) == 0x7F for character in value)
    ):
        raise LoopbackBindingError()


__all__ = [
    "LoopbackBinding",
    "LoopbackListener",
    "validate_loopback_binding",
    "validate_loopback_host",
    "validate_loopback_listener",
]
