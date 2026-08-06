#!/usr/bin/env python3
"""Build the audited V3 Notebook without mutating the original or V2."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "notebooks" / "gemma4_emotion_lora_multimodal_safe_v2.ipynb"
OUTPUT = ROOT / "notebooks" / "gemma4_emotion_lora_multimodal_safe_v3.ipynb"


def source_of(cell: dict) -> str:
    source = cell.get("source", [])
    return "".join(source) if isinstance(source, list) else str(source)


def set_source(cell: dict, text: str) -> None:
    cell["source"] = [line + "\n" for line in text.rstrip().splitlines()]


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


notebook = json.loads(SOURCE.read_text(encoding="utf-8"))
cells = notebook["cells"]

set_source(
    cells[0],
    """
# Gemma 4 E4B-it emotion LoRA — audited multimodal-safe Radeon V3

This version fixes strict-label scoring, loads the official multimodal model
class, uses a positive text-projection LoRA allowlist, fingerprints every
frozen vision/audio module before and after training, separates development
validation from the one-time final test, and documents the external
Accelerate/RCCL multi-GPU path. The original and V2 Notebooks remain unchanged.
""",
)

for cell in cells:
    if cell.get("cell_type") != "code":
        continue
    source = source_of(cell)
    # JSON's \b escape had become literal backspace bytes in the executable
    # Notebook source. Make the Python regex contain real word-boundary escapes.
    source = source.replace("\x08", "\\b")
    source = source.replace(
        "AutoModelForCausalLM",
        "AutoModelForMultimodalLM",
    )
    source = source.replace(
        "torch_dtype=MODEL_DTYPE",
        "dtype=MODEL_DTYPE",
    )
    source = source.replace(
        "trust_remote_code=True",
        "trust_remote_code=False",
    )
    set_source(cell, source)

config_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and 'MODELSCOPE_DATASET_ID = "AI-ModelScope/emotion"' in source_of(cell)
)
config_source = source_of(config_cell)
config_source = config_source.replace(
    'MODELSCOPE_DATASET_ID = "AI-ModelScope/emotion"\n',
    '''MODELSCOPE_DATASET_ID = "AI-ModelScope/emotion"

RUN_PROFILE = os.environ.get("PROOFLAUNCH_GEMMA_PROFILE", "smoke").lower()
MODEL_REVISION = os.environ.get(
    "PROOFLAUNCH_GEMMA_MODEL_REVISION",
    "1fe35ce743b357484b97a11646125adffee0b410",
)
DATASET_REVISION = os.environ.get(
    "PROOFLAUNCH_GEMMA_DATASET_REVISION",
    "21e1bff1b4ff17af78543d79d69f074a26b08266",
)
if RUN_PROFILE not in {"smoke", "candidate", "final"}:
    raise ValueError("RUN_PROFILE must be smoke, candidate, or final")
if RUN_PROFILE == "final" and not (
    re.fullmatch(r"[0-9a-f]{40}", MODEL_REVISION)
    and re.fullmatch(r"[0-9a-f]{40}", DATASET_REVISION)
):
    raise RuntimeError(
        "Final profile requires immutable model and dataset revisions"
    )
''',
)
config_source = config_source.replace(
    'OUTPUT_DIR = "./gemma4-it-emotion-lora-ms-single-gpu"',
    'OUTPUT_DIR = f"./gemma4-it-emotion-lora-ms-{RUN_PROFILE}-single-gpu"',
)
config_source = config_source.replace(
    """TRAIN_LIMIT = 4000
VALIDATION_LIMIT = 400
TEST_LIMIT = 400
EVAL_LIMIT = 400""",
    """PROFILE_LIMITS = {
    "smoke": (1000, 200, 400, 200),
    "candidate": (4000, 400, 400, 400),
    "final": (None, None, None, None),
}
(
    TRAIN_LIMIT,
    VALIDATION_LIMIT,
    TEST_LIMIT,
    EVAL_LIMIT,
) = PROFILE_LIMITS[RUN_PROFILE]""",
)
set_source(config_cell, config_source)

model_download_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "model_dir = snapshot_download" in source_of(cell)
)
model_download_source = source_of(model_download_cell).replace(
    "MODELSCOPE_MODEL_ID,\n    cache_dir",
    "MODELSCOPE_MODEL_ID,\n    revision=MODEL_REVISION,\n    cache_dir",
)
set_source(model_download_cell, model_download_source)

dataset_download_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "dataset_dir = dataset_snapshot_download" in source_of(cell)
)
dataset_download_source = source_of(dataset_download_cell).replace(
    "MODELSCOPE_DATASET_ID,\n    cache_dir",
    "MODELSCOPE_DATASET_ID,\n    revision=DATASET_REVISION,\n    cache_dir",
)
set_source(dataset_download_cell, dataset_download_source)

install_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "!uv pip install" in source_of(cell)
)
install = source_of(install_cell)
install = install.replace("vllm ", "")
install = install.replace(
    '"transformers>=5.5.0" accelerate datasets trl peft',
    '"transformers==5.14.0" "accelerate>=1.12,<2" datasets '
    '"trl==0.24.0" "peft>=0.19,<0.20"',
)
install = install.replace(" --extra-index-url https://wheels.vllm.ai/rocm/", "")
set_source(install_cell, install)

extract_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "def extract_label" in source_of(cell)
)
extract_source = source_of(extract_cell)
start = extract_source.index("def extract_label")
end = extract_source.index("\ndef generate_label")
strict_extract = """def extract_label(raw_text: str) -> str:
    # The contract says exactly one label. A verbose sentence containing a
    # label is invalid and must not inflate accuracy.
    normalized = raw_text.strip().lower()
    return normalized if normalized in VALID_LABELS else "INVALID"
