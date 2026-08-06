"""ScrewShell hardware-adaptive autotune — L1/L2 planning + L3 runtime governor.

L1 SkillPack  -> screwshell/autotune/skillpack.py
L2 detection + planning -> screwshell/autotune/hardware.py, planner.py
L2 guardrails -> screwshell/autotune/doctor.py, tuner.py
L3 runtime governor -> screwshell/autotune/governor.py
                     (mode select / step clustering / gear machine / lifecycle)

Stdlib-only (no torch/CUDA) so it runs on the deploy host (where rocm-smi
lives) and in local unit tests with a mocked profile.
"""
from screwshell.autotune.hardware import (
    HardwareProfile, detect, QUANT_VRAM_GB, BASE_MODEL,
)
from screwshell.autotune.skillpack import (
    SkillPack, scan_skillpacks, build_skill_map,
)
from screwshell.autotune.planner import plan, PlanResult, CANONICAL_SKILLS
from screwshell.autotune.doctor import preflight, PreflightReport
from screwshell.autotune.tuner import resolve, DeploymentSpec
from screwshell.autotune.governor import (
    Governor, GovernorConfig, GovernorAction, RuntimeMetrics,
    SwapStep, SwapPlan, select_mode, cluster_steps, LlamaServerLifecycle,
)

__all__ = [
    "HardwareProfile", "detect", "SkillPack", "scan_skillpacks",
    "build_skill_map", "plan", "PlanResult", "CANONICAL_SKILLS",
    "QUANT_VRAM_GB", "BASE_MODEL", "preflight", "PreflightReport",
    "resolve", "DeploymentSpec",
    "Governor", "GovernorConfig", "GovernorAction", "RuntimeMetrics",
    "SwapStep", "SwapPlan", "select_mode", "cluster_steps",
    "LlamaServerLifecycle",
]
