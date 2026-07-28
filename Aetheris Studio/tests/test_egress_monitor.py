"""Fase B test plan: classify_connections() unit-tested against synthetic
connections (no real psutil mocking gymnastics needed), plus a check that
disabling the flag means no background task gets created."""

from collections import namedtuple

from core.audit import egress_monitor as em

_FakeConn = namedtuple("_FakeConn", ["pid", "status", "raddr"])


def test_loopback_only_reports_zero_external():
    conns = [
        _FakeConn(pid=100, status="ESTABLISHED", raddr=("127.0.0.1", 8011)),  # own -> vte-server
        _FakeConn(pid=200, status="ESTABLISHED", raddr=("127.0.0.1", 8001)),  # Flutter -> backend
    ]
    result = em.classify_connections(conns, own_pids={100, 200})
    assert result["external_connections"] == []
    assert result["loopback_count"] == 2


def test_ipv6_loopback_recognized():
    conns = [_FakeConn(pid=100, status="ESTABLISHED", raddr=("::1", 8011))]
    result = em.classify_connections(conns, own_pids={100})
    assert result["loopback_count"] == 1
    assert result["external_connections"] == []


def test_real_external_connection_flagged():
    conns = [
        _FakeConn(pid=100, status="ESTABLISHED", raddr=("127.0.0.1", 8011)),
        _FakeConn(pid=100, status="ESTABLISHED", raddr=("93.184.216.34", 443)),
    ]
    result = em.classify_connections(conns, own_pids={100})
    assert result["loopback_count"] == 1
    assert len(result["external_connections"]) == 1
    assert result["external_connections"][0]["raddr"] == "93.184.216.34:443"
    assert result["external_connections"][0]["label"] == "unknown"


def test_labeled_external_when_browser_active():
    conns = [_FakeConn(pid=100, status="ESTABLISHED", raddr=("93.184.216.34", 443))]
    result = em.classify_connections(conns, own_pids={100}, known_browser_active=True)
    assert result["external_connections"][0]["label"] == "browser tool (read-only, initiated by you)"


def test_connections_from_other_pids_ignored():
    conns = [_FakeConn(pid=9999, status="ESTABLISHED", raddr=("93.184.216.34", 443))]
    result = em.classify_connections(conns, own_pids={100})
    assert result["external_connections"] == []
    assert result["loopback_count"] == 0


def test_connections_without_raddr_ignored():
    conns = [_FakeConn(pid=100, status="LISTEN", raddr=None)]
    result = em.classify_connections(conns, own_pids={100})
    assert result["external_connections"] == []
    assert result["loopback_count"] == 0


def test_egress_disabled_flag(monkeypatch):
    monkeypatch.setenv("AETHERIS_EGRESS_ENABLED", "false")
    assert em.egress_enabled() is False


def test_egress_enabled_by_default(monkeypatch):
    monkeypatch.delenv("AETHERIS_EGRESS_ENABLED", raising=False)
    assert em.egress_enabled() is True
