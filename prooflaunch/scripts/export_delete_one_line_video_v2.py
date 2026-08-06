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
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-video-v2"
AUDIO_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/audio-candidate-receipt.json"
AUDIO = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/master/voice-cross-examiner-a-48k-stereo-24bit.wav"
EXPERIENCE_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-experience-v1/receipt.json"
CAROUSEL_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-carousel-v2/receipt.json"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FFMPEG = ROOT.parent / "tapnow-libtv-local-studio/backend-node/node_modules/ffmpeg-static/ffmpeg"
FFPROBE = ROOT.parent / "tapnow-libtv-local-studio/backend-node/node_modules/@ffprobe-installer/darwin-arm64/ffprobe"


SCENES = [
    {
        "id": "01",
        "theme": "paper",
        "eyebrow": "0:00 / OWNED BROWSER CAPTURE",
        "headline": "YOUR BEST<br>HOMEPAGE LINE.",
        "content": '<div class="input"><span>EXACT PUBLIC SENTENCE</span><b>AN AI GTM EMPLOYEE THAT MAKES ANY BRAND GO VIRAL.</b><i></i></div><div class="cursor">ASK FOR ONE WITNESS <em>→</em></div>',
        "footer": "THE CLAIM ENTERS UNDER OATH",
    },
    {
        "id": "02",
        "theme": "acid",
        "eyebrow": "0:03 / CALL THE WITNESSES",
        "headline": "FOUR BOXES.<br>ZERO ARRIVALS.",
        "content": '<div class="witness-grid"><div>INDEPENDENT WIN<strong>NO WITNESS</strong></div><div>ORGANIC BREAKOUT<strong>NO WITNESS</strong></div><div>ATTRIBUTED CONVERSION<strong>NO WITNESS</strong></div><div>RECONCILED REVENUE<strong>NO WITNESS</strong></div></div>',
        "footer": "A MODEL OUTPUT IS NOT AN OUTCOME WITNESS",
    },
    {
        "id": "03",
        "theme": "red",
        "eyebrow": "0:06 / LOCAL VERDICT",
        "headline": "NO<br>WITNESS.",
        "content": '<div class="stricken">AN AI GTM EMPLOYEE THAT MAKES ANY BRAND GO VIRAL.</div><div class="stamp">DELETE FROM PUBLIC PROOF</div>',
        "footer": "KEEP THE AMBITION · STOP PRESENTING IT AS OBSERVED",
    },
    {
        "id": "04",
        "theme": "ink",
        "eyebrow": "0:10 / THE VERSION EVIDENCE CAN CARRY",
        "headline": "KEEP THE<br>HYPOTHESIS.",
        "content": '<div class="replacement"><span>SUPPORTED TODAY</span><b>ProofLaunch turns approved product evidence into an inspectable, human-governed GTM workspace and campaign draft pack.</b></div><div class="final-cta">PUT YOUR CLAIM ON TRIAL <em>→</em></div>',
        "footer": "THE MARKET WILL CROSS-EXAMINE IT ANYWAY",
    },
]