"""
extract_source = extract_source[:start] + strict_extract + extract_source[end:]
set_source(extract_cell, extract_source)

model_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "base_model = AutoModelForMultimodalLM.from_pretrained" in source_of(cell)
)
model_source = source_of(model_cell)
model_source = model_source.replace(
    "TEMPLATE_SOURCE_MODEL_ID,\n            cache_dir",
    "TEMPLATE_SOURCE_MODEL_ID,\n            revision=MODEL_REVISION,\n            cache_dir",
)
model_source = model_source.replace(
    'f"{TEMPLATE_SOURCE_MODEL_ID}/repo?Revision=master&FilePath=chat_template.jinja"',
    'f"{TEMPLATE_SOURCE_MODEL_ID}/repo?Revision={MODEL_REVISION}"\n'
    '        "&FilePath=chat_template.jinja"',
)
model_source = model_source.replace(
    """base_model = AutoModelForMultimodalLM.from_pretrained(
    LOCAL_MODEL_DIR,
    dtype=MODEL_DTYPE,
    low_cpu_mem_usage=True,
    trust_remote_code=False,
)""",
    """base_model = AutoModelForMultimodalLM.from_pretrained(
    LOCAL_MODEL_DIR,
    dtype=MODEL_DTYPE,
    low_cpu_mem_usage=True,
    trust_remote_code=False,
    attn_implementation="sdpa",
)""",
)
if 'attn_implementation="sdpa"' not in model_source:
    raise RuntimeError("Gemma 4 model-load anchor not found")
set_source(model_cell, model_source)

lora_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "language_linear_targets =" in source_of(cell)
)
set_source(
    lora_cell,
    r'''
TEXT_LORA_PROJECTION_PATTERN = re.compile(
    r"(?:^|\.)model\.language_model\.layers\.\d+\."
    r"(?:self_attn\.(?:q_proj|k_proj|v_proj|o_proj)|"
    r"mlp\.(?:gate_proj|up_proj|down_proj))$"
)
FORBIDDEN_MULTIMODAL_PATHS = (
    "vision_tower",
    "audio_tower",
    "embed_vision",
    "embed_audio",
    "vision_projection",
    "audio_projection",
    "multi_modal",
    "multimodal",
    "mm_projector",
    "lm_head",
    "embed_tokens",
    "embed_tokens_per_layer",
    "per_layer_model_projection",
)

language_linear_targets = sorted(
    name
    for name, module in base_model.named_modules()
    if isinstance(module, torch.nn.Linear)
    and TEXT_LORA_PROJECTION_PATTERN.search(name)
)
assert language_linear_targets, (
    "No allowlisted Gemma 4 text projection matched; refusing all-linear fallback"
)
assert not any(
    any(token in name for token in FORBIDDEN_MULTIMODAL_PATHS)
    for name in language_linear_targets
), "A frozen or multimodal path entered the LoRA target set"

print("Allowlisted language-side LoRA target count:", len(language_linear_targets))
print("Target examples:", language_linear_targets[:20])

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=language_linear_targets,
)
''',
)

training_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "training_args = SFTConfig" in source_of(cell)
)
training_source = source_of(training_cell)
training_source = training_source.replace(
    'greater_is_better=False,\n',
    'greater_is_better=False,\n    load_best_model_at_end=True,\n',
)
training_source = training_source.replace(
    'gradient_checkpointing=True,\n',
    'gradient_checkpointing=True,\n'
    '    gradient_checkpointing_kwargs={"use_reentrant": False},\n',
)
training_source = training_source.replace(
    'report_to="none",\n',
    'report_to="none",\n'
    '    include_tokens_per_second=True,\n'
    '    include_num_input_tokens_seen=True,\n',
)
set_source(training_cell, training_source)

train_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "forbidden_trainable =" in source_of(cell)
)
train_source = source_of(train_cell)
train_source = train_source.replace(
    'assert all("language_model" in name for name in trainable_param_names), (\n'
    '    "A trainable LoRA parameter exists outside language_model"\n'
    ')\n',
    'trainable_boundary_violations = [\n'
    '    name for name in trainable_param_names\n'
    '    if "lora_" not in name\n'
    '    or ".model.language_model.layers." not in name\n'
    '    or any(token in name for token in FORBIDDEN_MULTIMODAL_PATHS)\n'
    ']\n'
    'assert not trainable_boundary_violations, (\n'
    '    "Trainable-boundary violations: "\n'
    '    + ", ".join(trainable_boundary_violations[:20])\n'
    ')\n',
)
set_source(train_cell, train_source)

visual_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "VISUAL_FIXTURE_DIR" in source_of(cell)
)
visual_source = source_of(visual_cell)
fingerprint_code = r'''
import hashlib

FROZEN_MODALITY_MODULES = (
    "model.vision_tower",
    "model.audio_tower",
    "model.embed_vision",
    "model.embed_audio",
)

def frozen_modality_fingerprints(model):
    candidates = [
        model,
        getattr(model, "base_model", None),
        getattr(getattr(model, "base_model", None), "model", None),
    ]
    result = {}
    for module_path in FROZEN_MODALITY_MODULES:
        module = None
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                module = candidate.get_submodule(module_path)
                break
            except AttributeError:
                continue
        if module is None:
            raise RuntimeError(
                f"Required frozen modality module is missing: {module_path}"
            )
        digest = hashlib.sha256()
        parameter_count = 0
        for name, tensor in sorted(module.state_dict().items()):
            value = tensor.detach().contiguous()
            digest.update(name.encode("utf-8"))
            digest.update(str(tuple(value.shape)).encode("ascii"))
            digest.update(str(value.dtype).encode("ascii"))
            digest.update(value.view(torch.uint8).cpu().numpy().tobytes())
            parameter_count += value.numel()
        result[module_path] = {
            "sha256": digest.hexdigest(),
            "parameter_count": parameter_count,
        }
    return result

pre_frozen_modality_fingerprints = frozen_modality_fingerprints(base_model)
print(json.dumps(pre_frozen_modality_fingerprints, indent=2))

'''
set_source(visual_cell, fingerprint_code + visual_source)

for cell in cells:
    if cell.get("cell_type") != "code":
        continue
    source = source_of(cell)
    source = source.replace(
        'evaluate_model(base_model, tokenizer, split="test", limit=EVAL_LIMIT)',
        'evaluate_model(base_model, tokenizer, split="validation", limit=EVAL_LIMIT)',
    )
    source = source.replace(
        'evaluate_model(ft_model, tokenizer, split="test", limit=EVAL_LIMIT)',
        'evaluate_model(ft_model, tokenizer, split="validation", limit=EVAL_LIMIT)',
    )
    set_source(cell, source)

post_visual_index = next(
    index
    for index, cell in enumerate(cells)
    if cell.get("cell_type") == "code"
    and "post_visual_retention =" in source_of(cell)
)
post_visual = source_of(cells[post_visual_index])
post_visual += r'''

post_frozen_modality_fingerprints = frozen_modality_fingerprints(ft_model)
assert post_frozen_modality_fingerprints == pre_frozen_modality_fingerprints, (
    "A frozen vision/audio module changed during text-only LoRA training"
)
with open(
    os.path.join(OUTPUT_DIR, "frozen_modality_fingerprints.json"),
    "w",
    encoding="utf-8",
) as handle:
    json.dump(
        {
            "pre": pre_frozen_modality_fingerprints,
            "post": post_frozen_modality_fingerprints,
            "identical": True,
        },
        handle,
        ensure_ascii=False,
        indent=2,
    )
'''
set_source(cells[post_visual_index], post_visual)

final_test_markdown = markdown(
    """
