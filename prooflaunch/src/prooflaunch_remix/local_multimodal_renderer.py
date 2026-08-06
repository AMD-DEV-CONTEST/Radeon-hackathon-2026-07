from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .files import atomic_write_text, sha256_file


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class LocalRenderError(ValueError):
    """Raised when a local rendered artifact cannot be truthfully sealed."""


@dataclass(frozen=True)
class MultimodalRenderSpec:
    campaign_id: str
    brand_name: str
    headline: str
    proof: str
    call_to_action: str
    evidence_sha256: str
    source_pack_sha256: str
    rights_locator: str
    voiceover_script: str
    accent_hex: str = "#7C5CFF"

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if name in {"evidence_sha256", "source_pack_sha256", "accent_hex"}:
                continue
            if not isinstance(value, str) or not value.strip():
                raise LocalRenderError(f"{name} is required")
        if not _SHA256.fullmatch(self.evidence_sha256):
            raise LocalRenderError("evidence_sha256 must be a lowercase SHA-256 digest")
        if not _SHA256.fullmatch(self.source_pack_sha256):
            raise LocalRenderError("source_pack_sha256 must be a lowercase SHA-256 digest")
        if not _HEX.fullmatch(self.accent_hex):
            raise LocalRenderError("accent_hex must use #RRGGBB")
        if len(self.headline) > 180 or len(self.proof) > 520:
            raise LocalRenderError("headline/proof exceeds the local layout contract")


@dataclass(frozen=True)
class RenderedMediaArtifact:
    artifact_id: str
    relative_path: str
    media_type: str
    content_sha256: str
    bytes: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    generation_backend: str
    rights_locator: str


@dataclass(frozen=True)
class LocalMultimodalRenderReceipt:
    campaign_id: str
    source_pack_sha256: str
    output_root: str
    artifacts: tuple[RenderedMediaArtifact, ...]
    rendered_modalities: tuple[str, ...]
    manifest_path: str
    manifest_sha256: str
    external_publish_executed: bool = False
    four_a_effect_proven: bool = False
    radeon_inference_executed: bool = False
    schema: str = "ProofLaunchLocalMultimodalRenderReceiptV1"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/SFNSDisplay-Bold.otf" if bold else "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
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
    xy: tuple[int, int],
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    spacing: int,
) -> int:
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        box = draw.textbbox((x, y), line, font=font)
        y += box[3] - box[1] + spacing
    return y


