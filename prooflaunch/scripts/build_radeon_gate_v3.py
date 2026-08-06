from __future__ import annotations

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--version", default="v3")
args = parser.parse_args()
version = args.version.lower()
if version not in {"v3", "v4"}:
    raise SystemExit("version must be v3 or v4")

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


cells = [
    markdown(
        """
# ProofLaunch Radeon Gate V3

**Track 1 — Development of Multimodal Content Creation Tools**

Run only when the kernel shows **Connected**. This gate fails closed. It does
not publish, submit a PR, overwrite the Gemma training Notebook, or reinterpret
the procedural fallback as model output.
"""
    ),
    code(
        """
from pathlib import Path
import hashlib, json, os, platform, subprocess, sys, time

print("python:", sys.version)
print("platform:", platform.platform())
print("cwd:", Path.cwd())
"""
    ),
    markdown("## 1. Reassemble, hash-verify, and extract the versioned source"),
    code(
        """
archive = Path("prooflaunch-radeon-v3.tar.gz")
parts = sorted(Path(".").glob("prooflaunch-radeon-v3.part-*"))
if not archive.exists() and parts:
    with archive.open("wb") as destination:
        for part in parts:
            destination.write(part.read_bytes())
    print(f"reassembled {len(parts)} parts -> {archive}")

checksum_file = Path("prooflaunch-radeon-v3.sha256")
assert archive.is_file(), f"Missing archive and parts: {archive}"
assert checksum_file.is_file(), f"Missing checksum: {checksum_file}"
expected = checksum_file.read_text().split()[0].strip()
actual = hashlib.sha256(archive.read_bytes()).hexdigest()
print("archive sha256:", actual)
assert actual == expected, f"Archive hash mismatch: expected {expected}, got {actual}"
subprocess.run(["tar", "-xzf", str(archive)], check=True)
repo = Path("prooflaunch_submission")
assert (repo / "pyproject.toml").is_file(), "Extracted repository is incomplete"
"""
    ),
    markdown("## 2. Install declared dependencies and run Level-1 gates"),
    code(
        """
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-e", f"{repo}[radeon]"],
    check=True,
)
env = {**os.environ, "PYTHONPATH": str(repo / "src")}
tests = subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-s", str(repo / "tests"), "-v"],
    env=env, text=True, capture_output=True
)
print(tests.stdout)
print(tests.stderr)
assert tests.returncode == 0, "Unit/integration tests failed"

control_eval = subprocess.run(
    [
        sys.executable,
        str(repo / "scripts" / "run_control_plane_eval.py"),
        "--cases-per-mode", "50",
        "--output", str(repo / "evidence" / "radeon" / "control-plane-eval.json"),
    ],
    env=env, text=True, capture_output=True
)
print(control_eval.stdout)
print(control_eval.stderr)
assert control_eval.returncode == 0, "250-case control-plane gate failed"
"""
    ),
    markdown("## 3. Prove the local AMD Radeon runtime"),
    code(
        """
import torch

runtime = {
    "torch_version": torch.__version__,
    "hip_version": getattr(torch.version, "hip", None),
    "gpu_available": torch.cuda.is_available(),
    "gpu_count": torch.cuda.device_count(),
    "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "total_vram_bytes": (
        torch.cuda.get_device_properties(0).total_memory
        if torch.cuda.is_available() else 0
    ),
}
print(json.dumps(runtime, indent=2))
assert runtime["gpu_available"], "AMD Radeon GPU is not available"
assert runtime["hip_version"], "PyTorch does not report a ROCm/HIP runtime"

from prooflaunch_remix.model_registry import RadeonModelRouter

available_vram_gb = runtime["total_vram_bytes"] / (1024 ** 3)
execution_plan = RadeonModelRouter().report(
    available_vram_gb=available_vram_gb,
    roles=("affect_critic", "image_generation", "image_text_scoring"),
)
print(json.dumps(execution_plan, indent=2))
"""
    ),
    markdown(
        """
## 4. Reload, evaluate, record, and unload the multimodal-safe Gemma adapter

The gate requires the multimodal-retention artifact produced by
`gemma4_emotion_lora_multimodal_safe_v2.ipynb`. It reloads the local adapter,
runs the frozen emotion set, records the campaign pulse, then unloads Gemma
before SDXL enters Radeon memory.
"""
    ),
    code(
        """
import gc, re
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from prooflaunch_remix.audience_pulse import GemmaAudiencePulse, RecordedAudiencePulse
from prooflaunch_remix.contracts import CreativeBrief

base_model_dir = Path("./models/google/gemma-4-E4B-it")
adapter_dir = Path("./gemma4-it-emotion-lora-ms-single-gpu")
retention_path = adapter_dir / "multimodal_retention.json"
assert base_model_dir.is_dir(), f"Missing local Gemma model: {base_model_dir}"
assert adapter_dir.is_dir(), f"Missing safe LoRA adapter: {adapter_dir}"
assert retention_path.is_file(), (
    "Missing multimodal retention evidence; run the safe V2 training Notebook"
)
retention = json.loads(retention_path.read_text(encoding="utf-8"))
assert retention["post_accuracy"] >= retention["minimum_post_accuracy"]
assert (
    retention["pre_accuracy"] - retention["post_accuracy"]
    <= retention["maximum_allowed_drop"]
)

gemma_tokenizer = AutoTokenizer.from_pretrained(
    base_model_dir,
    use_fast=True,
    trust_remote_code=True,
)
gemma_base = AutoModelForCausalLM.from_pretrained(
    base_model_dir,
    torch_dtype=torch.bfloat16,
    low_cpu_mem_usage=True,
    trust_remote_code=True,
).to("cuda")
gemma_ft = PeftModel.from_pretrained(gemma_base, adapter_dir).to("cuda")
gemma_ft.eval()
valid_emotions = {"sadness", "joy", "love", "anger", "fear", "surprise"}

def predict_emotion_ft(user_text: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Read the user's text and answer with exactly one label. "
                "Only choose from: sadness, joy, love, anger, fear, surprise."
            ),
        },
        {
            "role": "user",
            "content": f"Classify the emotion of this text:\\n\\n{user_text}",
        },
    ]
    inputs = gemma_tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = {key: value.to("cuda") for key, value in inputs.items()}
    input_len = inputs["input_ids"].shape[-1]
    with torch.inference_mode():
        output = gemma_ft.generate(
            **inputs,
            max_new_tokens=4,
            do_sample=False,
            pad_token_id=gemma_tokenizer.pad_token_id,
            eos_token_id=gemma_tokenizer.eos_token_id,
        )
    raw = gemma_tokenizer.decode(
        output[0][input_len:],
        skip_special_tokens=True,
    ).strip().lower()
    match = re.search(r"\\b(sadness|joy|love|anger|fear|surprise)\\b", raw)
    return match.group(1) if match else "invalid"

audience_pulse = GemmaAudiencePulse(
    classifier=predict_emotion_ft,
    model_ref="google/gemma-4-E4B-it+emotion-lora:multimodal-safe-v2",
)
emotion_cases = [
    ("I feel joyful and bright today.", "joy"),
    ("This wonderful launch makes me happy.", "joy"),
    ("I love spending time with you.", "love"),
    ("My heart is full of affection.", "love"),
    ("I am frightened by the sudden noise.", "fear"),
    ("That shadow makes me afraid.", "fear"),
    ("I am furious about the mistake.", "anger"),
    ("The unfair result makes me angry.", "anger"),
    ("I feel deeply sad about the loss.", "sadness"),
    ("The goodbye left me sorrowful.", "sadness"),
    ("What an unexpected surprise!", "surprise"),
    ("I cannot believe that happened.", "surprise"),
]
emotion_predictions = [
    {"text": text, "expected": expected, "predicted": predict_emotion_ft(text).strip().lower()}
    for text, expected in emotion_cases
]
emotion_accuracy = sum(
    row["expected"] == row["predicted"] for row in emotion_predictions
) / len(emotion_predictions)
emotion_evidence = {
    "model_ref": audience_pulse.model_ref,
    "case_count": len(emotion_predictions),
    "accuracy": emotion_accuracy,
    "required_accuracy": 0.80,
    "predictions": emotion_predictions,
    "limitation": "Six synthetic labels do not measure campaign persuasion.",
}
radeon_evidence = repo / "evidence" / "radeon"
radeon_evidence.mkdir(parents=True, exist_ok=True)
(radeon_evidence / "post-finetune-evaluation.json").write_text(
    json.dumps(emotion_evidence, indent=2), encoding="utf-8"
)
print(json.dumps(emotion_evidence, indent=2))
assert emotion_accuracy >= 0.80, "Post-fine-tuning accuracy is below the precommitted bar"

preflight_brief = CreativeBrief(
    id="BRF-001",
    headline="Aster Arc — Battery life up to 18 hours under the documented test.",
    claim_ids=("CLM-001",),
    visual_direction="evidence-led launch",
    target_emotion="joy",
)
recorded_audience = RecordedAudiencePulse(audience_pulse.review(preflight_brief))

del audience_pulse, predict_emotion_ft, gemma_ft, gemma_base, gemma_tokenizer
gc.collect()
torch.cuda.empty_cache()
print("Gemma phase complete; Radeon memory released before image generation")
"""
    ),
    markdown(
        """
## 5. Run the key local visual inference on Radeon

The default is SDXL Base through Diffusers. Override `PROOFLAUNCH_IMAGE_MODEL`
only with a locally runnable model whose identifier and license are recorded.
The model creates the background; ProofLaunch composites the immutable product
layer, audits four mechanical gates plus the SigLIP2 semantic gate, repairs at
most twice, then exports.
"""
    ),
    code(
        """
from diffusers import AutoPipelineForText2Image
from PIL import Image, ImageDraw

from prooflaunch_remix.contracts import CampaignRequest, Stage
from prooflaunch_remix.files import sha256_file
from prooflaunch_remix.ledger import EvidenceLedger
from prooflaunch_remix.runtime import build_supervisor
from prooflaunch_remix.studio import DiffusersBackgroundProvider
from prooflaunch_remix.visual_semantics import HuggingFaceSigLIP2Scorer

model_id = os.environ.get(
    "PROOFLAUNCH_IMAGE_MODEL",
    "stabilityai/stable-diffusion-xl-base-1.0",
)
steps = int(os.environ.get("PROOFLAUNCH_IMAGE_STEPS", "20"))
pipe = AutoPipelineForText2Image.from_pretrained(
    model_id,
    torch_dtype=torch.float16,
    use_safetensors=True,
).to("cuda")
background = DiffusersBackgroundProvider(
    pipe,
    model_ref=model_id,
    steps=steps,
    guidance_scale=4.0,
    release_after_render=True,
)
semantic_scorer = HuggingFaceSigLIP2Scorer(
    model_id="google/siglip2-base-patch16-224",
    minimum_positive_probability=0.34,
    minimum_margin=0.05,
)

run_label = os.environ.get("PROOFLAUNCH_RUN_LABEL", "frozen-visual-001")
run_dir = radeon_evidence / run_label
run_dir.mkdir(parents=True, exist_ok=True)
product_path = run_dir / "fixture-product.png"
product = Image.new("RGBA", (720, 900), (0, 0, 0, 0))
draw = ImageDraw.Draw(product)
draw.rounded_rectangle(
    (95, 55, 625, 835), radius=90,
    fill=(245, 248, 255, 255), outline=(174, 201, 239, 255), width=12,
)
draw.rounded_rectangle((185, 180, 535, 565), radius=36, fill=(16, 74, 154, 255))
draw.ellipse((275, 655, 445, 825), fill=(255, 187, 76, 255))
product.save(product_path, format="PNG", optimize=False)

request = CampaignRequest(
    product_name="Aster Arc",
    product_image=str(product_path),
    specification_text="Battery life up to 18 hours under the documented test.",
    market="Japan",
    platform="TikTok",
    goal="launch",
    target_emotion="joy",
)
supervisor = build_supervisor(
    background=background,
    audience=recorded_audience,
    seed=202607,
    canvas_overrides={"TikTok": (768, 1344)},
    unsafe_first_pass=True,
    semantic_scorer=semantic_scorer,
)
torch.cuda.empty_cache()
torch.cuda.reset_peak_memory_stats()
started = time.perf_counter()
state = supervisor.run(request, str(run_dir), run_id="radeon-frozen-visual-001")
torch.cuda.synchronize()
latency_seconds = time.perf_counter() - started
peak_vram_bytes = torch.cuda.max_memory_allocated()
semantic_scorer.release()

assert state.stage is Stage.DELIVER, state.blocked_reason
assert not state.release_blockers, state.release_blockers
assert state.repair_count <= 2
assert state.assets[0].metadata["semantic_score"]["passed"]
assert EvidenceLedger.verify(run_dir / "evidence-ledger.jsonl")
visual_evidence = {
    "schema": "ProofLaunchRadeonVisualRunV1",
    "runtime": runtime,
    "execution_plan": execution_plan,
    "model_id": model_id,
    "steps": steps,
    "seed": 202607,
    "canvas": [768, 1344],
    "stage": state.stage.value,
    "repair_count": state.repair_count,
    "latency_seconds": latency_seconds,
    "peak_vram_bytes": peak_vram_bytes,
    "asset_path": state.assets[0].path,
    "asset_sha256": sha256_file(state.assets[0].path),
    "product_source_sha256": sha256_file(product_path),
    "protected_layer_sha256": state.assets[0].metadata["product_layer_sha256"],
    "semantic_score": state.assets[0].metadata.get("semantic_score"),
    "backend_kind": state.assets[0].metadata["backend_kind"],
    "exports": [
        {"path": path, "sha256": sha256_file(path)} for path in state.exports
    ],
}
(radeon_evidence / "generation-benchmark.json").write_text(
    json.dumps(visual_evidence, indent=2), encoding="utf-8"
)
print(json.dumps(visual_evidence, indent=2))
"""
    ),
    markdown(
        """
## 6. Submission handoff

Do not change `SUBMISSION_GATE.json` to ready from this one fixture. Complete the
30-product / three-ratio / five-seed benchmark, blinded human comparison,
3–5 minute real-operation video, and final English PR checklist first.
"""
    ),
]

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3 (ipykernel)",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

payload = json.dumps(notebook, ensure_ascii=False, indent=1)
if version == "v4":
    payload = payload.replace("V3", "V4").replace("v3", "v4")
destination = Path(f"notebooks/prooflaunch_radeon_gate_{version}.ipynb")
destination.write_text(
    payload,
    encoding="utf-8",
)
print(destination)
