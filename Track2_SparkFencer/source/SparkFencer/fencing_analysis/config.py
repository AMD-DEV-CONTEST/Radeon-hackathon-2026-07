import os

import yaml

DEFAULT_CONFIG = {
    "language": "zh",     # zh | en — output language for scorecard/report text
    "weapon": "general",  # general | epee | foil | sabre
    "pose": {
        "model": "weights/yolo11s-pose.pt",
        "conf": 0.25,
        "device": "auto",
    },
    "blade": {
        "enabled": True,
        "detector": "cv",    # cv | yolo | pose (learned detectors require model_path)
        "model_path": None,  # fine-tuned YOLO box / YOLO-Pose blade model
        "imgsz": 1280,       # blade-model inference size; use ~native res for thin tips
        "filter": "kalman",  # kalman | ema | none — tip smoothing method
        "ema_alpha": 0.45,
    },
    "piste": {
        "length": 14.0,
        "width": 1.5,
    },
    "scene_gate": {
        # Skip frames that are not the main bout camera (broadcast cutaways).
        # Reference = piste-region histogram, locked when both fencers first
        # stand on the piste. Disable for fixed-camera training videos if the
        # gate ever misfires.
        "enabled": True,
    },
    "footwork": {
        "advance_speed": 0.35,     # m/s along-piste hip speed to call advance/retreat
        "smooth_window_sec": 0.25,
        "lunge_spread_jump": 0.45,  # sudden ankle-spread increase (m) within lunge_window
        "lunge_window_sec": 0.5,
        "lunge_min_elbow_deg": 140.0,
        "min_segment_sec": 0.16,
    },
    "actions": {
        "extension_elbow_deg": 150.0,
        "min_extension_gain_deg": 16.0,
        "attack_min_speed": 0.4,
        "attack_min_closing_speed": 0.12,
        "attack_window_sec": 0.45,
        "defense_window_sec": 0.75,
        "defense_wrist_multiplier": 2.1,
        "defense_retreat_speed": 0.25,
        "min_counter_delay_sec": 0.10,
        "min_gap_sec": 0.6,
        # Blade-tip corroboration (calibrated against real detections.jsonl:
        # attack/counter/parry median tip-forward-speed peaks were ~6.5/5.3/3.9 m/s).
        # Only trusted when enough of the window has a confident tip fix.
        "tip_min_coverage": 0.35,
        "attack_tip_reach_boost_px": 60.0,
        "defense_tip_counter_speed": 4.5,
        "defense_tip_strong_counter_speed": 6.0,
    },
    "reaction": {
        "onset_speed": 0.5,        # opponent movement onset threshold (m/s)
        "response_window_sec": 1.2,
        "min_reaction_sec": 0.12,  # below human reaction floor -> tracking noise
    },
    "phrase": {
        "activity_speed": 0.25,
        "max_gap_sec": 1.5,
        "min_phrase_sec": 1.0,
    },
    "evidence": {
        "max_keyframes": 4,
        "max_events_per_type": 6,
    },
    "privacy": {
        "local_only": True,
        "audit_log": "outputs/.audit/agent_tools.jsonl",
    },
    "agents": {
        "backend": "local",  # local by default; claude is opt-in development only
        "claude": {
            "model": "claude-opus-4-8",
            "max_tokens": 4000,
        },
        "local": {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen3-vl:32b",
            "api_key": "none",
            "max_tokens": 4000,
            "timeout": 1200,
        },
        # Embedding service for RAG (knowledge base + session archive search).
        # Configured independently from agents.local — e.g. the VLM/chat model
        # can run on llama.cpp while embeddings still come from ollama, or vice versa.
        "rag": {
            "provider": "ollama",  # ollama (/api/embed) | llama.cpp (/v1/embeddings)
            "base_url": "http://127.0.0.1:11434",
            "model": "bge-m3",
        },
        # 本地 32B VLM 约 2.5 分钟/次调用（含思考），事件数别设太大；
        # Claude API 后端每次仅数秒，可放宽。用 --max-events 覆盖。
        "max_events_to_review": 8,
    },
}


def _deep_merge(base, override):
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path=None):
    config = DEFAULT_CONFIG
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(DEFAULT_CONFIG, user_config)
    return config
