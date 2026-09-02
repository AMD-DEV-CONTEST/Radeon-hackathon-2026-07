"""
scripts/determinex_vision.py - Sprint 2: Multimodal Eyes
=====================================================
Vision input adapter for the Determinex local stack.

Architecture:
    image (PNG/JPG/WEBP) -> base64 -> Ollama multimodal model (qwen2.5-vl by
    default) -> structured description string -> consumed by determinex_ask.py
    or, if the call is destined for cloud, run through Project Cloak first.

The local default is `qwen2.5-vl:7b` (~5 GB Q4_K_M) because it fits alongside
the Determinex 1.5B Engineer on a 6 GB VRAM card with model swap. Operators with
larger cards can override via DETERMINEX_VISION_MODEL.

Falls back to Claude API (via the existing DETERMINEX_ANTHROPIC_VISION flag and
ANTHROPIC_API_KEY in .env) when the local model is unavailable. Cloud fallback
ALWAYS goes through Cloak's identifier obfuscation if DETERMINEX_CLOAK=1 - same
sovereignty contract as the SWE-bench agent.

Public API:
    describe_image(path)      -> structured natural-language description
    ocr(path)                 -> extracted text content only
    classify_screenshot(path) -> {kind, key_observations, suggested_action}

Usage from CLI:
    python scripts/determinex_vision.py describe ./docker_desktop.png
    python scripts/determinex_vision.py ocr ./stack_trace.png --json
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("determinex.vision")

# --- Config -------------------------------------------------------------------
_OLLAMA_URL = os.getenv("DETERMINEX_OLLAMA_URL", "http://localhost:11434")
_parsed = urllib.parse.urlparse(_OLLAMA_URL)
if (_parsed.hostname or "") not in {"localhost", "127.0.0.1", "::1"}:
    raise ValueError(f"DETERMINEX_OLLAMA_URL host '{_parsed.hostname}' not allowed (SSRF guard)")

VISION_MODEL = os.getenv("DETERMINEX_VISION_MODEL", "qwen2.5-vl:7b")
VISION_TIMEOUT = int(os.getenv("DETERMINEX_VISION_TIMEOUT", "120"))
VISION_NUM_CTX = int(os.getenv("DETERMINEX_VISION_NUM_CTX", "4096"))
VISION_MAX_TOK = int(os.getenv("DETERMINEX_VISION_MAX_TOKENS", "512"))

CLOUD_FALLBACK = os.getenv("DETERMINEX_ANTHROPIC_VISION", "0") == "1"
CLOAK_ENABLED = os.getenv("DETERMINEX_CLOAK", "0") == "1"

_SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_MAX_IMAGE_MB = int(os.getenv("DETERMINEX_VISION_MAX_MB", "8"))


# --- Helpers ------------------------------------------------------------------


def _read_image_b64(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"image not found: {path}")
    if path.suffix.lower() not in _SUPPORTED_EXTS:
        raise ValueError(
            f"unsupported image extension '{path.suffix}'; expected one of {sorted(_SUPPORTED_EXTS)}"
        )
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > _MAX_IMAGE_MB:
        raise ValueError(f"image {path.name} is {size_mb:.1f} MB > limit {_MAX_IMAGE_MB} MB")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _ollama_vision_chat(image_b64: str, prompt: str, system: str) -> str:
    """POST a multimodal /api/chat request. Returns content or '' on failure."""
    body = json.dumps(
        {
            "model": VISION_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt, "images": [image_b64]},
            ],
            "stream": False,
            "options": {
                "num_ctx": VISION_NUM_CTX,
                "num_predict": VISION_MAX_TOK,
                "temperature": 0.1,
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{_OLLAMA_URL.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=VISION_TIMEOUT) as resp:  # noqa: S310 (localhost only)
            payload = json.loads(resp.read().decode("utf-8"))
        return (payload.get("message", {}).get("content") or "").strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        log.warning("Ollama HTTP %d: %s", e.code, body)
        if "model" in body.lower() and "not" in body.lower():
            log.error(
                "Vision model '%s' not available. Pull it with: "
                "ollama pull %s   (this Sprint 2 deliverable assumes the operator "
                "pulls the model before first use; not auto-pulled to avoid "
                "consuming bandwidth on unattended runs).",
                VISION_MODEL,
                VISION_MODEL,
            )
        return ""
    except urllib.error.URLError as e:
        log.warning("Ollama unreachable: %s", e)
        return ""
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Malformed Ollama response: %s", e)
        return ""


def _cloud_vision_fallback(image_b64: str, prompt: str, ext: str) -> str:
    """Claude API multimodal call. Routes through Cloak's text obfuscation
    for the prompt before sending. The image itself cannot be cloaked, so
    callers MUST decide if image content is safe to send to the cloud."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("DETERMINEX_ANTHROPIC_VISION=1 but ANTHROPIC_API_KEY not set")
        return ""

    cleaned_prompt = prompt
    if CLOAK_ENABLED:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from determinex_cloak import obfuscate_text  # type: ignore

            cleaned_prompt = obfuscate_text(prompt)
        except (ImportError, AttributeError):
            log.warning(
                "DETERMINEX_CLOAK=1 but cloak text-obfuscator not exposed; sending prompt verbatim"
            )

    media_type = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "bmp": "image/bmp",
    }.get(ext.lower().lstrip("."), "image/png")

    body = json.dumps(
        {
            "model": os.getenv("DETERMINEX_ANTHROPIC_VISION_MODEL", "claude-sonnet-4-6"),
            "max_tokens": VISION_MAX_TOK,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": cleaned_prompt},
                    ],
                }
            ],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=VISION_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        blocks = payload.get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        log.error("cloud vision fallback failed: %s", e)
        return ""


