#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_free_cloud_router import compile_free_cloud_execution_plan


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "config/cortex_x_v10_frontier_api_panel.json"
OUTPUT = ROOT / "evidence/v10/free-cloud-execution-plan-v2.json"


def _present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def main() -> int:
    panel = json.loads(PANEL.read_text(encoding="utf-8"))
    credential_names = sorted(
        {
            str(row["api_key_env"])
            for row in panel["candidates"]
            if row.get("access_class") == "zero_cost_rate_limited"
        }
    )
    credential_state = {name: _present(name) for name in credential_names}
    auxiliary_state = {
        "CLOUDFLARE_ACCOUNT_ID": _present("CLOUDFLARE_ACCOUNT_ID"),
        "LIGHTNING_FREE_ONLY_ACK": os.environ.get("LIGHTNING_FREE_ONLY_ACK", "").strip() == "1",
    }
    compute_session_state = {
        name: _present(name)
        for name in (
            "KAGGLE_API_TOKEN",
            "KAGGLE_USERNAME",
            "KAGGLE_KEY",
            "LIGHTNING_API_KEY",
            "MODELSCOPE_NOTEBOOK_SESSION_READY",
            "MODAL_TOKEN_ID",
            "MODAL_TOKEN_SECRET",
            "HF_TOKEN",
            "HF_ZEROGPU_SPACE_READY",
            "GOOGLE_COLAB_SESSION_READY",
            "NVIDIA_LAUNCHPAD_SESSION_READY",
            "SAGEMAKER_STUDIO_LAB_ACCOUNT_READY",
        )
    }
    compute_session_state.update(
        {
            "KAGGLE_CONFIG_PRESENT": (Path.home() / ".kaggle/kaggle.json").is_file(),
            "MODAL_CONFIG_PRESENT": (Path.home() / ".modal.toml").is_file(),
        }
    )
    plan = compile_free_cloud_execution_plan(
        panel,
        credential_state=credential_state,
        auxiliary_state=auxiliary_state,
        compute_session_state=compute_session_state,
        observed_at=date.today().isoformat(),
    )
    plan["panel_sha256"] = sha256_file(PANEL)
    plan["secret_values_persisted"] = False
    plan["credential_environment_present"] = credential_state
    plan["auxiliary_environment_present"] = auxiliary_state
    plan["compute_session_signals_present"] = compute_session_state
    atomic_write_text(OUTPUT, json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": plan["status"],
                "api_roles_ready": f'{plan["ready_api_role_count"]}/{plan["possible_api_role_count"]}',
                "selected_api_candidates": plan["selected_api_candidate_count"],
                "selected_weight_training_route": plan["selected_weight_training_route"],
                "selected_short_inference_route": plan["selected_short_inference_route"],
                "secret_values_persisted": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
