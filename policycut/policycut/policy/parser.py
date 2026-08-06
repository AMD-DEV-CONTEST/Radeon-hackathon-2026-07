"""Policy parser: Qwen LLM with strict JSON output, keyword fallback.

parse_policy(text, use_llm=True) -> (PolicySpec, source) with source in
{"llm", "llm_repaired", "keyword_fallback"}.

torch/transformers are imported lazily inside functions; any import, load, or
generation failure degrades gracefully to the deterministic keyword parser.
POLICYCUT_NO_LLM=1 forces the keyword fallback. Model + tokenizer are cached
at module level; unload_llm() frees them (and VRAM).
"""

import gc
import json
import logging
import os
import threading

from pydantic import ValidationError

from .keyword_parser import parse_keyword_policy
from .schema import DEFAULT_PROMPTS, PolicySpec

logger = logging.getLogger(__name__)

_QWEN_FALLBACK_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"

_LLM_CACHE: dict = {}
_LLM_LOCK = threading.Lock()

_SYSTEM_PROMPT = """You are the policy compiler of a local video redaction tool. Convert the user's natural-language redaction policy into ONE JSON object matching this exact schema. Output ONLY the JSON object: no markdown, no code fences, no comments, no extra text.

Schema:
{
  "schema_version": "1.0",
  "language": "en",
  "visual_targets": [
    {"category": "<face|license_plate|id_document|screen>",
     "prompts": ["<detection phrase>", "..."],
     "action": {"type": "<blur|pixelate|solid>", "strength": <integer 1-100>}}
  ],
  "audio_targets": [
    {"category": "<phone|email|address>",
     "action": {"type": "<mute|beep>"},
     "padding_before_ms": 150,
     "padding_after_ms": 250}
  ],
  "unsupported_terms": ["<requested-but-unsupported target>", "..."],
  "review_required": true
}

Rules:
1. Supported visual categories: face, license_plate, id_document, screen. Supported audio categories: phone (spoken phone numbers), email (spoken email addresses), address (spoken street/home addresses).
2. Visual actions: blur, pixelate, solid (opaque cover). Audio actions: mute, beep. Defaults when unspecified: visual pixelate strength 65; audio mute.
3. Default prompts per visual category (use unless the user is more specific): face -> ["human face"]; license_plate -> ["license plate", "vehicle registration plate"]; id_document -> ["identity card", "passport", "driver's license"]; screen -> ["computer monitor", "laptop screen", "smartphone screen", "tablet screen"].
4. Negations ("do not blur screens", "don't pixelate faces", "except faces", "but not plates") mean that target MUST NOT appear in visual_targets or audio_targets.
5. Anything requested that maps to no supported category (e.g. tattoos, names, voices, minors, children, logos, signatures) goes into unsupported_terms only.
6. Never invent targets the user did not ask for. "review_required" is always true. "schema_version" is always "1.0". "language" is always "en".
7. "strength N", "at N", or "N%" set the visual strength, clamped to 1-100."""

