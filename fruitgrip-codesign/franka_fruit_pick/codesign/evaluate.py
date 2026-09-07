"""Multi-trial candidate scoring: build once per gripper design, run a *fixed* trial
set (shared across every candidate and the baseline -- project brief S6/A4) under the
stock demo's existing Layer-B runtime domain randomization (friction/mass -- S6/A3,
"the optimizer will exploit the physics engine" defense), and reduce to one fitness
number via reward.py.

Build cost (scene compile) is paid once per distinct gripper geometry; per-trial cost
is just `EnvRandomizer.reset()` + one scripted episode on the already-built scene.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import numpy as np  # noqa: E402

import genesis as gs  # noqa: E402

from build_scene import build_scene  # noqa: E402
from grasp_demo import TaskSpec  # noqa: E402
from randomize import DomainRandomizationConfig, RandomizationConfig, EnvRandomizer  # noqa: E402

from controller_adapt import ControllerParams, adapt_grasp_profile  # noqa: E402
from gripper_gen import GripperParams, generate_gripper_xml  # noqa: E402
from reward import TrialAggregate, aggregate_trials, fitness  # noqa: E402
from sim_episode import GripperRuntime, run_pick_place  # noqa: E402

# Fixed trial-instance seeds shared by *every* candidate and the baseline (S6/A4:
# identical task instances, identical trial count -- an asymmetry here would let a
# competent judge dismantle the central claim in one question). Each seed drives both
# the object-pose jitter and the (randomize_pick=True) task-object choice via
# EnvRandomizer, so the set already spans multiple pick objects deterministically.
DEFAULT_TRIAL_SEEDS: tuple[int, ...] = (100, 101, 102)

# Layer-B domain randomization: on for every scored trial (A3 defense -- a design that
# only works at exactly nominal friction/mass is not a design we want to reward).
DEFAULT_DR = DomainRandomizationConfig(enabled=True, friction_ratio_range=(0.7, 1.3), mass_ratio_range=(0.8, 1.2))

# Overridable module-level default backend (session 4, ROCm benchmark): lets a driver
# script flip every existing search/attribution call site (search.py, run_attribution.py,
# run_attribution_multiseed.py) onto the GPU backend via `evaluate.DEFAULT_BACKEND =
# gs.amdgpu` before calling them, without threading a new parameter through the whole
# call chain -- none of those callers pass `backend=` explicitly today.
DEFAULT_BACKEND = None  # None -> gs.cpu, resolved lazily in evaluate_candidate (gs isn't guaranteed importable at import time on every host)


@dataclass
class CandidateResult:
    params: GripperParams
    xml_path: str
    agg: TrialAggregate
    fitness: float
    build_seconds: float
    trial_seconds: float
    per_trial_success: list = field(default_factory=list)
    per_trial_pick_object: list = field(default_factory=list)
    per_trial_peak_force: list = field(default_factory=list)
    per_trial_max_slip: list = field(default_factory=list)
    per_trial_contact_uptime: list = field(default_factory=list)


def evaluate_candidate(
    params: GripperParams, *, trial_seeds: tuple[int, ...] = DEFAULT_TRIAL_SEEDS, backend=None,
    save_frames_dir: Path | None = None, controller: ControllerParams | None = None,
    force_pick_object: str | None = None,
) -> CandidateResult:
    """`force_pick_object`: session 5 addition -- deterministically forces every trial
    in this call to the given object (instead of `EnvRandomizer`'s random per-trial
    pick), by temporarily narrowing `randomize.RELIABLE_PICK_POOL` to a single-object
    tuple. Used to build a per-object-STRATIFIED sequential reference that is directly
    comparable to the batched pipeline's per-object grouping (see
    evaluate_candidate_grouped / evaluate_candidate_batched below) -- a fair batched-
    vs-sequential parity check needs both sides evaluating the *same* per-object trial
    split, not independently-random pool sampling on one side only.
    """
    import randomize as randomize_mod

    params = params.clipped()
    xml_path = generate_gripper_xml(params)

    gs.init(backend=backend or DEFAULT_BACKEND or gs.cpu)
    t0 = time.time()
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=save_frames_dir is not None, add_wrist_cam=False, franka_xml_path=str(xml_path))
    build_seconds = time.time() - t0

    rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))
    orig_pool = randomize_mod.RELIABLE_PICK_POOL
    if force_pick_object is not None:
        randomize_mod.RELIABLE_PICK_POOL = (force_pick_object,)
    randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=force_pick_object is None, dr=DEFAULT_DR))

    metrics_list = []
    per_trial_success, per_trial_pick = [], []
    per_trial_peak_force, per_trial_max_slip, per_trial_contact_uptime = [], [], []
    t1 = time.time()
    for seed in trial_seeds:
        task: TaskSpec = randomizer.reset(seed=seed)
        profile = adapt_grasp_profile(params, task.pick_object, controller=controller)
        save_frames = save_frames_dir is not None
        m = run_pick_place(bundle, rt, task, profile, save_frames=save_frames)
        metrics_list.append(m)
        per_trial_success.append(m.success)
        per_trial_pick.append(task.pick_object)
        per_trial_peak_force.append(m.peak_contact_force)
        per_trial_max_slip.append(m.max_slip)
        per_trial_contact_uptime.append(m.contact_uptime_frac)
        if save_frames_dir is not None:
            import imageio.v2 as imageio

            out = save_frames_dir / params.key() / f"seed{seed}_{task.pick_object}"
            out.mkdir(parents=True, exist_ok=True)
            for tag, img in m.frames:
                imageio.imwrite(out / f"{tag}.png", img)
    trial_seconds = time.time() - t1
    randomize_mod.RELIABLE_PICK_POOL = orig_pool

    agg = aggregate_trials(metrics_list)
    result = CandidateResult(
        params=params, xml_path=str(xml_path), agg=agg, fitness=fitness(agg),
        build_seconds=build_seconds, trial_seconds=trial_seconds,
        per_trial_success=per_trial_success, per_trial_pick_object=per_trial_pick,
        per_trial_peak_force=per_trial_peak_force, per_trial_max_slip=per_trial_max_slip,
        per_trial_contact_uptime=per_trial_contact_uptime,
    )
    gs.destroy()
    return result


def _merge_candidate_results(params: GripperParams, xml_path, parts: list[CandidateResult], build_seconds: float, trial_seconds: float) -> CandidateResult:
    """Concatenate several per-object CandidateResults (from evaluate_candidate_grouped
    / evaluate_candidate_batched's per-object calls) into one aggregate, matching what
    a single evaluate_candidate(trial_seeds=<all seeds>) call would have produced."""
    per_trial_success = [s for p in parts for s in p.per_trial_success]
    per_trial_pick = [o for p in parts for o in p.per_trial_pick_object]
    per_trial_peak_force = [f for p in parts for f in p.per_trial_peak_force]
    per_trial_max_slip = [s for p in parts for s in p.per_trial_max_slip]
    per_trial_contact_uptime = [u for p in parts for u in p.per_trial_contact_uptime]

    agg = TrialAggregate(
        n_trials=len(per_trial_success),
        success_rate=float(np.mean(per_trial_success)) if per_trial_success else 0.0,
        mean_contact_uptime=float(np.mean(per_trial_contact_uptime)) if per_trial_contact_uptime else 0.0,
        mean_peak_force=float(np.mean(per_trial_peak_force)) if per_trial_peak_force else 0.0,
        mean_max_slip=float(np.mean(per_trial_max_slip)) if per_trial_max_slip else 0.0,
    )
    return CandidateResult(
        params=params, xml_path=str(xml_path), agg=agg, fitness=fitness(agg),
        build_seconds=build_seconds, trial_seconds=trial_seconds,
        per_trial_success=per_trial_success, per_trial_pick_object=per_trial_pick,
        per_trial_peak_force=per_trial_peak_force, per_trial_max_slip=per_trial_max_slip,
        per_trial_contact_uptime=per_trial_contact_uptime,
    )


def evaluate_candidate_grouped(
    params: GripperParams, seeds_by_object: dict[str, list[int]], *, backend=None,
    controller: ControllerParams | None = None,
) -> CandidateResult:
    """Sequential (n_envs=1) reference for the batched pipeline: evaluates the SAME
    per-object trial split as evaluate_candidate_batched (object -> deterministic
    seed list, forced via force_pick_object rather than random pool sampling), one
    object at a time, then merges. This -- not the original random-pool
    evaluate_candidate -- is the correct apples-to-apples comparison for a batched-
    vs-sequential parity check, since it isolates "batched execution vs sequential
    execution" as the only difference between the two paths.
    """
    params = params.clipped()
    xml_path = generate_gripper_xml(params)
    t0 = time.time()
    parts = []
    for obj, seeds in seeds_by_object.items():
        parts.append(evaluate_candidate(params, trial_seeds=tuple(seeds), backend=backend, controller=controller, force_pick_object=obj))
    total_wall = time.time() - t0
    build_seconds = sum(p.build_seconds for p in parts)
    trial_seconds = sum(p.trial_seconds for p in parts)
    result = _merge_candidate_results(params, xml_path, parts, build_seconds, trial_seconds)
    result.trial_seconds = total_wall  # wall-clock across the whole grouped call, for fair timing comparison
    return result


def evaluate_candidate_batched(
    params: GripperParams, seeds_by_object: dict[str, list[int]], *, backend=None,
    controller: ControllerParams | None = None,
) -> CandidateResult:
    """Batched counterpart of evaluate_candidate_grouped -- one Genesis scene per
    object, built with n_envs = len(seeds_by_object[object]), stepping all of that
    object's trials in lockstep instead of sequentially. See batched_episode.py.
    """
    from batched_episode import BatchEnvRandomizer, run_pick_place_batched

    params = params.clipped()
    xml_path = generate_gripper_xml(params)
    t0_total = time.time()

    parts = []
    total_build_seconds = 0.0
    for obj, seeds in seeds_by_object.items():
        n_envs = len(seeds)
        gs.init(backend=backend or DEFAULT_BACKEND or gs.cpu)
        t0 = time.time()
        bundle = build_scene(show_viewer=False, n_envs=n_envs, add_world_cam=False, add_wrist_cam=False, franka_xml_path=str(xml_path))
        total_build_seconds += time.time() - t0

        rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))
        randomizer = BatchEnvRandomizer(bundle, n_envs, RandomizationConfig(randomize_pick=False, dr=DEFAULT_DR))
        task = randomizer.reset(obj, seeds)
        profile = adapt_grasp_profile(params, obj, controller=controller)
        m = run_pick_place_batched(bundle, rt, task, profile)

        agg = TrialAggregate(
            n_trials=n_envs, success_rate=float(np.mean(m.success)),
            mean_contact_uptime=float(np.mean(m.contact_uptime_frac)),
            mean_peak_force=float(np.mean(m.peak_contact_force)), mean_max_slip=float(np.mean(m.max_slip)),
        )
        parts.append(CandidateResult(
            params=params, xml_path=str(xml_path), agg=agg, fitness=fitness(agg),
            build_seconds=total_build_seconds, trial_seconds=0.0,
            per_trial_success=list(m.success), per_trial_pick_object=[obj] * n_envs,
            per_trial_peak_force=list(m.peak_contact_force), per_trial_max_slip=list(m.max_slip),
            per_trial_contact_uptime=list(m.contact_uptime_frac),
        ))
        gs.destroy()

    total_wall = time.time() - t0_total
    result = _merge_candidate_results(params, xml_path, parts, total_build_seconds, total_wall)
    return result
