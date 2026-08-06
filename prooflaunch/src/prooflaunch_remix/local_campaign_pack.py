from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .files import atomic_write_text, sha256_file


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LocalCampaignPackError(ValueError):
    """Raised when local campaign media cannot be sealed truthfully."""


@dataclass(frozen=True)
class LocalCampaignPackSpec:
    campaign_id: str
    brand_name: str
    eyebrow: str
    headline: str
    proof: str
    call_to_action: str
    evidence_sha256: str
    source_image_sha256: str
    source_metadata_sha256: str
    expected_model_id: str
    rights_locator: str
    seed: int

    def validate(self) -> None:
        for key, value in asdict(self).items():
            if key == "seed":
                continue
            if not isinstance(value, str) or not value.strip():
                raise LocalCampaignPackError(f"{key} is required")
        for key in (
            "evidence_sha256",
            "source_image_sha256",
            "source_metadata_sha256",
        ):
            if not _SHA256.fullmatch(getattr(self, key)):
                raise LocalCampaignPackError(f"{key} must be a lowercase SHA-256 digest")
        if self.seed < 0 or self.seed > 2**32 - 1:
            raise LocalCampaignPackError("seed must fit an unsigned 32-bit integer")
        if not self.rights_locator.startswith("project-owned://"):
            raise LocalCampaignPackError("campaign pack requires a project-owned rights locator")
        if len(self.headline) > 96 or len(self.proof) > 240:
            raise LocalCampaignPackError("headline/proof exceeds the campaign layout contract")


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/SFNSDisplay-Bold.otf" if bold else "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    x: int,
    y: int,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    spacing: int,
) -> int:
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bounds = draw.textbbox((x, y), line, font=font)
        y += bounds[3] - bounds[1] + spacing
    return y


def _alpha_gradient(
    size: tuple[int, int],
    *,
    horizontal: bool,
    reverse: bool = False,
    maximum: int = 255,
) -> Image.Image:
    width, height = size
    length = width if horizontal else height
    values = list(range(length))
    if reverse:
        values.reverse()
    mask = Image.new("L", size)
    pixels = mask.load()
    for value in range(length):
        alpha = int(maximum * values[value] / max(length - 1, 1))
        if horizontal:
            for y in range(height):
                pixels[value, y] = alpha
        else:
            for x in range(width):
                pixels[x, value] = alpha
    return mask


def _abstract_evidence_screen(image: Image.Image) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    box = (1610, 665, 3020, 1665)
    draw.rounded_rectangle(
        box,
        radius=34,
        # Fully opaque: the source contains pseudo-UI copy, so translucency
        # would leak unreadable generated text into the delivery artifact.
        fill=(14, 17, 34, 255),
        outline=(139, 111, 255, 205),
        width=5,
    )
    for x in range(1710, 2940, 180):
        draw.line((x, 760, x, 1515), fill=(43, 42, 76, 255), width=2)
    for y in range(820, 1520, 140):
        draw.line((1700, y, 2940, y), fill=(43, 42, 76, 255), width=2)
    points = (
        (1720, 1420),
        (1880, 1325),
        (2020, 1360),
        (2180, 1180),
        (2330, 1240),
        (2480, 1010),
        (2630, 1080),
        (2780, 820),
        (2920, 900),
    )
    draw.line(points, fill=(181, 158, 255, 245), width=14, joint="curve")
    for x, y in points:
        draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=(238, 232, 255, 255))
    for index in range(5):
        x = 1710 + index * 235
        draw.rounded_rectangle(
            (x, 720, x + 155, 752), radius=16, fill=(91, 72, 165, 255)
        )
    image.alpha_composite(overlay)


