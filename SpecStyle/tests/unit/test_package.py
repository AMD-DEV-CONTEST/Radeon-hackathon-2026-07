"""Unit tests for package imports, version, and exception hierarchy.

Cover the frozen BOOT-001 contract: top-level package import, exact version
``0.1.0``, ``SpecStyleError`` inheritance from ``Exception``, domain and
infrastructure inheritance from ``SpecStyleError``, and normal raise/catch
behavior for all three exceptions.
"""

import pytest


def test_package_importable():
    """specstyle imports as a top-level package."""
    import specstyle  # noqa: F401


def test_version_is_0_1_0():
    """__version__ equals 0.1.0 exactly."""
    import specstyle

    assert specstyle.__version__ == "0.1.0"


def test_specstyle_error_inherits_exception():
    """SpecStyleError derives from Exception."""
    from specstyle.errors import SpecStyleError

    assert issubclass(SpecStyleError, Exception)


def test_domain_error_inherits_specstyle_error():
    """DomainError derives from SpecStyleError."""
    from specstyle.errors import DomainError, SpecStyleError

    assert issubclass(DomainError, SpecStyleError)


def test_infrastructure_error_inherits_specstyle_error():
    """InfrastructureError derives from SpecStyleError."""
    from specstyle.errors import InfrastructureError, SpecStyleError

    assert issubclass(InfrastructureError, SpecStyleError)


def test_specstyle_error_raise_and_catch():
    """SpecStyleError can be raised and caught directly."""
    from specstyle.errors import SpecStyleError

    with pytest.raises(SpecStyleError):
        raise SpecStyleError("boom")


def test_domain_error_raise_and_catch_as_base():
    """DomainError can be caught as itself or as SpecStyleError."""
    from specstyle.errors import DomainError, SpecStyleError

    with pytest.raises(DomainError):
        raise DomainError("domain")
    with pytest.raises(SpecStyleError):
        raise DomainError("as base")


def test_infrastructure_error_raise_and_catch_as_base():
    """InfrastructureError can be caught as itself or as SpecStyleError."""
    from specstyle.errors import InfrastructureError, SpecStyleError

    with pytest.raises(InfrastructureError):
        raise InfrastructureError("infra")
    with pytest.raises(SpecStyleError):
        raise InfrastructureError("as base")
