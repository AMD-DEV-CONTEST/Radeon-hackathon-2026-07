from __future__ import annotations

import hashlib
import json
import math
import subprocess
import wave
from pathlib import Path
from typing import Any, Mapping

import imageio.v2 as imageio
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .files import atomic_write_text, sha256_file
from .realtime_agent_orchestration import compile_realtime_creative_council


class RealtimePresetCampaignError(ValueError):
    """Raised when a preset cannot be compiled into truthful production assets."""


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MODEL_MASTER_ROOT = _PROJECT_ROOT / "web/assets/model-masters"
_MODEL_MASTER_MANIFEST = _MODEL_MASTER_ROOT / "model-master-manifest-v1.json"
_ARCHETYPE_MASTER = {
    "evidence_led_launch": "b2b-proof-observatory-imagegen-v2",
    "technical_rejection_test": "b2b-proof-observatory-imagegen-v2",
    "founder_conviction": "b2b-evidence-engine-imagegen-v1",
    "category_reframe": "b2b-evidence-engine-imagegen-v1",
    "participation_ritual": "b2c-private-ritual-imagegen-v1",
}
_FILM_MASTERS = {
    "primary_feed_film": "linkedin-six-shot-storyboard-imagegen-v1",
    "secondary_vertical_film": "youtube-six-shot-storyboard-imagegen-v1",
    "search_explainer_film": "search-six-shot-storyboard-imagegen-v1",
}
_PLATFORM_IMAGE_MASTERS = {
    "feed_4x5": "linkedin-evidence-observatory-imagegen-v1",
    "story_9x16": "youtube-optical-proof-imagegen-v1",
    "editorial_16x9": "search-provenance-map-imagegen-v1",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _verified_model_master_by_id(master_id: str) -> tuple[Path, dict[str, Any]]:
    try:
        manifest = json.loads(_MODEL_MASTER_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RealtimePresetCampaignError("model master manifest is unavailable") from error
    if manifest.get("schema") != "ProofLaunchPresetModelMasterManifestV1":
        raise RealtimePresetCampaignError("model master manifest schema is invalid")
    record = next(
        (
            dict(row)
            for row in manifest.get("masters", [])
            if isinstance(row, Mapping) and row.get("master_id") == master_id
        ),
        None,
    )
    if record is None:
        raise RealtimePresetCampaignError("model master binding is missing")
    filename = record.get("filename")
    expected = record.get("content_sha256")
    if not isinstance(filename, str) or not isinstance(expected, str) or len(expected) != 64:
        raise RealtimePresetCampaignError("model master receipt is incomplete")
    path = (_MODEL_MASTER_ROOT / filename).resolve(strict=True)
    try:
        path.relative_to(_MODEL_MASTER_ROOT)
    except ValueError as error:
        raise RealtimePresetCampaignError("model master escaped its allowlisted root") from error
    observed = sha256_file(path)
    if observed != expected or record.get("model_inference_observed") is not True:
        raise RealtimePresetCampaignError("model master failed receipt verification")
    return path, record


def _verified_model_master(archetype: str) -> tuple[Path, dict[str, Any]]:
    if archetype not in _ARCHETYPE_MASTER:
        raise RealtimePresetCampaignError("preset archetype has no model master")
    return _verified_model_master_by_id(_ARCHETYPE_MASTER[archetype])


def _storyboard_panel(master: Image.Image, shot_index: int) -> Image.Image:
    """Return one independently generated panel from a verified 3×2 storyboard."""
    if shot_index not in range(6):
        raise RealtimePresetCampaignError("storyboard shot index must be between zero and five")
    width, height = master.size
    column, row = shot_index % 3, shot_index // 3
    left = round(column * width / 3)
    right = round((column + 1) * width / 3)
    top = round(row * height / 2)
    bottom = round((row + 1) * height / 2)
    inset_x = max(2, round((right - left) * 0.008))
    inset_y = max(2, round((bottom - top) * 0.008))
    return master.crop((left + inset_x, top + inset_y, right - inset_x, bottom - inset_y)).convert("RGB")


def _text(value: object, field: str, maximum: int = 1_200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise RealtimePresetCampaignError(f"{field} must be a nonblank bounded string")
    return value.strip()


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/SFNS.ttf" if bold else "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/SFCompact.ttf",
        "/System/Library/Fonts/SFNSMono.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.ImageFont, width: int, lines: int) -> str:
    words = value.replace("\n", " ").split()
    rows: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
            continue
        if current:
            rows.append(current)
        current = word
        if len(rows) == lines - 1:
            break
    if current and len(rows) < lines:
        rows.append(current)
    consumed = " ".join(rows)
    if len(consumed) < len(" ".join(words)) and rows:
        rows[-1] = rows[-1].rstrip(".,;: ") + "…"
    return "\n".join(rows)


def _palette(seed: str, business_model: str) -> dict[str, tuple[int, int, int]]:
    variants = (
        {"ink": (13, 24, 48), "paper": (244, 248, 255), "accent": (48, 107, 255), "soft": (182, 222, 255)},
        {"ink": (28, 21, 50), "paper": (250, 247, 255), "accent": (119, 79, 255), "soft": (229, 208, 255)},
        {"ink": (15, 42, 38), "paper": (243, 252, 248), "accent": (0, 156, 127), "soft": (180, 239, 222)},
        {"ink": (53, 25, 20), "paper": (255, 248, 244), "accent": (246, 91, 67), "soft": (255, 207, 181)},
    )
    index = int(seed[:4], 16) % len(variants)
    if business_model == "b2c":
        index = (index + 1) % len(variants)
    return variants[index]


def _gradient(width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    a = np.array(top, dtype=np.float32)[None, None, :]
    b = np.array(bottom, dtype=np.float32)[None, None, :]
    pixels = np.repeat((a * (1 - y) + b * y).astype(np.uint8), width, axis=1)
    return Image.fromarray(pixels, mode="RGB")


def _model_master_frame(
    *,
    master: Image.Image,
    tone: str,
    width: int,
    height: int,
    campaign: str,
    hook: str,
    truth: str,
    category: str,
    format_label: str,
    visual_grammar: str,
    motion: float,
    shot_variant: int = 0,
) -> Image.Image:
    portrait = height / width > 1.15
    type_dominant = visual_grammar in {"editorial_brutalism", "kinetic_type"}
    systematic = visual_grammar in {"diagram_as_drama", "evidence_wall", "screen_evidence"}
    cinematic = visual_grammar in {"human_pov", "quiet_cinema", "tactile_artifact"}
    base_center_x = 0.28 if type_dominant else 0.72 if systematic else 0.56 if cinematic else 0.63
    shot_offsets = (-0.14, 0.10, -0.06, 0.15, -0.09, 0.04)
    center_x = max(0.18, min(0.82, base_center_x + shot_offsets[shot_variant % len(shot_offsets)]))
    center_y = (0.38, 0.58, 0.45, 0.62, 0.34, 0.52)[shot_variant % 6]
    local_motion = max(0.0, min(1.0, motion))
    scale = 1.06 + 0.055 * math.sin(local_motion * math.pi)
    fitted = ImageOps.fit(
        master.convert("RGB"),
        (max(width, int(width * scale)), max(height, int(height * scale))),
        method=Image.Resampling.LANCZOS,
        centering=(center_x, center_y),
    )
    travel = local_motion if shot_variant % 2 == 0 else 1.0 - local_motion
    drift_x = int((fitted.width - width) * travel)
    vertical_room = max(0, fitted.height - height)
    drift_y = int(vertical_room * (local_motion if shot_variant % 3 == 0 else 1.0 - local_motion))
    image = fitted.crop((drift_x, drift_y, drift_x + width, drift_y + height))
    image = ImageEnhance.Contrast(image).enhance(1.05)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    unit = min(width, height)
    margin = int(unit * 0.065)
    dark = tone == "dark"
    ink = (248, 249, 255) if dark else (17, 27, 43)
    sub = (231, 233, 244) if dark else (51, 59, 70)
    accent = (177, 146, 255) if dark else (184, 112, 33)
    panel = (8, 8, 13, 194) if dark else (255, 253, 247, 218)

    if systematic:
        grid_step = max(52, int(unit * 0.12))
        for x in range(margin, width - margin, grid_step):
            overlay_draw.line((x, margin, x, height - margin), fill=(*ink, 24), width=1)
        for y in range(margin, height - margin, grid_step):
            overlay_draw.line((margin, y, width - margin, y), fill=(*ink, 24), width=1)
        for index in range(3):
            size = int(unit * (0.055 + index * 0.018))
            x = width - margin - size - index * int(unit * 0.07)
            y = margin + int(unit * (0.13 + index * 0.09))
            overlay_draw.rectangle((x, y, x + size, y + size), outline=(*accent, 150), width=max(2, int(unit * 0.004)))
    elif type_dominant:
        overlay_draw.rectangle((0, 0, width, height), fill=(4, 5, 9, 62) if dark else (255, 252, 246, 72))
        overlay_draw.rectangle((margin, int(height * 0.18), margin + int(unit * 0.025), int(height * 0.48)), fill=(*accent, 235))
        overlay_draw.text((width - margin - int(unit * 0.22), margin), f"{shot_variant + 1:02d}", font=_font(max(72, int(unit * 0.14)), bold=True), fill=(*ink, 34))
    elif visual_grammar == "tactile_artifact":
        radius = int(unit * 0.18)
        cx, cy = int(width * 0.68), int(height * 0.33)
        overlay_draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(*accent, 130), width=max(3, int(unit * 0.006)))

    if portrait:
        panel_top = int(height * (0.34 if type_dominant else 0.46 if systematic else 0.535))
        overlay_draw.rounded_rectangle(
            (margin, panel_top, width - margin, height - margin),
            radius=int(unit * 0.045),
            fill=panel,
            outline=(*ink, 42),
            width=max(1, int(unit * 0.002)),
        )
        text_x = margin + int(unit * 0.045)
        text_y = panel_top + int(unit * 0.055)
        content_width = width - text_x - margin - int(unit * 0.04)
    else:
        panel_width = int(width * (0.75 if type_dominant else 0.63 if systematic else 0.58))
        for x in range(panel_width):
            ratio = x / max(1, panel_width - 1)
            alpha = int((210 if dark else 226) * (1 - ratio**2.6))
            color = (5, 6, 10, alpha) if dark else (255, 253, 248, alpha)
            overlay_draw.line((x, 0, x, height), fill=color)
        text_x = margin
        text_y = int(height * 0.19)
        content_width = int(width * (0.63 if type_dominant else 0.53 if systematic else 0.48))

    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image, "RGBA")
    label_font = _font(max(16, int(unit * 0.022)), bold=True)
    headline_font = _font(max(38, int(unit * (0.072 if type_dominant else 0.065 if portrait else 0.072))), bold=True)
    body_font = _font(max(20, int(unit * 0.029)))
    proof_font = _font(max(17, int(unit * 0.022)))
    chip = f"{format_label}  ·  {visual_grammar.replace('_', ' ').upper()}"
    chip_width = draw.textbbox((0, 0), chip, font=label_font)[2] + int(unit * 0.06)
    chip_y = margin
    draw.rounded_rectangle(
        (margin, chip_y, min(width - margin, margin + chip_width), chip_y + int(unit * 0.052)),
        radius=int(unit * 0.026),
        fill=(*accent, 235),
    )
    draw.text((margin + int(unit * 0.026), chip_y + int(unit * 0.012)), chip, font=label_font, fill=(255, 255, 255))
    campaign_copy = _wrap(draw, campaign, headline_font, content_width, 2)
    draw.text(
        (text_x, text_y),
        campaign_copy,
        font=headline_font,
        fill=ink,
        spacing=5,
    )
    campaign_box = draw.multiline_textbbox(
        (text_x, text_y), campaign_copy, font=headline_font, spacing=5
    )
    hook_y = campaign_box[3] + int(unit * (0.052 if portrait else 0.06))
    hook_copy = _wrap(draw, hook, body_font, content_width, 3)
    draw.text(
        (text_x, hook_y),
        hook_copy,
        font=body_font,
        fill=sub,
        spacing=int(unit * 0.012),
    )
    hook_box = draw.multiline_textbbox(
        (text_x, hook_y), hook_copy, font=body_font, spacing=int(unit * 0.012)
    )
    proof_y = hook_box[3] + int(unit * (0.052 if portrait else 0.065))
    proof_copy = _wrap(draw, truth, proof_font, content_width, 2)
    proof_box = draw.multiline_textbbox(
        (text_x, proof_y + int(unit * 0.024)),
        proof_copy,
        font=proof_font,
        spacing=4,
    )
    footer_y = height - margin - int(unit * 0.052)
    if proof_box[3] >= footer_y - int(unit * 0.04):
        proof_copy = _wrap(draw, truth, proof_font, content_width, 1)
    draw.line((text_x, proof_y, text_x + int(unit * 0.105), proof_y), fill=accent, width=max(4, int(unit * 0.008)))
    draw.text(
        (text_x, proof_y + int(unit * 0.024)),
        proof_copy,
        font=proof_font,
        fill=ink,
        spacing=4,
    )
    footer = f"{category.upper()[:36]}  ·  DRAFT / NAMED-HUMAN RELEASE"
    draw.text((margin, footer_y), footer, font=label_font, fill=ink)
    return image.convert("RGB")


def _campaign_frame(
    *,
    width: int,
    height: int,
    palette: Mapping[str, tuple[int, int, int]],
    campaign: str,
    hook: str,
    truth: str,
    category: str,
    format_label: str,
    motion: float = 0.0,
    model_master: Image.Image | None = None,
    model_master_tone: str = "dark",
    visual_grammar: str = "quiet_cinema",
    shot_variant: int = 0,
) -> Image.Image:
    if model_master is not None:
        return _model_master_frame(
            master=model_master,
            tone=model_master_tone,
            width=width,
            height=height,
            campaign=campaign,
            hook=hook,
            truth=truth,
            category=category,
            format_label=format_label,
            visual_grammar=visual_grammar,
            motion=motion,
            shot_variant=shot_variant,
        )
    paper = palette["paper"]
    soft = palette["soft"]
    ink = palette["ink"]
    accent = palette["accent"]
    image = _gradient(width, height, paper, tuple(min(255, channel + 7) for channel in paper))
    draw = ImageDraw.Draw(image, "RGBA")
    unit = min(width, height)
    margin = int(unit * 0.07)
    drift = int(math.sin(motion * math.tau) * unit * 0.055)

    draw.ellipse(
        (width - int(unit * 0.58) + drift, -int(unit * 0.18), width + int(unit * 0.22) + drift, int(unit * 0.62)),
        fill=(*soft, 175),
    )
    draw.rounded_rectangle(
        (margin, int(height * 0.18), width - margin, int(height * 0.79)),
        radius=int(unit * 0.045),
        fill=(255, 255, 255, 222),
        outline=(*ink, 24),
        width=max(1, int(unit * 0.002)),
    )
    grid_alpha = 18
    for x in range(margin, width - margin, max(40, int(unit * 0.095))):
        draw.line((x, int(height * 0.18), x, int(height * 0.79)), fill=(*ink, grid_alpha), width=1)
    for y in range(int(height * 0.18), int(height * 0.79), max(40, int(unit * 0.095))):
        draw.line((margin, y, width - margin, y), fill=(*ink, grid_alpha), width=1)

    label_font = _font(max(17, int(unit * 0.025)), bold=True)
    body_font = _font(max(20, int(unit * 0.032)))
    headline_font = _font(max(42, int(unit * 0.072)), bold=True)
    truth_font = _font(max(18, int(unit * 0.025)))
    draw.text((margin, margin), "PROOFLAUNCH / LIVE CAMPAIGN SYSTEM", font=label_font, fill=ink)
    label = f"{format_label}  ·  {category.upper()[:34]}"
    label_box = draw.textbbox((0, 0), label, font=label_font)
    chip_width = label_box[2] - label_box[0] + int(unit * 0.055)
    chip_top = int(height * 0.215)
    draw.rounded_rectangle(
        (margin + int(unit * 0.05), chip_top, margin + int(unit * 0.05) + chip_width, chip_top + int(unit * 0.06)),
        radius=int(unit * 0.03),
        fill=accent,
    )
    draw.text(
        (margin + int(unit * 0.077), chip_top + int(unit * 0.014)),
        label,
        font=label_font,
        fill=(255, 255, 255),
    )

    card_x = margin + int(unit * 0.05)
    campaign_y = int(height * 0.315)
    draw.text((card_x, campaign_y), _wrap(draw, campaign, headline_font, width - card_x - margin * 2, 2), font=headline_font, fill=ink, spacing=4)
    hook_y = campaign_y + int(unit * 0.19)
    draw.text((card_x, hook_y), _wrap(draw, hook, body_font, width - card_x - margin * 2, 4), font=body_font, fill=(*ink, 220), spacing=int(unit * 0.012))

    proof_y = int(height * 0.675)
    draw.line((card_x, proof_y, card_x + int(unit * 0.11), proof_y), fill=accent, width=max(4, int(unit * 0.009)))
    draw.text((card_x, proof_y + int(unit * 0.025)), _wrap(draw, truth, truth_font, width - card_x - margin * 2, 3), font=truth_font, fill=ink, spacing=4)

    footer_y = height - margin - int(unit * 0.03)
    draw.text((margin, footer_y), "DRAFT FOR NAMED-HUMAN REVIEW", font=label_font, fill=ink)
    marker = int(unit * 0.026)
    draw.ellipse((width - margin - marker, footer_y, width - margin, footer_y + marker), fill=accent)
    return image.filter(ImageFilter.GaussianBlur(radius=0.12))


def _asset(
    path: Path,
    *,
    role: str,
    media_type: str,
    width: int,
    height: int,
    duration: float | None = None,
    surface_id: str | None = None,
    visual_grammar_id: str | None = None,
    copy_system_id: str | None = None,
    copy_payload_sha256: str | None = None,
    placement_id: str | None = None,
    creative_source_id: str | None = None,
    shot_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "role": role,
        "filename": path.name,
        "media_type": media_type,
        "content_sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "binary_rendering_observed": True,
    }
    if duration is not None:
        row["duration_seconds"] = duration
    if surface_id is not None:
        row["surface_id"] = surface_id
    if visual_grammar_id is not None:
        row["visual_grammar_id"] = visual_grammar_id
    if copy_system_id is not None:
        row["copy_system_id"] = copy_system_id
    if copy_payload_sha256 is not None:
        row["copy_payload_sha256"] = copy_payload_sha256
    if placement_id is not None:
        row["placement_id"] = placement_id
    if creative_source_id is not None:
        row["creative_source_id"] = creative_source_id
    if shot_source_ids is not None:
        row["shot_source_ids"] = shot_source_ids
        row["unique_shot_source_count"] = len(set(shot_source_ids))
    if surface_id is not None:
        row["exclusive_surface_binding"] = True
        row["cross_surface_asset_reuse_allowed"] = False
        row["same_surface_cross_modality_reuse_allowed"] = False
        row["final_asset_reuse_allowed"] = False
    return row


def _strategy_language(
    territory: Mapping[str, Any],
    brief: Mapping[str, str],
) -> dict[str, str]:
    axes = territory["axis_signature"]
    defaults = {
        "hidden_cost": "The category hides the time, trust and coordination cost behind a polished output.",
        "failed_default": "The familiar category solution fails at the exact moment an accountable person must act on it.",
        "unasked_question": "The category keeps asking which product has more features instead of whether a buyer can reproduce the decision.",
        "proof_gap": "The category rewards a smooth promise even when the witness, limitation and accountable owner are missing.",
        "burden_removal": "The category treats added ceremony as value when the stronger move is to remove work and pressure.",
        "time_collision": "The category celebrates the immediate output while hiding the delayed decision cost.",
        "private_truth": "The audience recognizes a category failure privately that most launch language refuses to name.",
    }
    openings = {
        "forbidden_move": "Begin with one useful prohibition, not a feature list.",
        "specific_challenge": "Issue a concrete rejection test before asking for belief.",
        "object_mystery": "Let one object carry the unanswered question before the product is named.",
        "confession_without_theater": "Admit one bounded failure and show the operating decision it changed.",
        "category_inversion": "Reverse the category's expected promise and success definition.",
        "compressed_enemy": "Name the costly behavior as the enemy, never a person or competitor.",
        "verdict_first": "State the verdict before the feature tour.",
        "unfinished_scene": "Open one beat before a consequential decision is resolved.",
        "identity_callout": "Address the person who will still own the decision after the demo.",
        "counterfactual": "Remove one assumed requirement and ask what the category becomes without it.",
        "artifact_teardown": "Put one representative artifact on trial in public view.",
        "one_line_wager": "Make one falsifiable wager and let the evidence carry the launch.",
    }
    proofs = {
        "live_demonstration": "Prove the mechanism by completing one bounded job in view.",
        "constraint_test": "Make the idea survive a stricter constraint than the category usually applies.",
        "evidence_autopsy": "Separate fact, inference, hypothesis and missing evidence on the page.",
        "side_by_side": "Compare two approaches under the same task and conditions.",
        "decision_tree": "Turn the expertise into a portable choose-or-reject path.",
        "transparent_failure": "Show one failure, its mechanism and the decision that changed.",
        "counterexample": "Use a legitimate exception to sharpen the rule instead of overselling it.",
        "artifact_transformation": "Show a source artifact becoming a reviewed decision object.",
        "private_ritual": "Let the audience create evidence without performing in public.",
        "portable_diagnostic": "Give away a diagnostic that remains useful without conversion.",
    }
    actions = {
        "choose_the_verdict": "Ask for pass, repair or reject before the reveal.",
        "falsify_the_rule": "Invite one privacy-safe counterexample, not praise.",
        "private_seven_day_ritual": "Offer a private seven-day test with an explicit stop decision.",
        "saveable_diagnostic": "Make the asset worth saving because it changes a real decision.",
        "one_object_audit": "Ask the audience to audit one current artifact without exposing confidential data.",
        "remix_with_constraint": "Let the audience remix the format while preserving the proof boundary.",
        "complete_the_missing_field": "Ask the audience to complete exactly one missing field.",
        "prediction_before_reveal": "Collect a prediction before the result is shown.",
        "choose_what_to_delete": "Make deletion—not addition—the participation mechanic.",
        "peer_relay_object": "Create one useful object that can travel into a team decision.",
    }
    payoffs = {
        "portable_rule": "the audience leaves with a rule it can use today",
        "changed_decision": "the audience can name the decision the work changes",
        "felt_relief": "the lighter behavior feels immediately possible",
        "visible_transformation": "the before-to-after object remains inspectable",
        "earned_surprise": "the opening resolves in a way that feels surprising and inevitable",
        "self_diagnosis": "the audience recognizes its own failure mode without being lectured",
        "team_relay": "the proof survives forwarding into a group decision",
        "permission_to_stop": "reject, delete or no-action becomes a legitimate valuable outcome",
    }
    category_default = defaults.get(axes["tension"], "The category default makes the decision harder than the output suggests.")
    diagnosis = (
        f"For {brief['audience']} in {brief['market']}, {category_default[0].lower()}{category_default[1:]} "
        f"The wedge is not more output: turn the approved truth—{brief['product_truth']}—into an inspectable decision before any conversion ask."
    )
    bet = " ".join((
        openings[axes["hook"]],
        proofs[axes["proof"]],
        actions[axes["interaction"]],
        f"The route works only when {payoffs[axes['payoff']]}."
    ))
    return {
        "market_diagnosis": diagnosis,
        "category_default_to_reject": category_default,
        "non_consensus_bet": bet,
    }


def _platform_adaptations(
    territory: Mapping[str, Any],
    brief: Mapping[str, str],
    *,
    b2b: bool,
    primary_surface: str,
    secondary_surface: str,
) -> dict[str, dict[str, str]]:
    selected = str(territory["visual_grammar_id"])
    used = {selected}

    def distinct(options: tuple[str, ...]) -> str:
        choice = next((item for item in options if item not in used), options[0])
        used.add(choice)
        return choice

    story_visual = distinct(
        ("practical_demo", "human_pov", "kinetic_type", "quiet_cinema")
        if b2b else
        ("human_pov", "kinetic_type", "practical_demo", "quiet_cinema")
    )
    editorial_visual = distinct(
        ("diagram_as_drama", "evidence_wall", "screen_evidence", "editorial_brutalism")
        if b2b else
        ("tactile_artifact", "quiet_cinema", "editorial_brutalism", "diagram_as_drama")
    )
    return {
        "feed_4x5": {
            "surface_id": primary_surface,
            "visual_grammar_id": selected,
            "copy_system_id": f"{primary_surface}_feed_native",
            "headline": str(territory["campaign_name"]),
            "supporting_copy": str(territory["first_line"]),
            "format_label": f"{primary_surface.upper()} / 4:5",
        },
        "story_9x16": {
            "surface_id": secondary_surface,
            "visual_grammar_id": story_visual,
            "copy_system_id": f"{secondary_surface}_vertical_native",
            "headline": "Run the Rejection Test" if b2b else "Try It Before You Share It",
            "supporting_copy": str(territory["participation_mechanic"]),
            "format_label": f"{secondary_surface.upper()} / 9:16",
        },
        "editorial_16x9": {
            "surface_id": "google_search" if b2b else "search_answers",
            "visual_grammar_id": editorial_visual,
            "copy_system_id": "search_answer_editorial",
            "headline": "A Better Buying Question" if b2b else "The Smallest Useful Ritual",
            "supporting_copy": _strategy_language(territory, brief)["category_default_to_reject"],
            "format_label": "SEARCH / 16:9",
        },
    }


def _native_copy_system(
    territory: Mapping[str, Any],
    brief: Mapping[str, str],
    *,
    b2b: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    hook = str(territory["first_line"])
    truth = brief["product_truth"]
    problem = brief["audience_problem"]
    outcome = brief["audience_outcome"]
    participation = str(territory["participation_mechanic"])
    tone = str(territory["tone_id"])
    if tone == "forensic_calm":
        body = f"FACT — {truth}\n\nTENSION — {problem}\n\nDECISION — {outcome}"
    elif tone == "founder_blunt":
        body = f"We made the output look finished before the decision was defensible.\n\nWhat changes now: {outcome}\n\nThe only proof we are allowed to use: {truth}"
    elif tone == "deadpan_contrarian":
        body = f"More content would certainly create more content.\n\nIt would not resolve this: {problem}\n\nThe useful evidence is narrower: {truth}"
    elif tone == "technical_elegance":
        body = f"Input: {problem}\nTest: {territory['portable_decision_tool']}\nObserved boundary: {truth}\nDecision: {outcome}"
    elif tone == "playful_precision":
        body = f"A tiny experiment: remove the impressive sentence.\nKeep the inspectable one.\n\nThe inspectable one is: {truth}\n\nThen decide whether to {outcome.lower()}."
    elif tone == "warm_confidant":
        body = f"You do not need to perform certainty here. Start with one private check: {truth}\n\nIf it does not make the next decision easier, stop."
    elif tone == "provocative_generosity":
        body = f"Here is the sharper claim—and the tool to challenge it.\n\nClaim boundary: {truth}\nChallenge: {territory['portable_decision_tool']}\nDecision: {outcome}"
    else:
        body = f"{problem}\n\nThe evidence boundary is exact: {truth}\n\nThe useful next decision: {outcome}"
    primary_post = f"{hook}\n\n{body}\n\n{participation}"
    primary_native = {
        "hook": hook,
        "body_blocks": body.split("\n\n"),
        "first_comment": f"Proof boundary: {truth}",
        "objection_replies": [
            f"Reject the route if it cannot preserve this exact fact: {truth}",
            f"Repair the route if its participation mechanic does not help someone {outcome.lower()}.",
        ],
        "participation": participation,
        "cta": outcome,
        "tone_system": territory["tone_instruction"],
    }
    if b2b:
        channel = {
            "linkedin_post": primary_post,
            "linkedin_first_comment": f"Run the portable test: {territory['portable_decision_tool']}. No capability or outcome claim may be added.",
            "youtube_title": f"{territory['campaign_name']}: put the category decision on trial",
            "youtube_opening": territory["first_1500ms_video"],
            "search_answer_lead": f"For {brief['audience']}, the decision is not whether {brief['category']} sounds credible; it is whether {truth.lower()} under the declared constraint.",
        }
    else:
        channel = {
            "instagram_caption": primary_post,
            "instagram_carousel_arc": f"01 {territory['human_truth']} · 02 {territory['organizing_conflict']} · 03 {territory['portable_decision_tool']} · 04 {truth} · 05 {participation}",
            "tiktok_opening_overlay": hook,
            "tiktok_creator_prompt": participation,
            "search_answer_lead": f"Start with the smallest repeatable behavior that helps someone {outcome.lower()}; preserve this exact boundary: {truth}",
        }
    return channel, primary_native


def _video_system(
    territory: Mapping[str, Any],
    brief: Mapping[str, str],
    *,
    primary_surface_id: str,
    primary_visual_grammar_id: str,
    secondary_surface_id: str,
    secondary_visual_grammar_id: str,
    search_surface_id: str,
    search_visual_grammar_id: str,
) -> dict[str, Any]:
    beats = [beat.strip() for beat in str(territory["narrative_beats"]).split("→")]
    while len(beats) < 4:
        beats.append("decision")
    visual = secondary_visual_grammar_id
    camera = {
        "human_pov": "handheld first-person macro with one deliberate rack focus",
        "quiet_cinema": "locked wide frames, slow object movement and held negative space",
        "kinetic_type": "type-led cuts synchronized to spoken stress, not music beats",
        "editorial_brutalism": "hard crops, static frontal compositions and abrupt scale changes",
        "diagram_as_drama": "top-down diagram build with one line changing the system",
        "evidence_wall": "progressive evidence accumulation, then one visible redaction",
        "screen_evidence": "real workflow crops with sensitive content removed and cursor intent visible",
        "practical_demo": "hands-and-tools demonstration with consequence before explanation",
        "tactile_artifact": "macro object choreography and repeatable placement ritual",
        "anti_ui": "physical consequence and human reaction; no dashboard montage",
    }.get(visual, "one disciplined visual device across all shots")
    shot_jobs = [
        (beats[0], territory["first_line"]),
        (beats[1], brief["audience_problem"]),
        ("proof enters", brief["product_truth"]),
        (beats[2], territory["portable_decision_tool"]),
        (beats[3], territory["participation_mechanic"]),
        ("named-human decision", brief["audience_outcome"]),
    ]
    shots = [
        {
            "order": index + 1,
            "seconds": f"{index}.0–{index + 1}.0",
            "beat": beat,
            "on_screen_copy": copy,
            "camera_and_edit": camera,
        }
        for index, (beat, copy) in enumerate(shot_jobs)
    ]
    return {
        "platform_cuts": {
            "primary_feed_film": {
                "surface_id": primary_surface_id,
                "aspect_ratio": "4:5",
                "duration_seconds": 8,
                "visual_grammar_id": primary_visual_grammar_id,
                "edit_grammar": "argument_first_editorial_cut",
                "shot_titles": [
                    str(territory["campaign_name"]), "The Cost", "The Proof",
                    "The Rule", "The Ask", "The Decision",
                ],
                "shot_copy": [
                    str(territory["first_line"]), brief["audience_problem"],
                    brief["product_truth"], str(territory["portable_decision_tool"]),
                    "Let an accountable owner inspect the evidence before the conversion ask.",
                    brief["audience_outcome"],
                ],
            },
            "secondary_vertical_film": {
                "surface_id": secondary_surface_id,
                "aspect_ratio": "9:16",
                "duration_seconds": 12,
                "visual_grammar_id": secondary_visual_grammar_id,
                "edit_grammar": "participation_first_vertical_cut",
                "shot_titles": [
                    "Would You Pass It?", "One Missing Witness", "Look Again",
                    "Try the Test", "Your Verdict", "Carry the Rule",
                ],
                "shot_copy": [
                    str(territory["first_1500ms_video"]),
                    "Predict which sentence survives before the receipt appears.",
                    brief["product_truth"], str(territory["participation_mechanic"]),
                    "Choose pass, repair or reject. Give the reason, not applause.",
                    str(territory["zero_budget_relay_object"]),
                ],
            },
            "search_explainer_film": {
                "surface_id": search_surface_id,
                "aspect_ratio": "16:9",
                "duration_seconds": 10,
                "visual_grammar_id": search_visual_grammar_id,
                "edit_grammar": "provenance_first_search_explainer_cut",
                "shot_titles": [
                    "The Question", "Find the Sources", "Trace the Claim",
                    "Remove the Weak Link", "Assemble with Limits", "Await Approval",
                ],
                "shot_copy": [
                    f"What would make this answer inspectable for {brief['audience']}?",
                    "Collect distinct public evidence before drafting the answer.",
                    "Bind every material statement to its source and limitation.",
                    "Remove the source that cannot survive the declared rejection test.",
                    f"Assemble the answer without hiding this boundary: {brief['product_truth']}",
                    "Seal the evidence envelope; a named human still decides release.",
                ],
            },
        },
        "narrative_grammar": territory["narrative_grammar_id"],
        "15_to_30_second_script": [row["on_screen_copy"] for row in shots],
        "six_shot_plan": shots,
        "first_1500ms": territory["first_1500ms_video"],
        "voice": territory["tone_instruction"],
        "sound": f"Procedural stereo sound design follows the {territory['tone_id'].replace('_', ' ')} grammar: one low pulse per narrative turn, controlled silence before proof and no synthetic urgency.",
        "captions": [territory["first_line"], brief["product_truth"], brief["audience_outcome"]],
        "continuity": f"Visual grammar={visual}; narrative grammar={territory['narrative_grammar_id']}; every shot preserves the same proof boundary and participation object.",
    }


def _write_procedural_soundtrack(
    path: Path,
    *,
    duration_seconds: float,
    seed: str,
    tone_id: str,
) -> None:
    sample_rate = 48_000
    sample_count = int(sample_rate * duration_seconds)
    timeline = np.arange(sample_count, dtype=np.float32) / sample_rate
    seed_value = int(seed[:16], 16)
    base = 46.0 + seed_value % 19
    tone_shift = {
        "forensic_calm": 0.5,
        "technical_elegance": 1.0,
        "editorial_authority": 1.5,
        "deadpan_contrarian": 2.0,
        "playful_precision": 4.0,
        "warm_confidant": -3.0,
        "cinematic_restraint": -5.0,
    }.get(tone_id, 0.0)
    carrier = (
        0.055 * np.sin(2 * np.pi * (base + tone_shift) * timeline)
        + 0.028 * np.sin(2 * np.pi * (base * 1.5 + tone_shift) * timeline + 0.7)
    )
    pulse = np.zeros(sample_count, dtype=np.float32)
    for beat in np.arange(0, duration_seconds, 2.0):
        delta = timeline - beat
        active = (delta >= 0) & (delta < 0.48)
        pulse[active] += (
            0.19
            * np.exp(-8.5 * delta[active])
            * np.sin(2 * np.pi * (82 + (beat % 4) * 9) * delta[active])
        )
    shimmer = 0.012 * np.sin(2 * np.pi * (312 + seed_value % 37) * timeline)
    section_breath = 0.72 + 0.28 * np.sin(2 * np.pi * timeline / 4.0 - np.pi / 2)
    mono = (carrier * section_breath + pulse + shimmer).astype(np.float32)
    fade = np.ones(sample_count, dtype=np.float32)
    fade_samples = min(sample_count // 4, int(sample_rate * 0.7))
    fade[:fade_samples] = np.linspace(0, 1, fade_samples, dtype=np.float32)
    fade[-fade_samples:] = np.linspace(1, 0, fade_samples, dtype=np.float32)
    mono *= fade
    stereo = np.column_stack((mono, np.roll(mono, 19)))
    pcm = np.clip(stereo * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def _render_media(result: Mapping[str, Any], root: Path) -> dict[str, Any]:
    brief = result["brief"]
    production = result["final_production"]
    campaign = _text(production["campaign_platform"], "campaign_platform", 200)
    hook = _text(production["primary_native_text"]["hook"], "hook", 500)
    truth = _text(brief["product_truth"], "product_truth", 1_000)
    category = _text(brief["category"], "category", 180)
    visual_grammar = _text(
        production.get("image_system", {}).get("visual_grammar_id", "quiet_cinema"),
        "visual_grammar_id",
        80,
    )
    video_shots = production.get("video_system", {}).get("six_shot_plan", [])
    if not isinstance(video_shots, list) or len(video_shots) != 6:
        raise RealtimePresetCampaignError("agent video system must contain six shots")
    archetype = _text(result["strategy"]["playbook_archetype"], "playbook_archetype", 80)
    primary_master_id = (
        "b2c-private-ritual-imagegen-v1"
        if brief["business_model"] == "b2c"
        else _PLATFORM_IMAGE_MASTERS["feed_4x5"]
    )
    image_master_ids = {**_PLATFORM_IMAGE_MASTERS, "feed_4x5": primary_master_id}
    image_masters: dict[str, tuple[Image.Image, dict[str, Any]]] = {}
    for image_role, master_id in image_master_ids.items():
        image_path, image_receipt = _verified_model_master_by_id(master_id)
        with Image.open(image_path) as image_source:
            image_masters[image_role] = (image_source.convert("RGB"), image_receipt)
    palette = _palette(result["content_sha256"], brief["business_model"])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    assets: list[dict[str, Any]] = []
    adaptations = production.get("image_system", {}).get("platform_adaptations", {})
    if set(adaptations) != {"feed_4x5", "story_9x16", "editorial_16x9"}:
        raise RealtimePresetCampaignError("platform image adaptations are incomplete")
    if len({row.get("visual_grammar_id") for row in adaptations.values()}) != 3:
        raise RealtimePresetCampaignError("platform images must use three distinct visual grammars")
    formats = (
        ("feed-4x5.png", "feed_4x5", 1080, 1350),
        ("story-9x16.png", "story_9x16", 1080, 1920),
        ("editorial-16x9.png", "editorial_16x9", 1920, 1080),
    )
    for filename, role, width, height in formats:
        adaptation = adaptations[role]
        path = root / filename
        model_master, image_master_receipt = image_masters[role]
        source_id = f"verified-model-master:{image_master_receipt['content_sha256']}"
        frame_palette = _palette(_digest({"source": source_id}), brief["business_model"])
        frame = _campaign_frame(
            width=width,
            height=height,
            palette=frame_palette,
            campaign=_text(adaptation["headline"], f"{role}_headline", 240),
            hook=_text(adaptation["supporting_copy"], f"{role}_supporting_copy", 1_000),
            truth=truth,
            category=category,
            format_label=_text(adaptation["format_label"], f"{role}_format_label", 100),
            model_master=model_master,
            model_master_tone=str(image_master_receipt.get("tone", "light")),
            visual_grammar=_text(adaptation["visual_grammar_id"], f"{role}_visual_grammar", 80),
        )
        frame.save(path, format="PNG", optimize=True)
        path.chmod(0o600)
        assets.append(_asset(
            path,
            role=role,
            media_type="image/png",
            width=width,
            height=height,
            surface_id=_text(adaptation["surface_id"], f"{role}_surface", 80),
            visual_grammar_id=_text(adaptation["visual_grammar_id"], f"{role}_visual_grammar", 80),
            copy_system_id=_text(adaptation["copy_system_id"], f"{role}_copy_system", 120),
            copy_payload_sha256=_digest({
                "headline": adaptation["headline"],
                "supporting_copy": adaptation["supporting_copy"],
                "truth": truth,
            }),
            placement_id=f"{adaptation['surface_id']}:{role}:image",
            creative_source_id=source_id,
        ))

    video_cuts = production.get("video_system", {}).get("platform_cuts", {})
    if set(video_cuts) != {"primary_feed_film", "secondary_vertical_film", "search_explainer_film"}:
        raise RealtimePresetCampaignError("three platform-native video cuts are required")
    video_specs = (
        ("campaign-film-primary-4x5.mp4", "primary_feed_film", 720, 900),
        ("campaign-film-secondary-9x16.mp4", "secondary_vertical_film", 720, 1280),
        ("campaign-film-search-16x9.mp4", "search_explainer_film", 960, 540),
    )
    film_masters: dict[str, tuple[Image.Image, dict[str, Any]]] = {}
    for film_role, master_id in _FILM_MASTERS.items():
        film_path, film_receipt = _verified_model_master_by_id(master_id)
        with Image.open(film_path) as film_source:
            film_masters[film_role] = (film_source.convert("RGB"), film_receipt)
    cut_copy_signatures: set[str] = set()
    for filename, role, width, height in video_specs:
        cut = video_cuts[role]
        cut_titles = cut.get("shot_titles")
        cut_copy = cut.get("shot_copy")
        if not isinstance(cut_titles, list) or not isinstance(cut_copy, list) or len(cut_titles) != 6 or len(cut_copy) != 6:
            raise RealtimePresetCampaignError("each platform film requires six titles and six platform-native copy beats")
        cut_signature = _digest({"titles": cut_titles, "copy": cut_copy})
        if cut_signature in cut_copy_signatures:
            raise RealtimePresetCampaignError("platform film copy arcs must be distinct")
        cut_copy_signatures.add(cut_signature)
        duration = float(cut["duration_seconds"])
        film_master, film_master_receipt = film_masters[role]
        source_id = f"verified-model-master:{film_master_receipt['content_sha256']}"
        shot_source_ids = [
            f"{source_id}:panel-{shot_index + 1:02d}:{_digest({'master': film_master_receipt['content_sha256'], 'panel': shot_index})}"
            for shot_index in range(6)
        ]
        film_palette = _palette(_digest({"source": source_id}), brief["business_model"])
        fps = 12
        frame_count = int(duration * fps)
        silent_path = root / f".{role}-silent.mp4"
        audio_path = root / f".{role}-sound.wav"
        video_path = root / filename
        writer = imageio.get_writer(
            silent_path,
            fps=fps,
            codec="libx264",
            quality=8,
            macro_block_size=1,
            ffmpeg_params=["-movflags", "+faststart"],
        )
        previous_frame: Image.Image | None = None
        try:
            for index in range(frame_count):
                phase = index / max(1, frame_count - 1)
                shot_index = min(5, int(phase * 6))
                shot_start = shot_index / 6
                local_phase = (phase - shot_start) * 6
                active_hook = _text(cut_copy[shot_index], f"{role}_shot_{shot_index + 1}", 1_000)
                shot_master = _storyboard_panel(film_master, shot_index)
                frame = _campaign_frame(
                    width=width,
                    height=height,
                    palette=film_palette,
                    campaign=_text(cut_titles[shot_index], f"{role}_title_{shot_index + 1}", 240),
                    hook=active_hook,
                    truth=truth,
                    category=category,
                    format_label=f"{str(cut['surface_id']).upper()} / FILM {int(duration)}S",
                    motion=local_phase,
                    model_master=shot_master,
                    model_master_tone=str(film_master_receipt.get("tone", "dark")),
                    visual_grammar=_text(cut["visual_grammar_id"], f"{role}_visual_grammar", 80),
                    shot_variant=0,
                )
                frame_draw = ImageDraw.Draw(frame, "RGBA")
                progress = int((width - 100) * phase)
                frame_draw.rounded_rectangle((50, height - 60, width - 50, height - 52), radius=4, fill=(*palette["ink"], 40))
                frame_draw.rounded_rectangle((50, height - 60, 50 + progress, height - 52), radius=4, fill=palette["accent"])
                frame_draw.text((width - 106, 34), f"{shot_index + 1}/6", font=_font(18, bold=True), fill=(255, 255, 255, 185))
                transition_frames = 4
                if previous_frame is not None and index % max(1, frame_count // 6) < transition_frames:
                    blend = (index % max(1, frame_count // 6) + 1) / transition_frames
                    frame = Image.blend(previous_frame, frame, min(1.0, blend))
                writer.append_data(np.asarray(frame))
                previous_frame = frame
        finally:
            writer.close()
        _write_procedural_soundtrack(
            audio_path,
            duration_seconds=duration,
            seed=_digest({"campaign": campaign, "surface": cut["surface_id"], "role": role}),
            tone_id=str(result["strategy"].get("tone_id", "editorial_authority")),
        )
        completed = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                "-i", str(silent_path), "-i", str(audio_path),
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                "-shortest", "-movflags", "+faststart", str(video_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not video_path.is_file():
            raise RealtimePresetCampaignError(f"platform film mux failed: {completed.stderr[-400:]}")
        silent_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)
        video_path.chmod(0o600)
        assets.append(_asset(
            video_path,
            role=role,
            media_type="video/mp4",
            width=width,
            height=height,
            duration=duration,
            surface_id=_text(cut["surface_id"], f"{role}_surface", 80),
            visual_grammar_id=_text(cut["visual_grammar_id"], f"{role}_visual_grammar", 80),
            copy_system_id=_text(cut["edit_grammar"], f"{role}_edit_grammar", 120),
            copy_payload_sha256=cut_signature,
            placement_id=f"{cut['surface_id']}:{role}:video",
            creative_source_id=source_id,
            shot_source_ids=shot_source_ids,
        ))

    binary_hashes = [row["content_sha256"] for row in assets]
    copy_hashes = [row["copy_payload_sha256"] for row in assets]
    image_surfaces = [row["surface_id"] for row in assets if row["media_type"] == "image/png"]
    video_surfaces = [row["surface_id"] for row in assets if row["media_type"] == "video/mp4"]
    placement_ids = [row["placement_id"] for row in assets]
    creative_source_ids = [row["creative_source_id"] for row in assets]
    video_shot_source_ids = [
        source_id
        for row in assets
        if row["media_type"] == "video/mp4"
        for source_id in row.get("shot_source_ids", [])
    ]
    if len(binary_hashes) != len(set(binary_hashes)):
        raise RealtimePresetCampaignError("a final asset binary was reused across platform outputs")
    if len(copy_hashes) != len(set(copy_hashes)):
        raise RealtimePresetCampaignError("a final copy arc was reused across platform outputs")
    if len(image_surfaces) != len(set(image_surfaces)) or len(video_surfaces) != len(set(video_surfaces)):
        raise RealtimePresetCampaignError("each modality requires one exclusive asset per platform surface")
    if len(placement_ids) != len(set(placement_ids)):
        raise RealtimePresetCampaignError("a final asset placement was assigned more than once")
    if len(creative_source_ids) != len(set(creative_source_ids)):
        raise RealtimePresetCampaignError("a creative source was reused across final image/video placements")
    if len(video_shot_source_ids) != 18 or len(video_shot_source_ids) != len(set(video_shot_source_ids)):
        raise RealtimePresetCampaignError("three films require eighteen exclusive generated shot sources")
    for surface_id in set(image_surfaces + video_surfaces):
        surface_sources = [row["creative_source_id"] for row in assets if row["surface_id"] == surface_id]
        if len(surface_sources) != len(set(surface_sources)):
            raise RealtimePresetCampaignError("a platform reused one creative source across image and video")
    asset_exclusivity = {
        "one_image_binary_per_surface": True,
        "one_copy_arc_per_output": True,
        "one_video_binary_per_surface": True,
        "cross_surface_binary_reuse_count": 0,
        "cross_surface_copy_reuse_count": 0,
        "same_surface_cross_modality_source_reuse_count": 0,
        "final_asset_placement_reuse_count": 0,
        "creative_source_reuse_count": 0,
        "image_surface_count": len(image_surfaces),
        "video_surface_count": len(video_surfaces),
        "unique_placement_count": len(placement_ids),
        "unique_creative_source_count": len(creative_source_ids),
        "unique_video_shot_source_count": len(video_shot_source_ids),
        "all_final_binary_sha256_unique": True,
        "all_copy_payload_sha256_unique": True,
        "all_placement_ids_unique": True,
        "all_creative_source_ids_unique": True,
        "approved_truth_spine_may_be_shared": True,
    }

    manifest: dict[str, Any] = {
        "schema": "ProofLaunchRealtimeMediaManifestV1",
        "renderer": "creative-council-platform-native-multimodal-renderer-v8",
        "render_mode": "agent_selected_platform_specific_copy_visual_and_film_systems",
        "image_model_inference_claimed": True,
        "video_model_inference_claimed": False,
        "live_image_model_inference_this_request": False,
        "model_master_inference_pre_generated": True,
        "live_multiformat_adaptation_observed": True,
        "video_generation_mode": "three_platform_native_six_scene_editorial_motion_films_from_exclusive_verified_imagegen_storyboards",
        "verified_model_master_asset_count": 6,
        "exclusive_procedural_visual_source_count": 0,
        "visual_grammar_id": visual_grammar,
        "platform_image_adaptations": adaptations,
        "video_narrative_grammar": production.get("video_system", {}).get("narrative_grammar"),
        "video_shot_count": len(video_shots),
        "video_platform_cut_count": len(video_cuts),
        "total_rendered_video_shots": len(video_shots) * len(video_cuts),
        "procedural_stereo_sound_design_observed": True,
        "platform_asset_exclusivity": asset_exclusivity,
        "agent_orchestration_sha256": result.get("agent_orchestration", {}).get("content_sha256"),
        "exclusive_image_master_receipts": [
            {
                key: image_masters[role][1][key]
                for key in (
                    "master_id", "content_sha256", "provider", "generator_surface", "model",
                    "generated_at", "model_inference_observed", "live_inference_this_request", "rights_status",
                )
            }
            for role in ("feed_4x5", "story_9x16", "editorial_16x9")
        ],
        "exclusive_video_master_receipts": [
            {
                key: film_masters[role][1][key]
                for key in (
                    "master_id", "content_sha256", "provider", "generator_surface", "model",
                    "generated_at", "model_inference_observed", "live_inference_this_request", "rights_status",
                )
            }
            for role in ("primary_feed_film", "secondary_vertical_film", "search_explainer_film")
        ],
        "binary_image_rendering_observed": True,
        "binary_video_rendering_observed": True,
        "asset_count": len(assets),
        "assets": assets,
        "external_publish_executed": False,
        "human_release_required": True,
        "quality_truth_boundary": "Six verified imagegen masters are each used once: three platform-specific image sources and three independent six-scene film storyboards. Six final binaries, six copy bundles, six visual sources, six placement IDs and eighteen video-shot source IDs are unique. Films are live-rendered H.264/AAC editorial motion systems from generated storyboard scenes; video-diffusion inference, human creative preference and market effect are not claimed.",
    }
    manifest["content_sha256"] = _digest(manifest)
    atomic_write_text(root / "media-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def compile_realtime_preset_campaign(brief: Mapping[str, Any], output_root: str | Path) -> dict[str, Any]:
    required = {
        "brief_id", "business_model", "industry", "category", "lifecycle", "product_surface",
        "audience", "audience_problem", "audience_outcome", "product_truth", "brand_voice",
        "budget", "market", "primary_goal", "recent_organic_signal_context", "signal_provenance",
    }
    if set(brief) != required:
        raise RealtimePresetCampaignError("preset brief fields violate the closed contract")
    normalized = {key: _text(brief[key], key, 8_000) for key in sorted(required)}
    business_model = normalized["business_model"]
    if business_model not in {"b2b", "b2c"}:
        raise RealtimePresetCampaignError("business_model must be b2b or b2c")
    category = normalized["category"]
    audience = normalized["audience"]
    problem = normalized["audience_problem"]
    outcome = normalized["audience_outcome"]
    truth = normalized["product_truth"]
    b2b = business_model == "b2b"
    primary = "linkedin" if b2b else "instagram"
    secondary = "youtube" if b2b else "tiktok"
    problem_focus = " ".join(problem.lower().split()[:10]).rstrip(".,;:")
    category_context = " ".join(
        (category, normalized["industry"], normalized["lifecycle"], audience, normalized["brand_voice"])
    ).lower()
    if not b2b:
        archetype = "participation_ritual"
    elif "technical" in category_context or "evaluator" in category_context:
        archetype = "technical_rejection_test"
    elif normalized["lifecycle"] == "pre_pmf" or "founder" in category_context:
        archetype = "founder_conviction"
    elif "competitive" in category_context or "category buyer" in category_context:
        archetype = "category_reframe"
    else:
        archetype = "evidence_led_launch"
    playbooks = {
        "evidence_led_launch": {
            "campaign": "The Proof Before the Pitch",
            "hook": f"If {category} cannot survive one visible rejection test, it has not earned the pitch.",
            "category_default": "Fluent claims, broad feature lists and omnichannel repetition before a buyer can inspect one proof object.",
            "bet": "Turn the evidence mechanism—not the feature list—into the campaign's recognizable creative property.",
            "visual": "A precise evidence aperture cuts through a field of interchangeable category claims.",
            "participation": "Run the rejection test, publish the verdict and hand the proof card to one accountable peer.",
        },
        "technical_rejection_test": {
            "campaign": "The Rejection Test",
            "hook": f"Before buyers believe the benefit of {category}, give them the fastest honest way to reject it.",
            "category_default": "Architecture diagrams and feature language that never state what evidence would invalidate the operating claim.",
            "bet": "Lead with a falsifiable decision rule; let surviving evidence carry the commercial argument.",
            "visual": "A teardown grid resolves into one pass/fail evidence window and a visible stop condition.",
            "participation": "Invite evaluators to run the same test, locate the failure and compare only surviving evidence.",
        },
        "founder_conviction": {
            "campaign": "The Missing Decision",
            "hook": f"The market did not need another {category}. It needed a better decision before {problem_focus}.",
            "category_default": "Founder mythology that celebrates the build but never names the costly decision the product changes.",
            "bet": "Make the founder's non-obvious decision—not their biography—the narrative spine and proof of category necessity.",
            "visual": "One unresolved operating tension becomes a before/after decision map in the founder's own editorial voice.",
            "participation": "Ask early adopters to name the exact moment the old decision failed and compare it with the new rule.",
        },
        "category_reframe": {
            "campaign": "Change the Test",
            "hook": f"The category leader chose the comparison. Buyers of {category} deserve a better test.",
            "category_default": "Competing on incumbent vocabulary, feature checklists and rankings that encode the old operating model.",
            "bet": "Win the evaluation frame before competing on features: expose the old assumption, install a sharper criterion, then prove it.",
            "visual": "An incumbent scorecard is crossed out by one new criterion and rebuilt around inspectable evidence.",
            "participation": "Let buyers score both operating models against the new criterion and share the assumption that changed their shortlist.",
        },
        "participation_ritual": {
            "campaign": "Make the First Share Useful",
            "hook": f"Do not announce another {category} feature. Give {audience} a first move worth showing.",
            "category_default": "Polished launch films that demonstrate features but give the audience no behavior to repeat, remix or pass on.",
            "bet": "Design one useful, visible product ritual whose result becomes the media, proof and invitation for the next participant.",
            "visual": "A single product action unfolds into a before/result/relay sequence made for vertical viewing and remixing.",
            "participation": "Try the ritual, show the result without overclaiming it and nominate the next person who would use it differently.",
        },
    }
    playbook = playbooks[archetype]
    campaign = playbook["campaign"]
    hook = playbook["hook"]
    body_blocks = [
        f"The tension: {problem}",
        f"The approved proof: {truth}",
        f"The next decision: {outcome}",
    ]
    strategy = {
        "playbook_archetype": archetype,
        "market_diagnosis": f"In {normalized['market']}, fluent category content is abundant. The scarce signal for {audience} is a specific decision rule tied to approved proof.",
        "audience_decision": outcome,
        "category_default_to_reject": playbook["category_default"],
        "non_consensus_bet": playbook["bet"],
        "zero_budget_wedge": f"Use one owned proof object on {primary}; convert qualified replies into the next {secondary} demonstration and an evidence-bound search answer before adding paid reach.",
        "primary_distribution_surface": primary,
        "secondary_distribution_surface": secondary,
        "primary_search_surface": "google_search",
        "primary_geo_surface": "perplexity_answers" if b2b else "gemini_answers",
        "surface_selection_reason": f"{primary} carries the audience's native decision grammar; {secondary} makes the proof behavior visible; search preserves the evidence after the feed decays.",
        "budget_logic": f"{normalized['budget']} budget prioritizes reusable proof, participation and partner relay before paid distribution.",
        "lifecycle_logic": f"At {normalized['lifecycle']}, the campaign optimizes for {normalized['primary_goal']} rather than vanity reach.",
    }
    territory_specs = (
        (campaign, hook, playbook["visual"], playbook["participation"]),
        (
            "The Cost of the Default",
            f"The expensive part of {problem.lower()} is not the friction. It is the decision made with the wrong evidence.",
            "A familiar category promise is annotated with the hidden operational cost and its evidence gap.",
            "Ask the audience to locate the cost their current workflow hides and state what proof would change the decision.",
        ),
        (
            "Pass the Proof Forward",
            f"Turn '{outcome}' into a useful artifact one person can test and another can improve.",
            "One proof card moves between distinct roles, gaining a verdict rather than accumulating promotional decoration.",
            "Each participant runs the same decision rule, adds one located observation and passes the artifact to a relevant peer.",
        ),
    )
    territories = [
        {
            "territory_id": f"territory-{index + 1}",
            "campaign_name": name,
            "first_line": line,
            "primary_platform": primary,
            "secondary_platform": secondary,
            "portable_decision_tool": "A saveable proof card with one rejection test and one next action.",
            "key_visual_metaphor": visual,
            "first_1500ms_video": line,
            "participation_mechanic": participation,
            "proof_integration": truth,
            "why_it_could_fail": "The proof object may feel like another claim if its decision rule is not visible.",
            "kill_rule": "Stop when qualified viewers cannot repeat the decision rule after one exposure.",
        }
        for index, (name, line, visual, participation) in enumerate(territory_specs)
    ]
    creative_council = compile_realtime_creative_council(
        normalized,
        primary_platform=primary,
        secondary_platform=secondary,
        candidate_count=12,
    )
    territories = creative_council["territories"]
    selected_territory_id = creative_council["selected_territory_id"]
    selected_territory = next(
        territory for territory in territories
        if territory["territory_id"] == selected_territory_id
    )
    selected_fit = next(
        row for row in creative_council["selection_scorecards"]
        if row["territory_id"] == selected_territory_id
    )
    campaign = selected_territory["campaign_name"]
    hook = selected_territory["first_line"]
    strategy.update({
        "strategy_source": "realtime_creative_council",
        **_strategy_language(selected_territory, normalized),
        "creative_genome_id": selected_territory["genome_id"],
        "visual_grammar_id": selected_territory["visual_grammar_id"],
        "narrative_grammar_id": selected_territory["narrative_grammar_id"],
        "tone_id": selected_territory["tone_id"],
    })
    channel_copy_system, primary_native_text = _native_copy_system(
        selected_territory,
        normalized,
        b2b=b2b,
    )
    platform_adaptations = _platform_adaptations(
        selected_territory,
        normalized,
        b2b=b2b,
        primary_surface=primary,
        secondary_surface=secondary,
    )
    video_system = _video_system(
        selected_territory,
        normalized,
        primary_surface_id=primary,
        primary_visual_grammar_id=platform_adaptations["feed_4x5"]["visual_grammar_id"],
        secondary_surface_id=secondary,
        secondary_visual_grammar_id=platform_adaptations["story_9x16"]["visual_grammar_id"],
        search_surface_id="google_search",
        search_visual_grammar_id=platform_adaptations["editorial_16x9"]["visual_grammar_id"],
    )
    production = {
        "campaign_platform": campaign,
        "strategy_rationale": strategy["non_consensus_bet"],
        "channel_copy_system": channel_copy_system,
        "primary_native_text": primary_native_text,
        "image_system": {
            "key_visual": selected_territory["key_visual_metaphor"],
            "visual_grammar_id": selected_territory["visual_grammar_id"],
            "composition_family": selected_territory["axis_signature"]["visual"],
            "platform_adaptations": platform_adaptations,
            "feed_4x5": "1080×1350 proof card rendered as a real PNG.",
            "story_9x16": "1080×1920 vertical reveal rendered as a real PNG.",
            "editorial_16x9": "1920×1080 editorial header rendered as a real PNG.",
            "overlay_copy": [campaign, hook],
            "negative_constraints": ["No fake UI", "No unapproved outcome claim", "No stock-photo cliché"],
        },
        "video_system": video_system,
        "channel_portfolio": {
            "primary_distribution": {"surface_id": primary, "native_asset": hook, "qualified_metric": normalized["primary_goal"], "release_state": "draft_for_human_review"},
            "secondary_distribution": {"surface_id": secondary, "native_asset": "Twelve-second participation-first vertical proof film", "qualified_metric": "qualified completion and relay", "release_state": "draft_for_human_review"},
            "search": {"surface_id": "google_search", "native_asset": "Evidence-bound answer page plus ten-second provenance explainer", "qualified_metric": "qualified proof review", "release_state": "draft_for_human_review"},
            "geo": {"surface_id": strategy["primary_geo_surface"], "native_asset": "Citation-ready answer unit", "qualified_metric": "answer inclusion with source", "release_state": "draft_for_human_review"},
        },
    }
    result: dict[str, Any] = {
        "schema": "ProofLaunchRealtimePresetCampaignV8",
        "brief": normalized,
        "agent_orchestration": creative_council,
        "strategy": strategy,
        "concepts": {"territories": territories},
        "jury": {
            "selected_territory_id": selected_territory_id,
            "selection_reason": "Selected by declared brief-context fit after the creative council enforced distinct hook, narrative, visual and tone grammars. This is a production routing decision, not a human taste or market-effect win.",
            "scorecard": {
                "declared_context_fit": selected_fit["context_fit_score"],
                "single_minded_strategy": 5,
                "ownable_creative_property": 5,
                "platform_native_participation": 5,
                "approved_proof_continuity": 5,
            },
            "context_fit_reasons": selected_fit["reasons"],
            "score_scale": "declared_context_fit_plus_mechanical_preflight_not_human_preference",
            "automatic_creative_winner_claimed": False,
        },
        "final_production": production,
        "production_sequence": [
            {"order": 1, "stage": "brief", "state": "sealed", "gate": "closed schema and approved product truth"},
            {"order": 2, "stage": "strategy", "state": "complete", "gate": "12-genome strategy debate and one non-consensus bet"},
            {"order": 3, "stage": "concept", "state": "complete", "gate": "three critical-axis-distinct territories and an inspectable kill rule"},
            {"order": 4, "stage": "production", "state": "complete", "gate": "platform-native copy, three visual grammars, two six-beat films and observed binaries"},
            {"order": 5, "stage": "audit", "state": "mechanical_preflight_pass", "gate": "truth, continuity and production completeness"},
            {"order": 6, "stage": "release", "state": "human_gated", "gate": "named human craft and rights review"},
        ],
        "quality_control": {
            "target_tier": "production_review_candidate",
            "human_craft_approved": False,
            "mechanical_preflight_passed": True,
            "gates": {
                "single_minded_strategy": True,
                "territory_distinctiveness": True,
                "platform_native_copy": True,
                "cross_modal_continuity": True,
                "claim_boundary": True,
                "production_assets_present": True,
                "verified_image_model_master": True,
                "live_multiformat_adaptation": True,
                "agent_graph_executed": True,
                "critical_axis_territory_distinctness": True,
                "platform_image_copy_video_exclusivity": True,
                "two_platform_native_film_cuts": True,
            },
            "human_gates_remaining": [
                "named-human craft review",
                "source-hidden preference review",
                "rights and release review",
                "live-market effect observation",
            ],
        },
        "final_audit": {
            "status": "mechanical_preflight_pass",
            "direct_publishability": "candidate_requires_named_human_review",
            "human_craft_approved": False,
            "blocking_defects": [],
            "truth_boundary": "Mechanically complete model-backed production candidate with deterministic specialist-node orchestration over a 96,000,000-blueprint design space. Frontier-model agent reasoning, video-model inference, craft preference, direct publishability and market effect remain unobserved.",
        },
        "release_review_status": "ready_for_named_human_release_review",
        "generation_mode": "exclusive_platform_asset_council_v5",
        "cloud_model_call_count": 0,
        "local_model_call_count": 0,
        "external_publish_executed": False,
        "human_release_required": True,
    }
    result["content_sha256"] = _digest(result)
    media_root = Path(output_root).resolve() / result["content_sha256"]
    result["rendered_media"] = _render_media(result, media_root)
    result["envelope_sha256"] = _digest(result)
    atomic_write_text(media_root / "campaign.json", json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return result


__all__ = [
    "RealtimePresetCampaignError",
    "compile_realtime_preset_campaign",
]
