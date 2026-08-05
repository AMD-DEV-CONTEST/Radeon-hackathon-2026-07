from omegaconf import OmegaConf

from rlinf.config import SupportedModel

from smolvla_qvgm_rlinf.extension import register


def test_extension_registration_is_idempotent():
    register()
    register()
    assert SupportedModel("smolvla").value == "smolvla"


def test_config_model_type_is_valid_after_registration():
    register()
    cfg = OmegaConf.create({"model_type": "smolvla"})
    assert SupportedModel(str(cfg.model_type)).value == "smolvla"
