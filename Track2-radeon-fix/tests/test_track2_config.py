from swe_experiments.config import ExperimentConfig, SamplingConfig


def test_final_variant_separates_controller_from_context():
    config = ExperimentConfig.from_legacy_variant("C0-J0-A1-V1R1")
    assert config.context == "C0"
    assert config.controller_policy == "A1"
    assert config.verifier == "V1R1"
    assert config.legacy_variant == "C0-J0-V1"


def test_legacy_c5_maps_to_budget_controller():
    config = ExperimentConfig.from_legacy_variant("C5-J0-V0")
    assert config.context == "C0"
    assert config.controller_policy == "A1"


def test_qwen_sampling_wire_fields_are_frozen():
    config = SamplingConfig()
    assert config.to_openai_kwargs() == {
        "temperature": 0.6,
        "top_p": 0.95,
        "presence_penalty": 0.0,
        "max_tokens": 8192,
        "seed": 0,
    }
    assert config.to_extra_body() == {"top_k": 20}
