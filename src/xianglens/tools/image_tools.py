"""Image validation, measurable properties, and privacy metadata checks."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class ImageValidationError(ValueError):
    pass


class ImageInspector:
    def __init__(self, max_bytes: int, max_pixels: int) -> None:
        self.max_bytes = max_bytes
        self.max_pixels = max_pixels

    def validate_upload(self, data: bytes) -> dict[str, Any]:
        if not data:
            raise ImageValidationError("The uploaded file is empty")
        if len(data) > self.max_bytes:
            raise ImageValidationError("The uploaded file exceeds the configured size limit")
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image_format = image.format or ""
                if image_format not in ALLOWED_FORMATS:
                    raise ImageValidationError("Only JPEG, PNG, and WebP images are accepted")
                width, height = image.size
                if width * height > self.max_pixels:
                    raise ImageValidationError("Decoded image dimensions exceed the pixel limit")
                if width < 32 or height < 32:
                    raise ImageValidationError("The image is too small for a useful review")
                return {
                    "format": image_format,
                    "mime_type": ALLOWED_FORMATS[image_format],
                    "width": width,
                    "height": height,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "extension": ".jpg" if image_format == "JPEG" else f".{image_format.lower()}",
                }
        except (UnidentifiedImageError, OSError) as exc:
            raise ImageValidationError("The file is not a decodable image") from exc

    def inspect(self, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with Image.open(path) as raw:
            image_format = raw.format or "unknown"
            width, height = raw.size
            exif = raw.getexif()
            image = ImageOps.exif_transpose(raw).convert("RGB")
            thumbnail = image.copy()
            thumbnail.thumbnail((64, 64), Image.Resampling.LANCZOS)
            colors = thumbnail.quantize(colors=5).getpalette()[:15]

        ratio = width / height
        measurement = {
            "image_id": path.stem,
            "format": image_format,
            "width": width,
            "height": height,
            "aspect_ratio": round(ratio, 4),
            "square_input": abs(ratio - 1.0) < 0.02,
            "corner_loss_in_circle_percent": 21.46,
            "small_preview_sizes": [32, 48, 64],
            "palette_rgb": [colors[index : index + 3] for index in range(0, len(colors), 3)],
        }
        findings = self._metadata_findings(exif)
        findings.extend(self._qr_findings(path))
        return measurement, findings

    def export_safe_copy(self, source: Path, destination: Path) -> dict[str, Any]:
        """Write a normalized JPEG without source metadata."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as raw:
            image = ImageOps.exif_transpose(raw)
            if image.mode in {"RGBA", "LA"}:
                canvas = Image.new("RGB", image.size, "white")
                alpha = image.getchannel("A")
                canvas.paste(image.convert("RGB"), mask=alpha)
                image = canvas
            else:
                image = image.convert("RGB")
            width, height = image.size
            image.save(destination, format="JPEG", quality=92, optimize=True)
        data = destination.read_bytes()
        with Image.open(destination) as exported:
            if exported.getexif():
                destination.unlink(missing_ok=True)
                raise ImageValidationError("The safe copy still contains metadata")
        return {
            "path": str(destination),
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "mime_type": "image/jpeg",
        }

    def _metadata_findings(self, exif: Image.Exif) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo) if ExifTags.IFD.GPSInfo in exif else {}
        if gps:
            findings.append(
                {
                    "type": "gps_exif",
                    "severity": "high",
                    "observable": True,
                    "summary": "The file contains GPS metadata.",
                    "recommendation": "Export a metadata-stripped derivative before sharing.",
                }
            )
        device_fields = {
            name: exif.get(tag)
            for tag, name in ((271, "camera_make"), (272, "camera_model"), (305, "software"))
            if exif.get(tag)
        }
        capture_time = exif.get(36867)
        if capture_time:
            device_fields["capture_time_present"] = True
        if device_fields:
            findings.append(
                {
                    "type": "device_exif",
                    "severity": "medium",
                    "observable": True,
                    "summary": "The file contains device, software, or capture-time metadata.",
                    "fields_present": sorted(device_fields),
                    "recommendation": "Remove metadata that is unnecessary for the avatar.",
                }
            )
        return findings

    def _qr_findings(self, path: Path) -> list[dict[str, Any]]:
        try:
            import cv2
        except ImportError:
            return [
                {
                    "type": "qr_scan",
                    "severity": "info",
                    "observable": False,
                    "summary": (
                        "QR scanning is unavailable because the optional dependency "
                        "is not installed."
                    ),
                }
            ]
        image = cv2.imread(str(path))
        if image is None:
            return []
        value, points, _ = cv2.QRCodeDetector().detectAndDecode(image)
        if points is None:
            return []
        return [
            {
                "type": "qr_code",
                "severity": "high",
                "observable": True,
                "summary": "A QR code is visible in the image.",
                "decoded_value_present": bool(value),
                "decoded_value_length": len(value),
                "recommendation": (
                    "Inspect the destination privately and crop or obscure it if unintended."
                ),
            }
        ]
