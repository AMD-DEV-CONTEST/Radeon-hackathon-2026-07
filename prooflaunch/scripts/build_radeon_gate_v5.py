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


source = ROOT / "notebooks" / "prooflaunch_radeon_gate_v4.ipynb"
notebook = json.loads(source.read_text(encoding="utf-8"))
for cell in notebook["cells"]:
    joined = "".join(cell.get("source", []))
    joined = joined.replace("V4", "V5").replace("v4", "v5")
    joined = joined.replace(
        'roles=("affect_critic", "image_generation", "image_text_scoring"),',
        'roles=(\n'
        '        "vision_language_audit",\n'
        '        "affect_critic",\n'
        '        "image_generation",\n'
        '        "image_text_scoring",\n'
        '        "video_generation",\n'
        '    ),',
    )
    cell["source"] = [line + "\n" for line in joined.rstrip().splitlines()]

runtime_index = next(
    index
    for index, cell in enumerate(notebook["cells"])
    if "## 4. Reload" in "".join(cell.get("source", []))
)
notebook["cells"][runtime_index:runtime_index] = [
    markdown(
        """
## 3A. Build the inspectable multimodal mission before loading any model

This V5 path accepts independently hashed image, PDF, audio, and video inputs.
The frozen demonstration uses an owned product image plus an exact-page PDF
brief, then requests both a social image and a short image-conditioned video.
No free-running swarm may change the graph after its hash is recorded.
"""
    ),
    code(
        """
import gc
from PIL import Image, ImageDraw
import fitz

from prooflaunch_remix.mission import (
    DeliverableKind,
    DeliverableSpec,
    MultimodalMissionPlanner,
)
from prooflaunch_remix.multimodal_ingest import (
    MediaSource,
    MultimodalIngestor,
    RightsStatus,
)

multimodal_run_dir = repo / "evidence" / "radeon" / "multimodal-v5"
multimodal_run_dir.mkdir(parents=True, exist_ok=True)
mission_product_path = multimodal_run_dir / "owned-product.png"
mission_product = Image.new("RGBA", (720, 900), (0, 0, 0, 0))
mission_draw = ImageDraw.Draw(mission_product)
mission_draw.rounded_rectangle(
    (95, 55, 625, 835), radius=90,
    fill=(245, 248, 255, 255), outline=(174, 201, 239, 255), width=12,
)
mission_draw.rounded_rectangle(
    (185, 180, 535, 565), radius=36, fill=(16, 74, 154, 255)
)
mission_draw.ellipse((275, 655, 445, 825), fill=(255, 187, 76, 255))
mission_product.save(mission_product_path, format="PNG", optimize=False)

brief_pdf_path = multimodal_run_dir / "owned-brief.pdf"
brief_document = fitz.open()
brief_page = brief_document.new_page()
brief_page.insert_text(
    (72, 96),
    "Aster Arc evidence brief\\nBattery life up to 18 hours under the documented test.\\n"
    "Market: Japan. Platform: TikTok. Target emotion: joy.",
)
brief_document.save(brief_pdf_path)
brief_document.close()

mission_artifacts = MultimodalIngestor().ingest(
    (
        MediaSource(
            str(mission_product_path),
            "product_identity",
            RightsStatus.OWNED,
        ),
        MediaSource(
            str(brief_pdf_path),
            "evidence_brief",
            RightsStatus.OWNED,
        ),
    )
)
mission_plan = MultimodalMissionPlanner().build(
    mission_id="radeon-multimodal-v5",
    artifacts=mission_artifacts,
    deliverables=(
        DeliverableSpec(DeliverableKind.SOCIAL_IMAGE, "9:16"),
        DeliverableSpec(DeliverableKind.SHORT_VIDEO, "3:2", 4),
    ),
    available_vram_gb=available_vram_gb,
)
mission_bundle = {
    "artifacts": [item.serializable() for item in mission_artifacts],
    "plan": mission_plan.serializable(),
    "graph_hash": mission_plan.graph_hash,
}
(multimodal_run_dir / "mission-plan.json").write_text(
    json.dumps(mission_bundle, indent=2), encoding="utf-8"
)
print(json.dumps(mission_bundle, indent=2))
"""
    ),
    markdown(
        """
## 3B. Understand image evidence with local Qwen3-VL; extract PDF text exactly

Qwen3-VL must return source IDs and spatial/frame locators. The PDF extractor
keeps exact page text rather than asking a model to paraphrase evidence. Both
adapters fail closed on missing locators or invented source IDs.
"""
    ),
    code(
        """
from prooflaunch_remix.multimodal_models import (
    LocalPDFTextExtractor,
    LocalQwen3VLAnalyzer,
)
from prooflaunch_remix.multimodal_ingest import MediaKind

image_artifacts = tuple(
    item for item in mission_artifacts if item.kind is MediaKind.IMAGE
)
pdf_artifact = next(
    item for item in mission_artifacts if item.kind is MediaKind.PDF
)
qwen_analyzer = LocalQwen3VLAnalyzer(
    model_id="Qwen/Qwen3-VL-2B-Instruct",
    max_new_tokens=512,
)
qwen_understanding = qwen_analyzer.analyze(
    image_artifacts,
    mission_prompt=(
        "Describe only visible product identity, colors, shape, logo/text, "
        "and composition constraints for an evidence-grounded launch."
    ),
)
pdf_observations = LocalPDFTextExtractor().extract(pdf_artifact)
understanding_evidence = {
    "qwen": {
        "summary": qwen_understanding.summary,
        "observations": [item.__dict__ for item in qwen_understanding.observations],
        "model_ref": qwen_understanding.model_ref,
    },
    "pdf": [item.__dict__ for item in pdf_observations],
}
(multimodal_run_dir / "understanding.json").write_text(
    json.dumps(understanding_evidence, indent=2), encoding="utf-8"
)
print(json.dumps(understanding_evidence, indent=2))

del qwen_analyzer
gc.collect()
torch.cuda.empty_cache()
print("Qwen3-VL phase complete; Radeon memory released")
"""
    ),
]