## 15B. One-time locked final test

Training and checkpoint selection use only train/validation. The test split is
generated once here after the adapter and retention gates are fixed.
"""
)
final_test_code = code(
    """
final_test_metrics, final_test_report, final_test_preds = evaluate_model(
    ft_model,
    tokenizer,
    split="test",
    limit=TEST_LIMIT,
)
print(json.dumps(final_test_metrics, indent=2))
pd.DataFrame(final_test_report).transpose()
"""
)
cells.insert(post_visual_index + 1, final_test_markdown)
cells.insert(post_visual_index + 2, final_test_code)

save_cell = next(
    cell
    for cell in cells
    if cell.get("cell_type") == "code"
    and "gemma4_emotion_before_after_metrics.csv" in source_of(cell)
)
save_source = source_of(save_cell)
save_source += """

with open(
    os.path.join(OUTPUT_DIR, "final_test_metrics.json"),
    "w",
    encoding="utf-8",
) as handle:
    json.dump(final_test_metrics, handle, ensure_ascii=False, indent=2)
pd.DataFrame(final_test_report).transpose().to_csv(
    os.path.join(OUTPUT_DIR, "final_test_classification_report.csv")
)
final_test_preds.to_csv(
    os.path.join(OUTPUT_DIR, "final_test_predictions.csv"),
    index=False,
)
confusion_matrix_df(final_test_preds).to_csv(
    os.path.join(OUTPUT_DIR, "final_test_confusion_matrix.csv")
)
"""
set_source(save_cell, save_source)

cells.extend(
    [
        markdown(
            """
