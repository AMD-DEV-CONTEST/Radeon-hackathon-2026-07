from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-video-v1"
VIDEO_FILENAME = "keep-the-unpostable-vertical-4k-v1.mp4"
RECEIPT_SCHEMA = "ProofLaunchKeepUnpostableVideoReceiptV1"
CREATIVE_VERSION = "v1"
STORY_BEATS = ["break the feed reflex", "one useless detail", "hide the payoff", "owner decides"]
AUDIO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-audio-v1/audio-candidate-receipt.json"
AUDIO = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-audio-v1/master/voice-private-documentary-a-48k-stereo-24bit.wav"
CAROUSEL_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-carousel-v1/receipt.json"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FFMPEG = ROOT.parent / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
FFPROBE = ROOT.parent / "tapnow-libtv-local-studio/backend-node/node_modules/@ffprobe-installer/darwin-arm64/ffprobe"


SCENES = (
    {
        "id": "01",
        "theme": "paper",
        "eyebrow": "0:00 / BREAK THE FEED REFLEX",
        "headline": "DO NOT<br>POST THIS.",
        "body": "Some moments lose value the moment they become content.",
        "motif": '<div class="note">TUE / THE TRAIN ARRIVED EARLY.</div><div class="ring"></div>',
        "footer": "YOUR DAY DOES NOT NEED A DOCUMENTARY",
    },
    {
        "id": "02",
        "theme": "blue",
        "eyebrow": "0:03 / LOWER THE BURDEN",
        "headline": "KEEP ONE<br>USELESS<br>DETAIL.",
        "body": "A SOUND · A COLOR · A SENTENCE · A PLACE",
        "motif": '<div class="tiles"><span>SOUND</span><span>COLOR</span><span>SENTENCE</span><span>PLACE</span></div>',
        "footer": "USELESS TO THE FEED · USEFUL TO YOU",
    },
    {
        "id": "03",
        "theme": "ink",
        "eyebrow": "0:07 / REMOVE THE AUDIENCE",
        "headline": "HIDE THE<br>PAYOFF.",
        "body": "ON DAY SEVEN, THE MEMORY STAYS FACE-DOWN UNTIL ITS OWNER CHOOSES.",
        "motif": '<div class="private-card"><i>DAY 07</i><b>PRIVATE MEMORY</b><span>OWNER CONTROLLED</span></div>',
        "footer": "A WEEKLY ARTIFACT IS NOT A REVEAL MECHANIC",
    },
    {
        "id": "04",
        "theme": "yellow",
        "eyebrow": "0:11 / LET THE OWNER DECIDE",
        "headline": "DID IT EARN<br>ANOTHER<br>WEEK?",
        "body": "KEEP · EDIT · EXPORT · DELETE",
        "motif": '<div class="reply">REPLY ONLY <b>KEEP</b><br><small>NOT THE MEMORY.</small></div>',
        "footer": "NO STREAK · NO AUDIENCE · NO CATCH-UP QUEST",
    },
)


