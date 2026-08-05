import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))


def test_find_snapshot_rehydrates_missing_hf_cache(tmp_path, monkeypatch):
    import pb_bulk_spec

    root = tmp_path / "snapshots"
    downloaded = root / "abc123"

    fake_hub = types.ModuleType("huggingface_hub")

    def fake_snapshot_download(**kwargs):
        downloaded.mkdir(parents=True)
        (downloaded / "owner__tool" / "tests").mkdir(parents=True)
        return str(downloaded)

    fake_hub.snapshot_download = fake_snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    monkeypatch.setattr(pb_bulk_spec, "HF_SNAP_ROOT", root)

    assert pb_bulk_spec.find_snapshot() == downloaded


def test_only_filter_accepts_hashless_slug():
    import pb_bulk_spec

    only = {"gabotechs__dep-tree"}

    assert pb_bulk_spec.matches_only("gabotechs__dep-tree.60a95a2", only) is True
    assert pb_bulk_spec.matches_only("other__tool.1234567", only) is False
