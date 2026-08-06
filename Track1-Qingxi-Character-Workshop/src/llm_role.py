from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import yaml

from src.models_schema import CharacterCard, parse_character_json
from src.paths import OUTPUTS, PROMPTS, ROOT
from src.world import WorldConfig, load_world


def _read(name: str) -> str:
    p = PROMPTS / name
    return p.read_text(encoding="utf-8")


def build_system_prompt(world: WorldConfig | None = None) -> str:
    world = world or load_world()
    role = _read("system_role.txt")
    schema = _read("json_schema.txt")
    few_shot = _read("few_shot.jsonl").strip()
    parts = [
        role,
        "",
        f"# World: {world.world_name}",
        f"tagline: {world.tagline}",
        f"ip_policy: {world.ip_policy}",
        "",
        "Affinities: "
        + ", ".join(f"{a.name}" for a in world.affinities),
        "spirit_domain: "
        + f"{world.spirit_domain.name} - " + world.spirit_domain.description,
        "",
        f"style_art: {world.style_art}",
        f"style_avoid: {world.style_avoid}",
        "",
        "# JSON schema",
        schema,
        "",
        "# Few-shot examples (one JSON per line)",
        few_shot,
    ]
    return "\n".join(parts)


_MOCK_ADJ = [
    "Azure", "Ember", "Silent", "Paper", "Verdant", "Umbral",
    "Gilded", "Hollow", "Radiant", "Icy",
]
_MOCK_NOUN = [
    "Walker", "Weaver", "Warden", "Seeker", "Scribe", "Ranger",
    "Herald", "Vagrant", "Keeper", "Drifter",
]


def _mock_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", text or "").lower()
    seed = abs(hash(cleaned or "anonymous"))
    return f"{_MOCK_ADJ[seed % len(_MOCK_ADJ)]} {_MOCK_NOUN[(seed // 7) % len(_MOCK_NOUN)]}"


def _guess_affinity(text: str, world: WorldConfig) -> str | None:
    low = (text or "").lower()
    for a in world.affinities:
        if a.name.lower() in low:
            return a.name
        # allow zh input convenience
        if a.name_zh and a.name_zh in (text or ""):
            return a.name
    return None


def _mock_card(
    user_text: str,
    affinity_pref: str | None = None,
    base_card: CharacterCard | None = None,
    revise_instruction: str | None = None,
) -> CharacterCard:
    world = load_world()
    names = world.affinity_names()
    pref = affinity_pref or _guess_affinity(user_text, world) or names[0]
    if pref not in names:
        raise ValueError(f"affinity_pref must be one of {names}, got {pref!r}")

    aff = {n: 30 for n in names}
    aff[pref] = 90
    for n in names:
        if n != pref:
            aff[n] = 25 + (abs(hash(n + pref)) % 20)

    pref_aff = world.affinity_by_name(pref)
    kw = ", ".join(pref_aff.visual_keywords) if pref_aff else ""

    if base_card is not None and revise_instruction:
        instr = revise_instruction
        new_appearance = f"{base_card.appearance} (revised: {instr})"
        new_image = f"{base_card.image_prompt}, {instr}"
        return base_card.model_copy(
            update={"appearance": new_appearance, "image_prompt": new_image}
        )

    data = {
        "name": _mock_name(user_text),
        "one_liner": "An original character inspired by your brief.",
        "appearance": "Original anime-style character design, clean silhouette.",
        "personality": "Calm and curious.",
        "backstory": (
            f"Grew up on a street corner of the {world.world_name}, "
            f"bonded with {pref} energy."
        ),
        "primary_affinity": pref,
        "affinities": aff,
        "spirit_domain": f"An inner domain themed around {pref}.",
        "ability_showcase": f"Channels {pref} energy in an original signature move.",
        "image_prompt": (
            f"anime character portrait, {pref} affinity theme, {kw}, {world.style_art}"
        ),
        "image_negative": world.style_avoid,
        "motion_prompt": f"camera slow orbit, {kw}, cinematic lighting",
    }
    return CharacterCard.model_validate(data)


def generate_character(
    user_text: str,
    affinity_pref: str | None = None,
    mock: bool | None = None,
    base_card: CharacterCard | None = None,
    revise_instruction: str | None = None,
) -> CharacterCard:
    world = load_world()

    if mock is None:
        try:
            import transformers  # noqa: F401
            mock = False
        except Exception:
            mock = True

    if mock:
        return _mock_card(
            user_text=user_text,
            affinity_pref=affinity_pref,
            base_card=base_card,
            revise_instruction=revise_instruction,
        )

    return _generate_with_transformers(
        user_text=user_text,
        affinity_pref=affinity_pref,
        world=world,
        base_card=base_card,
        revise_instruction=revise_instruction,
    )


_llm_model = None
_llm_tokenizer = None


def _llm_cfg() -> dict:
    p = ROOT / "configs" / "models.yaml"
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data.get("llm") or {}
    return {}


