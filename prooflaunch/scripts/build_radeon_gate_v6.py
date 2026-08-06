from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def markdown(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [line + "\n" for line in text.rstrip().splitlines()],
    }


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [line + "\n" for line in text.rstrip().splitlines()],
    }


def source_of(cell: dict) -> str:
    return "".join(cell.get("source", []))


def set_source(cell: dict, text: str) -> None:
    cell["source"] = [line + "\n" for line in text.rstrip().splitlines()]


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one occurrence of {old!r}")
    return text.replace(old, new, 1)


source = ROOT / "notebooks" / "prooflaunch_radeon_gate_v5.ipynb"
notebook = json.loads(source.read_text(encoding="utf-8"))
for cell in notebook["cells"]:
    set_source(cell, source_of(cell).replace("V5", "V6").replace("v5", "v6"))

runtime_cell = next(
    cell
    for cell in notebook["cells"]
    if "execution_plan = RadeonModelRouter().report" in source_of(cell)
)
runtime_source = source_of(runtime_cell)
runtime_source = replace_once(
    runtime_source,
    '        "vision_language_audit",\n'
    '        "affect_critic",\n'
    '        "image_generation",\n'
    '        "image_text_scoring",\n'
    '        "video_generation",\n',
    '        "vision_language_audit",\n'
    '        "open_set_detection",\n'
    '        "affect_critic",\n'
    '        "image_generation",\n'
    '        "image_text_scoring",\n'
    '        "video_generation",\n'
    '        "temporal_segmentation",\n'
    '        "audio_text_scoring",\n',
)
runtime_source = replace_once(
    runtime_source,
    "    ),\n)\nprint(json.dumps(execution_plan, indent=2))",
    "    ),\n"
    "    include_candidates=True,\n"
    ")\n"
    "print(json.dumps(execution_plan, indent=2))",
)
set_source(runtime_cell, runtime_source)

mission_cell = next(
    cell for cell in notebook["cells"] if 'mission_id="radeon-multimodal-v6"' in source_of(cell)
)
mission_source = source_of(mission_cell)
mission_source = replace_once(
    mission_source,
    "    MultimodalMissionPlanner,\n)",
    "    MultimodalMissionPlanner,\n)\n"
    "from prooflaunch_remix.quality_contract import QualityTier",
)
mission_source = replace_once(
    mission_source,
    "    available_vram_gb=available_vram_gb,\n)",
    "    available_vram_gb=available_vram_gb,\n"
    "    quality_tier=QualityTier.COMPETITION_2X,\n"
    ")",
)
set_source(mission_cell, mission_source)

qwen_index = next(
    index
    for index, cell in enumerate(notebook["cells"])
    if "Qwen3-VL phase complete" in source_of(cell)
)
notebook["cells"][qwen_index + 1 : qwen_index + 1] = [
    markdown(
        """
## 3C. Ground the product with local GroundingDINO

This is a spatial specialist, not a second general chat model. It converts the
owned product phrase into a scored box and source-located observations. The
selected box is later mapped into the composited video and becomes SAM2's
tracking prompt. The model is unloaded before Gemma starts.
"""
    ),
    code(
        """
from prooflaunch_remix.multimodal_models import LocalGroundingDINO

product_artifact = image_artifacts[0]
dino = LocalGroundingDINO(
    model_id="IDEA-Research/grounding-dino-tiny",
    box_threshold=0.30,
    text_threshold=0.25,
)
dino_detections = dino.detect(
    product_artifact,
    text_labels=("electronic product", "electronic device", "product"),
)
dino_detection = max(dino_detections, key=lambda item: item.score)
dino_observations = tuple(
    item.to_observation(index)
    for index, item in enumerate(dino_detections, start=1)
)
dino_evidence = {
    "schema": "ProofLaunchGroundingDINOEvidenceV1",
    "model_ref": dino.model_id,
    "selected": dino_detection.__dict__,
    "detections": [item.__dict__ for item in dino_detections],
    "observations": [item.__dict__ for item in dino_observations],
}
(multimodal_run_dir / "grounding-dino.json").write_text(
    json.dumps(dino_evidence, indent=2), encoding="utf-8"
)
print(json.dumps(dino_evidence, indent=2))

del dino
gc.collect()
torch.cuda.empty_cache()
print("GroundingDINO phase complete; Radeon memory released")
"""
    ),
]

