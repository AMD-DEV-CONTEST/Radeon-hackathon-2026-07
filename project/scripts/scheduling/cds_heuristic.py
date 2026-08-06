# project/scripts/scheduling/cds_heuristic.py
"""
R.A.G.E. Phase 3 - Module 3: Multi-Arm Flow Shop Scheduling (CDS Heuristic)

Purpose
-------
Robot A holds the GPU block still (active fixturing) for the whole
insertion pass; Robot B is the one doing sequential work, so the actual
scheduling problem lives entirely on Robot B's task queue: in what order
should it insert the 3 cables (red/blue/yellow) to minimize total
completion time (makespan) and idle time between stages?

We model each cable insertion as a job that passes through 3 sequential
*stages* (not to be confused with the two robot arms):
    Stage 1 - Approach   : move from current pose to pre-insertion hover
                            pose above the target port
    Stage 2 - Insert      : execute the contact-rich insertion motion
    Stage 3 - Verify      : hold + confirm seating (vision/force check)
Every job (cable) passes through every stage in the same order (1 -> 2 ->
3), on the *same* physical resource (Robot B) at each stage - which is
exactly the classical flow-shop scheduling assumption. Different cables
take different amounts of time per stage (e.g. the triangle port's tighter
tolerance makes Insert slower for the yellow cable), so the ORDER in which
Robot B processes the 3 cables changes the total makespan.

Algorithm: Campbell-Dudek-Smith (CDS) heuristic
------------------------------------------------
CDS extends Johnson's exact 2-machine algorithm to m >= 2 machines. It is
a heuristic (not guaranteed exactly optimal for m > 2) but is fast,
deterministic, and produces strong solutions in practice - a good fit for
a real-time-ish robotics scheduler.

For an m-machine problem, CDS builds (m - 1) auxiliary 2-machine problems,
indexed by k = 1 .. m-1:
    machine A_k(job) = sum of that job's processing times over stages 1..k
    machine B_k(job) = sum of that job's processing times over stages
                        (m-k+1)..m
Johnson's algorithm is run on each of these (m-1) two-machine problems,
producing (m-1) candidate job sequences. Each candidate sequence's TRUE
makespan is then evaluated against the *original* m-stage problem, and the
sequence with the lowest true makespan is returned.

Johnson's algorithm (used internally for each k)
--------------------------------------------------
Given 2-machine processing times (a_j, b_j) per job j:
  1. Split jobs into Set U = {j : a_j <= b_j} and Set V = {j : a_j > b_j}.
  2. Sort Set U ascending by a_j; sort Set V descending by b_j.
  3. Final sequence = Set U (ascending) followed by Set V (descending).
This is provably optimal for the true 2-machine flow-shop problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


# --------------------------------------------------------------------------- #
# Job / task schema
# --------------------------------------------------------------------------- #

STAGE_NAMES = ["approach", "insert", "verify"]


@dataclass
class InsertionJob:
    """One cable's full insertion task, with per-stage processing time (in
    simulated seconds) on Robot B."""
    job_id: str          # e.g. "cable_1_red"
    port_label: str      # e.g. "port_1_red_square"
    stage_times: List[float]  # length == len(STAGE_NAMES), same order

    def total_work(self) -> float:
        return sum(self.stage_times)


# Mock per-cable stage timings. Differences here are intentional and
# reflect the physical scene: the yellow/triangle port has the tightest
# angular tolerance (slowest Insert + Verify), the blue/circle port is the
# most forgiving (rotationally symmetric, fastest Insert), matching
# PORT_ROTATIONS / port geometry in server_assembly.py.
MOCK_JOBS: List[InsertionJob] = [
    InsertionJob(job_id="cable_1_red", port_label="port_1_red_square",
                 stage_times=[2.0, 3.5, 1.5]),   # square: moderate insert difficulty
    InsertionJob(job_id="cable_2_blue", port_label="port_2_blue_circle",
                 stage_times=[1.8, 2.5, 1.0]),   # circle: rotationally forgiving, fastest insert
    InsertionJob(job_id="cable_3_yellow", port_label="port_3_yellow_triangle",
                 stage_times=[2.2, 4.0, 2.0]),   # triangle: tightest tolerance, slowest insert+verify
]


# --------------------------------------------------------------------------- #
# Johnson's algorithm (exact, 2-machine case)
# --------------------------------------------------------------------------- #

def johnsons_algorithm(job_ids: List[str],
                        machine_a_times: Dict[str, float],
                        machine_b_times: Dict[str, float]) -> List[str]:
    """Return the optimal job sequence for a 2-machine flow-shop problem,
    per Johnson's rule."""
    set_u = [j for j in job_ids if machine_a_times[j] <= machine_b_times[j]]
    set_v = [j for j in job_ids if machine_a_times[j] > machine_b_times[j]]

    set_u.sort(key=lambda j: machine_a_times[j])                 # ascending on machine A
    set_v.sort(key=lambda j: machine_b_times[j], reverse=True)   # descending on machine B

    return set_u + set_v


