# -*- coding: utf-8 -*-
"""Intent layer v2 — free-form user instruction → structured pipeline params.

A small local instruct LLM (default Qwen2.5-1.5B-Instruct) parses what the
user WANTS and returns strict JSON: which engine to use, a rewritten precise
prompt, suggested strength, and a one-line Chinese summary shown in the UI
("🧠 Understood: ..."). The LLM only rewrites and routes — the pixel work
stays with the tuned pipelines.

Every interpret_* function has a deterministic rule-based fallback, so the
app keeps working (degraded) if the LLM is disabled, not downloaded, slow,
or outputs garbage. Callers treat the result as advisory overrides.
"""
from __future__ import annotations

import json
import re

import torch

# ---------------------------------------------------------------------------
# LLM plumbing
# ---------------------------------------------------------------------------

_SYS = (
    "You are the intent parser of an AI image-editing studio. Convert the "
    "user's editing instruction (Chinese or English) into ONE strict JSON "
    "object. Output JSON only — no markdown fences, no explanation, no "
    "trailing text."
)


def _chat(manager, task_prompt: str) -> str | None:
    """One LLM round-trip. Returns raw text or None on any failure."""
    if not manager.settings.enable_intent_llm:
        return None
    try:
        tok, model = manager.get_llm()
        msgs = [{"role": "system", "content": _SYS},
                {"role": "user", "content": task_prompt}]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_tensors="pt").to(model.device)
        with torch.inference_mode():
            out = model.generate(
                ids, max_new_tokens=manager.settings.intent_max_tokens,
                do_sample=False, temperature=None, top_p=None, top_k=None,
                pad_token_id=tok.eos_token_id)
        text = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
        return text.strip()
    except Exception:
        return None


