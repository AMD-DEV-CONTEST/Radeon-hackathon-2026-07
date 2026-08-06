from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "notebooks" / "gemma4_emotion_lora_modelscope_single_gpu_original.ipynb"
OUTPUT = ROOT / "notebooks" / "gemma4_emotion_lora_multimodal_safe_v2.ipynb"


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
cells = [
    cell
    for cell in notebook["cells"]
    if "__CODEX_UPLOAD_DONE__" not in "".join(cell.get("source", []))
    and "import base64, io, tarfile" not in "".join(cell.get("source", []))
]
while cells and not "".join(cells[-1].get("source", [])).strip():
    cells.pop()
notebook["cells"] = cells

cells[0]["source"] = [
    "# Gemma 4 E4B-it emotion LoRA — multimodal-safe Radeon edition\n",
    "\n",
    "This version preserves Gemma 4 image/audio towers while adapting the language "
    "side for emotion classification. It replaces `all-linear`, hard-blocks any "
    "vision/audio/projector LoRA parameter, and measures visual retention before "
    "and after training. The original Notebook remains unchanged.\n",
]

install_source = "".join(cells[2]["source"])
install_source = install_source.replace(
    "modelscope transformers accelerate",
    'modelscope "transformers>=5.5.0" accelerate',
)
cells[2]["source"] = [line + "\n" for line in install_source.rstrip().splitlines()]

import_source = "".join(cells[4]["source"])
import_source = import_source.replace(
    "from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed",
    "from transformers import AutoModelForCausalLM, AutoProcessor, AutoTokenizer, set_seed",
)
cells[4]["source"] = [line + "\n" for line in import_source.rstrip().splitlines()]

load_source = "".join(cells[14]["source"])
processor_block = """

print("Loading multimodal processor from:", LOCAL_MODEL_DIR)
processor = AutoProcessor.from_pretrained(
    LOCAL_MODEL_DIR,
    padding_side="left",
    trust_remote_code=True,
)
"""
anchor = 'print("Loading base model from:", LOCAL_MODEL_DIR)'
if anchor not in load_source:
    raise RuntimeError("base-model load anchor not found")
load_source = load_source.replace(anchor, processor_block + "\n" + anchor)
cells[14]["source"] = [line + "\n" for line in load_source.rstrip().splitlines()]

cells[23] = markdown(
    """
## 11. Configure language-side-only LoRA

Gemma 4 E4B-it is natively multimodal. `target_modules="all-linear"` also
matches the vision tower and can adapt it using text-only labels. This version
discovers only `torch.nn.Linear` modules whose full names belong to
`language_model`, then excludes vision, audio, multimodal embedders, and the
output head.
"""
)
cells[24] = code(
    """
FORBIDDEN_MULTIMODAL_PATHS = (
    "vision_tower",
    "audio_tower",
    "embed_vision",
    "embed_audio",
    "multi_modal",
    "multimodal",
)

language_linear_targets = [
    name
    for name, module in base_model.named_modules()
    if isinstance(module, torch.nn.Linear)
    and "language_model" in name
    and "lm_head" not in name
    and not any(token in name for token in FORBIDDEN_MULTIMODAL_PATHS)
]
assert language_linear_targets, "No language-side Linear modules were discovered"
assert not any(
    any(token in name for token in FORBIDDEN_MULTIMODAL_PATHS)
    for name in language_linear_targets
), "A multimodal encoder/projector entered the LoRA target set"

print("Language-side LoRA target count:", len(language_linear_targets))
print("Target examples:", language_linear_targets[:20])

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=language_linear_targets,
)
"""
)

train_source = "".join(cells[28]["source"])
needle = """if trainable_params == 0:
    raise RuntimeError("No trainable LoRA parameters were attached. Check target_modules before training.")
"""
replacement = needle + """

forbidden_trainable = [
    name
    for name in trainable_param_names
    if any(token in name for token in FORBIDDEN_MULTIMODAL_PATHS)
]
if forbidden_trainable:
    raise RuntimeError(
        "Multimodal retention gate failed: forbidden trainable parameters: "
        + ", ".join(forbidden_trainable[:20])
    )
assert all("language_model" in name for name in trainable_param_names), (
    "A trainable LoRA parameter exists outside language_model"
)
print("Multimodal safety gate: PASS — 0 vision/audio/projector trainable parameters")
"""
if needle not in train_source:
    raise RuntimeError("trainable-parameter anchor not found")
train_source = train_source.replace(needle, replacement)
cells[28]["source"] = [line + "\n" for line in train_source.rstrip().splitlines()]