# --------------------------------------------------------------------------- #
# True makespan evaluation for an m-stage flow shop
# --------------------------------------------------------------------------- #

def compute_makespan(sequence: List[str], jobs_by_id: Dict[str, InsertionJob]
                      ) -> Tuple[float, List[List[float]]]:
    """Compute the true completion-time matrix for `sequence` run through
    all stages, using the standard flow-shop recurrence:

        C[i][0] = C[i-1][0] + t[i][0]
        C[i][j] = max(C[i-1][j], C[i][j-1]) + t[i][j]

    where i indexes position-in-sequence and j indexes stage. Returns
    (makespan, completion_time_matrix) - the matrix is handy for computing
    per-stage idle time afterward.
    """
    n_stages = len(STAGE_NAMES)
    n_jobs = len(sequence)
    completion = [[0.0] * n_stages for _ in range(n_jobs)]

    for i, job_id in enumerate(sequence):
        times = jobs_by_id[job_id].stage_times
        for j in range(n_stages):
            same_job_prev_stage = completion[i][j - 1] if j > 0 else 0.0
            prev_job_same_stage = completion[i - 1][j] if i > 0 else 0.0
            start = max(same_job_prev_stage, prev_job_same_stage)
            completion[i][j] = start + times[j]

    makespan = completion[-1][-1]
    return makespan, completion


def compute_idle_time(completion: List[List[float]]) -> float:
    """Total idle time summed across all stages: gaps where a stage's
    resource (Robot B, at that stage) is waiting on the previous job to
    clear the previous stage."""
    n_jobs = len(completion)
    n_stages = len(completion[0]) if n_jobs else 0
    idle = 0.0
    for j in range(n_stages):
        prev_end = 0.0
        for i in range(n_jobs):
            stage_duration = completion[i][j] - (completion[i][j - 1] if j > 0 else
                                                   (completion[i - 1][j] if i > 0 else 0.0))
            start = completion[i][j] - stage_duration
            if i > 0:
                idle += max(0.0, start - prev_end)
            prev_end = completion[i][j]
    return idle


# --------------------------------------------------------------------------- #
# Campbell-Dudek-Smith heuristic
# --------------------------------------------------------------------------- #

@dataclass
class ScheduleResult:
    sequence: List[str]           # ordered job_ids - Robot B's pick order
    makespan: float
    idle_time: float
    k_used: int                   # which CDS sub-problem index produced this sequence
    completion_matrix: List[List[float]]