def _extract_json(text: str) -> dict | None:
    """Pull the first balanced {...} object out of LLM output and parse it."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        return obj if isinstance(obj, dict) else None
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None


def _str(obj: dict, key: str) -> str:
    v = obj.get(key)
    return v.strip() if isinstance(v, str) else ""


def _clamp_f(v, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Rule helpers (fallback + validation)
# ---------------------------------------------------------------------------

_COLOR_WORDS = (
    "red|crimson|scarlet|orange|amber|yellow|gold|golden|green|emerald|lime|"
    "teal|cyan|turquoise|aqua|blue|navy|azure|indigo|purple|violet|lavender|"
    "lilac|magenta|fuchsia|pink|rose|brown|burgundy|black|white|gray|grey|"
    "silver|红|橙|橘|黄|金|绿|青|蓝|紫|粉|玫|棕|褐|黑|白|灰|银"
)
_COLOR_RE = re.compile(r"(?:" + _COLOR_WORDS + r")", re.I)


def _count_color_mentions(text: str) -> int:
    return len(_COLOR_RE.findall(text or ""))


_CN_COLOR = {"红": "red", "橙": "orange", "橘": "orange", "黄": "yellow",
             "金": "gold", "绿": "green", "青": "teal", "蓝": "blue",
             "紫": "purple", "粉": "pink", "玫": "rose", "棕": "brown",
             "褐": "brown", "黑": "black", "白": "white", "灰": "gray",
             "银": "silver"}


def _colors_english(text: str) -> list[str]:
    """Ordered unique English color names found in text (CN mapped to EN)."""
    out: list[str] = []
    for m in _COLOR_RE.finditer(text or ""):
        w = m.group(0).lower()
        w = _CN_COLOR.get(w, w)
        if w not in out:
            out.append(w)
    return out


# Design/material-change detector. Deliberately EXCLUDES generic change verbs
# (变成/改成/换成/"change") and region nouns (shirt/skirt/衣) — "把衬衫变成紫色"
# is a pure recolor even though it contains 变成 and 衬衫. Only NEW-GARMENT
# nouns, wearable accessories, patterns/materials and add/remove/wear verbs
# route to the diffusion repaint engine.
_DESIGN_RE = re.compile(
    r"dress|gown|uniform|suit|bikini|costume|pattern|design|material|texture|"
    r"glasses|sunglasses|earring|necklace|wear|put on|add |remove|脱掉|取下|"
    r"穿上|戴上|加上|添上|连衣裙|礼服|帽子|眼镜|墨镜|项链|耳环|制服|汉服|婚纱|"
    r"花纹|图案|材质|面料", re.I)


def _quality_suffix(kind: str) -> str:
    if kind == "repaint":
        return (", keep the original lineart, shading and lighting, preserve "
                "everything outside the edited area unchanged, high quality, "
                "detailed")
    if kind == "scene":
        return (", seamless extension of the original scene, consistent color "
                "palette, lighting and perspective, high quality, detailed")
    if kind == "backdrop":
        return (", empty scene, no people, no characters, cohesive soft "
                "lighting, professional photography, high quality, detailed")
    return ", high quality, detailed"


# ---------------------------------------------------------------------------
# Public interpreters — each returns a plan dict:
#   {engine: "llm"|"rules", summary: str, ...task-specific overrides}
# or None when there is nothing to interpret (empty instruction).
# ---------------------------------------------------------------------------

def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text or ""))


# Region vocabulary for multi-target recolor ("shirt purple, hair black").
# Longest-first so "t-shirt" beats "shirt"; CN and EN mixed.
_REGION_WORDS = [
    ("hair", r"hair|hairstyle|头发|頭髮|发丝|刘海"),
    ("eyes", r"eyes|eyebrows?|眼睛|眉毛"),
    ("lips", r"lips?|mouth|嘴唇|嘴巴"),
    ("hat", r"hat|cap|beret|帽子"),
    ("shirt", r"t-?shirt|shirt|blouse|top|sweater|hoodie|衬衫|上衣|毛衣|卫衣|t恤"),
    ("coat", r"coat|jacket|blazer|外套|夹克|大衣"),
    ("dress", r"dress|gown|连衣裙|长裙|礼服"),
    ("skirt", r"skirt|裙子|短裙|半身裙"),
    ("pants", r"pants|trousers|jeans|shorts|裤子|长裤|短裤|牛仔裤"),
    ("shoes", r"shoes?|boots?|sneakers?|鞋子|靴子|运动鞋"),
    ("background", r"background|backdrop|背景"),
    ("skin", r"skin|皮肤|肤色"),
]
_REGION_RE = [(name, re.compile(pat, re.I)) for name, pat in _REGION_WORDS]


def _pair_targets(text: str) -> list[dict]:
    """Pair region words with their nearest color word by text distance.
    Returns targets like [{"region":"shirt","color":"purple"}, ...] ordered by
    appearance. Colors with no region get region "" (whole mask)."""
    regions = [(m.start(), name)
               for name, rx in _REGION_RE for m in rx.finditer(text or "")]
    colors = []
    for m in _COLOR_RE.finditer(text or ""):
        w = m.group(0).lower()
        colors.append((m.start(), _CN_COLOR.get(w, w)))
    if not colors:
        return []
    targets, used_colors = [], set()
    for rpos, rname in sorted(regions):
        best, best_d = None, 1e9
        for ci, (cpos, cname) in enumerate(colors):
            d = abs(cpos - rpos)
            if d < best_d and ci not in used_colors:
                best, best_d = (ci, cname), d
        if best:
            used_colors.add(best[0])
            targets.append({"region": rname, "color": best[1]})
    for ci, (cpos, cname) in enumerate(colors):
        if ci not in used_colors:
            targets.append({"region": "", "color": cname})
    # de-dup regions (first mention wins)
    seen, out = set(), []
    for t in targets:
        if t["region"] and t["region"] in seen:
            continue
        seen.add(t["region"])
        out.append(t)
    return out[:4]


def _first_region(text: str) -> str:
    """First region noun mentioned (fences single-target recolor)."""
    best = None
    for name, rx in _REGION_RE:
        m0 = rx.search(text or "")
        if m0 and (best is None or m0.start() < best[0]):
            best = (m0.start(), name)
    return best[1] if best else ""


def _valid_targets(obj: dict) -> list[dict]:
    """Sanitize an LLM-provided targets list."""
    raw = obj.get("targets")
    if not isinstance(raw, list):
        return []
    out = []
    for t in raw[:4]:
        if not isinstance(t, dict):
            continue
        color = _str(t, "color")
        if not color or _has_cjk(color):
            continue
        out.append({"region": _str(t, "region"), "color": color})
    return out


def interpret_inpaint(manager, instruction: str) -> dict | None:
    """Decide recolor / recolor_multi / repaint + rewrite params."""
    text = (instruction or "").strip()
    if not text:
        return None

    prompt = f"""An image editor has a brush mask over the region the user wants to change.
