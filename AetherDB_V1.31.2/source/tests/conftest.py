import pytest

from services.embedding_tasks import wait_for_embedding_tasks
from services.media_vision import wait_for_visual_migrations


@pytest.fixture(autouse=True)
def isolate_embedding_worker_registry(monkeypatch):
    """Keep async embedding work inside the registry selected by each test."""
    assert wait_for_embedding_tasks(), "embedding worker did not become idle before test"
    assert wait_for_visual_migrations(), "visual migration worker did not become idle before test"
    yield
    assert wait_for_embedding_tasks(), "embedding worker did not become idle after test"
    assert wait_for_visual_migrations(), "visual migration worker did not become idle after test"