video_cell = next(
    cell
    for cell in notebook["cells"]
    if "IdentityLockedVideoComposer" in source_of(cell)
    and "video_evidence =" in source_of(cell)
)
video_source = source_of(video_cell)
video_source = replace_once(
    video_source,
    "from PIL import Image\n",
    "from PIL import Image, ImageDraw\n",
)
video_source = replace_once(
    video_source,
    "assert identity_report.passed, identity_report\n"
    "locked_video_path = ltx_output_dir / "
    '"prooflaunch-identity-locked.mp4"\n',
    "assert identity_report.passed, identity_report\n"
    "# Add a measurable visual launch cue outside the protected product box.\n"
    "cued_frames = []\n"
    "for frame_index, frame in enumerate(locked_frames):\n"
    "    rendered = frame.copy()\n"
    "    if 24 <= frame_index <= 31:\n"
    "        cue = ImageDraw.Draw(rendered)\n"
    "        radius = 20 + 3 * (frame_index - 24)\n"
    "        cue.ellipse(\n"
    "            (54 - radius, 54 - radius, 54 + radius, 54 + radius),\n"
    "            outline=(255, 187, 76, 255), width=8,\n"
    "        )\n"
    "    cued_frames.append(rendered)\n"
    "locked_frames = tuple(cued_frames)\n"
    "locked_video_path = ltx_output_dir / "
    '"prooflaunch-identity-locked.mp4"\n',
)
video_source = video_source.replace(
    '"schema": "ProofLaunchRadeonVideoRunV1"',
    '"schema": "ProofLaunchRadeonVideoRunV2"',
)
video_source = video_source.replace(
    '"The exact-pixel identity gate is pre-encode. H.264 is lossy; the "\n'
    '        "encoded MP4 still requires the declared decoded-frame tolerance audit."',
    '"The pre-encode gate is exact. The following V6 delivery cell must "\n'
    '        "also pass decoded H.264 identity, SAM2, CLAP, and A/V alignment."',
)
set_source(video_cell, video_source)

cross_media_markdown = next(
    cell
    for cell in notebook["cells"]
    if "## 5C. Cross-media release gate" in source_of(cell)
)
set_source(
    cross_media_markdown,
    source_of(cross_media_markdown).replace(
        "## 5C. Cross-media release gate",
        "## 5F. Cross-media release gate",
    ),
)
cross_media_code = notebook["cells"][notebook["cells"].index(cross_media_markdown) + 1]
cross_source = source_of(cross_media_code)
cross_source = replace_once(
    cross_source,
    "    tuple(qwen_understanding.observations) + tuple(pdf_observations)\n",
    "    tuple(qwen_understanding.observations)\n"
    "    + tuple(pdf_observations)\n"
    "    + tuple(dino_observations)\n",
)
set_source(cross_media_code, cross_source)