visual_markdown = markdown(
    """
## 10A. Frozen visual-retention benchmark

Four generated fixtures test color, count, and spatial understanding. The same
prompts run before and after LoRA. The post-training accuracy must remain at
least 75% and may not drop by more than five percentage points. These synthetic
cases are a regression guard, not a general Gemma 4 vision benchmark.
"""
)
visual_code = code(
    """
from PIL import Image, ImageDraw

VISUAL_FIXTURE_DIR = os.path.join(OUTPUT_DIR, "visual-retention-fixtures")
os.makedirs(VISUAL_FIXTURE_DIR, exist_ok=True)

def make_visual_fixtures():
    cases = []

    red = Image.new("RGB", (384, 384), "white")
    ImageDraw.Draw(red).rectangle((72, 72, 312, 312), fill="red")
    red_path = os.path.join(VISUAL_FIXTURE_DIR, "red-square.png")
    red.save(red_path)
    cases.append((red_path, "What color is the large square? Answer one lowercase word.", "red"))

    blue = Image.new("RGB", (384, 384), "white")
    ImageDraw.Draw(blue).ellipse((72, 72, 312, 312), fill="blue")
    blue_path = os.path.join(VISUAL_FIXTURE_DIR, "blue-circle.png")
    blue.save(blue_path)
    cases.append((blue_path, "What color is the large circle? Answer one lowercase word.", "blue"))

    count = Image.new("RGB", (384, 384), "white")
    count_draw = ImageDraw.Draw(count)
    for x in (70, 172, 274):
        count_draw.ellipse((x - 38, 165 - 38, x + 38, 165 + 38), fill="green")
    count_path = os.path.join(VISUAL_FIXTURE_DIR, "three-green-circles.png")
    count.save(count_path)
    cases.append((count_path, "How many green circles are shown? Answer one word.", "three"))

    spatial = Image.new("RGB", (384, 384), "white")
    spatial_draw = ImageDraw.Draw(spatial)
    spatial_draw.ellipse((152, 48, 232, 128), fill="yellow")
    spatial_draw.rectangle((112, 244, 272, 316), fill="black")
    spatial_path = os.path.join(VISUAL_FIXTURE_DIR, "yellow-above-black.png")
    spatial.save(spatial_path)
    cases.append((
        spatial_path,
        "Is the yellow circle above or below the black rectangle? Answer one lowercase word.",
        "above",
    ))
    return cases

VISUAL_CASES = make_visual_fixtures()

def generate_visual_answer(model, image_path: str, question: str) -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": Image.open(image_path).convert("RGB")},
                {"type": "text", "text": question},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    device = next(model.parameters()).device
    inputs = {
        key: (
            value.to(device=device, dtype=model.dtype)
            if torch.is_floating_point(value)
            else value.to(device)
        )
        for key, value in inputs.items()
    }
    input_len = inputs["input_ids"].shape[-1]
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=8,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    return processor.decode(
        output[0][input_len:],
        skip_special_tokens=True,
    ).strip().lower()

def evaluate_visual_retention(model, stage: str):
    rows = []
    for image_path, question, expected in VISUAL_CASES:
        prediction = generate_visual_answer(model, image_path, question)
        rows.append(
            {
                "stage": stage,
                "image": image_path,
                "question": question,
                "expected": expected,
                "prediction": prediction,
                "correct": expected in prediction.split(),
            }
        )
    accuracy = sum(row["correct"] for row in rows) / len(rows)
    return {"stage": stage, "accuracy": accuracy, "rows": rows}

pre_visual_retention = evaluate_visual_retention(base_model, "pre_finetuning")
print(json.dumps(pre_visual_retention, indent=2))
"""
)

cells.insert(23, visual_markdown)
cells.insert(24, visual_code)

# The insertion shifted all original indices by two.
post_visual_markdown = markdown(
    """
## 15A. Post-fine-tuning multimodal retention gate

The adapter cannot be accepted if the frozen visual set regresses materially.
"""
)
post_visual_code = code(
    """
post_visual_retention = evaluate_visual_retention(ft_model, "post_finetuning")
visual_retention_summary = {
    "pre_accuracy": pre_visual_retention["accuracy"],
    "post_accuracy": post_visual_retention["accuracy"],
    "minimum_post_accuracy": 0.75,
    "maximum_allowed_drop": 0.05,
    "pre_rows": pre_visual_retention["rows"],
    "post_rows": post_visual_retention["rows"],
}
print(json.dumps(visual_retention_summary, indent=2))
assert post_visual_retention["accuracy"] >= 0.75, (
    "Multimodal retention failed: post-training visual accuracy below 75%"
)
assert (
    pre_visual_retention["accuracy"] - post_visual_retention["accuracy"] <= 0.05
), "Multimodal retention failed: visual accuracy dropped by more than 5 points"

with open(
    os.path.join(OUTPUT_DIR, "multimodal_retention.json"),
    "w",
    encoding="utf-8",
) as handle:
    json.dump(visual_retention_summary, handle, ensure_ascii=False, indent=2)
"""
)

# Locate the post-fine-tuning evaluation block after insertion and append the gate.
post_index = next(
    index
    for index, cell in enumerate(cells)
    if "post_metrics, post_report, post_preds" in "".join(cell.get("source", []))
)
cells.insert(post_index + 1, post_visual_markdown)
cells.insert(post_index + 2, post_visual_code)

notebook["metadata"]["prooflaunch"] = {
    "schema": "ProofLaunchMultimodalSafeGemmaNotebookV2",
    "source": SOURCE.name,
    "preservesOriginal": True,
    "forbiddenLoRAPaths": [
        "vision_tower",
        "audio_tower",
        "embed_vision",
        "embed_audio",
        "multi_modal",
        "multimodal",
    ],
    "visualRetentionCases": 4,
    "minimumPostAccuracy": 0.75,
    "maximumAllowedDrop": 0.05,
}
for cell in cells:
    if cell["cell_type"] == "code":
        cell["execution_count"] = None
        cell["outputs"] = []

OUTPUT.write_text(
    json.dumps(notebook, ensure_ascii=False, indent=1),
    encoding="utf-8",
)
print(OUTPUT)
