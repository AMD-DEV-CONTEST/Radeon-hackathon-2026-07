#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_human_capability_kernel import (
    compile_gtm_human_capability_kernel,
)


DEFAULT_OUTPUT = ROOT / "evidence/v10/gtm-human-capability-kernel-v2.json"
DEFAULT_DOC = ROOT / "docs/product/GTM_HUMAN_CAPABILITY_KERNEL_V2.md"
INPUTS = {
    "team_capability_matrix": ROOT / "evidence/v10/gtm-team-capability-matrix-v1.json",
    "craft_handoff_matrix": ROOT / "evidence/v10/gtm-craft-handoff-matrix-v1.json",
    "adaptive_capability_graph": ROOT / "evidence/v10/gtm-adaptive-capability-graph-matrix-v1.json",
    "open_source_radar": ROOT / "config/gtm_open_source_capability_radar_v1.json",
}


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"unsafe or missing input: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"input must be a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render_markdown(payload: Mapping[str, Any]) -> str:
    coverage = payload["coverage"]
    lines = [
        "# GTM human-capability kernel V2",
        "",
        "This is the executable professional-capability layer for the 4A GTM employee. It expands role labels into inspectable skill contracts while keeping model, provider and hardware replaceable.",
        "",
        "## Sealed coverage",
        "",
        f"- Functional squads: **{coverage['functional_squad_count']}**",
        f"- Professional roles: **{coverage['role_count']}**",
        f"- Atomic professional skills: **{coverage['professional_skill_card_count']}**",
        f"- Execution axes: **{coverage['professional_axis_count']:,}** ({coverage['professional_axes_per_skill']} per skill)",
        f"- Evaluation checks: **{coverage['eval_check_count']:,}** ({coverage['eval_checks_per_skill']} per skill)",
        f"- KPI bindings: **{coverage['kpi_binding_count']:,}**",
        f"- Deterministic staffing contexts: **{coverage['staffing_context_count']}**",
        f"- Public distribution/search/GEO surfaces: **{coverage['surface_count']}**",
        f"- Surface specialist lenses: **{coverage['surface_specialist_lens_count']}**",
        f"- Non-consensus high-leverage edge-play cards: **{coverage['unconventional_edge_play_card_count']}**",
        f"- Referenced pinned OSS projects: **{payload['open_source_composition']['referenced_project_count']}**",
        "- Automatic external actions: **0**",
        "",
        "The 10× detail claim is mechanical: each of 220 skill names expands into exactly ten professional execution axes and ten evaluation checks. It is not a craft or effect claim.",
        "",
        "## Functional team",
        "",
        "| Squad | Mission | Roles |",
        "|---|---|---:|",
    ]
    for squad in payload["functional_squads"]:
        lines.append(
            f"| `{squad['squad_id']}` | {squad['mission']} | {len(squad['role_ids'])} |"
        )
    lines.extend(
        [
            "",
            "## Platform-specific last mile",
            "",
            "Each surface has four separate professional lenses: platform strategy, native copy editing, creative direction and organic-breakout analysis. A candidate does not pass merely because one generic agent likes it.",
            "",
            "Each of the 13 surfaces also has distinct B2B and B2C non-consensus edge-play cards. These cards optimize for unusually strong hooks, progression, participation and proof while explicitly prohibiting fake identity, manufactured engagement, spam, undisclosed automation, promise mismatch and access-control bypass.",
            "",
            "| Surface | Type | Native format contract |",
            "|---|---|---|",
        ]
    )
    for surface in payload["surface_operating_system"]["playbooks"]:
        lines.append(
            f"| `{surface['surface_id']}` | {surface['category']} | {surface['native_format_contract']} |"
        )
    lines.extend(
        [
            "",
            "## Architecture",
            "",
            "`diagnose → research → strategize → design_system → produce → prepare_release → human_release → observe → learn_next_cycle`",
            "",
            "The campaign remains single-writer and depth-first. Only independent research may fan out. Each node uses a bounded evaluator-optimizer loop, deterministic assertions, tamper-evident traces and human approval before external action.",
            "",
            "## Evidence boundary",
            "",
            payload["truth_boundary"],
            "",
            "Current comparative state remains **0 authorized named-product baselines, 0 completed named-product PK rows and 0 wins**. No 4A, organic-breakout, conversion or revenue claim is promoted by this structural artifact.",
            "",
        ]
    )
    return "\n".join(lines)


def compile_from_files() -> dict[str, Any]:
    loaded = {key: _load(path) for key, path in INPUTS.items()}
    source_hashes = {
        path.relative_to(ROOT).as_posix(): _sha256(path) for path in INPUTS.values()
    }
    return compile_gtm_human_capability_kernel(
        team_matrix=loaded["team_capability_matrix"],
        craft_matrix=loaded["craft_handoff_matrix"],
        adaptive_graph=loaded["adaptive_capability_graph"],
        open_source_radar=loaded["open_source_radar"],
        source_file_sha256=source_hashes,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    args = parser.parse_args()
    payload = compile_from_files()
    atomic_write_text(
        args.output,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(args.doc, _render_markdown(payload))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "doc": str(args.doc),
                "role_count": payload["coverage"]["role_count"],
                "skill_card_count": payload["coverage"]["professional_skill_card_count"],
                "professional_axis_count": payload["coverage"]["professional_axis_count"],
                "eval_check_count": payload["coverage"]["eval_check_count"],
                "surface_count": payload["coverage"]["surface_count"],
                "surface_specialist_lens_count": payload["coverage"]["surface_specialist_lens_count"],
                "unconventional_edge_play_card_count": payload["coverage"]["unconventional_edge_play_card_count"],
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