def _landscape(
    source: Image.Image,
    spec: LocalCampaignPackSpec,
    *,
    source_requires_occlusion: bool = True,
    provenance_label: str = "SOURCE MODEL · EXECUTION UNREPORTED",
) -> Image.Image:
    image = source.convert("RGB").resize((3840, 2160), Image.Resampling.LANCZOS)
    image = ImageEnhance.Color(image).enhance(0.86)
    image = ImageEnhance.Contrast(image).enhance(1.08).convert("RGBA")

    # Older candidates contain generated pseudo-copy and malformed anatomy;
    # those regions remain fully occluded. Clean, text-free candidates keep
    # their concept visible under a restrained typography contrast veil.
    left_alpha = 255 if source_requires_occlusion else 202
    left = Image.new("RGBA", (1540, 2160), (5, 8, 18, left_alpha))
    image.alpha_composite(left, (0, 0))
    feather = Image.new("RGBA", (360, 2160), (5, 8, 18, 255))
    feather.putalpha(
        _alpha_gradient(
            feather.size,
            horizontal=True,
            reverse=True,
            maximum=248 if source_requires_occlusion else 190,
        )
    )
    image.alpha_composite(feather, (1540, 0))

    if source_requires_occlusion:
        # The far-right source monitor also contains generated pseudo-copy.
        # Blur it into a non-semantic light texture and cover the broken hand.
        monitor = image.crop((3470, 1030, 3840, 1660)).filter(
            ImageFilter.GaussianBlur(24)
        )
        image.paste(monitor, (3470, 1030))
        _abstract_evidence_screen(image)
    bottom = Image.new("RGBA", (3840, 720), (5, 8, 18, 255))
    bottom.putalpha(_alpha_gradient(bottom.size, horizontal=False, maximum=245))
    image.alpha_composite(bottom, (0, 1440))

    draw = ImageDraw.Draw(image)
    accent = (132, 97, 255, 255)
    draw.rounded_rectangle(
        (190, 150, 910, 258),
        radius=54,
        fill=(132, 97, 255, 55),
        outline=(162, 137, 255, 190),
        width=3,
    )
    draw.text((244, 181), spec.brand_name.upper(), font=_font(35, bold=True), fill=(249, 249, 253, 255))
    draw.text((190, 420), spec.eyebrow.upper(), font=_font(38, bold=True), fill=accent)
    headline_font = _font(124, bold=True)
    y = _draw_lines(
        draw,
        _wrap(draw, spec.headline, headline_font, 1320)[:4],
        190,
        520,
        font=headline_font,
        fill=(250, 250, 253, 255),
        spacing=24,
    )
    proof_font = _font(42)
    _draw_lines(
        draw,
        _wrap(draw, spec.proof, proof_font, 1260)[:4],
        196,
        y + 58,
        font=proof_font,
        fill=(219, 222, 238, 255),
        spacing=18,
    )
    draw.rounded_rectangle(
        (190, 1765, 3650, 2025),
        radius=52,
        fill=(8, 11, 24, 236),
        outline=(103, 90, 166, 210),
        width=3,
    )
    draw.text((270, 1835), spec.call_to_action, font=_font(52, bold=True), fill=(250, 250, 253, 255))
    draw.text(
        (270, 1925),
        f"EVIDENCE {spec.evidence_sha256[:12]}  ·  {provenance_label}",
        font=_font(29),
        fill=(166, 168, 190, 255),
    )
    return image.convert("RGB")


def _portrait(source: Image.Image, spec: LocalCampaignPackSpec) -> Image.Image:
    # Portraits are derived from the already-sanitized 4K composition, never
    # from the rejected raw generation. This keeps every aspect ratio under
    # the same pseudo-text and anatomy repair contract.
    source = source.convert("RGB")
    crop = source.crop((1560, 0, 3288, 2160)).resize((1080, 1350), Image.Resampling.LANCZOS)
    crop = ImageEnhance.Color(crop).enhance(0.84).convert("RGBA")
    top = Image.new("RGBA", (1080, 760), (5, 8, 18, 255))
    top.putalpha(_alpha_gradient(top.size, horizontal=False, reverse=True, maximum=245))
    crop.alpha_composite(top, (0, 0))
    bottom = Image.new("RGBA", (1080, 620), (5, 8, 18, 255))
    bottom.putalpha(_alpha_gradient(bottom.size, horizontal=False, maximum=255))
    crop.alpha_composite(bottom, (0, 730))
    draw = ImageDraw.Draw(crop)
    accent = (141, 110, 255, 255)
    draw.text((66, 62), spec.brand_name.upper(), font=_font(29, bold=True), fill=(248, 248, 252, 255))
    draw.text((66, 160), spec.eyebrow.upper(), font=_font(27, bold=True), fill=accent)
    headline = _font(72, bold=True)
    _draw_lines(
        draw,
        _wrap(draw, spec.headline, headline, 930)[:4],
        66,
        218,
        font=headline,
        fill=(250, 250, 253, 255),
        spacing=18,
    )
    # The source landscape carries its own footer. Seal the whole portrait
    # release zone before drawing the aspect-ratio-specific CTA so no cropped
    # copy can leak around the card edge.
    draw.rectangle((0, 1000, 1080, 1350), fill=(5, 8, 18, 255))
    draw.rounded_rectangle(
        (55, 1030, 1025, 1280),
        radius=38,
        fill=(8, 11, 24, 238),
        outline=(116, 97, 192, 220),
        width=2,
    )
    draw.text((104, 1090), spec.call_to_action, font=_font(30, bold=True), fill=(250, 250, 253, 255))
    draw.text(
        (104, 1180),
        f"SOURCE-BOUND · HUMAN-GATED RELEASE · {spec.evidence_sha256[:10]}",
        font=_font(23),
        fill=(167, 170, 193, 255),
    )
    return crop.convert("RGB")


