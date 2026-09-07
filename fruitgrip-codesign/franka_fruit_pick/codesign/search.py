"""CMA-ES driver over the end-effector design space.

Project brief S4: the design space is mixed continuous / discrete / categorical with
conditional dependencies (curvature only means something given >=2 segments; finger
count is categorical). Candidates are scored by physics simulation -> a
non-differentiable score. That combination rules out gradient-based design
optimization by construction, so this is black-box, population-based search
(CMA-ES) -- not a compromise, the correct method for this problem.

Finger count (categorical, {2, 3}) is handled as an *outer* loop: one independent
CMA-ES run per finger count, each searching the continuous sub-space (finger_length,
curvature_deg, aperture, compliance). CMA-ES itself only ever sees continuous,
roughly-unit-scaled vectors (each bound mapped to [0, 1]).

Diversity/niching (S6/A2, "premature morphological convergence"): a bonus term is
added to the fitness CMA-ES optimizes against (not to the reported fitness) equal to
each candidate's normalized parameter-space distance to the running elite archive.
This is reported separately in the result so the true (un-niched) fitness stays the
number used for ranking/reporting.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import cma  # noqa: E402
import numpy as np  # noqa: E402

from controller_adapt import CLOSE_FORCE_BOUNDS, HEIGHT_OFFSET_BOUNDS, ControllerParams  # noqa: E402
from evaluate import CandidateResult, DEFAULT_TRIAL_SEEDS, evaluate_candidate  # noqa: E402
from gripper_gen import (  # noqa: E402
    APERTURE_BOUNDS,
    COMPLIANCE_BOUNDS,
    CURVATURE_DEG_BOUNDS,
    FINGER_LENGTH_BOUNDS,
    GripperParams,
)

_BOUNDS = [FINGER_LENGTH_BOUNDS, CURVATURE_DEG_BOUNDS, APERTURE_BOUNDS, COMPLIANCE_BOUNDS]
_DIM = len(_BOUNDS)

_CONTROLLER_BOUNDS = [CLOSE_FORCE_BOUNDS, HEIGHT_OFFSET_BOUNDS]
_CONTROLLER_DIM = len(_CONTROLLER_BOUNDS)

NICHE_WEIGHT = 0.15  # weight of the diversity bonus fed to the optimizer (not to the reported fitness)


def _to_unit(x: np.ndarray) -> np.ndarray:
    return np.array([(x[i] - lo) / (hi - lo) for i, (lo, hi) in enumerate(_BOUNDS)])


def _from_unit(u: np.ndarray, n_fingers: int) -> GripperParams:
    u = np.clip(u, 0.0, 1.0)
    vals = [lo + u[i] * (hi - lo) for i, (lo, hi) in enumerate(_BOUNDS)]
    return GripperParams(n_fingers=n_fingers, finger_length=vals[0], curvature_deg=vals[1], aperture=vals[2], compliance=vals[3])


@dataclass
class SearchLogEntry:
    generation: int
    n_fingers: int
    params: GripperParams
    fitness: float
    niched_fitness: float
    agg: dict
    build_seconds: float
    trial_seconds: float
    controller: ControllerParams | None = None


@dataclass
class BranchResult:
    n_fingers: int
    log: list = field(default_factory=list)  # list[SearchLogEntry]
    best: CandidateResult | None = None
    best_controller: ControllerParams | None = None  # only set by run_controller_search


def _diversity_bonus(u: np.ndarray, archive: list) -> float:
    if not archive:
        return 1.0  # first candidate in an empty archive is maximally "novel"
    dists = [float(np.linalg.norm(u - a)) for a in archive]
    return min(dists) / np.sqrt(_DIM)  # normalize by the unit hypercube's diagonal scale


def run_branch(
    n_fingers: int, *, population: int, generations: int, sigma0: float = 0.3,
    trial_seeds: tuple[int, ...] = DEFAULT_TRIAL_SEEDS, seed: int = 0, log_fn=print,
    controller: ControllerParams | None = None,
) -> BranchResult:
    """`controller=None` (default): joint search -- each candidate's controller is
    analytically co-adapted from its own geometry (see controller_adapt.py). Pass a
    fixed `controller` (e.g. `controller_adapt.BASELINE_CONTROLLER`) for the
    attribution experiment's "geometry-only" arm (S7): geometry varies, controller
    does not.
    """
    x0 = np.full(_DIM, 0.5)
    es = cma.CMAEvolutionStrategy(
        x0, sigma0,
        {"popsize": population, "bounds": [0.0, 1.0], "seed": seed, "verbose": -9},
    )

    branch = BranchResult(n_fingers=n_fingers)
    elite_archive: list = []  # unit-space vectors of the top candidates seen so far

    gen = 0
    while gen < generations and not es.stop():
        us = es.ask()
        raw_fitnesses = []
        for u in us:
            u = np.asarray(u)
            params = _from_unit(u, n_fingers)
            result = evaluate_candidate(params, trial_seeds=trial_seeds, controller=controller)
            niche_bonus = _diversity_bonus(u, elite_archive)
            niched = result.fitness + NICHE_WEIGHT * niche_bonus
            raw_fitnesses.append(-niched)  # cma minimizes

            branch.log.append(SearchLogEntry(
                generation=gen, n_fingers=n_fingers, params=params, fitness=result.fitness,
                niched_fitness=niched, agg=vars(result.agg),
                build_seconds=result.build_seconds, trial_seconds=result.trial_seconds,
            ))
            if branch.best is None or result.fitness > branch.best.fitness:
                branch.best = result

            log_fn(
                f"[gen {gen}] n_fingers={n_fingers} {params.key()} "
                f"len={params.finger_length:.3f} curv={params.curvature_deg:.1f} "
                f"aper={params.aperture:.3f} compl={params.compliance:.2f} "
                f"-> success={result.agg.success_rate:.2f} fitness={result.fitness:.3f} (niched {niched:.3f})"
            )

        # Update the elite archive with this generation's best candidate (keeps the
        # niching bonus meaningful across generations without an unbounded archive).
        best_idx = int(np.argmax([f for f in (-np.array(raw_fitnesses))]))
        elite_archive.append(np.asarray(us[best_idx]))

        es.tell(us, raw_fitnesses)
        gen += 1

    return branch


def run_search(
    *, population: int = 4, generations: int = 2, trial_seeds: tuple[int, ...] = DEFAULT_TRIAL_SEEDS,
    finger_counts: tuple[int, ...] = (2, 3), log_fn=print, controller: ControllerParams | None = None,
    cma_seed_offset: int = 0,
) -> dict:
    branches = {}
    for nf in finger_counts:
        log_fn(f"=== branch n_fingers={nf}: population={population} generations={generations} ===")
        branches[nf] = run_branch(
            nf, population=population, generations=generations, trial_seeds=trial_seeds, seed=nf + cma_seed_offset,
            log_fn=log_fn, controller=controller,
        )
    return branches


def _controller_from_unit(u: np.ndarray) -> ControllerParams:
    u = np.clip(u, 0.0, 1.0)
    vals = [lo + u[i] * (hi - lo) for i, (lo, hi) in enumerate(_CONTROLLER_BOUNDS)]
    return ControllerParams(close_force=vals[0], height_offset=vals[1])


def run_controller_search(
    geometry: GripperParams, *, population: int = 5, generations: int = 5, sigma0: float = 0.3,
    trial_seeds: tuple[int, ...] = DEFAULT_TRIAL_SEEDS, seed: int = 0, log_fn=print,
) -> BranchResult:
    """Attribution experiment's "controller-only" arm (S7): geometry is held fixed at
    `geometry` (the baseline design); only the controller (close_force, height_offset)
    is searched. Same CMA-ES machinery as the geometry search, just over the 2D
    controller space instead -- an apples-to-apples black-box search budget for a fair
    comparison against the geometry-only and joint arms.
    """
    x0 = np.full(_CONTROLLER_DIM, 0.5)
    es = cma.CMAEvolutionStrategy(
        x0, sigma0,
        {"popsize": population, "bounds": [0.0, 1.0], "seed": seed, "verbose": -9},
    )

    branch = BranchResult(n_fingers=geometry.n_fingers)
    elite_archive: list = []

    gen = 0
    while gen < generations and not es.stop():
        us = es.ask()
        raw_fitnesses = []
        for u in us:
            u = np.asarray(u)
            controller = _controller_from_unit(u)
            result = evaluate_candidate(geometry, trial_seeds=trial_seeds, controller=controller)
            niche_bonus = _diversity_bonus(u, elite_archive)
            niched = result.fitness + NICHE_WEIGHT * niche_bonus
            raw_fitnesses.append(-niched)

            branch.log.append(SearchLogEntry(
                generation=gen, n_fingers=geometry.n_fingers, params=geometry, fitness=result.fitness,
                niched_fitness=niched, agg=vars(result.agg),
                build_seconds=result.build_seconds, trial_seconds=result.trial_seconds, controller=controller,
            ))
            if branch.best is None or result.fitness > branch.best.fitness:
                branch.best = result
                branch.best_controller = controller

            log_fn(
                f"[gen {gen}] controller-only close_force={controller.close_force:.2f} "
                f"height_offset={controller.height_offset*1000:.1f}mm "
                f"-> success={result.agg.success_rate:.2f} fitness={result.fitness:.3f} (niched {niched:.3f})"
            )

        best_idx = int(np.argmax(-np.array(raw_fitnesses)))
        elite_archive.append(np.asarray(us[best_idx]))
        es.tell(us, raw_fitnesses)
        gen += 1

    return branch