Instruction: "{text}"

Decide the editing plan and return JSON with exactly these keys:
- "mode": one of:
  * "recolor" — the whole brushed region becomes ONE single color, drawing itself untouched (hue shift only).
  * "recolor_multi" — the instruction asks for TWO OR MORE different colors on different parts (e.g. shirt one color, hair another). Pure color change only, no design/material change.
  * "repaint" — any design / material / pattern change, adding or replacing objects, changing garment TYPE (shirt→dress), or anything that is not a pure color change.
- "color": for recolor only — the single target color word IN ENGLISH (e.g. "purple", "navy blue"). Otherwise "".
- "region": for recolor only — the single body part or garment being recolored, IN ENGLISH (e.g. "shirt", "hair", "dress"); "" when not mentioned. Otherwise "".
- "targets": for recolor_multi only — a list of {{"region": "<body part or item, English>", "color": "<target color, English>"}} pairing EACH mentioned item with its target color. Otherwise [].
- "prompt": for repaint only — a detailed English diffusion prompt that ANCHORS identity first, then describes the edit. ALWAYS start with "the same character, same pose, same face," then describe ONLY the requested change (colors, clothing, material) as attributes of that same subject, then append exactly: ", everything else unchanged, keep the original lineart, shading and lighting, preserve everything outside the mask unchanged, high quality, detailed". Never describe a new person, a new body or a full scene. Otherwise "".
- "strength": for repaint only — float 0.8 to 0.95 (0.85 for color/material swaps, 0.9 for new objects or changing garment TYPE such as shirt→dress). Never go below 0.8 — lower values leave the original image unchanged. Otherwise 0.
- "summary": one short Chinese sentence (≤30字) stating what will be done.

