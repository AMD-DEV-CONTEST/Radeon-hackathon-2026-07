"""Shared helpers for HighwayEnv DQN demos."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gymnasium as gym
import highway_env
import imageio.v2 as imageio
import numpy as np
import torch

from safety import REWARD_PROFILES, SafetyRewardWrapper


ACTION_NAMES = {
    0: "LANE_LEFT",
    1: "IDLE",
    2: "LANE_RIGHT",
    3: "FASTER",
    4: "SLOWER",
}

_RUN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class RunPaths:
    """All artifacts for one experiment live under a single run directory."""

    run_name: str
    root: Path
    models: Path
    metrics: Path
    videos: Path
    tensorboard: Path
    meta_path: Path

    def ensure(self) -> "RunPaths":
        for path in (self.root, self.models, self.metrics, self.videos):
            path.mkdir(parents=True, exist_ok=True)
        return self


def sanitize_run_name(name: str) -> str:
    name = name.strip().replace(" ", "_")
    if not name or not _RUN_NAME_RE.match(name):
        raise ValueError(
            f"Invalid --run-name {name!r}. "
            "Use letters/digits/._- and start with alphanumeric."
        )
    return name


def make_run_name(explicit: str | None = None, *, prefix: str | None = None) -> str:
    """
    Build a run id under outputs/runs/.

    - explicit given: use it as-is (after sanitize). Reusing the same name
      overwrites that run's artifacts on purpose.
    - omitted: `<YYYYMMDD_HHMMSS>` or `<YYYYMMDD_HHMMSS>_<prefix>`
    """
    if explicit:
        return sanitize_run_name(explicit)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if prefix:
        return f"{stamp}_{sanitize_run_name(prefix)}"
    return stamp


def resolve_run_paths(
    run_name: str,
    *,
    outputs_root: Path | str = "outputs",
) -> RunPaths:
    run_name = sanitize_run_name(run_name)
    root = Path(outputs_root) / "runs" / run_name
    return RunPaths(
        run_name=run_name,
        root=root,
        models=root / "models",
        metrics=root / "metrics",
        videos=root / "videos",
        tensorboard=root / "tensorboard",
        meta_path=root / "run_meta.json",
    )


def find_run_from_model(model_path: Path) -> RunPaths | None:
    """If model lives under outputs/runs/<name>/models/, return that run."""
    path = Path(model_path).resolve()
    parts = path.parts
    if "runs" not in parts:
        return None
    idx = parts.index("runs")
    if idx + 1 >= len(parts):
        return None
    run_name = parts[idx + 1]
    outputs_root = Path(*parts[:idx]) if idx > 0 else Path("outputs")
    # Prefer relative outputs/ when cwd is the demo root.
    try:
        outputs_root = Path("outputs") if (Path("outputs") / "runs" / run_name).exists() else outputs_root
    except OSError:
        pass
    return resolve_run_paths(run_name, outputs_root=outputs_root)


def write_run_meta(
    run: RunPaths,
    *,
    stage: str,
    argv: list[str],
    params: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> None:
    """Create or update run_meta.json so experiments stay attributable."""
    run.ensure()
    existing: dict[str, Any] = {}
    if run.meta_path.exists():
        try:
            existing = json.loads(run.meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    history = list(existing.get("history", []))
    history.append({"stage": stage, "at": now, "argv": argv})

    meta = {
        **existing,
        "run_name": run.run_name,
        "root": str(run.root),
        "updated_at": now,
        "created_at": existing.get("created_at", now),
        "last_stage": stage,
        "params": {**existing.get("params", {}), **params},
        "artifacts": {
            "models": str(run.models),
            "metrics": str(run.metrics),
            "videos": str(run.videos),
            "tensorboard": str(run.tensorboard),
        },
        "history": history,
    }
    if extra:
        meta.update(extra)

    run.meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_run_dirs(outputs_root: Path | str = "outputs") -> list[Path]:
    runs_root = Path(outputs_root) / "runs"
    if not runs_root.exists():
        return []
    return sorted(
        [p for p in runs_root.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )


def setup_headless_runtime() -> Path:
    """Avoid XDG/SDL warnings on headless cloud instances."""
    runtime_dir = Path("/tmp/highway-runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.chmod(0o700)
    os.environ.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    return runtime_dir


def resolve_device(device: str) -> str:
    """Resolve cuda/cpu/auto and validate AMD ROCm availability when needed."""
    requested = device.lower()
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA/HIP device requested, but torch.cuda.is_available() is False. "
                "Install the ROCm PyTorch wheel from the platform image."
            )
        return "cuda"
    if requested == "cpu":
        return "cpu"
    raise ValueError(f"Unsupported device: {device}")


def print_rocm_info(device: str) -> None:
    print("=== AMD ROCm Environment ===")
    print("PyTorch:", torch.__version__)
    print("HIP:", torch.version.hip)
    print("Requested device:", device)
    print("GPU available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
        print("GPU count:", torch.cuda.device_count())


def normalize_model_path(path: Path) -> Path:
    """Return a path without a trailing .zip; SB3 save/load adds it."""
    path = Path(path)
    return path.with_suffix("") if path.suffix == ".zip" else path


def model_zip_path(path: Path) -> Path:
    """Return the on-disk zip path corresponding to an SB3 model stem."""
    stem = normalize_model_path(path)
    return stem.with_suffix(".zip")


def monitor_csv_path(path: Path) -> Path:
    """
    Force a filename that ends with monitor.csv.

    Stable-Baselines3 appends `.monitor.csv` unless the filename already
    ends with that suffix.
    """
    path = Path(path)
    name = path.name
    if name.endswith("monitor.csv"):
        return path
    if name.endswith(".csv"):
        return path.with_name(name[: -len(".csv")] + ".monitor.csv")
    return path.with_name(name + ".monitor.csv")


def create_highway_env(
    *,
    duration: int = 20,
    vehicles: int = 30,
    render_mode: str | None = None,
    seed: int | None = None,
    reward_profile: str = "baseline",
) -> gym.Env:
    """Build a HighwayEnv instance wrapped with TTC safety instrumentation.

    ``reward_profile`` selects one of ``safety.REWARD_PROFILES``. Every
    profile attaches ``SafetyRewardWrapper`` so that safety metrics are always
    recorded; only the shaping term and the collision reward differ.
    """
    if reward_profile not in REWARD_PROFILES:
        raise ValueError(
            f"Unknown reward profile: {reward_profile}. "
            f"Available: {sorted(REWARD_PROFILES)}"
        )
    profile = REWARD_PROFILES[reward_profile]

    gym.register_envs(highway_env)

    kwargs: dict[str, Any] = {}
    if render_mode is not None:
        kwargs["render_mode"] = render_mode

    env = gym.make("highway-fast-v0", **kwargs)
    env.unwrapped.configure(
        {
            "duration": duration,
            "vehicles_count": vehicles,
            "simulation_frequency": 15,
            "policy_frequency": 5,
            "screen_width": 960,
            "screen_height": 240,
            "offscreen_rendering": True,
            "show_trajectories": False,
            "normalize_reward": profile["normalize_reward"],
            "collision_reward": profile["collision_reward"],
        }
    )

    env = SafetyRewardWrapper(env, shaping=profile["shaping"])

    if seed is not None:
        env.reset(seed=seed)

    return env


def write_video(path: Path, frames: list[np.ndarray], fps: int = 5) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    writer = imageio.get_writer(
        path,
        fps=fps,
        codec="libx264",
        quality=8,
        macro_block_size=2,
    )
    try:
        for frame in frames:
            writer.append_data(frame)
    finally:
        writer.close()
