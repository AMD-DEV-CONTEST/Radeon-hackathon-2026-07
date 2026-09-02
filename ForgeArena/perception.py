"""
ForgeArena Perception Module
Unified interface: text, image → WorldState
"""

import json, time, urllib.request, base64, io, os, re

VL_API_URL = "http://127.0.0.1:15001/vision"

TFT_VL_PROMPT = """You are a TFT game state analyzer. Extract structured game state from this screenshot.

Return ONLY valid JSON (no markdown, no other text):
{
  "stage": "e.g. 2-1, 3-2, 4-5 etc. or null if not visible",
  "level": number or null,
  "gold": number or null,
  "hp": number or null,
  "champions_on_board": "brief description of visible champions",
  "items": "visible item components or completed items",
  "synergies": "visible active synergies",
  "round_type": "creeps/pvp/carousel/neutral or null",
  "notes": "anything else notable about the state"
}

If a field is not visible, set it to null. Be precise with numeric values."""


def call_vl(image_bytes: bytes, prompt: str = TFT_VL_PROMPT, timeout: int = 60) -> dict:
    """Call VL server → raw observation dict"""
    b64 = base64.b64encode(image_bytes).decode()
    payload = json.dumps({"image": b64, "prompt": prompt}).encode()

    try:
        req = urllib.request.Request(VL_API_URL, data=payload,
            headers={"Content-Type": "application/json"})
        t0 = time.time()
        resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        resp["_latency_ms"] = round((time.time() - t0) * 1000)
        return resp
    except Exception as e:
        return {"error": str(e), "result": ""}


def _extract_json(raw: str) -> dict:
    """Extract JSON from model output, handling markdown fences"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def parse_vl_result(vl_resp: dict) -> dict:
    """
    Parse VL server response → structured world_state + observations with confidence.
    Returns:
    {
        "world_state": {...},
        "observations": [{"field":"gold","value":70,"confidence":0.92,"source":"visual"}],
        "extraction_status": "success"|"partial"|"failed",
        "latency_ms": 12345,
        "raw_summary": "brief text summary"
    }
    """
    if vl_resp.get("error"):
        return {
            "world_state": {},
            "observations": [],
            "extraction_status": "failed",
            "error": vl_resp["error"],
            "latency_ms": 0,
            "raw_summary": f"VL error: {vl_resp['error']}"
        }

    raw = vl_resp.get("result", "")
    parsed = _extract_json(raw)
    latency = vl_resp.get("_latency_ms", 0)
    time_ms = vl_resp.get("time_ms", latency)

    if not parsed:
        return {
            "world_state": {"vl_raw": raw[:200]},
            "observations": [],
            "extraction_status": "failed",
            "latency_ms": time_ms,
            "raw_summary": raw[:150] + "..." if len(raw) > 150 else raw
        }

    # Map VL fields → world_state, track confidence
    world_state = {}
    observations = []

    field_names = ["stage", "level", "gold", "hp", "champions_on_board",
                   "items", "synergies", "round_type", "notes"]

    visible_count = 0
    for key in field_names:
        val = parsed.get(key)
        if val is not None and val != "" and val != "null":
            visible_count += 1
            world_state[key] = str(val)
            # Confidence heuristic: numeric fields higher confidence
            conf = 0.85 if isinstance(val, (int, float)) else 0.75
            observations.append({
                "field": key,
                "value": val,
                "confidence": conf,
                "source": "visual"
            })

    if visible_count == 0:
        status = "failed"
    elif visible_count <= 3:
        status = "partial"
    else:
        status = "success"

    return {
        "world_state": world_state,
        "observations": observations,
        "extraction_status": status,
        "latency_ms": time_ms,
        "raw_summary": f"Extracted {visible_count} fields from image ({time_ms}ms)"
    }


def analyze_input(text: str = None, image_bytes: bytes = None) -> dict:
    """
    Unified perception interface.
    Returns a dict compatible with analyze_scene() output + perception metadata.

    Priority: image > text > fallback
    """
    if image_bytes:
        vl_resp = call_vl(image_bytes)
        perception = parse_vl_result(vl_resp)

        # Determine domain
        domain = "game"
        sub_domain = "TFT"
        task = "TFT decision"
        question = text or "Analyze this game state"

        return {
            "domain": domain,
            "sub_domain": sub_domain,
            "task": task,
            "world_state": perception["world_state"],
            "decision_question": question,
            "perception": perception,  # extra metadata
        }

    # No image → caller falls back to text-only
    return None