def cds_heuristic(jobs: List[InsertionJob]) -> ScheduleResult:
    """Run the full CDS heuristic over `jobs` and return the best sequence
    found (lowest TRUE makespan across all (m-1) candidate sequences)."""
    jobs_by_id = {job.job_id: job for job in jobs}
    job_ids = [job.job_id for job in jobs]
    n_stages = len(STAGE_NAMES)

    if n_stages < 2:
        raise ValueError("CDS heuristic requires at least 2 stages/machines.")

    best_result: ScheduleResult | None = None

    for k in range(1, n_stages):  # k = 1 .. m-1
        # Auxiliary 2-machine problem for this k:
        #   machine A = sum of stage times [0 .. k-1]  (first k stages)
        #   machine B = sum of stage times [m-k .. m-1] (last k stages)
        machine_a_times = {
            job_id: sum(jobs_by_id[job_id].stage_times[0:k])
            for job_id in job_ids
        }
        machine_b_times = {
            job_id: sum(jobs_by_id[job_id].stage_times[n_stages - k:n_stages])
            for job_id in job_ids
        }

        candidate_sequence = johnsons_algorithm(job_ids, machine_a_times, machine_b_times)
        makespan, completion = compute_makespan(candidate_sequence, jobs_by_id)
        idle = compute_idle_time(completion)

        print(f"[cds_heuristic] k={k}: sequence={candidate_sequence} "
              f"-> true makespan={makespan:.2f}s, idle={idle:.2f}s")

        if best_result is None or makespan < best_result.makespan:
            best_result = ScheduleResult(
                sequence=candidate_sequence,
                makespan=makespan,
                idle_time=idle,
                k_used=k,
                completion_matrix=completion,
            )

    assert best_result is not None
    return best_result


# --------------------------------------------------------------------------- #
# Convenience wrapper for Phase 4's run_pipeline.py
# --------------------------------------------------------------------------- #

def schedule_cable_insertions(jobs: List[InsertionJob] = None) -> ScheduleResult:
    """Entry point Phase 4's pipeline should call: takes the detected/
    known cable insertion jobs and returns Robot B's optimized pick order.
    Defaults to MOCK_JOBS so this can be called before real per-cable
    timing estimates exist (e.g. before the vision pipeline + a motion-
    planner cost model can populate real stage_times).
    """
    jobs = jobs if jobs is not None else MOCK_JOBS
    return cds_heuristic(jobs)


# --------------------------------------------------------------------------- #
# Standalone test block
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    print("=" * 70)
    print("[cds_heuristic] Standalone test")
    print("=" * 70)

    print("\nInput jobs (Robot B insertion tasks):")
    for job in MOCK_JOBS:
        print(f"    {job.job_id:16s} -> {job.port_label:24s} "
              f"stage_times(approach/insert/verify)={job.stage_times} "
              f"total_work={job.total_work():.2f}s")

    print(f"\nRunning CDS heuristic across k=1..{len(STAGE_NAMES) - 1} "
          f"auxiliary 2-machine sub-problems...\n")

    result = schedule_cable_insertions()

    print("\n" + "-" * 70)
    print(f"[cds_heuristic] BEST sequence found (from k={result.k_used}):")
    print(f"    Robot B pick order : {' -> '.join(result.sequence)}")
    print(f"    Predicted makespan : {result.makespan:.2f}s")
    print(f"    Total idle time    : {result.idle_time:.2f}s")
    print("-" * 70)

    # Sanity checks so this test block doubles as a regression guard.
    assert set(result.sequence) == {job.job_id for job in MOCK_JOBS}, \
        "Schedule must include every job exactly once"
    assert result.makespan > 0
    # Makespan can never be less than the single longest job's total work,
    # nor less than the sum of any one stage's total processing time
    # across all jobs (that stage is a hard bottleneck).
    stage_totals = [sum(job.stage_times[s] for job in MOCK_JOBS) for s in range(len(STAGE_NAMES))]
    assert result.makespan >= max(stage_totals) - 1e-6, \
        "Makespan cannot be less than the busiest single stage's total load"

    print("\n[cds_heuristic] OK: valid schedule produced and sanity-checked.")