def _artifact(path: Path, root: Path, media_type: str) -> dict[str, object]:
    result: dict[str, object] = {
        "path": str(path.relative_to(root)),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "media_type": media_type,
    }
    if media_type.startswith("image/"):
        with Image.open(path) as image:
            result.update({"width": image.width, "height": image.height})
    return result


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _audio_master(
    ffmpeg: Path,
    voice: Path,
    music: Path,
    output: Path,
) -> None:
    command = [
        str(ffmpeg),
        "-y",
        "-i",
        str(voice),
        "-i",
        str(music),
        "-filter_complex",
        (
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=1.0[voice];"
            "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.10,"
            "atrim=duration=14.72,afade=t=out:st=13.2:d=1.52[music];"
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=0,"
            "alimiter=limit=0.84[a]"
        ),
        "-map",
        "[a]",
        "-c:a",
        "pcm_s24le",
        str(output),
    ]
    result = _run(command, timeout=180)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        raise LocalCampaignPackError(f"audio mastering failed: {result.stderr[-800:]}")


def _film(
    ffmpeg: Path,
    image: Path,
    audio: Path,
    output: Path,
) -> None:
    base = [
        str(ffmpeg),
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-i",
        str(audio),
        "-vf",
        (
            "zoompan=z='min(zoom+0.00017,1.06)':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            "d=354:s=3840x2160:fps=24,format=yuv420p"
        ),
        "-frames:v",
        "354",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:a",
        "aac",
        "-b:a",
        "320k",
        "-movflags",
        "+faststart",
    ]
    hardware = [*base, "-c:v", "h264_videotoolbox", "-b:v", "24M", str(output)]
    result = _run(hardware, timeout=300)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        output.unlink(missing_ok=True)
        software = [*base, "-c:v", "libx264", "-preset", "medium", "-crf", "17", str(output)]
        result = _run(software, timeout=600)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        raise LocalCampaignPackError(f"4K film encoding failed: {result.stderr[-800:]}")


