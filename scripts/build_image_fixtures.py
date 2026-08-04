#!/usr/bin/env python3
"""Download open Wikimedia Commons images and build XiangLens fixtures."""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import re
from pathlib import Path
from typing import Any

import requests
import yaml
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
from PIL.TiffImagePlugin import IFDRational

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "XiangLensDataset/0.1 (https://github.com/ld0574/Radeon-hackathon-2026-07)"
ALLOWED_LICENSES = {
    "CC0",
    "Public domain",
    "CC BY 4.0",
    "CC BY-SA 4.0",
    "CC BY 3.0",
    "CC BY-SA 3.0",
}
IMAGE_SIZE = 512


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def metadata_value(metadata: dict[str, Any], key: str) -> str:
    return clean_html(metadata.get(key, {}).get("value", ""))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def fetch_records(catalog: list[dict[str, Any]], width: int) -> dict[str, dict[str, Any]]:
    titles = [item["commons_title"] for item in catalog]
    response = requests.get(
        COMMONS_API,
        params={
            "action": "query",
            "format": "json",
            "titles": "|".join(titles),
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": width,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {}).values()
    records: dict[str, dict[str, Any]] = {}
    for page in pages:
        if page.get("missing"):
            continue
        info = page.get("imageinfo", [{}])[0]
        records[page["title"]] = info
    return records


def download_source(
    item: dict[str, Any],
    info: dict[str, Any],
    output_path: Path,
    force: bool,
) -> Image.Image:
    if output_path.exists() and not force:
        return Image.open(output_path).convert("RGB")
    url = info.get("thumburl") or info["url"]
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content))
    image = ImageOps.exif_transpose(image).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=94, optimize=True)
    return image


def square(image: Image.Image) -> Image.Image:
    return ImageOps.fit(
        image.convert("RGB"),
        (IMAGE_SIZE, IMAGE_SIZE),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.45),
    )


def tight_crop(image: Image.Image, index: int) -> Image.Image:
    base = square(image).resize((660, 660), Image.Resampling.LANCZOS)
    x = 0 if index % 2 == 0 else 148
    y = 12 if index % 3 else 88
    return base.crop((x, y, x + IMAGE_SIZE, y + IMAGE_SIZE))


