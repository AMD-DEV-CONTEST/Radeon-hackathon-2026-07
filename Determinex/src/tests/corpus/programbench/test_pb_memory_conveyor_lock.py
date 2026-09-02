import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))


def test_oracle_green_slugs_reads_nested_churn_route_schema(monkeypatch, tmp_path: Path):
    import determinex_pb_memory_conveyor as conveyor

    override_root = tmp_path / "overrides"
    slug = "ducaale__xh.4a6e44f"
    (override_root / slug).mkdir(parents=True)
    monkeypatch.setattr(conveyor, "OVERRIDES", override_root)
    monkeypatch.setattr(conveyor, "_tool_is_terminal", lambda _slug: False)

    events = [
        {
            "slug": slug,
            "ts": "2026-06-30T15:00:00+00:00",
            "route": {"verdict": "oracle-green-ready-for-official"},
            "action": {"name": "hold-official-eval"},
        }
    ]

    assert conveyor._oracle_green_slugs(events, set()) == [slug]


def test_oracle_green_slugs_ignores_nested_non_green_route(monkeypatch, tmp_path: Path):
    import determinex_pb_memory_conveyor as conveyor

    override_root = tmp_path / "overrides"
    slug = "yoav-lavi__melody.f4af9b4"
    (override_root / slug).mkdir(parents=True)
    monkeypatch.setattr(conveyor, "OVERRIDES", override_root)
    monkeypatch.setattr(conveyor, "_tool_is_terminal", lambda _slug: False)

    events = [
        {
            "slug": slug,
            "ts": "2026-06-30T15:00:00+00:00",
            "route": {"verdict": "needs-native-reimpl"},
            "action": {"name": "write-native-reimpl"},
        }
    ]

    assert conveyor._oracle_green_slugs(events, set()) == []