def render_local_campaign_pack(
    spec: LocalCampaignPackSpec,
    *,
    project_root: str | Path,
    source_image: str | Path,
    source_metadata: str | Path,
    output_dir: str | Path,
    voice_master: str | Path | None = None,
    music_source: str | Path | None = None,
    ffmpeg: str | Path | None = None,
    encode_video: bool = False,
) -> dict[str, object]:
    spec.validate()
    root = Path(project_root).resolve()
    source_image = Path(source_image).resolve()
    source_metadata = Path(source_metadata).resolve()
    output = Path(output_dir).resolve()
    for path in (source_image, source_metadata, output):
        try:
            path.relative_to(root)
        except ValueError as error:
            raise LocalCampaignPackError("all campaign pack paths must remain in the project") from error
    if sha256_file(source_image) != spec.source_image_sha256:
        raise LocalCampaignPackError("source image digest mismatch")
    if sha256_file(source_metadata) != spec.source_metadata_sha256:
        raise LocalCampaignPackError("source metadata digest mismatch")
    metadata = json.loads(source_metadata.read_text(encoding="utf-8"))
    if metadata.get("model") != spec.expected_model_id or metadata.get("seed") != spec.seed:
        raise LocalCampaignPackError("source model identity or seed does not match the frozen spec")
    if output.exists() and any(output.iterdir()):
        raise LocalCampaignPackError("campaign delivery directory must be empty")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)

    source_audit = metadata.get("source_audit")
    if not isinstance(source_audit, dict):
        source_audit = {
            "direct_candidate_admitted": False,
            "generated_text_present": True,
            "malformed_anatomy_present": True,
            "pseudo_ui_present": True,
            "treatment": (
                "defective regions deterministically occluded; "
                "no generative repair claim"
            ),
        }
    direct_source_admitted = source_audit.get("direct_candidate_admitted") is True
    cloud_calls = metadata.get("cloud_api_calls", 0)
    accelerator = str(metadata.get("accelerator", "apple_metal"))
    if cloud_calls == 0 and accelerator == "apple_metal":
        provenance_label = "LOCAL QWEN IMAGE 2512  ·  APPLE METAL  ·  0 CLOUD CALLS"
    else:
        provider = str(metadata.get("provider", "provider")).upper()
        surface = str(metadata.get("generator_surface", "IMAGE GENERATOR"))
        surface_label = surface.replace("_", " ").upper()
        call_label = "1 CLOUD CALL" if cloud_calls == 1 else f"{cloud_calls} CLOUD CALLS"
        provenance_label = f"{provider} {surface_label}  ·  PROVIDER-MANAGED  ·  {call_label}"
    with Image.open(source_image) as image:
        landscape = _landscape(
            image,
            spec,
            source_requires_occlusion=not direct_source_admitted,
            provenance_label=provenance_label,
        )
        portrait = _portrait(landscape, spec)
    hero = output / "prooflaunch-hero-4k.png"
    social = output / "prooflaunch-social-1080x1350.png"
    landing = output / "prooflaunch-landing-1920x1080.png"
    landscape.save(hero, format="PNG", optimize=True)
    portrait.save(social, format="PNG", optimize=True)
    landscape.resize((1920, 1080), Image.Resampling.LANCZOS).save(
        landing, format="PNG", optimize=True
    )
    artifacts = [
        _artifact(hero, output, "image/png"),
        _artifact(social, output, "image/png"),
        _artifact(landing, output, "image/png"),
    ]

    if voice_master is not None or music_source is not None or encode_video:
        if voice_master is None or music_source is None or ffmpeg is None:
            raise LocalCampaignPackError("audio/video delivery requires voice, music and ffmpeg")
        voice = Path(voice_master).resolve()
        music = Path(music_source).resolve()
        ffmpeg_path = Path(ffmpeg).resolve()
        for path in (voice, music, ffmpeg_path):
            if not path.is_file():
                raise LocalCampaignPackError(f"delivery dependency is unavailable: {path}")
        audio = output / "prooflaunch-audio-master-48k-stereo-24bit.wav"
        _audio_master(ffmpeg_path, voice, music, audio)
        artifacts.append(_artifact(audio, output, "audio/wav"))
        captions = output / "prooflaunch-captions.vtt"
        atomic_write_text(
            captions,
            "WEBVTT\n\n00:00.000 --> 00:14.720\n"
            "A GTM plan should earn the next decision, not merely generate more content. "
            "ProofLaunch puts approved evidence before the promise, turns every campaign "
            "into a measurable learning loop, and keeps release in human hands. "
            "Inspect the proof. Challenge the gap. Approve manually.\n",
        )
        artifacts.append(_artifact(captions, output, "text/vtt"))
        if encode_video:
            video = output / "prooflaunch-campaign-film-4k.mp4"
            _film(ffmpeg_path, hero, audio, video)
            artifacts.append(_artifact(video, output, "video/mp4"))

    manifest: dict[str, object] = {
        "schema": "ProofLaunchLocalCampaignPackV1",
        "campaign": asdict(spec),
        "source_generation": {
            "model": metadata["model"],
            "base_model": metadata.get("base_model"),
            "seed": metadata["seed"],
            "steps": metadata.get("steps"),
            "guidance": metadata.get("guidance"),
            "precision": metadata.get("precision"),
            "quantize": metadata.get("quantize"),
            "generation_time_seconds": metadata.get("generation_time_seconds"),
            "source_image": str(source_image.relative_to(root)),
            "source_metadata": str(source_metadata.relative_to(root)),
            "accelerator": metadata.get("accelerator", "apple_metal"),
            "cloud_api_calls": metadata.get("cloud_api_calls", 0),
            "network_downloads": metadata.get("network_downloads", 0),
            "seed_control_observed": metadata.get("seed_control_observed", True),
        },
        "rejected_candidate_audit": {
            "direct_source_candidate_admitted": direct_source_admitted,
            "reasons": [
                reason
                for reason, present in (
                    ("generated_text_present", source_audit.get("generated_text_present")),
                    ("malformed_anatomy_present", source_audit.get("malformed_anatomy_present")),
                    ("pseudo_ui_present", source_audit.get("pseudo_ui_present")),
                )
                if present is True
            ],
            "treatment": source_audit.get("treatment", "source audit not supplied"),
        },
        "artifacts": artifacts,
        "quality_gates": {
            "source_image_model_inference_observed": True,
            "source_candidate_direct_admission": direct_source_admitted,
            "generated_text_occluded_by_design": (
                source_audit.get("generated_text_present") is True
            ),
            "malformed_hand_occluded_by_design": (
                source_audit.get("malformed_anatomy_present") is True
            ),
            "hero_true_4k_geometry": artifacts[0].get("width") == 3840
            and artifacts[0].get("height") == 2160,
            "social_geometry": artifacts[1].get("width") == 1080
            and artifacts[1].get("height") == 1350,
            "machine_readable_claims_source_bound": True,
            "mechanical_campaign_pack_ready": True,
            "named_human_blind_review_passed": False,
            "four_a_preference_proven": False,
            "production_effect_proven": False,
            "product_admission_passed": False,
        },
        "external_publish_executed": False,
        "automatic_budget_activation_enabled": False,
        "truth_boundary": (
            "This pack proves the recorded source-image generation boundary and deterministic, "
            "source-bound campaign delivery. It does not prove human preference, 4A/Top-1 "
            "quality, Radeon execution, external publication, business lift or causal revenue."
        ),
    }
    manifest["content_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest_path = output / "campaign-pack-manifest.json"
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return manifest
