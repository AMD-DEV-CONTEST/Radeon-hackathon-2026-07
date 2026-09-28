import io
import os
import sys
from pathlib import Path
import pytest
from PIL import Image

BACKEND = Path(__file__).parents[1]
sys.path.insert(0, str(BACKEND))

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    import app.core.config as config
    config.STORAGE_ROOT = tmp_path / "storage"
    import app.services.store as store_module
    store_module.store = store_module.ProjectStore(config.STORAGE_ROOT)
    import app.api.routes as routes
    routes.store = store_module.store
    routes.STORAGE_ROOT = config.STORAGE_ROOT
    import app.api.rocm as rocm_routes
    rocm_routes.store = store_module.store
    from fastapi.testclient import TestClient
    from app.main import app
    yield TestClient(app)

@pytest.fixture
def payload():
    return {"product_name":"Test Product","product_category":"Skincare","campaign_goal":"Launch awareness","target_audience":"Design-conscious adults","key_benefits":"Simple and durable","brand_tone":"Refined","brand_colors":["#e52f3c","#111318"],"negative_instructions":"","creative_styles":["Luxury"],"output_formats":["Instagram Square"]}

@pytest.fixture
def image_bytes():
    data = io.BytesIO()
    Image.new("RGB", (64, 64), (220, 47, 60)).save(data, "PNG")
    return data.getvalue()
