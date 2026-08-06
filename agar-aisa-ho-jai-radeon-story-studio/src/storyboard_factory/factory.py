#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def event(name: str, **fields: Any) -> None:
    parts = [f"EVENT={name}"]
    for key, value in fields.items():
        parts.append(f"{key}={str(value).replace(' ', '_')}")
    print(" ".join(parts), flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def post_json(url: str, payload: dict[str, Any], timeout: int = 900) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_json_object(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("model response contains no JSON object")
        text = text[start : end + 1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("model response JSON must be an object")
    return value


def call_model(
    api_base: str,
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
    phase: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    event("QWEN_CALL_START", phase=phase, max_tokens=max_tokens)
    started = time.monotonic()
    response = post_json(f"{api_base}/chat/completions", payload)
    elapsed = time.monotonic() - started
    content = response["choices"][0]["message"]["content"]
    parsed = extract_json_object(content)
    usage = response.get("usage", {})
    metrics = {
        "phase": phase,
        "elapsed_seconds": elapsed,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "completion_tokens_per_second": (
            usage.get("completion_tokens", 0) / elapsed if elapsed > 0 else None
        ),
        "response_id": response.get("id"),
        "served_model": response.get("model"),
    }
    event(
        "QWEN_CALL_COMPLETE",
        phase=phase,
        seconds=f"{elapsed:.3f}",
        completion_tokens=usage.get("completion_tokens"),
        tokens_per_second=(
            f"{metrics['completion_tokens_per_second']:.3f}"
            if metrics["completion_tokens_per_second"] is not None
            else "unknown"
        ),
    )
    return parsed, metrics


def require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def validate_plan(plan: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    require_str(plan.get("title"), "title")
    cast = plan.get("cast")
    scenes = plan.get("scenes")
    if not isinstance(cast, list) or not cast:
        raise ValueError("cast must be a non-empty list")
    if not isinstance(scenes, list) or not (4 <= len(scenes) <= config["maximum_scenes"]):
        raise ValueError("scenes must contain between 4 and maximum_scenes items")

    cast_by_id: dict[str, dict[str, Any]] = {}
    for index, member in enumerate(cast, start=1):
        if not isinstance(member, dict):
            raise ValueError(f"cast[{index}] must be an object")
        member_id = require_str(member.get("id"), f"cast[{index}].id")
        animal = require_str(member.get("animal"), f"cast[{index}].animal").lower()
        if animal not in config["allowed_animals"]:
            raise ValueError(f"unsupported animal: {animal}")
        if member_id in cast_by_id:
            raise ValueError(f"duplicate cast id: {member_id}")
        member["animal"] = animal
        member["name"] = require_str(member.get("name"), f"cast[{index}].name")
        member["personality"] = require_str(
            member.get("personality"), f"cast[{index}].personality"
        )
        cast_by_id[member_id] = member

    seen_scene_ids: set[int] = set()
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ValueError(f"scenes[{index}] must be an object")
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, int) or scene_id <= 0:
            raise ValueError(f"scenes[{index}].scene_id must be a positive integer")
        if scene_id in seen_scene_ids:
            raise ValueError(f"duplicate scene id: {scene_id}")
        seen_scene_ids.add(scene_id)

        duration = scene.get("duration_seconds")
        if not isinstance(duration, int) or not (3 <= duration <= 8):
            raise ValueError(f"scene {scene_id}: duration must be 3-8 seconds")

        animal_id = require_str(scene.get("animal_id"), f"scene {scene_id}.animal_id")
        if animal_id not in cast_by_id and animal_id != "group":
            raise ValueError(f"scene {scene_id}: unknown animal_id {animal_id}")

        for field, allowed_key in (
            ("background", "allowed_backgrounds"),
            ("emotion", "allowed_emotions"),
            ("action", "allowed_actions"),
        ):
            value = require_str(scene.get(field), f"scene {scene_id}.{field}").lower()
            if value not in config[allowed_key]:
                raise ValueError(f"scene {scene_id}: unsupported {field} {value}")
            scene[field] = value

        scene["narration"] = require_str(
            scene.get("narration"), f"scene {scene_id}.narration"
        )
        scene["visual_direction"] = require_str(
            scene.get("visual_direction"), f"scene {scene_id}.visual_direction"
        )
        scene["child_safe_reason"] = require_str(
            scene.get("child_safe_reason"), f"scene {scene_id}.child_safe_reason"
        )

    plan["cast"] = cast
    plan["scenes"] = sorted(scenes, key=lambda item: item["scene_id"])
    return plan


def ensure_group_wave_final_scene(plan: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    scenes = plan["scenes"]
    if scenes and scenes[-1].get("animal_id") == "group" and scenes[-1].get("action") == "wave":
        return plan

    next_scene_id = scenes[-1]["scene_id"] + 1 if scenes else 1
    if len(scenes) >= config["maximum_scenes"]:
        last = scenes[-1]
        last.update(
            {
                "animal_id": "group",
                "background": "night_sky",
                "emotion": "happy",
                "action": "wave",
                "narration": "All the animal friends wave together and say, Good night!",
                "visual_direction": "Show all the animal friends together in one wide shot, smiling and waving to the audience under a calm night sky.",
                "child_safe_reason": "The friends are together, smiling, and peacefully saying good night.",
            }
        )
    else:
        scenes.append(
            {
                "scene_id": next_scene_id,
                "duration_seconds": 4,
                "animal_id": "group",
                "narration": "All the animal friends wave together and say, Good night!",
                "background": "night_sky",
                "emotion": "happy",
                "action": "wave",
                "visual_direction": "Show all the animal friends together in one wide shot, smiling and waving to the audience under a calm night sky.",
                "child_safe_reason": "The friends are together, smiling, and peacefully saying good night.",
                "future_image_prompt": "A gentle group shot of friendly baby animals waving good night under a calm moonlit sky.",
            }
        )
    plan["scenes"] = sorted(scenes, key=lambda item: item["scene_id"])
    return plan



def validate_review(
    review: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    if review.get("overall_status") != "pass":
        raise ValueError(f"safety review did not pass: {review}")
    items = review.get("scene_reviews")
    if not isinstance(items, list) or len(items) != len(plan["scenes"]):
        raise ValueError("scene_reviews count does not match scene count")
    expected = {scene["scene_id"] for scene in plan["scenes"]}
    seen: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("scene review must be an object")
        scene_id = item.get("scene_id")
        if scene_id not in expected:
            raise ValueError(f"review contains unknown scene id: {scene_id}")
        if item.get("status") != "pass":
            raise ValueError(f"scene {scene_id} did not pass review")
        require_str(item.get("reason"), f"review scene {scene_id}.reason")
        seen.add(scene_id)
    if seen != expected:
        raise ValueError("not every scene was reviewed")
    return review


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, fnt: ImageFont.ImageFont) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        bbox = draw.textbbox((0, 0), trial, font=fnt)
        if bbox[2] - bbox[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


PALETTES = {
    "elephant": ("#9AA6B2", "#F8B4C7"),
    "lion": ("#E7A84B", "#9A5A22"),
    "rabbit": ("#EEE8E2", "#F6AFC3"),
    "giraffe": ("#EACB63", "#9B6A2B"),
    "duck": ("#F6D94C", "#E8912D"),
    "turtle": ("#78A96B", "#426B45"),
}


def ellipse(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str = "#333333", width: int = 5) -> None:
    draw.ellipse(box, fill=fill, outline=outline, width=width)


def animal_elephant(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float) -> None:
    body, accent = PALETTES["elephant"]
    ellipse(draw, (cx - 145, cy - 60, cx + 80, cy + 90), body)
    ellipse(draw, (cx + 45, cy - 145, cx + 185, cy - 15), body)
    ellipse(draw, (cx + 18, cy - 130, cx + 100, cy - 45), accent)
    for x in (cx - 110, cx - 45, cx + 10, cx + 60):
        draw.rounded_rectangle((x, cy + 55, x + 34, cy + 170), radius=14, fill=body, outline="#333333", width=5)
    draw.line((cx + 165, cy - 60, cx + 185, cy + 60), fill=body, width=32)
    ellipse(draw, (cx + 173, cy + 45, cx + 195, cy + 70), body, width=3)
    ellipse(draw, (cx + 135, cy - 100, cx + 153, cy - 82), "#222222", width=2)
    draw.arc((cx + 112, cy - 82, cx + 160, cy - 38), 15, 150, fill="#333333", width=4)


def animal_lion(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float) -> None:
    body, mane = PALETTES["lion"]
    ellipse(draw, (cx - 105, cy + 5, cx + 95, cy + 140), body)
    ellipse(draw, (cx - 110, cy - 135, cx + 110, cy + 85), mane)
    ellipse(draw, (cx - 72, cy - 95, cx + 72, cy + 50), body)
    ellipse(draw, (cx - 92, cy - 118, cx - 38, cy - 62), body)
    ellipse(draw, (cx + 38, cy - 118, cx + 92, cy - 62), body)
    for x in (cx - 72, cx - 18, cx + 28, cx + 70):
        draw.rounded_rectangle((x, cy + 105, x + 30, cy + 190), radius=13, fill=body, outline="#333333", width=4)
    draw.arc((cx + 60, cy + 55, cx + 185, cy + 155), 170, 355, fill=mane, width=13)
    ellipse(draw, (cx + 160, cy + 118, cx + 190, cy + 150), mane, width=3)
    for x in (cx - 32, cx + 18):
        ellipse(draw, (x, cy - 40, x + 17, cy - 23), "#222222", width=2)
    ellipse(draw, (cx - 10, cy - 5, cx + 12, cy + 15), "#6B3E22", width=2)
    draw.arc((cx - 38, cy + 2, cx + 40, cy + 58), 12, 168, fill="#333333", width=5)


def animal_rabbit(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float) -> None:
    body, accent = PALETTES["rabbit"]
    ellipse(draw, (cx - 82, cy + 5, cx + 90, cy + 155), body)
    ellipse(draw, (cx - 68, cy - 92, cx + 68, cy + 48), body)
    ellipse(draw, (cx - 63, cy - 220, cx - 8, cy - 55), body)
    ellipse(draw, (cx + 8, cy - 220, cx + 63, cy - 55), body)
    ellipse(draw, (cx - 46, cy - 198, cx - 24, cy - 80), accent, width=3)
    ellipse(draw, (cx + 24, cy - 198, cx + 46, cy - 80), accent, width=3)
    ellipse(draw, (cx - 105, cy + 120, cx - 22, cy + 172), body)
    ellipse(draw, (cx + 22, cy + 120, cx + 110, cy + 172), body)
    ellipse(draw, (cx - 118, cy + 45, cx - 72, cy + 90), body)
    for x in (cx - 33, cx + 18):
        ellipse(draw, (x, cy - 38, x + 17, cy - 21), "#222222", width=2)
    ellipse(draw, (cx - 10, cy - 4, cx + 12, cy + 16), accent, width=2)
    draw.arc((cx - 30, cy + 8, cx + 30, cy + 50), 15, 165, fill="#333333", width=4)


def animal_giraffe(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float) -> None:
    body, spot = PALETTES["giraffe"]
    ellipse(draw, (cx - 112, cy + 40, cx + 80, cy + 150), body)
    draw.rounded_rectangle((cx + 18, cy - 135, cx + 76, cy + 95), radius=24, fill=body, outline="#333333", width=5)
    ellipse(draw, (cx - 30, cy - 205, cx + 112, cy - 105), body)
    for x in (cx - 82, cx - 32, cx + 20, cx + 58):
        draw.rounded_rectangle((x, cy + 120, x + 25, cy + 220), radius=10, fill=body, outline="#333333", width=4)
    for box in [
        (cx - 65, cy + 62, cx - 25, cy + 96),
        (cx + 3, cy + 80, cx + 39, cy + 115),
        (cx + 30, cy - 95, cx + 62, cy - 55),
        (cx + 28, cy - 22, cx + 62, cy + 18),
        (cx - 2, cy - 175, cx + 30, cy - 143),
        (cx + 52, cy - 170, cx + 84, cy - 138),
    ]:
        ellipse(draw, box, spot, outline=spot, width=1)
    draw.line((cx - 5, cy - 192, cx - 10, cy - 235), fill="#333333", width=7)
    draw.line((cx + 78, cy - 185, cx + 88, cy - 228), fill="#333333", width=7)
    ellipse(draw, (cx - 20, cy - 246, cx + 2, cy - 224), spot, width=2)
    ellipse(draw, (cx + 78, cy - 239, cx + 100, cy - 217), spot, width=2)
    ellipse(draw, (cx + 10, cy - 167, cx + 27, cy - 150), "#222222", width=2)
    ellipse(draw, (cx + 58, cy - 167, cx + 75, cy - 150), "#222222", width=2)
    draw.arc((cx + 20, cy - 153, cx + 78, cy - 118), 15, 165, fill="#333333", width=4)


def animal_duck(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float) -> None:
    body, beak = PALETTES["duck"]
    ellipse(draw, (cx - 130, cy - 35, cx + 95, cy + 110), body)
    ellipse(draw, (cx + 20, cy - 130, cx + 142, cy - 12), body)
    draw.polygon([(cx + 128, cy - 78), (cx + 205, cy - 48), (cx + 128, cy - 18)], fill=beak, outline="#333333")
    ellipse(draw, (cx + 88, cy - 92, cx + 105, cy - 75), "#222222", width=2)
    ellipse(draw, (cx - 55, cy + 2, cx + 40, cy + 75), "#E6BC36", outline="#D1A52F", width=5)
    draw.line((cx - 28, cy + 105, cx - 28, cy + 155), fill=beak, width=8)
    draw.line((cx + 35, cy + 100, cx + 35, cy + 150), fill=beak, width=8)
    draw.line((cx - 55, cy + 155, cx + 2, cy + 155), fill=beak, width=8)
    draw.line((cx + 8, cy + 150, cx + 65, cy + 150), fill=beak, width=8)


def animal_turtle(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float) -> None:
    shell, skin = PALETTES["turtle"]
    ellipse(draw, (cx - 145, cy - 70, cx + 105, cy + 105), shell)
    ellipse(draw, (cx + 78, cy - 28, cx + 170, cy + 55), skin)
    for x, y in ((cx - 112, cy + 72), (cx + 32, cy + 72), (cx - 112, cy - 70), (cx + 15, cy - 70)):
        ellipse(draw, (x, y, x + 58, y + 45), skin)
    for x, y in ((cx - 72, cy - 35), (cx + 2, cy - 35), (cx - 36, cy + 25)):
        ellipse(draw, (x, y, x + 62, y + 50), "#5E8C59", outline="#5E8C59", width=1)
    ellipse(draw, (cx + 126, cy - 3, cx + 143, cy + 14), "#222222", width=2)
    draw.arc((cx + 112, cy + 7, cx + 154, cy + 36), 12, 165, fill="#333333", width=3)


ANIMAL_DRAWERS = {
    "elephant": animal_elephant,
    "lion": animal_lion,
    "rabbit": animal_rabbit,
    "giraffe": animal_giraffe,
    "duck": animal_duck,
    "turtle": animal_turtle,
}


MOTION_FRAME_COUNT = 8


def draw_motion_lines(draw: ImageDraw.ImageDraw, x: int, y: int, direction: str = "right") -> None:
    sign = 1 if direction == "right" else -1
    for offset in (0, 18, 36):
        draw.arc((x + sign * offset - 18, y - 16, x + sign * offset + 18, y + 16), 220 if sign > 0 else -40, 320 if sign > 0 else 60, fill="#444444", width=4)


def draw_action_effects(draw: ImageDraw.ImageDraw, scene: dict[str, Any], cx: int, cy: int, width: int, height: int, phase: int, total_phases: int) -> None:
    action = scene["action"]
    wave = math.sin((phase / max(total_phases, 1)) * math.tau)
    if action == "wake":
        draw.ellipse((70, 55, 145, 130), fill="#FFD86B", outline="#E0A93A", width=4)
        for i in range(8):
            angle = (math.tau / 8) * i
            x1 = 107 + int(math.cos(angle) * 48)
            y1 = 92 + int(math.sin(angle) * 48)
            x2 = 107 + int(math.cos(angle) * 68)
            y2 = 92 + int(math.sin(angle) * 68)
            draw.line((x1, y1, x2, y2), fill="#F3B53F", width=4)
    elif action == "stretch":
        for dx in (-28, 28):
            draw.line((cx + dx, cy - 150, cx + dx * 2, cy - 205), fill="#7E7E7E", width=4)
        draw.line(
            (cx + 185, cy - 60, cx + 215, cy - 145, cx + 170, cy - 218),
            fill=PALETTES["elephant"][0],
            width=34,
            joint="curve",
        )
        ellipse(draw, (cx + 153, cy - 232, cx + 188, cy - 197), PALETTES["elephant"][0], width=3)
    elif action == "smile":
        draw.rounded_rectangle((width - 260, 60, width - 90, 138), radius=18, fill="#FFFFFF", outline="#555555", width=4)
        draw.text((width - 235, 86), "Hello!", font=font(24, bold=True), fill="#333333")
    elif action == "hop":
        for dx in (-45, -15, 15):
            draw.arc((cx + dx, cy + 115, cx + dx + 42, cy + 142), 200, 340, fill="#666666", width=4)
    elif action == "look":
        draw.ellipse((width - 165, 70, width - 95, 140), outline="#5C815C", width=5)
        draw.line((width - 125, 140, width - 170, 200), fill="#5C815C", width=5)
    elif action == "splash":
        for dx in (-75, -40, -5, 30, 65):
            top = cy + 90 - abs(dx) // 4 - int((wave + 1) * 6)
            draw.arc((cx + dx, top, cx + dx + 18, top + 28), 0, 180, fill="#3D9FC9", width=4)
    elif action == "walk":
        for step in range(4):
            px = cx - 110 + step * 42
            py = cy + 115 + (step % 2) * 10
            draw.ellipse((px, py, px + 18, py + 10), outline="#7C6B4D", width=3)
    elif action == "wave":
        draw_motion_lines(draw, cx + 110, cy - 95, "right")
    elif action == "sleep":
        draw.text((width - 170, 70), "Z z z", font=font(30, bold=True), fill="#F2F0FF")


def scene_subject_position(scene: dict[str, Any], phase: int, total_phases: int, width: int, height: int) -> tuple[int, int]:
    progress = phase / max(total_phases - 1, 1)
    action = scene["action"]
    base_x = int(width * 0.68)
    base_y = int(height * 0.56)
    if action == "hop":
        return int(base_x - 60 + progress * 120), int(base_y - math.sin(progress * math.pi) * 42)
    if action == "walk":
        return int(base_x - 90 + progress * 140), base_y
    if action == "stretch":
        return base_x, int(base_y - abs(math.sin(progress * math.pi)) * 16)
    if action == "splash":
        return base_x + int(math.sin(progress * math.tau) * 16), base_y + int(abs(math.sin(progress * math.pi)) * 8)
    if action == "wake":
        return base_x, base_y + int(math.sin(progress * math.tau) * 5)
    if action == "smile":
        return base_x, base_y + int(math.sin(progress * math.tau) * 4)
    if action == "look":
        return base_x + int(math.sin(progress * math.tau) * 18), base_y - int(math.sin(progress * math.tau) * 8)
    if action == "wave":
        return base_x + int(math.sin(progress * math.tau) * 10), base_y
    if action == "sleep":
        return base_x - 20, base_y + 10 + int(math.sin(progress * math.tau) * 4)
    return base_x, base_y


def paste_scaled_animal(
    base: Image.Image,
    animal: str,
    center_x: int,
    bottom_y: int,
    max_width: int = 145,
    max_height: int = 175,
) -> None:
    sprite_canvas = Image.new("RGBA", (520, 520), (0, 0, 0, 0))
    sprite_draw = ImageDraw.Draw(sprite_canvas)
    ANIMAL_DRAWERS[animal](sprite_draw, 260, 260, 1.0)
    bbox = sprite_canvas.getbbox()
    if bbox is None:
        raise ValueError(f"empty sprite for {animal}")
    sprite = sprite_canvas.crop(bbox)
    sprite.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    base.alpha_composite(
        sprite,
        (center_x - sprite.width // 2, bottom_y - sprite.height),
    )


def draw_elephant_pose(draw: ImageDraw.ImageDraw, cx: int, cy: int, phase: int, total_phases: int) -> None:
    body, accent = PALETTES["elephant"]
    progress = phase / max(total_phases - 1, 1)
    lift = math.sin(progress * math.pi)
    ellipse(draw, (cx - 145, cy - 60, cx + 80, cy + 90), body)
    ellipse(draw, (cx + 45, cy - 145, cx + 185, cy - 15), body)
    ellipse(draw, (cx + 18, cy - 130, cx + 100, cy - 45), accent)
    for x in (cx - 110, cx - 45, cx + 10, cx + 60):
        draw.rounded_rectangle((x, cy + 55, x + 34, cy + 170), radius=14, fill=body, outline="#333333", width=5)
    tip_x = cx + 175 - int(lift * 45)
    tip_y = cy + 60 - int(lift * 230)
    draw.line((cx + 165, cy - 58, cx + 198, cy - 15, tip_x, tip_y), fill=body, width=32, joint="curve")
    ellipse(draw, (tip_x - 13, tip_y - 13, tip_x + 16, tip_y + 16), body, width=3)
    ellipse(draw, (cx + 135, cy - 100, cx + 153, cy - 82), "#222222", width=2)
    draw.arc((cx + 112, cy - 82, cx + 160, cy - 38), 15, 150, fill="#333333", width=4)


def draw_lion_pose(draw: ImageDraw.ImageDraw, cx: int, cy: int, phase: int, total_phases: int) -> None:
    animal_lion(draw, cx, cy, 1.0)
    progress = phase / max(total_phases - 1, 1)
    paw_y = cy + 55 - int((math.sin(progress * math.tau) + 1) * 14)
    body = PALETTES["lion"][0]
    draw.line((cx + 55, cy + 65, cx + 110, paw_y), fill=body, width=22)
    ellipse(draw, (cx + 96, paw_y - 14, cx + 125, paw_y + 15), body, width=3)


def draw_giraffe_pose(draw: ImageDraw.ImageDraw, cx: int, cy: int, phase: int, total_phases: int) -> None:
    progress = phase / max(total_phases - 1, 1)
    head_shift = int(math.sin(progress * math.tau) * 22)
    body, spot = PALETTES["giraffe"]
    ellipse(draw, (cx - 112, cy + 40, cx + 80, cy + 150), body)
    draw.rounded_rectangle((cx + 18, cy - 135, cx + 76, cy + 95), radius=24, fill=body, outline="#333333", width=5)
    ellipse(draw, (cx - 30 + head_shift, cy - 205, cx + 112 + head_shift, cy - 105), body)
    for x in (cx - 82, cx - 32, cx + 20, cx + 58):
        draw.rounded_rectangle((x, cy + 120, x + 25, cy + 220), radius=10, fill=body, outline="#333333", width=4)
    for box in [
        (cx - 65, cy + 62, cx - 25, cy + 96),
        (cx + 3, cy + 80, cx + 39, cy + 115),
        (cx + 30, cy - 95, cx + 62, cy - 55),
        (cx + 28, cy - 22, cx + 62, cy + 18),
    ]:
        ellipse(draw, box, spot, outline=spot, width=1)
    ellipse(draw, (cx + 10 + head_shift, cy - 167, cx + 27 + head_shift, cy - 150), "#222222", width=2)
    ellipse(draw, (cx + 58 + head_shift, cy - 167, cx + 75 + head_shift, cy - 150), "#222222", width=2)
    draw.arc((cx + 20 + head_shift, cy - 153, cx + 78 + head_shift, cy - 118), 15, 165, fill="#333333", width=4)
    draw.line((cx + 75, cy - 118, cx + 76 + head_shift, cy - 142), fill=body, width=48)
    draw.line((cx + 155, cy - 145, cx + 215, cy - 185), fill="#4F824B", width=10)
    for dx, dy in ((0, 0), (22, -15), (43, 4)):
        ellipse(draw, (cx + 190 + dx, cy - 210 + dy, cx + 230 + dx, cy - 178 + dy), "#67A85D", outline="#355D34", width=3)


def draw_group_wave_limb(draw: ImageDraw.ImageDraw, animal: str, px: int, py: int, phase: int, total_phases: int) -> None:
    progress = phase / max(total_phases - 1, 1)
    swing = math.sin(progress * math.tau)
    body = PALETTES[animal][0]
    if animal == "elephant":
        anchor = (px + 35, py - 102)
        tip = (px + 68 + int(swing * 18), py - 150 - int(abs(swing) * 12))
        draw.line((anchor[0], anchor[1], tip[0], tip[1]), fill=body, width=11)
        ellipse(draw, (tip[0]-6, tip[1]-6, tip[0]+7, tip[1]+7), body, width=2)
    else:
        anchors = {
            "lion": (px + 24, py - 72),
            "rabbit": (px + 20, py - 65),
            "giraffe": (px + 18, py - 90),
            "duck": (px + 18, py - 52),
            "turtle": (px + 18, py - 43),
        }
        ax, ay = anchors.get(animal, (px + 18, py - 60))
        tx = ax + 28 + int(swing * 20)
        ty = ay - 34 - int(abs(swing) * 10)
        draw.line((ax, ay, tx, ty), fill=body, width=10)
        ellipse(draw, (tx - 7, ty - 7, tx + 8, ty + 8), body, width=2)


def action_landmark(scene: dict[str, Any], phase: int, total_phases: int) -> tuple[int, ...]:
    progress = phase / max(total_phases - 1, 1)
    action = scene["action"]
    if action in {"wake", "stretch"}:
        return (int(math.sin(progress * math.pi) * 230),)
    if action == "smile":
        return (int(math.sin(progress * math.tau) * 28),)
    if action == "hop":
        return (int(progress * 120), int(math.sin(progress * math.pi) * 42))
    if action == "look":
        return (int(math.sin(progress * math.tau) * 22),)
    if action == "splash":
        return (int(math.sin(progress * math.tau) * 16), int(abs(math.sin(progress * math.pi)) * 8))
    if action == "walk":
        return (int(progress * 140),)
    if action == "wave":
        return (int(math.sin(progress * math.tau) * 20),)
    return (phase,)


def render_scene_frame(
    scene: dict[str, Any],
    cast_by_id: dict[str, dict[str, Any]],
    output: Path,
    width: int,
    height: int,
    phase: int,
    total_phases: int,
    show_review_panel: bool = True,
) -> None:
    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw_background(draw, scene["background"], width, height)

    if scene["animal_id"] == "group":
        members = list(cast_by_id.values())
        positions = [(95, 515), (260, 510), (425, 518), (590, 508), (755, 518), (915, 515)]
        for idx, member in enumerate(members[: len(positions)]):
            px, py = positions[idx]
            wobble = int(math.sin((phase / max(total_phases, 1)) * math.tau + idx) * 5)
            paste_scaled_animal(image, member["animal"], px, py + wobble, max_width=150, max_height=190)
            draw_group_wave_limb(draw, member["animal"], px, py + wobble, phase, total_phases)
    else:
        member = cast_by_id[scene["animal_id"]]
        cx, cy = scene_subject_position(scene, phase, total_phases, width, height)
        animal = member["animal"]
        if animal == "elephant" and scene["action"] in {"wake", "stretch"}:
            draw_elephant_pose(draw, cx, cy, phase, total_phases)
        elif animal == "lion" and scene["action"] == "smile":
            draw_lion_pose(draw, cx, cy, phase, total_phases)
        elif animal == "giraffe" and scene["action"] == "look":
            draw_giraffe_pose(draw, cx, cy, phase, total_phases)
        else:
            ANIMAL_DRAWERS[animal](draw, cx, cy, 1.0)
        draw_action_effects(draw, scene, cx, cy, width, height, phase, total_phases)

    if show_review_panel:
        panel = (35, 35, int(width * 0.47), int(height * 0.54))
        draw.rounded_rectangle(panel, radius=28, fill="#FFFDF6", outline="#554F46", width=5)

        title_font = font(34, bold=True)
        body_font = font(25)
        small_font = font(19)
        scene_name = "All Friends" if scene["animal_id"] == "group" else cast_by_id[scene["animal_id"]]["name"]
        draw.text((65, 60), f"Scene {scene['scene_id']}: {scene_name}", font=title_font, fill="#2F2A24")

        y = 112
        for line in wrap_text(draw, scene["narration"], panel[2] - panel[0] - 60, body_font):
            draw.text((65, y), line, font=body_font, fill="#2F2A24")
            y += 34

        y += 14
        tags = f"{scene['emotion'].title()} • {scene['action'].title()} • {scene['background'].replace('_', ' ').title()}"
        for line in wrap_text(draw, tags, panel[2] - panel[0] - 60, small_font):
            draw.text((65, y), line, font=small_font, fill="#4F6F61")
            y += 27

        draw.text((40, height - 40), "AAHJ Animal Storyboard Factory v2.1 • Radeon/Qwen planned", font=font(16), fill="#3A3A3A")
    image.convert("RGB").save(output, format="PNG", optimize=True)


def draw_background(draw: ImageDraw.ImageDraw, background: str, width: int, height: int) -> None:
    draw.rectangle((0, 0, width, height), fill="#CFEFFF")
    ground_color = {
        "bedroom": "#F4D7B2",
        "garden": "#A9D987",
        "savannah": "#E3C66F",
        "pond": "#8FD3C7",
        "forest": "#8FC07A",
        "night_sky": "#4B5A87",
    }.get(background, "#A9D987")
    if background == "night_sky":
        draw.rectangle((0, 0, width, height), fill="#31456E")
        for x, y in ((90, 80), (210, 130), (410, 65), (690, 120), (860, 70)):
            draw.ellipse((x, y, x+9, y+9), fill="#FFF4B5")
        draw.ellipse((820, 45, 900, 125), fill="#FFF4B5")
    draw.rectangle((0, int(height * 0.62), width, height), fill=ground_color)
    if background in {"garden", "forest", "savannah"}:
        for x in (110, 830):
            draw.rectangle((x, 220, x+28, 390), fill="#7B5435")
            draw.ellipse((x-70, 130, x+100, 280), fill="#67A85D", outline="#355D34", width=5)
    if background == "pond":
        draw.ellipse((80, 340, 920, 620), fill="#6DBFD3", outline="#3E8EA4", width=6)
    if background == "bedroom":
        draw.rounded_rectangle((80, 275, 430, 485), radius=25, fill="#F6C6D2", outline="#77545B", width=6)
        draw.rectangle((95, 290, 240, 350), fill="#FFF7EA", outline="#77545B", width=4)


def render_scene(
    scene: dict[str, Any],
    cast_by_id: dict[str, dict[str, Any]],
    output: Path,
    width: int,
    height: int,
) -> None:
    render_scene_frame(scene, cast_by_id, output, width, height, MOTION_FRAME_COUNT // 2, MOTION_FRAME_COUNT)



def make_contact_sheet(scene_paths: list[Path], output: Path) -> None:
    thumb_w, thumb_h = 512, 288
    margin = 24
    columns = 2
    rows = math.ceil(len(scene_paths) / columns)
    sheet = Image.new(
        "RGB",
        (columns * thumb_w + (columns + 1) * margin, rows * thumb_h + (rows + 1) * margin),
        "#F5F1E8",
    )
    for index, path in enumerate(scene_paths):
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb_w, thumb_h))
        x = margin + (index % columns) * (thumb_w + margin)
        y = margin + (index // columns) * (thumb_h + margin)
        sheet.paste(image, (x, y))
    sheet.save(output, format="PNG", optimize=True)


def write_html(
    plan: dict[str, Any],
    review: dict[str, Any],
    metrics: list[dict[str, Any]],
    scene_paths: list[Path],
    output: Path,
) -> None:
    cards = []
    for scene, path in zip(plan["scenes"], scene_paths):
        cards.append(
            f"""
            <article>
              <img src="{html.escape(path.name)}" alt="Scene {scene['scene_id']}">
              <h2>Scene {scene['scene_id']}</h2>
              <p><strong>Narration:</strong> {html.escape(scene['narration'])}</p>
              <p><strong>Direction:</strong> {html.escape(scene['visual_direction'])}</p>
              <p><strong>Safety:</strong> {html.escape(scene['child_safe_reason'])}</p>
            </article>
            """
        )
    output.write_text(
        f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(plan['title'])}</title>
<style>
body {{ font-family: sans-serif; max-width: 1200px; margin: auto; background: #f7f2e8; color: #2e2924; }}
header {{ padding: 2rem 1rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 1rem; }}
article {{ background: white; padding: 1rem; border-radius: 18px; box-shadow: 0 2px 10px #0002; }}
img {{ width: 100%; border-radius: 12px; }}
pre {{ white-space: pre-wrap; background: #fff; padding: 1rem; border-radius: 12px; }}
</style>
</head>
<body>
<header>
<h1>{html.escape(plan['title'])}</h1>
<p>Planned and reviewed by the locally hosted Qwen3-Coder 30B model on AMD Radeon.</p>
</header>
<section class="grid">{''.join(cards)}</section>
<h2>Qwen performance</h2>
<pre>{html.escape(json.dumps(metrics, indent=2))}</pre>
<h2>Safety review</h2>
<pre>{html.escape(json.dumps(review, indent=2))}</pre>
</body>
</html>
"""
    )


def make_animatic(plan: dict[str, Any], cast_by_id: dict[str, dict[str, Any]], output: Path, width: int, height: int) -> bool:
    if subprocess.run(["bash", "-lc", "command -v ffmpeg >/dev/null"], capture_output=True).returncode != 0:
        return False
    frame_dir = output.parent / "animatic-frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    fps = 8
    frame_index = 0
    motion_evidence: list[dict[str, Any]] = []
    for scene in plan["scenes"]:
        total_phases = max(scene["duration_seconds"] * fps, MOTION_FRAME_COUNT)
        scene_hashes: set[str] = set()
        landmark_values: set[tuple[int, ...]] = set()
        for phase in range(total_phases):
            frame_path = frame_dir / f"frame-{frame_index:05d}.png"
            render_scene_frame(
                scene,
                cast_by_id,
                frame_path,
                width,
                height,
                phase,
                total_phases,
                show_review_panel=False,
            )
            scene_hashes.add(sha256_file(frame_path))
            landmark_values.add(action_landmark(scene, phase, total_phases))
            frame_index += 1
        motion_evidence.append(
            {
                "scene_id": scene["scene_id"],
                "action": scene["action"],
                "frame_count": total_phases,
                "unique_frame_hashes": len(scene_hashes),
                "motion_present": len(scene_hashes) >= 2,
                "action_landmark_states": len(landmark_values),
                "semantic_motion_present": len(landmark_values) >= 4,
            }
        )
    (output.parent / "motion-evidence.json").write_text(
        json.dumps(motion_evidence, indent=2) + "\n"
    )
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-framerate", str(fps), "-i", str(frame_dir / "frame-%05d.png"),
        "-vf", "format=yuv420p",
        "-c:v", "libx264", "-movflags", "+faststart", str(output),
    ]
    subprocess.run(command, check=True)
    return True


def write_checksums(output: Path) -> None:
    lines: list[str] = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(f"{sha256_file(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS").write_text("\n".join(lines) + "\n")



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    transcript = args.transcript.read_text().strip()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    system_plan = """You are the planning engine for a child-safe animal storyboard factory.
Return one JSON object only. No Markdown and no commentary.
Use only the animals, backgrounds, emotions, and actions supplied by the user.
Preserve the transcript's order and meaning. Keep language simple for children aged 2-3.
Prefer 7 scenes when the transcript naturally supports it, and use a final group-wave good-night scene when the story ends with all friends together.
Every scene must be gentle, visually clear, and free of danger, fear, violence, injury,
weapons, chasing, falling, fire, traffic, or unsupervised risky behavior."""

    plan_request = {
        "task": "Convert the transcript into a reusable illustrated storyboard plan.",
        "constraints": config,
        "required_json_shape": {
            "title": "string",
            "visual_style": "string",
            "cast": [
                {
                    "id": "short stable id",
                    "animal": "allowed animal",
                    "name": "name from transcript",
                    "personality": "short gentle description",
                }
            ],
            "scenes": [
                {
                    "scene_id": 1,
                    "duration_seconds": 4,
                    "animal_id": "cast id",
                    "narration": "one short sentence",
                    "background": "allowed background",
                    "emotion": "allowed emotion",
                    "action": "allowed action",
                    "visual_direction": "specific full-body composition",
                    "child_safe_reason": "why the visual is safe",
                    "future_image_prompt": "render-ready prompt for an external image provider",
                }
            ],
        },
        "transcript": transcript,
    }

    plan, plan_metrics = call_model(
        config["api_base"],
        config["served_model"],
        system_plan,
        json.dumps(plan_request, ensure_ascii=False),
        max_tokens=3000,
        temperature=0.15,
        phase="storyboard_plan",
    )
    plan = validate_plan(plan, config)
    plan = ensure_group_wave_final_scene(plan, config)
    (output / "storyboard-plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    )
    event("PLAN_VALIDATED", scenes=len(plan["scenes"]), cast=len(plan["cast"]))

    system_review = """You are an independent child-safety and visual-continuity reviewer.
Return one JSON object only. No Markdown. Review every scene independently.
The intended audience is age 2-3. Fail any frightening, risky, confusing, violent,
overstimulating, anatomically impossible, or continuity-breaking visual."""

    review_request = {
        "task": "Review this storyboard plan.",
        "required_json_shape": {
            "overall_status": "pass or fail",
            "scene_reviews": [
                {"scene_id": 1, "status": "pass or fail", "reason": "short reason"}
            ],
            "continuity_summary": "short string",
            "safety_summary": "short string",
        },
        "plan": plan,
    }
    review, review_metrics = call_model(
        config["api_base"],
        config["served_model"],
        system_review,
        json.dumps(review_request, ensure_ascii=False),
        max_tokens=1800,
        temperature=0.0,
        phase="safety_review",
    )
    review = validate_review(review, plan)
    (output / "safety-review.json").write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n"
    )
    event("SAFETY_REVIEW_VALIDATED", overall_status=review["overall_status"])

    cast_by_id = {member["id"]: member for member in plan["cast"]}
    scene_paths: list[Path] = []
    width = int(config["canvas"]["width"])
    height = int(config["canvas"]["height"])
    for scene in plan["scenes"]:
        animal_name = "group" if scene["animal_id"] == "group" else cast_by_id[scene["animal_id"]]["animal"]
        path = output / f"scene-{scene['scene_id']:02d}.png"
        event("FRAME_RENDER_START", scene=scene["scene_id"], animal=animal_name)
        render_scene(scene, cast_by_id, path, width, height)
        scene_paths.append(path)
        event(
            "FRAME_RENDER_COMPLETE",
            scene=scene["scene_id"],
            bytes=path.stat().st_size,
            sha256=sha256_file(path)[:16],
        )

    contact_sheet = output / "contact-sheet.png"
    event("CONTACT_SHEET_START")
    make_contact_sheet(scene_paths, contact_sheet)
    event("CONTACT_SHEET_COMPLETE", bytes=contact_sheet.stat().st_size)

    metrics = [plan_metrics, review_metrics]
    (output / "qwen-performance.json").write_text(json.dumps(metrics, indent=2) + "\n")

    html_path = output / "storyboard.html"
    write_html(plan, review, metrics, scene_paths, html_path)
    event("HTML_STORYBOARD_COMPLETE", bytes=html_path.stat().st_size)

    animatic = output / "storyboard-animatic.mp4"
    event("ANIMATIC_START")
    made_animatic = make_animatic(plan, cast_by_id, animatic, width, height)
    event(
        "ANIMATIC_COMPLETE" if made_animatic else "ANIMATIC_SKIPPED",
        bytes=animatic.stat().st_size if made_animatic else 0,
    )

    write_checksums(output)
    event("CHECKSUMS_COMPLETE", bytes=(output / "SHA256SUMS").stat().st_size)

    report = {
        "schema_version": "aahj.animal-storyboard-factory-report/v2.1",
        "status": "pass",
        "project_id": config["project_id"],
        "served_model": config["served_model"],
        "qwen_calls": metrics,
        "scene_count": len(plan["scenes"]),
        "cast_count": len(plan["cast"]),
        "safety_status": review["overall_status"],
        "safety_review_scope": "textual_storyboard_only",
        "animatic_created": made_animatic,
        "outputs": [path.name for path in sorted(output.iterdir()) if path.is_file()],
    }
    (output / "run-report.json").write_text(json.dumps(report, indent=2) + "\n")
    event("FACTORY_ACCEPTANCE_PASS", scenes=report["scene_count"], safety=report["safety_status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
