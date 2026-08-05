from pathlib import Path

import yaml
from PIL import Image

from xianglens.config import PROJECT_ROOT
from xianglens.tools.image_tools import ImageInspector


def _fixture(variant: str) -> Path:
    manifest = yaml.safe_load(
        (PROJECT_ROOT / "data/fixtures/manifest.yaml").read_text(encoding="utf-8")
    )
    item = next(record for record in manifest if record["variant"] == variant)
    return PROJECT_ROOT / item["file"]


def test_gps_exif_is_read_from_the_actual_jpeg() -> None:
    inspector = ImageInspector(max_bytes=20_000_000, max_pixels=30_000_000)
    measurement, findings = inspector.inspect(_fixture("gps_exif"))
    assert measurement["width"] == 512
    assert any(item["type"] == "gps_exif" for item in findings)


def test_device_exif_is_read_from_the_actual_jpeg() -> None:
    inspector = ImageInspector(max_bytes=20_000_000, max_pixels=30_000_000)
    _, findings = inspector.inspect(_fixture("device_exif"))
    assert any(item["type"] == "device_exif" for item in findings)


def test_qr_code_is_scanned_by_the_default_runtime() -> None:
    inspector = ImageInspector(max_bytes=20_000_000, max_pixels=30_000_000)
    _, findings = inspector.inspect(_fixture("qr_code"))
    assert any(item["type"] == "qr_code" for item in findings)
    assert all(item["type"] != "qr_scan" for item in findings)


def test_safe_copy_removes_actual_gps_exif(tmp_path: Path) -> None:
    inspector = ImageInspector(max_bytes=20_000_000, max_pixels=30_000_000)
    destination = tmp_path / "safe.jpg"
    details = inspector.export_safe_copy(_fixture("gps_exif"), destination)
    with Image.open(destination) as exported:
        assert exported.getexif() == {}
        assert exported.size == (512, 512)
    assert details["mime_type"] == "image/jpeg"
    assert len(details["sha256"]) == 64
