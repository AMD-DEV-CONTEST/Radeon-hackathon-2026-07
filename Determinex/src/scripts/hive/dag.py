"""
scripts/hive/dag.py — Topological sort and DAG invalidation
============================================================
Moved from determinex_hive.py (lines ~1295-1459).
"""

from __future__ import annotations

import logging
from collections import deque

from hive.manifest import ManifestSession, StepRecord

log = logging.getLogger("hive")


def topological_sort(
    steps: list[StepRecord],
) -> tuple[list[int | list[int]], list[list[int]]]:
    """
    Kahn's algorithm topological sort on the step DAG.

    Returns (execution_order, cycle_groups).

    execution_order:
        A list where each element is either:
          - an int (a single step ID to execute alone), or
          - a list[int] (a co-dependent group that must compile atomically).

    cycle_groups:
        Each inner list is a set of step IDs that form a dependency cycle.
    """
    id_map = {s.id: s for s in steps}
    in_deg = {s.id: 0 for s in steps}
    adj: dict[int, list[int]] = {s.id: [] for s in steps}

    for s in steps:
        for dep in s.depends_on:
            if dep in id_map:
                adj[dep].append(s.id)
                in_deg[s.id] += 1

    # ── Phase 1: standard Kahn's — peel off all acyclic nodes ──────────
    queue = deque(sid for sid, deg in in_deg.items() if deg == 0)
    linear_order: list[int] = []

    while queue:
        node = queue.popleft()
        linear_order.append(node)
        for nbr in adj[node]:
            in_deg[nbr] -= 1
            if in_deg[nbr] == 0:
                queue.append(nbr)

    # ── Phase 2: identify cycle groups via Tarjan-style SCC ────────────
    remaining = {s.id for s in steps} - set(linear_order)
    cycle_groups: list[list[int]] = []

    if remaining:
        cycle_adj: dict[int, list[int]] = {sid: [] for sid in remaining}
        for sid in remaining:
            for dep in id_map[sid].depends_on:
                if dep in remaining:
                    cycle_adj[dep].append(sid)

        # Kosaraju's SCC
        visited: set[int] = set()
        finish_order: list[int] = []

        # G29: iterative DFS — Python recursion limit (~1000) would crash on large DAGs
        def _dfs_forward_iter(start: int) -> None:
            stack = [start]
            while stack:
                n = stack[-1]
                if n not in visited:
                    visited.add(n)
                # Push unvisited neighbours; when we pop a fully-explored node
                # (all neighbours already visited), append to finish_order.
                pushed = False
                for nbr in cycle_adj.get(n, []):
                    if nbr not in visited:
                        stack.append(nbr)
                        pushed = True
                        break
                if not pushed:
                    finish_order.append(stack.pop())

        for sid in sorted(remaining):
            if sid not in visited:
                _dfs_forward_iter(sid)

        # Build reverse adjacency
        rev_adj: dict[int, list[int]] = {sid: [] for sid in remaining}
        for u in remaining:
            for v in cycle_adj[u]:
                rev_adj[v].append(u)

        visited.clear()
        components: list[list[int]] = []

        def _dfs_reverse_iter(start: int, comp: list[int]) -> None:
            stack = [start]
            while stack:
                n = stack.pop()
                if n in visited:
                    continue
                visited.add(n)
                comp.append(n)
                for nbr in rev_adj.get(n, []):
                    if nbr not in visited:
                        stack.append(nbr)

        for sid in reversed(finish_order):
            if sid not in visited:
                comp: list[int] = []
                _dfs_reverse_iter(sid, comp)
                components.append(sorted(comp))

        cycle_groups = [g for g in components if len(g) > 1]
        singletons = [g[0] for g in components if len(g) == 1]

        if cycle_groups:
            log.warning(
                "DAG CYCLE DETECTED: %d co-dependent group(s): %s "
                "— each group will compile as a single atomic unit",
                len(cycle_groups),
                cycle_groups,
            )

        if singletons:
            log.info(
                "DAG: %d nodes were blocked by cycle groups, appending after groups",
                len(singletons),
            )

    # ── Phase 3: build the unified execution_order ─────────────────────
    execution_order: list[int | list[int]] = list(linear_order)

    for group in cycle_groups:
        execution_order.append(group)

    if remaining:
        singletons_set = remaining - {sid for g in cycle_groups for sid in g}
        for sid in sorted(singletons_set):
            execution_order.append(sid)

    return execution_order, cycle_groups


def build_execution_waves(
    steps: list[StepRecord],
    execution_order: list[int | list[int]],
) -> list[list[int | list[int]]]:
    """
    Convert a flat topological execution order into parallel waves.

    Items within a wave have no dependencies on each other and can run
    concurrently.  Items in wave N depend only on items in waves 0..N-1.

    Used by run_session() to populate a ThreadPoolExecutor when
    hw_profile.max_parallel_steps > 1 (Tier 1+ only — Tier 0 gets a single
    wave per step, which is identical to the previous sequential loop).

    Returns: list of waves; each wave is a list of items (int or list[int]).
    """
    id_map = {s.id: s for s in steps}

    # Assign each step a wave level: max(dep wave levels) + 1, or 0 if no deps.
    wave_level: dict[int, int] = {}

    def _level(step_id: int) -> int:
        if step_id in wave_level:
            return wave_level[step_id]
        step = id_map.get(step_id)
        if step is None:
            wave_level[step_id] = 0
            return 0
        # Only count deps that are in execution_order (cycles handled separately)
        deps = [d for d in step.depends_on if d in id_map and d != step_id]
        lv = (max(_level(d) for d in deps) + 1) if deps else 0
        wave_level[step_id] = lv
        return lv

    for item in execution_order:
        ids = item if isinstance(item, list) else [item]
        # For co-dependent groups: all members share the same wave level —
        # the max across their external deps (deps outside the group).
        group_set = set(ids)
        ext_deps = [
            d
            for sid in ids
            for d in (id_map[sid].depends_on if id_map.get(sid) else [])
            if d in id_map and d not in group_set
        ]
        group_lv = (max(_level(d) for d in ext_deps) + 1) if ext_deps else 0
        for sid in ids:
            wave_level[sid] = group_lv

    max_lv = max(wave_level.values(), default=0)
    waves: list[list[int | list[int]]] = [[] for _ in range(max_lv + 1)]

    seen_groups: set[int] = set()
    for item in execution_order:
        if isinstance(item, list):
            oid = id(item)
            if oid not in seen_groups:
                seen_groups.add(oid)
                lv = wave_level.get(item[0], 0)
                waves[lv].append(item)
        else:
            lv = wave_level.get(item, 0)
            waves[lv].append(item)

    return [w for w in waves if w]


def flag_stale_downstream(session: ManifestSession, changed_step_id: int) -> int:
    """
    After a successful Architect re-plan that changes the public API,
    flag all TRANSITIVELY downstream steps as stale_instruction.
    Returns count of flagged steps.
    """
    id_set = {s.id for s in session.steps}
    fwd: dict[int, list[int]] = {s.id: [] for s in session.steps}
    for s in session.steps:
        for dep in s.depends_on:
            if dep in id_set:
                fwd[dep].append(s.id)

    # BFS from changed_step_id
    visited: set[int] = set()
    queue = deque(fwd.get(changed_step_id, []))
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        queue.extend(fwd.get(node, []))

    flagged = 0
    for step in session.steps:
        if step.id in visited and step.status not in ("complete",):
            step.status = "stale_instruction"
            flagged += 1
            log.warning(
                "Step %d flagged stale_instruction (transitively downstream of step %d)",
                step.id,
                changed_step_id,
            )
    return flagged