Examples:
Instruction: "turn the shirt purple" -> {{"mode":"recolor","color":"purple","region":"shirt","targets":[],"prompt":"","strength":0,"summary":"将衬衫换为紫色"}}
Instruction: "把衬衫变成紫色，头发变成黑色" -> {{"mode":"recolor_multi","color":"","region":"","targets":[{{"region":"shirt","color":"purple"}},{{"region":"hair","color":"black"}}],"prompt":"","strength":0,"summary":"衬衫改紫色、头发改黑色"}}
Instruction: "change the shirt to a pink dress" -> {{"mode":"repaint","color":"","region":"","targets":[],"prompt":"the same character, same pose, same face, wearing a soft pink dress with gentle fabric folds instead of the shirt, everything else unchanged, keep the original lineart, shading and lighting, preserve everything outside the mask unchanged, high quality, detailed","strength":0.9,"summary":"把衬衫改成粉色连衣裙"}}
"""
    raw = _chat(manager, prompt)
    obj = _extract_json(raw or "")
    if obj:
        mode = _str(obj, "mode")
        summary = _str(obj, "summary")
        p_prompt = _str(obj, "prompt")
        # Guard rails: a single Chinese color word works for recolor, but a
        # multi-color instruction must NEVER collapse into one recolor, and
        # diffusion prompts must be English.
        multi_color = _count_color_mentions(text) >= 2
        if mode == "recolor" and _str(obj, "color") and not multi_color:
            return {"engine": "llm", "mode": "recolor",
                    "color": _str(obj, "color"),
                    "region": _str(obj, "region") or _first_region(text),
                    "summary": summary}
        if mode == "recolor_multi":
            targets = _valid_targets(obj)
            if len(targets) >= 2:
                return {"engine": "llm", "mode": "recolor_multi",
                        "targets": targets, "summary": summary}
            # LLM said multi but gave garbage — repair with rule pairing
            targets = _pair_targets(text)
            if len(targets) >= 2:
                return {"engine": "rules", "mode": "recolor_multi",
                        "targets": targets,
                        "summary": summary or "多目标换色，分区即时换色"}
        design_hint = _DESIGN_RE.search(text)
        if mode == "repaint" and not multi_color and not design_hint:
            # 单目标纯换色被 LLM 误判为 repaint —— 降级回即时换色引擎（更快更准）
            colors = _colors_english(text)
            if colors:
                return {"engine": "llm", "mode": "recolor", "color": colors[0],
                        "region": _first_region(text),
                        "summary": summary or f"换色为 {colors[0]}"}
        if mode == "repaint" and multi_color and not design_hint:
            # 纯多色换色被误判为 repaint —— 多目标换色引擎更稳（保线稿、无幽影）
            targets = _pair_targets(text)
            if len(targets) >= 2:
                return {"engine": "rules", "mode": "recolor_multi",
                        "targets": targets,
                        "summary": summary or "多目标换色，分区即时换色"}
        if mode == "repaint" and p_prompt and not _has_cjk(p_prompt):
            return {"engine": "llm", "mode": "repaint",
                    "prompt": p_prompt,
                    "strength": _clamp_f(obj.get("strength"), 0.8, 0.95, 0.85),
                    "summary": summary}

    # ---------------- rule fallback ----------------
    n_colors = _count_color_mentions(text)
    design_hint = _DESIGN_RE.search(text)
    if n_colors >= 2 and not design_hint:
        targets = _pair_targets(text)
        if len(targets) >= 2:
            return {"engine": "rules", "mode": "recolor_multi",
                    "targets": targets, "summary": "多目标换色，分区即时换色"}
    if design_hint:
        colors = _colors_english(text)
        hint = (", ".join(colors) + ", ") if colors else ""
        return {"engine": "rules", "mode": "repaint",
                "prompt": "the same character, same pose, same face, "
                          + hint + text + ", everything else unchanged"
                          + _quality_suffix("repaint"),
                "strength": 0.9,
                "summary": "设计类修改，已切换 AI 重绘并补全提示词"}
    return {"engine": "rules", "mode": "recolor", "color": "",
            "region": _first_region(text),
            "summary": "单色换色，使用即时换色引擎"}


def interpret_outpaint(manager, instruction: str) -> dict | None:
    """Rewrite the scene description for canvas extension."""
    text = (instruction or "").strip()
    if not text:
        return None

    prompt = f"""The user extends an image canvas; the model must invent the new surroundings.
User scene request: "{text}"

Return JSON with exactly these keys:
- "prompt": a detailed English diffusion prompt describing the FULL final scene (old area + new area) in one coherent environment: setting, lighting, mood, color palette, perspective. IMPORTANT: the prompt value MUST be in English even when the request is Chinese. End with exactly: ", seamless extension of the original scene, consistent color palette, lighting and perspective, high quality, detailed".
- "summary": one short Chinese sentence (≤30字).

