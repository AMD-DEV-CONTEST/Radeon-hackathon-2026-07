import pytest
from app.services.blueprint_service import BlueprintService

def test_blueprint_service_generates_contextual_world():
    result=BlueprintService().generate("An ancient sandstone city stood among arid desert dunes.")
    assert result.environment.biome.value=="desert"
    assert result.architecture.style.value=="ancient"

def test_blueprint_service_rejects_blank_text():
    with pytest.raises(ValueError,match="cannot be empty"):
        BlueprintService().generate("   ")