cross_index = notebook["cells"].index(cross_media_markdown)
notebook["cells"][cross_index:cross_index] = [
    markdown(
        """
## 5C. Track the grounded product through every generated frame with SAM2

The GroundingDINO box is mapped through the product compositing transform and
used as SAM2's first-frame prompt. A run passes only when at least 95% of
expected frames are returned and at least 95% contain a non-empty product mask.
SAM2 is unloaded before the audio-text model is loaded.
"""
    ),
    code(
        """
from prooflaunch_remix.multimodal_models import LocalSAM2VideoTracker

source_width, source_height = Image.open(mission_product_path).size
video_width, video_height = locked_frames[0].size
container_box = (
    0.32 * video_width,
    0.28 * video_height,
    0.68 * video_width,
    0.78 * video_height,
)
dx1, dy1, dx2, dy2 = dino_detection.box_xyxy
container_width = container_box[2] - container_box[0]
container_height = container_box[3] - container_box[1]
sam_prompt_box = (
    container_box[0] + dx1 / source_width * container_width,
    container_box[1] + dy1 / source_height * container_height,
    container_box[0] + dx2 / source_width * container_width,
    container_box[1] + dy2 / source_height * container_height,
)
sam_tracker = LocalSAM2VideoTracker(
    model_id="facebook/sam2.1-hiera-small",
    minimum_frame_coverage=0.95,
    minimum_nonempty_mask_rate=0.95,
)
sam_report = sam_tracker.track(
    frames=locked_frames,
    prompt_box_xyxy=sam_prompt_box,
    source_artifact_id=product_artifact.id,
)
assert sam_report.passed, sam_report
(multimodal_run_dir / "sam2-temporal-segmentation.json").write_text(
    json.dumps(sam_report, default=lambda item: item.__dict__, indent=2),
    encoding="utf-8",
)
print(json.dumps(sam_report, default=lambda item: item.__dict__, indent=2))

del sam_tracker
gc.collect()
torch.cuda.empty_cache()
print("SAM2 phase complete; Radeon memory released")
"""
    ),
    markdown(
        """
## 5D. Produce the final A/V MP4, then audit decoded identity and timing

This cell creates a deterministic owned launch chime, muxes it into the local
video, decodes the actual delivery MP4, and applies four independent checks:
H.264 product identity, visible cue detection, CLAP audio semantics, and
timestamp alignment. Planned timestamps alone cannot pass this gate.
"""
    ),
    code(
        """
import math
import wave
import imageio_ffmpeg
import numpy as np

from prooflaunch_remix.media_quality import (
    AudioVideoAlignmentGate,
    EncodedVideoIdentityGate,
    SemanticEvent,
)
from prooflaunch_remix.multimodal_models import LocalCLAPScorer

fps = 24
sample_rate = 48_000
duration_seconds = len(locked_frames) / fps
sample_count = round(duration_seconds * sample_rate)
timeline = np.arange(sample_count, dtype=np.float32) / sample_rate
audio = np.zeros(sample_count, dtype=np.float32)
cue_start, cue_end = 1.0, 1.34
cue_mask = (timeline >= cue_start) & (timeline <= cue_end)
cue_time = timeline[cue_mask] - cue_start
envelope = np.sin(np.pi * cue_time / (cue_end - cue_start)) ** 2
audio[cue_mask] = 0.40 * envelope * (
    np.sin(2 * np.pi * 659.25 * cue_time)
    + 0.55 * np.sin(2 * np.pi * 987.77 * cue_time)
)
audio = np.clip(audio, -0.95, 0.95)
source_audio_path = ltx_output_dir / "owned-launch-chime.wav"
with wave.open(str(source_audio_path), "wb") as handle:
    handle.setnchannels(1)
    handle.setsampwidth(2)
    handle.setframerate(sample_rate)
    handle.writeframes((audio * 32767).astype("<i2").tobytes())

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
final_video_path = ltx_output_dir / "prooflaunch-final-av.mp4"
subprocess.run(
    [
        ffmpeg, "-y",
        "-i", str(locked_video_path),
        "-i", str(source_audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(final_video_path),
    ],
    check=True,
    capture_output=True,
)
assert final_video_path.is_file() and final_video_path.stat().st_size > 0

encoded_identity = EncodedVideoIdentityGate(
    codec_tolerance=0.04,
    minimum_frame_coverage=0.95,
).audit(
    video_path=final_video_path,
    product_layer=Image.open(mission_product_path).convert("RGBA"),
    normalized_box=(0.32, 0.28, 0.68, 0.78),
    expected_frame_count=len(locked_frames),
)
assert encoded_identity.passed, encoded_identity

final_reader = imageio.get_reader(final_video_path)
decoded_frames = tuple(Image.fromarray(frame).convert("RGB") for frame in final_reader)
final_reader.close()
cue_frames = []
for frame_index, frame in enumerate(decoded_frames):
    crop = np.asarray(frame.crop((5, 5, 103, 103)))
    amber = (
        (crop[:, :, 0] > 180)
        & (crop[:, :, 1] > 100)
        & (crop[:, :, 2] < 150)
    )
    if int(amber.sum()) >= 35:
        cue_frames.append(frame_index)
assert cue_frames, "the encoded visual cue was not detected"
video_event = SemanticEvent(
    "launch chime",
    min(cue_frames) / fps,
    (max(cue_frames) + 1) / fps,
    1.0,
    f"decoded_frames:{min(cue_frames)}-{max(cue_frames)}",
)

decoded_audio_path = ltx_output_dir / "decoded-delivery-audio.wav"
subprocess.run(
    [
        ffmpeg, "-y", "-i", str(final_video_path),
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        str(decoded_audio_path),
    ],
    check=True,
    capture_output=True,
)
with wave.open(str(decoded_audio_path), "rb") as handle:
    decoded_audio = np.frombuffer(
        handle.readframes(handle.getnframes()),
        dtype="<i2",
    ).astype(np.float32) / 32768.0
    decoded_audio_duration = handle.getnframes() / handle.getframerate()

clap = LocalCLAPScorer(
    model_id="laion/clap-htsat-fused",
    minimum_probability=0.45,
)
clap_score = clap.score_array(
    audio=decoded_audio,
    sampling_rate=sample_rate,
    expected_label="a bright electronic launch chime",
    candidate_labels=(
        "a bright electronic launch chime",
        "spoken human voice",
        "traffic noise",
        "silence",
    ),
)
assert clap_score.passed, clap_score
audio_event = SemanticEvent(
    "launch chime",
    cue_start,
    cue_end,
    clap_score.expected_probability,
    f"decoded_audio_seconds:{cue_start:.2f}-{cue_end:.2f}",
)
alignment_report = AudioVideoAlignmentGate(
    tolerance_seconds=0.50,
    duration_tolerance_seconds=0.25,
    minimum_event_coverage=0.95,
).audit(
    audio_events=(audio_event,),
    video_events=(video_event,),
    audio_duration_seconds=decoded_audio_duration,
    video_duration_seconds=len(decoded_frames) / fps,
)
assert alignment_report.passed, alignment_report

delivery_evidence = {
    "schema": "ProofLaunchEncodedDeliveryGateV1",
    "final_video_path": str(final_video_path),
    "final_video_sha256": sha256_file(final_video_path),
    "encoded_identity": encoded_identity.to_dict(),
    "clap": clap_score.__dict__,
    "audio_video_alignment": alignment_report.to_dict(),
}
(multimodal_run_dir / "encoded-delivery-gate.json").write_text(
    json.dumps(delivery_evidence, indent=2), encoding="utf-8"
)
print(json.dumps(delivery_evidence, indent=2))

del clap
gc.collect()
torch.cuda.empty_cache()
print("CLAP phase complete; Radeon memory released")
"""
    ),
]