class LocalMultimodalRenderer:
    """Render honest local demo media; never promote it as model or 4A evidence."""

    def __init__(self, *, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()

    def render(
        self,
        spec: MultimodalRenderSpec,
        output_dir: str | Path,
        *,
        encode_video: bool = True,
        synthesize_audio: bool = True,
        seconds_per_scene: float = 2.0,
    ) -> LocalMultimodalRenderReceipt:
        spec.validate()
        if not 0.5 <= seconds_per_scene <= 8:
            raise LocalRenderError("seconds_per_scene must be in [0.5, 8]")
        root = Path(output_dir).resolve()
        if root.exists() and any(root.iterdir()):
            raise LocalRenderError("render output directory must be empty")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        frame_root = root / "frames"
        frame_root.mkdir(mode=0o700)

        scenes = (
            ("01-tension", spec.headline, "THE DECISION, MADE INSPECTABLE"),
            ("02-proof", spec.proof, f"EVIDENCE · {spec.evidence_sha256[:12]}"),
            ("03-method", "One claim. One source. One learning loop.", "PROOF BEFORE PROMISE"),
            ("04-action", spec.call_to_action, "HUMAN REVIEW · MANUAL RELEASE"),
        )
        frame_paths: list[Path] = []
        for index, (slug, message, eyebrow) in enumerate(scenes, start=1):
            frame = self._scene(spec, message=message, eyebrow=eyebrow, index=index)
            frame_path = frame_root / f"{slug}.png"
            frame.save(frame_path, format="PNG", optimize=True)
            frame_path.chmod(0o600)
            frame_paths.append(frame_path)

        hero_path = root / "hero-4k.png"
        shutil.copyfile(frame_paths[1], hero_path)
        hero_path.chmod(0o600)
        social_path = root / "social-1080x1350.png"
        self._social(spec).save(social_path, format="PNG", optimize=True)
        social_path.chmod(0o600)
        subtitles_path = root / "captions.vtt"
        atomic_write_text(
            subtitles_path,
            self._captions(tuple(scene[1] for scene in scenes), seconds_per_scene),
        )
        subtitles_path.chmod(0o600)

        artifacts = [
            self._artifact("hero-4k", hero_path, root, "image/png", 3840, 2160, None, "pillow_local_compositor", spec.rights_locator),
            self._artifact("social-portrait", social_path, root, "image/png", 1080, 1350, None, "pillow_local_compositor", spec.rights_locator),
            self._artifact("captions", subtitles_path, root, "text/vtt", None, None, seconds_per_scene * len(scenes), "deterministic_text_track", spec.rights_locator),
        ]

        audio_path: Path | None = None
        if synthesize_audio:
            audio_path = root / "voiceover.aiff"
            self._synthesize_audio(spec.voiceover_script, audio_path)
            artifacts.append(
                self._artifact("voiceover", audio_path, root, "audio/aiff", None, None, self._audio_duration(audio_path), "macos_system_tts", spec.rights_locator)
            )
        if encode_video:
            video_path = root / "campaign-film-4k.mp4"
            if audio_path is None:
                self._encode_video(frame_paths, video_path, seconds_per_scene)
                backend = "macos_avfoundation_h264"
            else:
                silent_path = root / ".campaign-film-4k.silent.mp4"
                self._encode_video(frame_paths, silent_path, seconds_per_scene)
                self._mux_audio(silent_path, audio_path, video_path)
                silent_path.unlink(missing_ok=True)
                backend = "macos_avfoundation_h264_with_system_tts"
            artifacts.append(
                self._artifact("campaign-film-4k", video_path, root, "video/mp4", 3840, 2160, seconds_per_scene * len(scenes), backend, spec.rights_locator)
            )

        modalities = tuple(
            sorted({artifact.media_type.split("/", 1)[0] for artifact in artifacts})
        )
        manifest_basis = {
            "schema": "ProofLaunchLocalMultimodalManifestV1",
            "campaign_id": spec.campaign_id,
            "source_pack_sha256": spec.source_pack_sha256,
            "spec_sha256": hashlib.sha256(
                json.dumps(asdict(spec), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "artifacts": [asdict(artifact) for artifact in artifacts],
            "rendered_modalities": modalities,
            "external_publish_executed": False,
            "four_a_effect_proven": False,
            "radeon_inference_executed": False,
            "truth_boundary": (
                "These are locally rendered, content-addressed demo artifacts. They are not "
                "Radeon model output, human preference evidence, publication evidence, or "
                "proof of 4A/Top-1/business effect."
            ),
        }
        manifest_digest = hashlib.sha256(
            json.dumps(manifest_basis, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        manifest = {**manifest_basis, "manifest_sha256": manifest_digest}
        manifest_path = root / "multimodal-manifest.json"
        atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        manifest_path.chmod(0o600)
        return LocalMultimodalRenderReceipt(
            campaign_id=spec.campaign_id,
            source_pack_sha256=spec.source_pack_sha256,
            output_root=str(root),
            artifacts=tuple(artifacts),
            rendered_modalities=modalities,
            manifest_path=str(manifest_path),
            manifest_sha256=manifest_digest,
        )

    @staticmethod
    def _scene(
        spec: MultimodalRenderSpec,
        *,
        message: str,
        eyebrow: str,
        index: int,
    ) -> Image.Image:
        width, height = 3840, 2160
        image = Image.new("RGBA", (width, height), (8, 10, 19, 255))
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        accent = tuple(int(spec.accent_hex[i : i + 2], 16) for i in (1, 3, 5))
        glow_draw.ellipse((2380, -500, 4400, 1520), fill=(*accent, 135))
        glow = glow.filter(ImageFilter.GaussianBlur(170))
        image.alpha_composite(glow)
        draw = ImageDraw.Draw(image)
        for x in range(0, width, 160):
            draw.line((x, 0, x, height), fill=(255, 255, 255, 9), width=1)
        for y in range(0, height, 160):
            draw.line((0, y, width, y), fill=(255, 255, 255, 9), width=1)
        draw.rounded_rectangle((180, 150, 760, 250), radius=50, fill=(*accent, 50), outline=(*accent, 180), width=2)
        draw.text((230, 177), spec.brand_name.upper(), font=_font(34, bold=True), fill=(242, 244, 255, 255))
        draw.text((180, 390), eyebrow, font=_font(44, bold=True), fill=(*accent, 255))
        headline_font = _font(132 if index != 2 else 104, bold=True)
        lines = _wrap(draw, message, headline_font, 2850)
        _draw_lines(draw, lines[:5], (180, 510), font=headline_font, fill=(247, 247, 252, 255), spacing=30)
        draw.rounded_rectangle((180, 1780, 3650, 1950), radius=42, fill=(20, 23, 38, 255), outline=(70, 74, 104, 255), width=2)
        draw.text((250, 1831), f"0{index} / 04", font=_font(34, bold=True), fill=(*accent, 255))
        draw.text((630, 1827), "SOURCE-BOUND · HUMAN-GOVERNED · ZERO MEDIA SPEND", font=_font(42), fill=(224, 226, 238, 255))
        draw.text((3220, 2030), spec.campaign_id, font=_font(26), fill=(140, 145, 170, 255))
        return image.convert("RGB")

    @staticmethod
    def _social(spec: MultimodalRenderSpec) -> Image.Image:
        image = Image.new("RGBA", (1080, 1350), (8, 10, 19, 255))
        draw = ImageDraw.Draw(image)
        accent = tuple(int(spec.accent_hex[i : i + 2], 16) for i in (1, 3, 5))
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse((760, -180, 1330, 390), fill=(*accent, 145))
        image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(65)))
        draw = ImageDraw.Draw(image)
        draw.text((70, 72), spec.brand_name.upper(), font=_font(28, bold=True), fill=(245, 245, 250, 255))
        draw.text((70, 200), "PROOF BEFORE PROMISE", font=_font(28, bold=True), fill=(*accent, 255))
        lines = _wrap(draw, spec.headline, _font(72, bold=True), 930)
        y = _draw_lines(draw, lines[:5], (70, 270), font=_font(72, bold=True), fill=(248, 248, 252, 255), spacing=20)
        y += 55
        draw.rounded_rectangle((70, y, 1010, y + 260), radius=34, fill=(20, 23, 38, 255), outline=(70, 74, 104, 255), width=2)
        proof_lines = _wrap(draw, spec.proof, _font(31), 820)
        _draw_lines(draw, proof_lines[:5], (120, y + 55), font=_font(31), fill=(232, 234, 244, 255), spacing=12)
        draw.text((70, 1225), spec.call_to_action, font=_font(30, bold=True), fill=(*accent, 255))
        return image.convert("RGB")

    def _encode_video(self, frames: Sequence[Path], output: Path, seconds: float) -> None:
        swift = shutil.which("swift")
        helper = self.project_root / "scripts/encode_frames_avfoundation.swift"
        if swift is None or not helper.is_file():
            raise LocalRenderError(
                "video backend unavailable; install FFmpeg or run the checked macOS AVFoundation helper"
            )
        command = [
            swift,
            str(helper),
            str(output),
            "30",
            str(seconds),
            "3840",
            "2160",
            *(str(frame) for frame in frames),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=240, check=False)
        if completed.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
            raise LocalRenderError(
                f"AVFoundation video encoding failed: {completed.stderr[-800:]}"
            )
        output.chmod(0o600)

    @staticmethod
    def _synthesize_audio(script: str, output: Path) -> None:
        say = shutil.which("say")
        if say is None:
            raise LocalRenderError("local system TTS backend is unavailable")
        completed = subprocess.run(
            [say, "-v", "Samantha", "-r", "168", "-o", str(output), script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
            raise LocalRenderError(f"local audio synthesis failed: {completed.stderr[-800:]}")
        output.chmod(0o600)

    def _mux_audio(self, video: Path, audio: Path, output: Path) -> None:
        swift = shutil.which("swift")
        helper = self.project_root / "scripts/mux_audio_avfoundation.swift"
        if swift is None or not helper.is_file():
            raise LocalRenderError("audio mux backend is unavailable")
        completed = subprocess.run(
            [swift, str(helper), str(video), str(audio), str(output)],
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
            raise LocalRenderError(f"AVFoundation audio mux failed: {completed.stderr[-800:]}")
        output.chmod(0o600)

    @staticmethod
    def _audio_duration(path: Path) -> float | None:
        afinfo = shutil.which("afinfo")
        if afinfo is None:
            return None
        completed = subprocess.run(
            [afinfo, str(path)], capture_output=True, text=True, timeout=30, check=False
        )
        if completed.returncode != 0:
            return None
        match = re.search(r"estimated duration:\s*([0-9.]+)\s+sec", completed.stdout)
        return round(float(match.group(1)), 6) if match else None

    @staticmethod
    def _artifact(
        artifact_id: str,
        path: Path,
        root: Path,
        media_type: str,
        width: int | None,
        height: int | None,
        duration: float | None,
        backend: str,
        rights_locator: str,
    ) -> RenderedMediaArtifact:
        return RenderedMediaArtifact(
            artifact_id=artifact_id,
            relative_path=str(path.relative_to(root)),
            media_type=media_type,
            content_sha256=sha256_file(path),
            bytes=path.stat().st_size,
            width=width,
            height=height,
            duration_seconds=duration,
            generation_backend=backend,
            rights_locator=rights_locator,
        )

    @staticmethod
    def _captions(messages: Sequence[str], seconds: float) -> str:
        def timestamp(value: float) -> str:
            milliseconds = int(round(value * 1000))
            hours, remainder = divmod(milliseconds, 3_600_000)
            minutes, remainder = divmod(remainder, 60_000)
            sec, milli = divmod(remainder, 1000)
            return f"{hours:02d}:{minutes:02d}:{sec:02d}.{milli:03d}"

        lines = ["WEBVTT", ""]
        for index, message in enumerate(messages):
            start, end = index * seconds, (index + 1) * seconds
            lines.extend((str(index + 1), f"{timestamp(start)} --> {timestamp(end)}", message, ""))
        return "\n".join(lines)