def subject_small(image: Image.Image, index: int) -> Image.Image:
    base = square(image).resize((270, 270), Image.Resampling.LANCZOS)
    colors = [(226, 232, 240), (236, 229, 218), (220, 231, 224), (230, 226, 238)]
    canvas = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), colors[index % len(colors)])
    canvas.paste(base, ((IMAGE_SIZE - 270) // 2, (IMAGE_SIZE - 270) // 2))
    return canvas


def low_contrast(image: Image.Image) -> Image.Image:
    base = square(image)
    base = ImageEnhance.Contrast(base).enhance(0.32)
    gray = Image.new("RGB", base.size, (174, 174, 174))
    return Image.blend(base, gray, 0.28)


def circular_preview(image: Image.Image) -> Image.Image:
    base = square(image)
    canvas = Image.new("RGB", base.size, (238, 240, 244))
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).ellipse((8, 8, 504, 504), fill=255)
    canvas.paste(base, (0, 0), mask)
    return canvas


def busy_background(image: Image.Image) -> Image.Image:
    base = square(image)
    pattern = Image.new("RGB", base.size, "white")
    draw = ImageDraw.Draw(pattern)
    colors = [(46, 98, 140), (218, 151, 75), (85, 132, 88), (145, 82, 118)]
    cell = 32
    for y in range(0, IMAGE_SIZE, cell):
        for x in range(0, IMAGE_SIZE, cell):
            draw.rectangle(
                (x, y, x + cell - 1, y + cell - 1),
                fill=colors[((x // cell) + (y // cell)) % len(colors)],
            )
    return Image.blend(base, pattern, 0.30)


def with_qr(image: Image.Image, qr: Image.Image) -> Image.Image:
    base = square(image)
    marker = ImageOps.fit(qr.convert("RGB"), (120, 120), Image.Resampling.NEAREST)
    marker = ImageOps.expand(marker, border=8, fill="white")
    base.paste(marker, (IMAGE_SIZE - marker.width - 16, IMAGE_SIZE - marker.height - 16))
    return base


def with_badge(image: Image.Image, index: int) -> Image.Image:
    base = square(image)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    box = (36, 366, 244, 488)
    draw.rounded_rectangle(
        box, radius=12, fill=(248, 250, 252, 245), outline=(25, 55, 82, 255), width=4
    )
    draw.rectangle((36, 366, 244, 397), fill=(25, 91, 143, 255))
    draw.text((49, 371), "DEMO LAB", fill="white", font=load_font(18))
    draw.text((50, 408), f"ALEX TEST {index + 1:02d}", fill=(20, 28, 36), font=load_font(17))
    draw.text((50, 439), f"ID XL-{1000 + index}", fill=(20, 28, 36), font=load_font(15))
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def with_screen(image: Image.Image) -> Image.Image:
    base = square(image)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (250, 316, 504, 500),
        radius=10,
        fill=(18, 31, 46, 232),
        outline=(103, 164, 214, 255),
        width=3,
    )
    font = load_font(15)
    draw.text((268, 338), "dev@example.invalid", fill=(210, 238, 255), font=font)
    draw.text((268, 372), "CLIENT: ALPHA DEMO", fill=(170, 231, 184), font=font)
    draw.text((268, 406), "TOKEN: TEST-ONLY", fill=(255, 205, 144), font=font)
    draw.text((268, 440), "PRIVATE PREVIEW", fill=(255, 164, 164), font=font)
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def with_location_sign(image: Image.Image) -> Image.Image:
    base = square(image)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (40, 380, 472, 480),
        radius=12,
        fill=(250, 244, 207, 242),
        outline=(79, 64, 33, 255),
        width=4,
    )
    draw.text((74, 397), "42 SAMPLE STREET", fill=(39, 34, 25), font=load_font(26))
    draw.text((163, 438), "DEMO CITY", fill=(39, 34, 25), font=load_font(17))
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def with_small_text(image: Image.Image) -> Image.Image:
    base = square(image)
    draw = ImageDraw.Draw(base)
    font = load_font(10)
    draw.text((10, 10), "XIANGLENS LAB / SMALL TEXT TEST", fill=(70, 70, 70), font=font)
    draw.text((262, 490), "details disappear at avatar size", fill=(90, 90, 90), font=font)
    return base


def with_second_subject(image: Image.Image, other: Image.Image) -> Image.Image:
    left = ImageOps.fit(square(image), (256, IMAGE_SIZE), Image.Resampling.LANCZOS)
    right = ImageOps.fit(square(other), (256, IMAGE_SIZE), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), "white")
    canvas.paste(left, (0, 0))
    canvas.paste(right, (256, 0))
    return canvas


def save_jpeg(image: Image.Image, path: Path, exif: Image.Exif | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {"format": "JPEG", "quality": 90, "optimize": True}
    if exif is not None:
        kwargs["exif"] = exif
    image.convert("RGB").save(path, **kwargs)


def gps_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[0x8825] = {
        1: "N",
        2: (IFDRational(31, 1), IFDRational(14, 1), IFDRational(0, 1)),
        3: "E",
        4: (IFDRational(121, 1), IFDRational(28, 1), IFDRational(0, 1)),
        5: 0,
        6: IFDRational(12, 1),
    }
    return exif


def device_exif(index: int) -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "XiangLens Demo Camera"
    exif[0x0110] = f"Synthetic Metadata Model {index + 1:02d}"
    exif[0x0131] = "XiangLens Fixture Builder"
    exif[0x0132] = "2026:07:25 12:34:56"
    exif[0x9003] = "2026:07:25 12:34:56"
    return exif


def source_manifest_record(
    item: dict[str, Any], info: dict[str, Any], path: Path
) -> dict[str, Any]:
    metadata = info.get("extmetadata", {})
    license_name = metadata_value(metadata, "LicenseShortName")
    if license_name not in ALLOWED_LICENSES:
        raise ValueError(f"Unsupported license for {item['id']}: {license_name}")
    return {
        "id": item["id"],
        "role": item["role"],
        "motif": item["motif"],
        "file": path.as_posix(),
        "commons_title": item["commons_title"],
        "source_page": info.get("descriptionurl", ""),
        "download_url": info.get("thumburl") or info.get("url", ""),
        "author": metadata_value(metadata, "Artist"),
        "credit": metadata_value(metadata, "Credit"),
        "license": license_name,
        "license_url": metadata_value(metadata, "LicenseUrl"),
        "sha256": sha256(path),
    }


def fixture_record(
    fixture_id: str,
    path: Path,
    item: dict[str, Any],
    source_record: dict[str, Any],
    variant: str,
    expected_packs: list[str],
    expected_findings: list[str],
) -> dict[str, Any]:
    return {
        "id": fixture_id,
        "file": path.as_posix(),
        "source_id": item["id"],
        "group": item["role"],
        "motif": item["motif"],
        "variant": variant,
        "expected_packs": expected_packs,
        "expected_findings": expected_findings,
        "license": source_record["license"],
        "source_page": source_record["source_page"],
        "sha256": sha256(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--download-width", type=int, default=1200)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    fixture_root = root / "data" / "fixtures"
    catalog_path = fixture_root / "source_catalog.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    records = fetch_records(catalog, args.download_width)

    source_dir = fixture_root / "sources"
    image_dir = fixture_root / "images"
    source_images: dict[str, Image.Image] = {}
    source_manifests: dict[str, dict[str, Any]] = {}

    for item in catalog:
        info = records.get(item["commons_title"])
        if not info:
            raise RuntimeError(f"Commons file not found: {item['commons_title']}")
        suffix = ".png" if item["role"] == "auxiliary" else ".jpg"
        target = source_dir / f"{item['id']}{suffix}"
        image = download_source(item, info, target, args.force)
        source_images[item["id"]] = image
        relative_target = target.relative_to(root)
        source_manifests[item["id"]] = source_manifest_record(item, info, relative_target)

    qr = source_images["auxiliary_qr"]
    portraits = [item for item in catalog if item["role"] == "portrait"]
    culture = [item for item in catalog if item["role"] == "culture"]
    fixtures: list[dict[str, Any]] = []

    privacy_variants = [
        "qr_code",
        "visible_badge",
        "visible_screen",
        "location_sign",
        "small_text",
        "multiple_subjects",
        "gps_exif",
        "device_exif",
    ]

    for index, item in enumerate(portraits):
        source = source_images[item["id"]]
        source_record = source_manifests[item["id"]]
        variants: list[tuple[str, Image.Image, list[str], list[str], Image.Exif | None]] = [
            ("clean", square(source), ["global_professional_context"], ["clean_control"], None),
            (
                "tight_crop",
                tight_crop(source, index),
                ["profile_basics"],
                ["edge_clipping", "crop_risk"],
                None,
            ),
            (
                "subject_small",
                subject_small(source, index),
                ["profile_basics"],
                ["subject_small", "small_size_clarity"],
                None,
            ),
            (
                "low_contrast",
                low_contrast(source),
                ["profile_basics"],
                ["low_contrast", "weak_subject_background_separation"],
                None,
            ),
        ]
        challenge = privacy_variants[index % len(privacy_variants)]
        if challenge == "qr_code":
            image, findings, exif = with_qr(source, qr), ["qr_code", "encoded_link"], None
        elif challenge == "visible_badge":
            image, findings, exif = (
                with_badge(source, index),
                ["badge", "name", "identifier", "employer"],
                None,
            )
        elif challenge == "visible_screen":
            image, findings, exif = (
                with_screen(source),
                ["screen", "email", "project_text", "token_text"],
                None,
            )
        elif challenge == "location_sign":
            image, findings, exif = (
                with_location_sign(source),
                ["street_sign", "location_text"],
                None,
            )
        elif challenge == "small_text":
            image, findings, exif = with_small_text(source), ["small_text", "thin_detail"], None
        elif challenge == "multiple_subjects":
            other = source_images[portraits[(index + 1) % len(portraits)]["id"]]
            image, findings, exif = (
                with_second_subject(source, other),
                ["multiple_subjects", "competing_focal_points"],
                None,
            )
        elif challenge == "gps_exif":
            image, findings, exif = square(source), ["exif", "gps", "geolocation"], gps_exif()
        else:
            image, findings, exif = (
                square(source),
                ["exif", "device_model", "capture_time", "software"],
                device_exif(index),
            )
        challenge_pack = (
            "profile_basics"
            if challenge in {"small_text", "multiple_subjects"}
            else "privacy_safety"
        )
        variants.append((challenge, image, [challenge_pack], findings, exif))

        for variant, image, packs, findings, exif in variants:
            fixture_id = f"{item['id']}__{variant}"
            output = image_dir / f"{fixture_id}.jpg"
            save_jpeg(image, output, exif)
            fixtures.append(
                fixture_record(
                    fixture_id,
                    output.relative_to(root),
                    item,
                    source_record,
                    variant,
                    packs,
                    findings,
                )
            )

    for index, item in enumerate(culture):
        source = source_images[item["id"]]
        source_record = source_manifests[item["id"]]
        variants = [
            ("clean", square(source), ["cultural_motif"]),
            ("circle_preview", circular_preview(source), ["cultural_motif", "circle_crop"]),
            ("subject_small", subject_small(source, index), ["cultural_motif", "subject_small"]),
            ("low_contrast", low_contrast(source), ["cultural_motif", "low_contrast"]),
            ("busy_background", busy_background(source), ["cultural_motif", "busy_background"]),
        ]
        for variant, image, findings in variants:
            fixture_id = f"{item['id']}__{variant}"
            output = image_dir / f"{fixture_id}.jpg"
            save_jpeg(image, output)
            fixtures.append(
                fixture_record(
                    fixture_id,
                    output.relative_to(root),
                    item,
                    source_record,
                    variant,
                    ["open_chinese_symbolism"],
                    findings,
                )
            )

    source_manifest_path = fixture_root / "source_manifest.yaml"
    manifest_path = fixture_root / "manifest.yaml"
    source_manifest_path.write_text(
        yaml.safe_dump(list(source_manifests.values()), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    manifest_path.write_text(
        yaml.safe_dump(fixtures, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    print(f"Sources: {len(source_manifests)}")
    print(f"Fixtures: {len(fixtures)}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