def page(scene: dict[str, str]) -> str:
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
:root{{--paper:#f2eee4;--ink:#090a08;--acid:#dfff2d;--red:#ff4e38;--blue:#3158ff}}*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1920px;overflow:hidden}}body{{font-family:Arial,Helvetica,sans-serif;background:var(--paper);color:var(--ink)}}main{{height:1920px;padding:62px;display:flex;flex-direction:column;border:4px solid currentColor}}body.acid main{{background:var(--acid)}}body.red main{{background:var(--red)}}body.ink main{{background:var(--ink);color:var(--paper);border-color:var(--paper)}}header{{display:flex;justify-content:space-between;gap:30px;border-bottom:3px solid currentColor;padding-bottom:22px}}header div,.eyebrow,footer,.input span,.replacement span{{font:900 18px/1.15 ui-monospace,SFMono-Regular,monospace;letter-spacing:.08em}}.eyebrow{{text-align:right}}h1{{font-size:118px;line-height:.82;letter-spacing:-.075em;margin:100px 0 58px}}.content{{display:flex;flex-direction:column;gap:30px}}.input,.replacement{{border:4px solid currentColor;padding:30px;background:white;color:var(--ink)}}.input b,.replacement b{{display:block;font-size:38px;line-height:1.06;margin-top:24px}}.input{{position:relative}}.input i{{position:absolute;left:28px;right:28px;bottom:25px;height:16px;background:var(--red);transform:rotate(-1deg)}}.cursor,.final-cta{{align-self:flex-start;background:var(--ink);color:var(--paper);padding:24px 28px;font:900 26px/1 ui-monospace,monospace;box-shadow:10px 10px 0 var(--red)}}.cursor em,.final-cta em{{color:var(--acid);font-style:normal}}.witness-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.witness-grid div{{min-height:235px;border:4px solid currentColor;padding:24px;font:900 22px/1.1 ui-monospace,monospace;display:flex;flex-direction:column;justify-content:space-between}}.witness-grid strong{{font-size:34px}}.stricken{{font-size:42px;line-height:1.08;font-weight:900;border:4px solid currentColor;padding:30px;text-decoration:line-through;text-decoration-thickness:16px;text-decoration-color:var(--ink)}}.stamp{{font:900 31px/1 ui-monospace,monospace;border:5px solid var(--ink);align-self:flex-start;padding:22px;transform:rotate(-2deg)}}.replacement{{background:var(--acid);padding:36px}}.replacement b{{font-size:45px}}.final-cta{{background:var(--blue);box-shadow:10px 10px 0 var(--acid);font-size:31px}}footer{{margin-top:auto;border-top:3px solid currentColor;padding-top:26px;display:flex;justify-content:space-between}}footer:after{{content:"PROOFLAUNCH / CLAIM TRIAL"}}
</style></head><body class="{scene['theme']}"><main><header><div>PROOFLAUNCH<br>CLAIM TRIAL</div><div class="eyebrow">{scene['eyebrow']}</div></header><h1>{scene['headline']}</h1><div class="content">{scene['content']}</div><footer>{scene['footer']}</footer></main></body></html>'''


def render(html_path: Path, png_path: Path) -> None:
    png_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"dol-video-{html_path.stem}-", dir="/private/tmp") as profile:
        command = [
            str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
            f"--user-data-dir={profile}", "--window-size=1080,1920", "--force-device-scale-factor=1",
            "--virtual-time-budget=1000", f"--screenshot={png_path}", html_path.as_uri(),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=8)
        except subprocess.TimeoutExpired as error:
            if png_path.is_file():
                return
            raise RuntimeError(f"Chrome timed out before writing {png_path.name}") from error
    if result.returncode != 0 or not png_path.is_file():
        raise RuntimeError(f"Chrome failed for {html_path.name}: {result.stderr[-1000:]}")


def encode(scene_paths: list[Path], target: Path) -> None:
    durations = (3.2, 3.3, 3.5, 5.6)
    inputs: list[str] = []
    for duration, path in zip(durations, scene_paths, strict=True):
        inputs += ["-loop", "1", "-framerate", "30", "-t", str(duration), "-i", str(path)]
    inputs += ["-i", str(AUDIO)]
    filters = []
    frames = (96, 99, 105, 168)
    for index, count in enumerate(frames):
        drift = "0.00022" if index % 2 == 0 else "0.00016"
        filters.append(
            f"[{index}:v]scale=2160:3840,zoompan=z='min(max(zoom,pzoom)+{drift},1.035)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=2160x3840:fps=30,trim=end_frame={count},setpts=PTS-STARTPTS[v{index}]"
        )
    filters += [
        "[v0][v1]xfade=transition=wipeup:duration=0.2:offset=3.0[x1]",
        "[x1][v2]xfade=transition=fadeblack:duration=0.2:offset=6.1[x2]",
        "[x2][v3]xfade=transition=wipeleft:duration=0.2:offset=9.4[vout]",
    ]
    command = [
        str(FFMPEG), "-y", *inputs, "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "4:a:0", "-t", "15.0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not target.is_file():
        raise RuntimeError(f"FFmpeg encode failed: {result.stderr[-4000:]}")


def probe(path: Path) -> dict:
    command = [str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])
    return json.loads(result.stdout)


def extract_audit_frames(video: Path) -> list[Path]:
    audit_dir = OUTPUT / "audit-frames"
    audit_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for timestamp in (1.0, 5.0, 12.0):
        target = audit_dir / f"frame-{timestamp:.1f}.png"
        command = [
            str(FFMPEG), "-y", "-ss", f"{timestamp:.1f}", "-i", str(video),
            "-frames:v", "1", str(target),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not target.is_file():
            raise RuntimeError(f"FFmpeg audit-frame extraction failed: {result.stderr[-2000:]}")
        with Image.open(target) as image:
            if image.size != (2160, 3840):
                raise RuntimeError(f"audit-frame dimension drifted: {target} {image.size}")
        paths.append(target)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-scenes", action="store_true")
    parser.add_argument("--encode", action="store_true")
    args = parser.parse_args()
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    experience = json.loads(EXPERIENCE_RECEIPT.read_text(encoding="utf-8"))
    carousel = json.loads(CAROUSEL_RECEIPT.read_text(encoding="utf-8"))
    if audio_receipt["human_preference_observed"] or experience["production_effect_observed"] or carousel["production_effect_observed"]:
        raise SystemExit("source truth boundary drifted")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    paths = []
    for scene in SCENES:
        html_path = OUTPUT / f"scene-{scene['id']}.html"
        png_path = OUTPUT / f"scene-{scene['id']}-1080x1920.png"
        atomic_write_text(html_path, page(scene))
        if args.render_scenes:
            render(html_path, png_path)
        if not png_path.is_file():
            raise SystemExit(f"missing rendered scene: {png_path}")
        with Image.open(png_path) as image:
            if image.size != (1080, 1920):
                raise SystemExit(f"scene dimension drifted: {png_path} {image.size}")
        paths.append(png_path)
    video = OUTPUT / "prooflaunch-delete-one-line-vertical-4k-v2.mp4"
    if args.encode:
        encode(paths, video)
    if not video.is_file():
        raise SystemExit(f"missing encoded video: {video}")
    media = probe(video)
    video_stream = next(stream for stream in media["streams"] if stream["codec_type"] == "video")
    audio_stream = next(stream for stream in media["streams"] if stream["codec_type"] == "audio")
    duration = float(media["format"]["duration"])
    if (int(video_stream["width"]), int(video_stream["height"])) != (2160, 3840) or not 14.8 <= duration <= 15.1:
        raise SystemExit(f"video contract drifted: {video_stream['width']}x{video_stream['height']} {duration}")
    audit_frames = extract_audit_frames(video)
    receipt = seal({
        "schema": "ProofLaunchDeleteOneLineVideoReceiptV2",
        "creative_concept": "Delete One Line",
        "story_beats": ["owned claim input", "four missing witnesses", "visible deletion verdict", "bounded replacement and retrial"],
        "scene_files": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "bytes": path.stat().st_size} for path in paths],
        "video": {"path": str(video.relative_to(ROOT)), "sha256": sha256_file(video), "bytes": video.stat().st_size, "width": 2160, "height": 3840, "duration_seconds": duration, "codec": video_stream["codec_name"]},
        "encoded_audit_frames": [
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "width": 2160,
                "height": 3840,
            }
            for path in audit_frames
        ],
        "audio": {"path": str(AUDIO.relative_to(ROOT)), "sha256": sha256_file(AUDIO), "codec": audio_stream["codec_name"], "human_listening_review_status": "pending"},
        "source_bindings": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
            for path in (AUDIO_RECEIPT, EXPERIENCE_RECEIPT, CAROUSEL_RECEIPT)
        ],
        "visible_browser_mechanism_present": True,
        "missing_witness_classes_visible": 4,
        "visible_deletion_present": True,
        "bounded_replacement_present": True,
        "first_three_second_human_hook_reviewed": False,
        "human_preference_observed": False,
        "external_publish_executed": False,
        "production_effect_observed": False,
        "truth_boundary": "This is a locally rendered 4K vertical challenger with four inspectable story beats and bound audio. It proves no human preference, platform retention, organic breakout, conversion, revenue, 4A quality or named-product superiority.",
    })
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(video), "duration_seconds": duration, "size": [2160, 3840], "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