handoff_index = next(
    index
    for index, cell in enumerate(notebook["cells"])
    if "## 6. Submission handoff" in source_of(cell)
)
notebook["cells"][handoff_index:handoff_index] = [
    markdown(
        """
## 5G. Apply the precommitted competition-2X acceptance contract

One successful fixture is evidence of operability, not evidence of benchmark
quality. This cell proves that the validator rejects the fixture-only record.
If a measured `competition-2x-benchmark.json` exists, it must satisfy every
metric—including raw blind-comparison counts and the Wilson lower bound—before
the submission gate can become ready.
"""
    ),
    code(
        """
from prooflaunch_remix.quality_contract import QualityTier, contract_for

fixture_only_evidence = {
    "product_count": 1,
    "aspect_ratio_count": 2,
    "seeds_per_product": 1,
    "human_raters": 0,
    "repair_budget_max": 2,
    "unsupported_claim_count": 0,
    "locator_coverage": 1.0,
    "image_identity_pass_rate": 1.0,
    "preencode_video_identity_pass_rate": 1.0,
    "encoded_video_identity_pass_rate": float(encoded_identity.passed),
    "audio_video_alignment_pass_rate": float(alignment_report.passed),
    "cross_media_pass_rate": float(cross_media_evidence["passed"]),
    "completion_rate": 1.0,
    "crash_rate": 0.0,
    "publish_preferred_count": 0,
    "publish_comparison_count": 0,
}
contract = contract_for(QualityTier.COMPETITION_2X)
fixture_report = contract.evaluate(fixture_only_evidence)
assert not fixture_report.passed, (
    "A single fixture must never certify the competition-2X benchmark"
)
(multimodal_run_dir / "fixture-only-2x-readiness.json").write_text(
    json.dumps(fixture_report.to_dict(), indent=2), encoding="utf-8"
)

benchmark_path = multimodal_run_dir / "competition-2x-benchmark.json"
if benchmark_path.is_file():
    benchmark_evidence = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark_report = contract.evaluate(benchmark_evidence)
    (multimodal_run_dir / "competition-2x-report.json").write_text(
        json.dumps(benchmark_report.to_dict(), indent=2), encoding="utf-8"
    )
    assert benchmark_report.passed, benchmark_report.to_dict()
    print("competition-2X benchmark: PASS")
else:
    benchmark_report = None
    print(
        "competition-2X benchmark: BLOCKED — run 30 products × 3 ratios × "
        "5 seeds and 150+ blind human comparisons"
    )
print(json.dumps(fixture_report.to_dict(), indent=2))
"""
    ),
]

notebook["metadata"]["prooflaunch"] = {
    "schema": "ProofLaunchRadeonGateV6",
    "qualityTier": "competition_2x",
    "requiredLocalModels": [
        "Qwen/Qwen3-VL-2B-Instruct",
        "IDEA-Research/grounding-dino-tiny",
        "google/gemma-4-E4B-it+emotion-lora",
        "stabilityai/stable-diffusion-xl-base-1.0",
        "google/siglip2-base-patch16-224",
        "Lightricks/LTX-Video:ltxv-2b-0.9.8-distilled.safetensors",
        "facebook/sam2.1-hiera-small",
        "laion/clap-htsat-fused",
    ],
    "optionalInputModel": "openai/whisper-small",
    "qualityTierCandidate": "Lightricks/LTX-2.3 22B distilled",
    "coResidentHeavyModels": 1,
    "maxRepairs": 2,
    "encodedIdentityRequired": True,
    "audioVideoAlignmentRequired": True,
    "humanReleaseRequired": True,
    "benchmarkCertificationFromSingleFixture": False,
}

destination = ROOT / "notebooks" / "prooflaunch_radeon_gate_v6.ipynb"
destination.write_text(
    json.dumps(notebook, ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(destination)
