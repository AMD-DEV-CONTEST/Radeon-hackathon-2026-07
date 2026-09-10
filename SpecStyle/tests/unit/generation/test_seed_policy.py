import pytest

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.generation.seed_policy import SeedSnapshot, derive_seed


def test_seed_is_stable_and_matches_fixed_vector() -> None:
    snapshot = derive_seed(Sha256("a" * 64), Sha256("b" * 64), "xhs_grid", 7)
    assert snapshot.seed == 5248768830337932911
    assert snapshot.algorithm == "specstyle.seed.v1"
    assert derive_seed(Sha256("a" * 64), Sha256("b" * 64), "xhs_grid", 7) == snapshot


@pytest.mark.parametrize("value", (-1, 2**31, True, 1.0))
def test_seed_rejects_invalid_variation_index(value: object) -> None:
    with pytest.raises(DomainError):
        derive_seed(Sha256("a" * 64), Sha256("b" * 64), "xhs_grid", value)  # type: ignore[arg-type]


def test_seed_materials_change_but_nonmaterials_do_not() -> None:
    base = derive_seed(Sha256("a" * 64), Sha256("b" * 64), "xhs_grid", 0)
    assert base != derive_seed(Sha256("c" * 64), Sha256("b" * 64), "xhs_grid", 0)
    assert base != derive_seed(Sha256("a" * 64), Sha256("c" * 64), "xhs_grid", 0)
    assert base != derive_seed(
        Sha256("a" * 64), Sha256("b" * 64), "background_sequence", 0
    )
    assert base != derive_seed(Sha256("a" * 64), Sha256("b" * 64), "xhs_grid", 1)
    assert 0 <= base.seed < 2**63


def test_seed_rejects_string_subclass_output_profile() -> None:
    class Profile(str):
        pass

    with pytest.raises(DomainError):
        derive_seed(Sha256("a" * 64), Sha256("b" * 64), Profile("xhs_grid"), 0)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ("source_sha256", "compiled_spec_hash"))
def test_seed_snapshot_rejects_forged_nested_hash(field: str) -> None:
    snapshot = derive_seed(Sha256("a" * 64), Sha256("b" * 64), "xhs_grid", 0)
    object.__setattr__(getattr(snapshot, field), "value", "forged")

    with pytest.raises(DomainError):
        SeedSnapshot(
            snapshot.source_sha256,
            snapshot.compiled_spec_hash,
            snapshot.output_profile,
            snapshot.variation_index,
        )