def _load_llm():
    """Load and cache tokenizer+model once per process.

    Prefers a local checkpoint under models/llm (PVC-persisted); otherwise
    falls back to the HF model id from config (which may download to the
    standard HF cache on first use).
    """
    global _llm_model, _llm_tokenizer
    if _llm_model is not None and _llm_tokenizer is not None:
        return _llm_tokenizer, _llm_model

    import torch  # type: ignore
    from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

    from src.device import torch_device_string
    from src.model_paths import has_local_llm, local_llm_dir

    cfg = _llm_cfg()
    if has_local_llm():
        model_name = str(local_llm_dir())
    else:
        model_name = cfg.get("model_id", "Qwen/Qwen2.5-7B-Instruct")
    device = torch_device_string()
    _llm_tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    _llm_model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        trust_remote_code=True,
    ).to(device)
    _llm_model.eval()
    return _llm_tokenizer, _llm_model


def unload_llm() -> None:
    """Free LLM weights (call before loading big diffusion models on tight VRAM)."""
    global _llm_model, _llm_tokenizer
    _llm_model = None
    _llm_tokenizer = None
    try:
        import gc

        import torch  # type: ignore

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _dump_debug(raw: str, tag: str) -> Path:
    d = OUTPUTS / "_llm_debug"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{time.strftime('%Y%m%d-%H%M%S')}_{tag}.txt"
    p.write_text(raw, encoding="utf-8")
    return p


def _chat_generate(messages: list[dict], max_new_tokens: int, greedy: bool) -> str:
    tokenizer, model = _load_llm()
    import torch  # type: ignore

    prompt_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=not greedy,
            temperature=0.7 if not greedy else None,
            top_p=0.9 if not greedy else None,
            pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(
        out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
    )


def _few_shot_messages() -> list[dict]:
    msgs: list[dict] = []
    fs = PROMPTS / "few_shot.jsonl"
    if fs.exists():
        for line in fs.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ex = json.loads(line)
            except json.JSONDecodeError:
                continue
            msgs.append({"role": "user", "content": ex["user"]})
            msgs.append(
                {
                    "role": "assistant",
                    "content": json.dumps(ex["assistant"], ensure_ascii=False),
                }
            )
    return msgs


def _few_shot_example() -> dict:
    """Return the first few-shot assistant object (used in attempt 3 prompt)."""
    fs = PROMPTS / "few_shot.jsonl"
    if fs.exists():
        for line in fs.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ex = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ex.get("assistant"), dict):
                return ex["assistant"]
    return {}


def _generate_with_transformers(
    user_text: str,
    affinity_pref: str | None,
    world: WorldConfig,
    base_card: CharacterCard | None = None,
    revise_instruction: str | None = None,
) -> CharacterCard:
    """Lazy HF text-generation path. Model cached; JSON-first greedy decoding."""
    cfg = _llm_cfg()
    max_new_tokens = int(cfg.get("max_new_tokens", 1536))

    system_prompt = build_system_prompt(world)

    if affinity_pref and affinity_pref not in world.affinity_names():
        raise ValueError(
            f"affinity_pref must be one of {world.affinity_names()}, "
            f"got {affinity_pref!r}"
        )

    user_content = user_text
    if affinity_pref:
        user_content += f"\nPreferred affinity: {affinity_pref}"
    if base_card is not None and revise_instruction:
        user_content += (
            f"\nOriginal character: {base_card.model_dump_json()}\n"
            f"Revision request: {revise_instruction}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        *_few_shot_messages(),
        {"role": "user", "content": user_content},
    ]

    # Attempt 1: greedy — most reliable for strict JSON output
    raw = ""
    raw2 = ""
    raw3 = ""
    first_error: Exception | None = None
    second_error: Exception | None = None
    third_error: Exception | None = None

    try:
        raw = _chat_generate(messages, max_new_tokens=max_new_tokens, greedy=True)
        return parse_character_json(raw)
    except Exception as e:
        first_error = e
        try:
            _dump_debug(raw or "no output", "attempt1")
        except Exception:
            pass

    # Attempt 2: same context but sampling decode (different output trajectory)
    try:
        raw2 = _chat_generate(messages, max_new_tokens=max_new_tokens, greedy=False)
        return parse_character_json(raw2)
    except Exception as e:
        second_error = e
        try:
            _dump_debug(raw2 or "no output", "attempt2")
        except Exception:
            pass

    # Attempt 3: minimal "JSON API" prompt + sampling, no few-shot noise
    strict_messages = [
        {
            "role": "system",
            "content": (
                "You are a JSON API. Reply with exactly one JSON object matching "
                "the schema. No prose, no markdown, no explanation. "
                "Every field listed below must be a plain string (never an "
                "object or array)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Schema: {_read('json_schema.txt')}\n"
                f"Example: {json.dumps(_few_shot_example(), ensure_ascii=False)}\n"
                f"Brief: {user_content}\n"
                "Output JSON only."
            ),
        },
    ]
    try:
        raw3 = _chat_generate(strict_messages, max_new_tokens=max_new_tokens, greedy=False)
        return parse_character_json(raw3)
    except Exception as e3:
        third_error = e3
        p3 = _dump_debug(raw3 or "no output", "attempt3")
        ex1 = (raw or "")[:200].replace("\n", " ")
        ex2 = (raw2 or "")[:200].replace("\n", " ")
        ex3 = (raw3 or "")[:200].replace("\n", " ")
        raise ValueError(
            "LLM did not produce valid JSON after 3 attempts. "
            f"Errors: first={first_error}; second={second_error}; third={third_error}. "
            f"Raw1 excerpt: {ex1!r}. "
            f"Raw2 excerpt: {ex2!r}. "
            f"Raw3 dumped to {p3}, excerpt: {ex3!r}"
        )
