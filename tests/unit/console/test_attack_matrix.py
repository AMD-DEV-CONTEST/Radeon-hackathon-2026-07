import pytest
from httpx import ASGITransport, AsyncClient

from cortex.console.attack_matrix import AttackMatrixTracker
from cortex.console.backend import create_app_with_broker
from cortex.console.fanout import Fanout


@pytest.mark.asyncio
async def test_attack_matrix_counts_findings_per_technique(tmp_path):
    tracker = AttackMatrixTracker()
    tracker.on_event({"event": "article.published", "data": {"article": {"id": "a1", "type": "finding", "payload": {"attack_id": "T1059.001"}}}})
    tracker.on_event({"event": "article.published", "data": {"article": {"id": "a2", "type": "finding", "payload": {"attack_id": "T1059.001"}}}})
    assert tracker.counts() == {"T1059.001": 2}


@pytest.mark.asyncio
async def test_attack_matrix_endpoint(tmp_path):
    tracker = AttackMatrixTracker()
    tracker.on_event({"event": "article.published", "data": {"article": {"id": "a1", "type": "finding", "payload": {"attack_id": "T1059.001"}}}})
    app = create_app_with_broker(static_dir=tmp_path, registry_path=tmp_path / "r.json", fanout=Fanout(), broker_url=None, attack_matrix=tracker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/attack-matrix")
    assert r.status_code == 200
    assert r.json() == {"counts": {"T1059.001": 1}}