Example:
User scene request: "给我一个正常的卧室" -> {{"prompt":"a cozy normal bedroom at night, warm dim bedside lamp, wooden floor, neat bed with soft bedding, quiet atmosphere, seamless extension of the original scene, consistent color palette, lighting and perspective, high quality, detailed","summary":"扩展出温馨的正常卧室"}}
"""
    raw = _chat(manager, prompt)
    obj = _extract_json(raw or "")
    if obj and _str(obj, "prompt") and not _has_cjk(_str(obj, "prompt")):
        return {"engine": "llm", "prompt": _str(obj, "prompt"),
                "summary": _str(obj, "summary")}

    return {"engine": "rules", "prompt": text + _quality_suffix("scene"),
            "summary": "已按原指令补全场景一致性提示词"}


def interpret_background(manager, instruction: str) -> dict | None:
    """Rewrite the AI-backdrop description."""
    text = (instruction or "").strip()
    if not text:
        return None

    prompt = f"""The user replaces the background behind a cut-out subject with an AI-generated scene.
User background request: "{text}"

Return JSON with exactly these keys:
- "prompt": a detailed English diffusion prompt for a full-frame EMPTY background scene (strictly no people / characters): environment, lighting, color palette, depth. IMPORTANT: the prompt value MUST be in English even when the request is Chinese. End with exactly: ", empty scene, no people, no characters, cohesive soft lighting, professional photography, high quality, detailed".
- "summary": one short Chinese sentence (≤30字).
"""
    raw = _chat(manager, prompt)
    obj = _extract_json(raw or "")
    if obj and _str(obj, "prompt") and not _has_cjk(_str(obj, "prompt")):
        return {"engine": "llm", "prompt": _str(obj, "prompt"),
                "summary": _str(obj, "summary")}

    return {"engine": "rules", "prompt": text + _quality_suffix("backdrop"),
            "summary": "已按原指令补全空场景提示词"}


def interpret_style(manager, instruction: str, presets: list[str]) -> dict | None:
    """Map free text to a style preset (or enriched custom prompt)."""
    text = (instruction or "").strip()
    if not text:
        return None

    prompt = f"""The user restyles an image. Available style presets: {json.dumps(presets)}.
User request: "{text}"

Return JSON with exactly these keys:
- "preset": the single best-matching preset name from the list, or "" if none fits well.
- "custom_prompt": only when no preset fits — a detailed English style prompt (art style, medium, color treatment, quality tags). Otherwise "".
- "strength": float 0.3 to 0.7 (0.4-0.5 keeps the subject clearly recognizable; only go higher if the user asks for a drastic change).
- "summary": one short Chinese sentence (≤30字).
"""
    raw = _chat(manager, prompt)
    obj = _extract_json(raw or "")
    if obj:
        preset = _str(obj, "preset")
        custom = _str(obj, "custom_prompt")
        if custom and _has_cjk(custom):
            custom = ""  # 扩散模型只认英文风格词
        if preset in presets or custom:
            return {"engine": "llm", "preset": preset if preset in presets else "",
                    "custom_prompt": custom,
                    "strength": _clamp_f(obj.get("strength"), 0.3, 0.7, 0.5),
                    "summary": _str(obj, "summary")}

    low = text.lower()
    kw = {"Anime": ("anime", "动漫", "二次元", "动画"),
          "Cyberpunk": ("cyberpunk", "赛博", "neon", "霓虹"),
          "Watercolor": ("watercolor", "水彩"),
          "Oil Painting": ("oil", "油画"),
          "Pixel Art": ("pixel", "像素"),
          "Film Photo": ("film", "胶片", "kodak", "电影感")}
    for name, words in kw.items():
        if name in presets and any(w in low for w in words):
            return {"engine": "rules", "preset": name, "custom_prompt": "",
                    "strength": 0.5, "summary": f"已匹配风格预设：{name}"}
    return {"engine": "rules", "preset": "", "custom_prompt": text,
            "strength": 0.5, "summary": "未匹配预设，按自定义风格提示词处理"}


def llm_status(manager) -> str:
    """Human-readable intent-layer status for the System tab."""
    if not manager.settings.enable_intent_llm:
        return "disabled by AISTUDIO_ENABLE_INTENT=0"
    return f"ready — {manager.settings.intent_model_id} (loads on first use)"