## 20. Multi-GPU progression (outside Jupyter)

Notebook kernels are not distributed launchers. Run the checked script from a
terminal only after the RCCL all-reduce preflight succeeds. DDP increases
throughput but keeps a full model replica on every GPU; FSDP2 shards model
state when per-GPU memory is the constraint. Neither path uses
`device_map="auto"`.
"""
        ),
        code(
            r'''
# Terminal commands — documentation only; do not execute this cell unchanged.
#
# 1) Verify two Radeon devices and RCCL collectives:
# torchrun --standalone --nproc_per_node=2 scripts/verify_rocm_multigpu.py
#
# 2) Frozen single-GPU baseline, global batch = 2 * 8 * 1 = 16:
# accelerate launch --config_file configs/accelerate/rocm_1gpu_baseline.yaml \
#   scripts/train_gemma4_emotion_multigpu.py \
#   --run-profile candidate \
#   --model-revision <IMMUTABLE_MODEL_REVISION> \
#   --dataset-revision <IMMUTABLE_DATASET_REVISION> \
#   --expected-world-size 1 --parallelism single \
#   --per-device-train-batch-size 2 \
#   --gradient-accumulation-steps 8 \
#   --expected-global-batch-size 16
#
# 3) DDP, invariant effective global batch = 2 * 4 * 2 = 16:
# accelerate launch --config_file configs/accelerate/rocm_2gpu_ddp.yaml \
#   scripts/train_gemma4_emotion_multigpu.py \
#   --run-profile candidate \
#   --model-revision <IMMUTABLE_MODEL_REVISION> \
#   --dataset-revision <IMMUTABLE_DATASET_REVISION> \
#   --expected-world-size 2 --parallelism ddp \
#   --expected-global-batch-size 16
#
# 4) FSDP2 when the model does not fit comfortably per GPU:
# accelerate launch --config_file configs/accelerate/rocm_2gpu_fsdp2.yaml \
#   scripts/train_gemma4_emotion_multigpu.py \
#   --run-profile final \
#   --model-revision <IMMUTABLE_MODEL_REVISION> \
#   --dataset-revision <IMMUTABLE_DATASET_REVISION> \
#   --expected-world-size 2 --parallelism fsdp2 \
#   --expected-global-batch-size 16
#
# 5) After three identical multi-GPU repeats, compare equivalence and speed:
# python scripts/verify_multigpu_training_admission.py \
#   --single-manifest <single>/distributed-training-manifest.json \
#   --multi-manifest <repeat-1>/distributed-training-manifest.json \
#   --multi-manifest <repeat-2>/distributed-training-manifest.json \
#   --multi-manifest <repeat-3>/distributed-training-manifest.json \
#   --output evidence/v10/multigpu-training-admission.json
''',
        ),
    ]
)

notebook["metadata"]["prooflaunch"] = {
    "schema": "ProofLaunchMultimodalSafeGemmaNotebookV3",
    "source": SOURCE.name,
    "preservesOriginal": True,
    "officialModelClass": "AutoModelForMultimodalLM",
    "runProfiles": ["smoke", "candidate", "final"],
    "globalBatchInvariantRequired": True,
    "everyRankReceiptRequired": True,
    "multiGpuAdmissionScript": (
        "scripts/verify_multigpu_training_admission.py"
    ),
    "immutableRevisionsRequiredForFinal": True,
    "strictExactLabelScoring": True,
    "positiveTextProjectionAllowlist": True,
    "frozenModalityFingerprintRequired": True,
    "visualRetentionCases": 4,
    "visualRetentionScope": "synthetic regression guard only",
    "audioSemanticRetentionRequiredForMultimodalCertification": True,
    "testUsedOnceAfterSelection": True,
    "minimumPostAccuracy": 0.75,
    "maximumAllowedDrop": 0.05,
    "distributedTrainingScript": "scripts/train_gemma4_emotion_multigpu.py",
    "rocmMultiGpuPreflight": "scripts/verify_rocm_multigpu.py",
    "deviceMapTrainingAllowed": False,
}
for cell in cells:
    if cell.get("cell_type") == "code":
        cell["execution_count"] = None
        cell["outputs"] = []

OUTPUT.write_text(
    json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
    encoding="utf-8",
)
print(OUTPUT)
