from cortex.bench.targets import (
    BROKER_FANOUT_PER_SEC_TARGET,
    EMBEDS_PER_SEC_CPU_TARGET,
    EMBEDS_PER_SEC_RADEON_TARGET,
    QUERIES_PER_SEC_RADEON_TARGET,
)


def test_embeds_radeon_target_matches_design_16_2():
    assert EMBEDS_PER_SEC_RADEON_TARGET == 350


def test_embeds_cpu_target_matches_design_16_2():
    assert EMBEDS_PER_SEC_CPU_TARGET == 30


def test_queries_radeon_target_matches_design_16_2():
    assert QUERIES_PER_SEC_RADEON_TARGET == 50


def test_broker_fanout_target_matches_design_16_2():
    assert BROKER_FANOUT_PER_SEC_TARGET == 1000