# --- Public API ---------------------------------------------------------------

_DESCRIBE_SYSTEM = (
    "You are Determinex's vision adapter. Describe the supplied image factually and "
    "concisely. Surface what an engineer would care about: visible text verbatim, "
    "container names, error codes, line numbers, UI states. Do not speculate "
    "about content that is not actually visible."
)

_DESCRIBE_PROMPT = (
    "Describe this image in 6 lines max. If it shows code or terminal output, "
    "transcribe the visible text. If it shows a UI, name the application and "
    "describe what state it is in. End with one line labelled 'KEY:' summarizing "
    "the single most important observation."
)


def describe_image(path: str | Path) -> str:
    """High-level structured description. Empty string on failure."""
    p = Path(path)
    image_b64 = _read_image_b64(p)
    out = _ollama_vision_chat(image_b64, _DESCRIBE_PROMPT, _DESCRIBE_SYSTEM)
    if out:
        return out
    if CLOUD_FALLBACK:
        log.info("local vision unavailable - falling back to cloud (Cloak=%s)", CLOAK_ENABLED)
        return _cloud_vision_fallback(image_b64, _DESCRIBE_PROMPT, p.suffix)
    return ""


_OCR_SYSTEM = (
    "You are Determinex's OCR adapter. Extract every word of legible text from the "
    "supplied image. Preserve reading order and line breaks. Do NOT paraphrase, "
    "summarize, or add commentary."
)

_OCR_PROMPT = "Extract all visible text from this image exactly as it appears."


def ocr(path: str | Path) -> str:
    """Text-only extraction. Returns extracted text, or '' on failure."""
    p = Path(path)
    image_b64 = _read_image_b64(p)
    out = _ollama_vision_chat(image_b64, _OCR_PROMPT, _OCR_SYSTEM)
    if not out and CLOUD_FALLBACK:
        out = _cloud_vision_fallback(image_b64, _OCR_PROMPT, p.suffix)
    return out


_CLASSIFY_SYSTEM = (
    "You are Determinex's screenshot classifier. Identify the kind of screenshot "
    "(stack_trace | terminal | docker_desktop | code_editor | ui_state | other), "
    "extract 2-4 key observations, and suggest a single concrete next action."
)


def classify_screenshot(path: str | Path) -> dict:
    """Return structured triage of a screenshot. Always returns a dict;
    keys: kind, key_observations (list), suggested_action (str), raw (str).

    On model unavailable, kind='unavailable' and raw carries the diagnosis."""
    p = Path(path)
    image_b64 = _read_image_b64(p)
    prompt = (
        "Output strict JSON only: "
        '{"kind": "<one of: stack_trace|terminal|docker_desktop|code_editor|ui_state|other>", '
        '"key_observations": ["...", "...", "..."], '
        '"suggested_action": "..."}'
    )
    raw = _ollama_vision_chat(image_b64, prompt, _CLASSIFY_SYSTEM)
    if not raw and CLOUD_FALLBACK:
        raw = _cloud_vision_fallback(image_b64, prompt, p.suffix)
    if not raw:
        return {
            "kind": "unavailable",
            "key_observations": [],
            "suggested_action": "pull vision model: ollama pull " + VISION_MODEL,
            "raw": "",
        }
    # Best-effort JSON extraction (models often wrap in fences)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip().strip("`").strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            parsed["raw"] = raw
            return parsed
    except json.JSONDecodeError:
        pass
    return {
        "kind": "other",
        "key_observations": [],
        "suggested_action": "(non-JSON response; see raw)",
        "raw": raw,
    }


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="determinex-vision", description="Sprint 2 - multimodal eyes for Determinex"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_d = sub.add_parser("describe", help="Structured description")
    p_d.add_argument("image", type=Path)
    p_d.add_argument("--json", dest="json_out", action="store_true")

    p_o = sub.add_parser("ocr", help="Text extraction only")
    p_o.add_argument("image", type=Path)
    p_o.add_argument("--json", dest="json_out", action="store_true")

    p_c = sub.add_parser("classify", help="Screenshot triage")
    p_c.add_argument("image", type=Path)

    p_r = sub.add_parser("report", help="Config + availability check (no model call)")

    args = parser.parse_args(argv)

    if args.cmd == "report":
        report = {
            "vision_model": VISION_MODEL,
            "ollama_url": _OLLAMA_URL,
            "cloud_fallback": CLOUD_FALLBACK,
            "cloak_enabled": CLOAK_ENABLED,
            "max_image_mb": _MAX_IMAGE_MB,
            "supported_exts": sorted(_SUPPORTED_EXTS),
        }
        print(json.dumps(report, indent=2))
        return 0

    if args.cmd == "describe":
        result = describe_image(args.image)
        if not result:
            print(
                f"ERROR: vision model '{VISION_MODEL}' unavailable; pull with `ollama pull {VISION_MODEL}`",
                file=sys.stderr,
            )
            return 1
        if args.json_out:
            print(json.dumps({"image": str(args.image), "description": result}, ensure_ascii=False))
        else:
            print(result)
        return 0

    if args.cmd == "ocr":
        result = ocr(args.image)
        if not result:
            print(f"ERROR: vision model '{VISION_MODEL}' unavailable", file=sys.stderr)
            return 1
        if args.json_out:
            print(json.dumps({"image": str(args.image), "text": result}, ensure_ascii=False))
        else:
            print(result)
        return 0

    if args.cmd == "classify":
        result = classify_screenshot(args.image)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("kind") not in {"unavailable"} else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