handoff_index = next(
    index
    for index, cell in enumerate(notebook["cells"])
    if "## 6. Submission handoff" in "".join(cell.get("source", []))
)
notebook["cells"][handoff_index:handoff_index] = [
    markdown(
        """
## 5B. Generate a short local video with official LTX-Video 2B on Radeon

The 2B distilled checkpoint is the 24 GB-safe required tier. A separately
declared LTX-2.3 22B quality tier may be benchmarked only when the instance has
at least 46 GB and its ROCm patch is recorded. This cell uses the official
Lightricks inference library and records the exact Git revision and checkpoint.
It then overlays the owned product layer after generation on every frame.
"""
    ),
    code(
        """
import imageio.v2 as imageio
from PIL import Image

ltx_root = repo / ".vendor" / "LTX-Video"
if not (ltx_root / ".git").is_dir():
    ltx_root.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git", "clone", "--depth", "1",
            "https://github.com/Lightricks/LTX-Video.git",
            str(ltx_root),
        ],
        check=True,
    )
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-e", f"{ltx_root}[inference]"],
    check=True,
)
ltx_revision = subprocess.check_output(
    ["git", "-C", str(ltx_root), "rev-parse", "HEAD"],
    text=True,
).strip()
sys.path.insert(0, str(ltx_root))
from ltx_video.inference import InferenceConfig, infer
from prooflaunch_remix.video_generation import IdentityLockedVideoComposer

ltx_output_dir = multimodal_run_dir / "ltx-video"
ltx_output_dir.mkdir(parents=True, exist_ok=True)
before_videos = set(ltx_output_dir.glob("*.mp4"))
torch.cuda.empty_cache()
torch.cuda.reset_peak_memory_stats()
video_started = time.perf_counter()
infer(
    InferenceConfig(
        pipeline_config=str(
            ltx_root / "configs" / "ltxv-2b-0.9.8-distilled.yaml"
        ),
        prompt=(
            "A precise studio product shot. The camera makes a slow dolly-in. "
            "Soft blue and amber light moves across a clean dark background. "
            "The supplied product remains centered, rigid, and unchanged. "
            "No text, no extra objects, no logo mutation."
        ),
        output_path=str(ltx_output_dir),
        seed=202607,
        height=512,
        width=768,
        num_frames=97,
        frame_rate=24,
        offload_to_cpu=available_vram_gb < 30,
        conditioning_media_paths=[str(mission_product_path)],
        conditioning_strengths=[1.0],
        conditioning_start_frames=[0],
    )
)
torch.cuda.synchronize()
video_latency_seconds = time.perf_counter() - video_started
video_peak_vram_bytes = torch.cuda.max_memory_allocated()
new_videos = set(ltx_output_dir.glob("*.mp4")) - before_videos
assert new_videos, "LTX-Video did not create a new MP4"
raw_video_path = max(new_videos, key=lambda item: item.stat().st_mtime_ns)

reader = imageio.get_reader(raw_video_path)
raw_frames = tuple(Image.fromarray(frame).convert("RGBA") for frame in reader)
reader.close()
locked_frames, identity_report = IdentityLockedVideoComposer().compose(
    generated_frames=raw_frames,
    product_layer=Image.open(mission_product_path).convert("RGBA"),
    normalized_box=(0.32, 0.28, 0.68, 0.78),
)
assert identity_report.passed, identity_report
locked_video_path = ltx_output_dir / "prooflaunch-identity-locked.mp4"
with imageio.get_writer(
    locked_video_path,
    fps=24,
    codec="libx264",
    quality=10,
) as writer:
    for frame in locked_frames:
        writer.append_data(frame.convert("RGB"))
assert locked_video_path.is_file() and locked_video_path.stat().st_size > 0

video_evidence = {
    "schema": "ProofLaunchRadeonVideoRunV1",
    "runtime": runtime,
    "model": "Lightricks/LTX-Video:ltxv-2b-0.9.8-distilled.safetensors",
    "model_license": "LTX-Video Open Weights License 1.0",
    "official_code_revision": ltx_revision,
    "seed": 202607,
    "frame_count": identity_report.frame_count,
    "fps": 24,
    "latency_seconds": video_latency_seconds,
    "peak_vram_bytes": video_peak_vram_bytes,
    "raw_video_path": str(raw_video_path),
    "raw_video_sha256": sha256_file(raw_video_path),
    "locked_video_path": str(locked_video_path),
    "locked_video_sha256": sha256_file(locked_video_path),
    "pre_encode_identity_report": identity_report.__dict__,
    "truth_boundary": (
        "The exact-pixel identity gate is pre-encode. H.264 is lossy; the "
        "encoded MP4 still requires the declared decoded-frame tolerance audit."
    ),
}
(multimodal_run_dir / "video-benchmark.json").write_text(
    json.dumps(video_evidence, indent=2), encoding="utf-8"
)
print(json.dumps(video_evidence, indent=2))

gc.collect()
torch.cuda.empty_cache()
"""
    ),
    markdown(
        """
## 5C. Cross-media release gate

Every deliverable claim must point to a Qwen bounding box/frame locator or an
exact PDF page. Unknown rights, missing source IDs, or absent locators block the
pack. Video and image outputs stay in review until a human approves release.
"""
    ),
    code(
        """
from prooflaunch_remix.cross_media import (
    CrossMediaReleaseGate,
    DeliverableClaim,
)

all_observations = (
    tuple(qwen_understanding.observations) + tuple(pdf_observations)
)
claim_observation = next(
    item for item in pdf_observations if "18 hours" in item.claim
)
cross_media_findings = CrossMediaReleaseGate().audit(
    artifacts=mission_artifacts,
    observations=all_observations,
    claims=(
        DeliverableClaim(
            deliverable_id="social-image",
            text="Battery life up to 18 hours under the documented test.",
            observation_ids=(claim_observation.id,),
        ),
        DeliverableClaim(
            deliverable_id="short-video",
            text="Battery life up to 18 hours under the documented test.",
            observation_ids=(claim_observation.id,),
        ),
    ),
)
assert not cross_media_findings, cross_media_findings
cross_media_evidence = {
    "schema": "ProofLaunchCrossMediaGateV1",
    "finding_count": len(cross_media_findings),
    "passed": not cross_media_findings,
    "human_release_required": True,
    "mission_graph_hash": mission_plan.graph_hash,
}
(multimodal_run_dir / "cross-media-gate.json").write_text(
    json.dumps(cross_media_evidence, indent=2), encoding="utf-8"
)
print(json.dumps(cross_media_evidence, indent=2))
"""
    ),
]

notebook["metadata"]["prooflaunch"] = {
    "schema": "ProofLaunchRadeonGateV5",
    "requiredLocalModels": [
        "Qwen/Qwen3-VL-2B-Instruct",
        "google/gemma-4-E4B-it+emotion-lora",
        "stabilityai/stable-diffusion-xl-base-1.0",
        "google/siglip2-base-patch16-224",
        "Lightricks/LTX-Video:ltxv-2b-0.9.8-distilled.safetensors",
    ],
    "optionalInputModel": "openai/whisper-small",
    "qualityTierCandidate": "Lightricks/LTX-2.3 22B distilled",
    "coResidentHeavyModels": 1,
    "maxRepairs": 2,
    "humanReleaseRequired": True,
}

destination = ROOT / "notebooks" / "prooflaunch_radeon_gate_v5.ipynb"
destination.write_text(
    json.dumps(notebook, ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(destination)
