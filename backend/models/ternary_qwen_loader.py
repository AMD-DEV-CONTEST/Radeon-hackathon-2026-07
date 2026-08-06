"""Helpers for loading 1.58-bit ternary Qwen checkpoints.

These checkpoints live under the parallel `quantized_llm/` directory and require
the custom `ternary_quantization` code from `RaDialog_LLaVA` as well as a newer
`transformers` version than the main `e2e` environment provides. Therefore the
actual inference is usually run in a separate worker process (e.g. the
`radialog-qwen35` conda environment).
"""
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


# Parent of the end2end_xray project.
_QUANTIZED_LLM_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
_RADIALOG_LLAVAL_DIR = _QUANTIZED_LLM_DIR / "RaDialog_LLaVA"


def _ensure_radialog_path():
    if str(_RADIALOG_LLAVAL_DIR) not in sys.path:
        sys.path.insert(0, str(_RADIALOG_LLAVAL_DIR))


def load_ternary_qwen(model_dir: str | Path, device_map: str | None = None):
    """Load a ternary Qwen/Qwen3.5 checkpoint.

    model_dir must contain quantization_meta.pt and quantized_state_dict.pt.
    Returns (model, processor).
    """
    _ensure_radialog_path()
    import torch
    from quantization.ternary_quantization import replace_linear_with_ternary
    from transformers import AutoModelForMultimodalLM, AutoProcessor

    model_dir = Path(model_dir)
    meta_path = model_dir / "quantization_meta.pt"
    state_path = model_dir / "quantized_state_dict.pt"
    if not meta_path.exists():
        raise FileNotFoundError(f"Missing {meta_path}")
    if not state_path.exists():
        raise FileNotFoundError(f"Missing {state_path}")

    meta = torch.load(str(meta_path), map_location="cpu", weights_only=False)
    model_id = meta["model_id"]
    compute_dtype = _parse_compute_dtype(meta.get("compute_dtype", "bfloat16"))

    if device_map is None:
        device_map = "auto"

    model = AutoModelForMultimodalLM.from_pretrained(
        model_id,
        torch_dtype=compute_dtype,
        device_map=device_map,
        trust_remote_code=True,
    )
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    processor.image_processor.do_resize = False

    replace_linear_with_ternary(
        model.model.language_model,
        keep_modules=set(meta.get("keep_modules", ["embed_tokens"])),
        keep_patterns=meta.get("keep_patterns", []),
        scale_type=meta["scale_type"],
        compute_dtype=compute_dtype,
        verbose=False,
    )
    state_dict = torch.load(str(state_path), map_location="cpu", weights_only=False)
    model.load_state_dict(state_dict, strict=True)
    model.eval()
    return model, processor


def generate_text(
    model: Any,
    processor: Any,
    prompt: str,
    images: Optional[list] = None,
    max_new_tokens: int = 256,
    do_sample: bool = False,
    temperature: float = 0.7,
    repetition_penalty: float = 1.1,
    no_repeat_ngram_size: int = 3,
) -> str:
    """Generate text (optionally conditioned on images) with a ternary Qwen model."""
    import torch

    if images is None:
        images = []
    messages = [
        {
            "role": "user",
            "content": [{"type": "image", "image": img} for img in images]
            + [{"type": "text", "text": prompt}],
        }
    ]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=images, return_tensors="pt", padding=True).to(model.device)

    gen_kwargs = {
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "repetition_penalty": repetition_penalty,
        "no_repeat_ngram_size": no_repeat_ngram_size,
    }
    if do_sample:
        gen_kwargs["temperature"] = temperature

    with torch.inference_mode():
        generated_ids = model.generate(**inputs, **gen_kwargs)

    generated_ids_trimmed = [
        out_ids[len(in_ids) :]
        for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    response = processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()
    return response


def _parse_compute_dtype(dtype: Any) -> Any:
    import torch

    if dtype in ("bfloat16", "bf16"):
        return torch.bfloat16
    if dtype in ("float16", "fp16"):
        return torch.float16
    if dtype in ("float32", "fp32"):
        return torch.float32
    return torch.bfloat16


def is_ternary_qwen_dir(model_dir: str | Path) -> bool:
    """Return True if model_dir looks like a static ternary Qwen checkpoint."""
    model_dir = Path(model_dir)
    return (model_dir / "quantization_meta.pt").exists() and (
        model_dir / "quantized_state_dict.pt"
    ).exists()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--model_dir", type=str, required=True)
    parser.add_argument("--prompt", type=str, default="Hello, are you there?")
    parser.add_argument("--max_new_tokens", type=int, default=64)
    args = parser.parse_args()

    print(f"Loading ternary Qwen from {args.model_dir}...", flush=True)
    model, processor = load_ternary_qwen(args.model_dir)
    print("Loaded. Generating...", flush=True)
    response = generate_text(model, processor, args.prompt, max_new_tokens=args.max_new_tokens)
    print("Response:", response)
