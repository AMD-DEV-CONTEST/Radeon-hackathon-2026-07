import asyncio

import pytest

from cortex.console.fanout import Fanout


@pytest.mark.asyncio
async def test_fanout_event_reaches_all_clients():
    fanout = Fanout()
    q1 = fanout.add_event_client()
    q2 = fanout.add_event_client()
    fanout.publish_event({"id": 1})
    r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    r2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert r1 == {"id": 1}
    assert r2 == {"id": 1}
    assert q1.empty()
