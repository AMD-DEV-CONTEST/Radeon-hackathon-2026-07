from cortex.console.ring_buffer import EventRingBuffer, MetricsRingBuffer


def test_event_ring_keeps_last_1000():
    buf = EventRingBuffer(capacity=1000)
    for i in range(1001):
        buf.append({"id": i})
    items = buf.snapshot()
    assert len(items) == 1000
    assert items[0] == {"id": 1}
    assert items[-1] == {"id": 1000}


def test_metrics_ring_per_node_last_60():
    buf = MetricsRingBuffer(per_node_capacity=60)
    for i in range(61):
        buf.append({"node": "soc-alpha", "embeds_per_sec_radeon": float(i)})
    buf.append({"node": "soc-beta", "embeds_per_sec_radeon": 1.0})
    alpha = buf.snapshot(node="soc-alpha")
    beta = buf.snapshot(node="soc-beta")
    assert len(alpha) == 60
    assert alpha[0]["embeds_per_sec_radeon"] == 1.0
    assert alpha[-1]["embeds_per_sec_radeon"] == 60.0
    assert len(beta) == 1