_FEWSHOT: list[tuple[str, dict]] = [
    (
        "Blur all faces and mute any spoken phone numbers.",
        {
            "schema_version": "1.0",
            "language": "en",
            "visual_targets": [
                {
                    "category": "face",
                    "prompts": ["human face"],
                    "action": {"type": "blur", "strength": 65},
                }
            ],
            "audio_targets": [
                {
                    "category": "phone",
                    "action": {"type": "mute"},
                    "padding_before_ms": 150,
                    "padding_after_ms": 250,
                }
            ],
            "unsupported_terms": [],
            "review_required": True,
        },
    ),
    (
        "Pixelate license plates at strength 80 and hide tattoos, but do not blur the screens.",
        {
            "schema_version": "1.0",
            "language": "en",
            "visual_targets": [
                {
                    "category": "license_plate",
                    "prompts": ["license plate", "vehicle registration plate"],
                    "action": {"type": "pixelate", "strength": 80},
                }
            ],
            "audio_targets": [],
            "unsupported_terms": ["tattoos"],
            "review_required": True,
        },
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_policy(text: str, use_llm: bool = True) -> tuple[PolicySpec, str]:
    """Parse a natural-language policy into a PolicySpec.

    Returns (spec, source) with source in {"llm", "llm_repaired",
    "keyword_fallback"}. Never raises for missing ML dependencies.
    """
    text = (text or "").strip()
    no_llm_env = os.environ.get("POLICYCUT_NO_LLM", "").strip().lower() in ("1", "true", "yes")
    if not use_llm or no_llm_env or not text:
        return parse_keyword_policy(text), "keyword_fallback"

    try:
        return _parse_with_llm(text)
    except Exception as exc:  # any import/load/generation/validation failure
        logger.warning("LLM policy parsing unavailable (%s); using keyword fallback", exc)
        return parse_keyword_policy(text), "keyword_fallback"


def unload_llm() -> None:
    """Release the cached Qwen model and tokenizer, freeing VRAM."""
    with _LLM_LOCK:
        model = _LLM_CACHE.pop("model", None)
        _LLM_CACHE.pop("tokenizer", None)
        _LLM_CACHE.pop("device", None)
    if model is not None:
        del model
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def extract_first_json(text: str) -> dict | None:
    """Extract the first complete top-level JSON object via brace matching."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : i + 1]
                        try:
                            obj = json.loads(candidate)
                        except json.JSONDecodeError:
                            break  # malformed; try the next opening brace
                        return obj if isinstance(obj, dict) else None
        start = text.find("{", start + 1)
    return None


# ---------------------------------------------------------------------------
# LLM internals (lazy imports)
# ---------------------------------------------------------------------------

def _resolve_device() -> str:
    try:
        from policycut.core.device import get_device

        return get_device()
    except Exception:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"


def _resolve_model_id() -> str:
    try:
        from policycut.config import get_settings

        return get_settings().qwen_model
    except Exception:
        return _QWEN_FALLBACK_MODEL_ID


def _load_llm():
    """Load and cache Qwen model + tokenizer. Raises on failure (caller falls back)."""
    with _LLM_LOCK:
        if "model" in _LLM_CACHE:
            return _LLM_CACHE["model"], _LLM_CACHE["tokenizer"], _LLM_CACHE["device"]

        from transformers import AutoModelForCausalLM, AutoTokenizer  # lazy import
        import torch  # lazy import

        model_id = _resolve_model_id()
        device = _resolve_device()
        logger.info("Loading policy LLM %s on %s", model_id, device)
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        load_kwargs = {}
        if device == "cuda":
            # transformers >= 5 renamed from_pretrained's torch_dtype -> dtype
            # (torch_dtype still works in 5.x but is deprecated; 4.4x only
            # knows torch_dtype, so gate on the major version).
            try:
                import transformers

                major = int(str(transformers.__version__).split(".")[0])
            except Exception:
                major = 4
            dtype_kw = "dtype" if major >= 5 else "torch_dtype"
            load_kwargs[dtype_kw] = torch.float16  # fp16 on GPU
        model = AutoModelForCausalLM.from_pretrained(model_id, **load_kwargs)
        model.to(device)
        model.eval()

        _LLM_CACHE["model"] = model
        _LLM_CACHE["tokenizer"] = tokenizer
        _LLM_CACHE["device"] = device
        return model, tokenizer, device


def _generate(messages: list[dict]) -> str:
    """Greedy-decode a chat completion; returns only the newly generated text."""
    model, tokenizer, device = _load_llm()
    import torch  # lazy import

    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer([prompt], return_tensors="pt").to(device)
    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None:
        pad_token_id = tokenizer.eos_token_id
    with torch.no_grad():
        output = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=800,
            pad_token_id=pad_token_id,
        )
    new_tokens = output[0][inputs["input_ids"].shape[1] :]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def _build_messages(text: str) -> list[dict]:
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for user_text, spec_dict in _FEWSHOT:
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": json.dumps(spec_dict, indent=2)})
    messages.append({"role": "user", "content": text})
    return messages


def _sanitize(data: dict) -> dict:
    """Gentle pre-validation cleanup: clamp numeric strengths to 1..100."""
    targets = data.get("visual_targets")
    if isinstance(targets, list):
        for target in targets:
            if not isinstance(target, dict):
                continue
            action = target.get("action")
            if isinstance(action, dict):
                strength = action.get("strength")
                if isinstance(strength, (int, float)) and not isinstance(strength, bool):
                    action["strength"] = int(max(1, min(100, strength)))
    return data


def _validate_spec(data: dict) -> PolicySpec:
    if hasattr(PolicySpec, "model_validate"):  # pydantic v2
        return PolicySpec.model_validate(data)
    return PolicySpec.parse_obj(data)  # pydantic v1


def _try_validate(raw: str) -> tuple[PolicySpec | None, str | None]:
    """Extract + validate; returns (spec, None) or (None, error_message)."""
    data = extract_first_json(raw)
    if data is None:
        return None, "no valid JSON object found in the reply"
    try:
        return _validate_spec(_sanitize(data)), None
    except ValidationError as exc:
        return None, str(exc)[:600]


def _normalize_spec(spec: PolicySpec) -> PolicySpec:
    """Post-validation cleanup: default prompts, dedupe, force review."""
    seen_visual: set[str] = set()
    visual_targets = []
    for target in spec.visual_targets:
        if target.category in seen_visual:
            continue
        seen_visual.add(target.category)
        if not target.prompts:
            target.prompts = list(DEFAULT_PROMPTS.get(target.category, []))
        visual_targets.append(target)
    seen_audio: set[str] = set()
    audio_targets = []
    for target in spec.audio_targets:
        if target.category in seen_audio:
            continue
        seen_audio.add(target.category)
        audio_targets.append(target)
    spec.visual_targets = visual_targets
    spec.audio_targets = audio_targets
    spec.unsupported_terms = list(dict.fromkeys(str(t) for t in spec.unsupported_terms))
    spec.schema_version = "1.0"
    spec.review_required = True
    return spec


def _parse_with_llm(text: str) -> tuple[PolicySpec, str]:
    """One LLM attempt + one repair round. Raises on final failure."""
    messages = _build_messages(text)
    raw = _generate(messages)
    spec, error = _try_validate(raw)
    if spec is not None:
        return _normalize_spec(spec), "llm"

    logger.warning("LLM policy JSON invalid (%s); requesting one repair", error)
    repair_messages = messages + [
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": (
                f"Your previous reply was rejected by the validator: {error}. "
                "Respond again with ONLY one corrected JSON object that matches "
                "the schema exactly. No explanations, no markdown."
            ),
        },
    ]
    raw_repaired = _generate(repair_messages)
    spec, error = _try_validate(raw_repaired)
    if spec is not None:
        return _normalize_spec(spec), "llm_repaired"
    raise ValueError(f"LLM policy parse failed after repair attempt: {error}")
