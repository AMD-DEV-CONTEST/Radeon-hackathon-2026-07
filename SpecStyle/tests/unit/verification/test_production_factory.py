"""Production verifier factory issuance and static binding contracts."""

from __future__ import annotations

import importlib

import pytest

from tests.unit.verification._production_fixtures import (
    _ProductionCase,
    production_case as production_case,
)


def test_production_verifier_factory_is_issued_only() -> None:
    production = importlib.import_module("specstyle.verification.production")

    with pytest.raises(TypeError):
        production._ProductionVerifierFactory()


def test_bound_production_verifier_is_issued_only() -> None:
    production = importlib.import_module("specstyle.verification.production")

    with pytest.raises(TypeError, match="^production verifiers are issued only$"):
        production._BoundProductionVerifier()


def test_factory_create_statically_binds_exact_request_and_plan_without_io(
    production_case: _ProductionCase,
) -> None:
    production = importlib.import_module("specstyle.verification.production")
    allowlist = production_case.allowlist(production)

    factory = production._create_production_verifier_factory(
        production_case.loaded, allowlist
    )
    verifier = factory.create(
        production_case.request,
        production_case.plan,
        production_case.artifact_resolver,
        production_case.style_resolver,
    )

    assert type(factory) is production._ProductionVerifierFactory
    assert callable(verifier.verify)
    assert production_case.artifact_resolver.calls == []
    assert production_case.style_resolver.calls == []
    assert production_case.evidence_calls == {}