def page(scene: dict[str, str]) -> str:
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
:root{{--paper:#eee9de;--ink:#0b0b0a;--blue:#345cff;--acid:#dcff32;--yellow:#ffd83d}}*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1920px;overflow:hidden}}body{{font-family:Arial,Helvetica,sans-serif;background:var(--paper);color:var(--ink)}}main{{position:relative;display:flex;flex-direction:column;width:100%;height:100%;padding:60px;border:4px solid currentColor;overflow:hidden}}body.blue main{{background:var(--blue);color:#fff}}body.ink main{{background:var(--ink);color:var(--paper);border-color:var(--paper)}}body.yellow main{{background:var(--yellow)}}header{{display:flex;justify-content:space-between;gap:25px;padding-bottom:22px;border-bottom:3px solid currentColor}}header div,.eyebrow,footer{{font:900 18px/1.15 ui-monospace,SFMono-Regular,monospace;letter-spacing:.09em}}.eyebrow{{max-width:560px;text-align:right}}h1{{position:relative;z-index:2;margin:100px 0 48px;font-size:119px;line-height:.82;letter-spacing:-.078em}}.body{{position:relative;z-index:2;max-width:910px;font-size:36px;font-weight:850;line-height:1.13}}.motif{{position:relative;z-index:1;flex:1}}footer{{position:relative;z-index:2;padding-top:25px;border-top:3px solid currentColor}}.note{{position:absolute;left:15px;bottom:220px;width:560px;padding:34px;background:#fff9bd;border:4px solid var(--ink);box-shadow:17px 17px 0 var(--ink);transform:rotate(-2deg);font:900 30px/1.2 ui-monospace,monospace}}.ring{{position:absolute;right:10px;bottom:80px;width:360px;height:360px;border:32px solid rgba(123,73,35,.25);border-radius:50%}}.tiles{{position:absolute;left:0;right:0;bottom:85px;display:grid;grid-template-columns:1fr 1fr;gap:14px}}.tiles span{{padding:34px 20px;border:4px solid currentColor;font:900 27px ui-monospace,monospace}}.tiles span:last-child{{background:var(--acid);color:var(--ink)}}.private-card{{position:absolute;left:100px;right:40px;bottom:95px;height:430px;padding:42px;background:linear-gradient(145deg,#c9c2b5,#f4f0e7);border:4px solid var(--paper);color:var(--ink);box-shadow:30px 30px 0 var(--blue);transform:rotate(-4deg);filter:blur(6px);display:flex;flex-direction:column;justify-content:space-between}}.private-card i,.private-card span{{font:900 22px ui-monospace,monospace}}.private-card b{{font-size:64px;letter-spacing:-.05em}}.reply{{position:absolute;left:0;right:0;bottom:130px;padding:42px;background:var(--ink);color:var(--paper);font:900 43px/1.1 ui-monospace,monospace;box-shadow:18px 18px 0 var(--blue)}}.reply b{{color:var(--acid)}}.reply small{{font-size:25px;color:#bdb8ae}}.truth{{position:absolute;right:60px;bottom:104px;max-width:470px;text-align:right;font:900 12px/1.3 ui-monospace,monospace;letter-spacing:.05em}}
</style></head><body class="{scene['theme']}"><main><header><div>LOOPNOTE<br>PRIVATE / 07</div><div class="eyebrow">{scene['eyebrow']}</div></header><h1>{scene['headline']}</h1><div class="body">{scene['body']}</div><div class="motif">{scene['motif']}</div><footer>{scene['footer']}</footer><div class="truth">SYNTHETIC CONCEPT · NO USER RESULT OR MARKET EFFECT</div></main></body></html>'''


def render(html_path: Path, png_path: Path) -> None:
    png_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"keep-video-{html_path.stem}-", dir="/private/tmp") as profile:
        try:
            result = subprocess.run(
                [
                    str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--user-data-dir={profile}", "--window-size=1080,1920", "--force-device-scale-factor=1",
                    "--virtual-time-budget=1000", f"--screenshot={png_path}", html_path.as_uri(),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired as error:
            if png_path.is_file():
                return
            raise RuntimeError(f"Chrome timed out before writing {png_path.name}") from error
    if result.returncode != 0 or not png_path.is_file():
        raise RuntimeError(f"Chrome failed for {html_path.name}: {result.stderr[-2000:]}")


def encode(scene_paths: list[Path], target: Path) -> None:
    durations = (3.2, 3.8, 4.0, 4.6)
    inputs: list[str] = []
    for duration, path in zip(durations, scene_paths, strict=True):
        inputs += ["-loop", "1", "-framerate", "30", "-t", str(duration), "-i", str(path)]
    inputs += ["-i", str(AUDIO)]
    frames = (96, 114, 120, 138)
    filters = []
    for index, frame_count in enumerate(frames):
        drift = ".00022" if index % 2 == 0 else ".00016"
        filters.append(
            f"[{index}:v]scale=2160:3840,zoompan=z='min(max(zoom,pzoom)+{drift},1.035)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=2160x3840:fps=30,"
            f"trim=end_frame={frame_count},setpts=PTS-STARTPTS[v{index}]"
        )
    filters += [
        "[v0][v1]xfade=transition=wipeup:duration=0.2:offset=3.0[x1]",
        "[x1][v2]xfade=transition=fadeblack:duration=0.2:offset=6.6[x2]",
        "[x2][v3]xfade=transition=wipeleft:duration=0.2:offset=10.4[vout]",
    ]
    result = subprocess.run(
        [
            str(FFMPEG), "-y", *inputs, "-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", "4:a:0", "-t", "15.0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not target.is_file():
        raise RuntimeError(f"FFmpeg encode failed: {result.stderr[-4000:]}")


def probe(path: Path) -> dict:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])
    return json.loads(result.stdout)


def extract_frames(video: Path) -> list[Path]:
    directory = OUTPUT / "audit-frames"
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for timestamp in (1.0, 5.0, 9.0, 13.0):
        target = directory / f"frame-{timestamp:.1f}.png"
        result = subprocess.run(
            [str(FFMPEG), "-y", "-ss", f"{timestamp:.1f}", "-i", str(video), "-frames:v", "1", str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not target.is_file():
            raise RuntimeError(f"audit-frame extraction failed: {result.stderr[-2000:]}")
        with Image.open(target) as image:
            if image.size != (2160, 3840):
                raise RuntimeError(f"audit-frame dimension drift: {target} {image.size}")
        rows.append(target)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-scenes", action="store_true")
    parser.add_argument("--encode", action="store_true")
    args = parser.parse_args()
    audio = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    carousel = json.loads(CAROUSEL_RECEIPT.read_text(encoding="utf-8"))
    if audio["human_preference_observed"] or carousel["human_preference_observed"]:
        raise SystemExit("source truth boundary drifted")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    scene_paths = []
    for scene in SCENES:
        html_path = OUTPUT / f"scene-{scene['id']}.html"
        png_path = OUTPUT / f"scene-{scene['id']}-1080x1920.png"
        atomic_write_text(html_path, page(scene))
        if args.render_scenes and not png_path.is_file():
            render(html_path, png_path)
        if not png_path.is_file():
            raise SystemExit(f"missing rendered scene: {png_path}")
        with Image.open(png_path) as image:
            if image.size != (1080, 1920):
                raise SystemExit(f"scene dimension drift: {png_path} {image.size}")
        scene_paths.append(png_path)
    video = OUTPUT / VIDEO_FILENAME
    if args.encode:
        encode(scene_paths, video)
    if not video.is_file():
        raise SystemExit(f"missing encoded video: {video}")
    media = probe(video)
    video_stream = next(stream for stream in media["streams"] if stream["codec_type"] == "video")
    audio_stream = next(stream for stream in media["streams"] if stream["codec_type"] == "audio")
    duration = float(media["format"]["duration"])
    if (int(video_stream["width"]), int(video_stream["height"])) != (2160, 3840) or not 14.8 <= duration <= 15.1:
        raise SystemExit(f"video contract drifted: {video_stream['width']}x{video_stream['height']} {duration}")
    audit_frames = extract_frames(video)
    receipt = seal(
        {
            "schema": RECEIPT_SCHEMA,
            "creative_version": CREATIVE_VERSION,
            "creative_platform": "Keep the Unpostable",
            "story_beats": STORY_BEATS,
            "scene_files": [
                {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                for path in scene_paths
            ],
            "video": {
                "path": str(video.relative_to(ROOT)), "sha256": sha256_file(video), "bytes": video.stat().st_size,
                "width": 2160, "height": 3840, "duration_seconds": duration, "codec": video_stream["codec_name"],
            },
            "audio": {
                "candidate_id": "voice-private-documentary-a", "path": str(AUDIO.relative_to(ROOT)),
                "sha256": sha256_file(AUDIO), "codec": audio_stream["codec_name"], "human_listening_review_status": "pending",
            },
            "audit_frames": [
                {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                for path in audit_frames
            ],
            "source_bindings": [
                {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
                for path in (AUDIO_RECEIPT, CAROUSEL_RECEIPT)
            ],
            "human_release_required": True,
            "human_visual_review_status": "pending",
            "human_listening_review_status": "pending",
            "external_publish_executed": False,
            "human_preference_observed": False,
            "organic_breakout_observed": False,
            "conversion_observed": False,
            "truth_boundary": (
                "This is a locally rendered 15-second 4K vertical challenger using one pending-review local Qwen3-TTS candidate. "
                "It proves no human preference, direct publishability, organic breakout, conversion, retention, 4A quality or named-product superiority."
            ),
        }
    )
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(video), "duration_seconds": duration, "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
