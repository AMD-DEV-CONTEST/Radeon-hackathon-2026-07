import pytest
from pydantic import ValidationError
from app.schemas import WorldBlueprintRequest

def test_blueprint_request_accepts_source_text():
    assert WorldBlueprintRequest(text="Frozen mountains").text=="Frozen mountains"

def test_blueprint_request_rejects_empty_text():
    with pytest.raises(ValidationError):
        WorldBlueprintRequest(text="")
