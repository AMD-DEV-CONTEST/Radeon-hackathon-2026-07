from fastapi.testclient import TestClient
from main import app
import pytest

@pytest.fixture
def client():
    return TestClient(app)