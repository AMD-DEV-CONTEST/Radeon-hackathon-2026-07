#!/usr/bin/env python3
"""Verify the weight-free Qwen3-32B Agentic SFT source bundle.

This verifier is intentionally CPU-only and standard-library-only.  It proves
that the copied sources and compact execution evidence are byte-identical to
the AMD formal run, that the frozen data/plan contracts still match, and that
no model/checkpoint payload was accidentally bundled.  It does not claim that
ROCm training can run on the local macOS host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


EXPECTED_FILES = {
    "artifacts/model-acquisition/qwen3-32b-bnb-7f721e74-verification.json": "5f8b675142ee4d2e6a968e756c1da6546f59dcfd34ed997ef23d95211feb7b0d",
    "artifacts/training-plan/qwen3-32b-agentic-loss-window-plan-v1.json": "7ef449cb41f37f5d32d4562c336aba4e3cb8f01b506850a93d34bccef6260afb",
    "artifacts/training-plan/qwen3-32b-agentic-train-plan-v1.json": "39d6ae20fcb566d6544049e2ea263c5bc64fe8ecd349c71b4a8ec58721134f25",
    "configs/guarded_process_controller_v7.py": "8f598ff868952eb46a94031bec27ca41085518258fd039d9e47a75b7d22a0cb0",
    "configs/qwen3_32b_agentic_formal_trainer_v2_cachebounded.py": "44978c4a386f638688a3ffdea30cf7595565489c1249a7d380343b26638a8edd",
    "configs/qwen3_agentic_common.py": "d0159dd2ab96961ea116dc4264833a65a98d63421a21c798aa70dcc8bfcb9f7f",
    "evidence/checkpoint-000010/COMPLETE": "acda17a28cbcfc122e72f3c5f6a40e4c0e950f382b2af536b0cdae558b2b4ac5",
    "evidence/checkpoint-000010/manifest.json": "bb1d0a5a6dd28107987e92796d1a6b823c8772046c099aaf0eb74bf956655016",
    "evidence/checkpoint-000010/state.json": "dfab5480b74154dae94872372f086fff7d19beb8271c39b6c791661ef729b8cf",
    "evidence/checkpoint-000119/COMPLETE": "2d4579b6c2b0b73e8962a274591cb07377572ea1a59ecf906d69ebd4b11127ba",
    "evidence/checkpoint-000119/manifest.json": "8e21e476dc8d756804425d1f863fd7308ca4712c666c431fd74e026322522481",
    "evidence/checkpoint-000119/state.json": "dd956ee9c5e76bcd562b12bcba71a2f38a0564cf459008ae5431dd5c69887382",
    "evidence/formal-restart-authorization.json": "58915505bc17184a5f7eabafe909c634c9476ac944747824c116143e04acd789",
    "evidence/launch/launch-binding.json": "e7df96730178a47b1220a859ffa8e3c1d4bdd30b71509ec2d4dc64f205b3a2ad",
    "evidence/launch/phase1-launch.json": "7f257aba2b90db45dc4fb6e3305d46fa83000f9632f22e12c9dd23255dfbf16d",
    "evidence/launch/phase2-launch-binding.json": "f7143688d76f47dde494b16df4518ebf389019095cdba673abcb0cabedcc9f8f",
    "evidence/launch/phase2-launch.json": "e1b8ff2ff3590cb0fda4fcae2b8a2489fdfdab4bdf11dd2b087973fb2cf09c30",
    "evidence/launch/resume-ack-phase2.json": "99c53cfbf644a548d36dcdef44a0b35782488ef90b29754e3ba26691c4508371",
    "evidence/phase1-controller/controller-result.json": "83721b28b9a4d93cde2ce291b8e36995a9ea2d000569842f8fc571f7ea85d574",
    "evidence/phase1-controller/gate-result.json": "af5f885e10abf43e5bb26001685854c92254ebdfc8c35d2f830ad8162b31a663",
    "evidence/phase2-controller/controller-result.json": "9e053fa610ea0668cc08e719899bbf6dbd8127c93c8ec8a0c9f2d856c66ee076",
    "evidence/phase2-controller/gate-result.json": "5a070ec6d5c5a08a4ef0bb2f4c546c9b74b91ebb824fb40edae86666007cf305",
    "evidence/preflight-gates/step-000006-controller/controller-result.json": "2dea6ec944c8d6d4575d2086113e25f5dfe286446150ad2e64b82b96edaa21ea",
    "evidence/preflight-gates/step-000006-controller/gate-result.json": "e13d5c64d8416ffd09a0b8836574c4fda78a6415fd32d4409e3b551af50eb83c",
    "evidence/preflight-gates/step-000006-controller/telemetry.jsonl": "3b2a08bb652bda716a89e1ccd5b5f153d85e9a4fb336ee4e10efa04a90df9654",
    "evidence/preflight-gates/step-000006-launch.json": "e3cc1f526f460f7a24d6d91c180b521d292c6f89a94cb8027148da9671b27f88",
    "evidence/preflight-gates/step-000032-controller/controller-result.json": "ea659578678d6ae7e5dff5baaf37e7ab54b245a4dbb20ba449b5acf11b27bf2e",
    "evidence/preflight-gates/step-000032-controller/gate-result.json": "cdfd96ee0cd1dfde2f35f20383556500c2a83e6a7d5392e8ab493de50cbe13f1",
    "evidence/preflight-gates/step-000032-controller/telemetry.jsonl": "d6fc941fd6acf0357e71fcdcb6604a7acec8ebd7fce2525a4aa853c49d9b5728",
    "evidence/preflight-gates/step-000032-launch.json": "be241ce53d39935c3e7aa5218bf7ecd00feea1aa5386934cd9cc51fe72d7f3f3",
    "evidence/run-manifest.json": "f328ccbe319ff84ee724794225ab92744b3a663692d6fb9ba37848c4617c8bf0",
    "evidence/validations/validation-step-000000.json": "b92ccb7cd1eb8fd9e5d256074748b7ff7d3ff39c8e5e55ea29fc8ef7fe9c22fd",
    "evidence/validations/validation-step-000030.json": "dad4afcd29a4f9267417f8974611fac39dd5c84e313df4f76b1ca83bfa6665aa",
    "evidence/validations/validation-step-000060.json": "fda153b791b655fe944d692b37217d0caed561bc2787275a4e3f46ac46c28f41",
    "evidence/validations/validation-step-000090.json": "fca1a376ff348df1df37557a40459df2eac04de63af21f68b0c3fac4499a0f5c",
    "evidence/validations/validation-step-000119.json": "8827f0186d6924c336c8da302e8de66134a43550e5bbd30ed77ca9a8616667df",
    "gates/qwen3_32b_accumulation_gate_cachebounded_v1.py": "eef88b00f8ef1c32cd12d60a55769fa68ed383f4629afc3b3e8a80d4c0aaa5d3",
    "tools/acquire_qwen3_32b_bnb.py": "6bd1c6ebf1c78b8bd0a31204997147d9488cb32c95535abb7112f472897c1452",
    "tools/build_qwen3_32b_loss_window_plan_v2.py": "f6eec8f1013f46bc07f82b8d2910cab759d268acd774a1172e66b2c058beeb81",
    "tools/build_qwen3_32b_train_plan.py": "d4f99cf16b451cace2bb56e7e6a95f46302300578ff416cd11d851422305f2a0",
    "tools/verify_qwen3_32b_bnb.py": "8f66d503e4d39877f716d3f0ff2fee7c4e73d9276725c105c25315975224dc60",
}

EXPECTED_DATA = {
    "train": (946, "707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58"),
    "validation": (116, "d4bbc65d196e0e073e75f275dd06b21727259c333046412f18a14b1ee1db666f"),
    "test": (113, "d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283"),
}

WEIGHT_SUFFIXES = {
    ".safetensors",
    ".bin",
    ".pt",
    ".pth",
    ".ckpt",
    ".gguf",
    ".onnx",
}

TRAINER_SHA = EXPECTED_FILES["configs/qwen3_32b_agentic_formal_trainer_v2_cachebounded.py"]
CONTROLLER_SHA = EXPECTED_FILES["configs/guarded_process_controller_v7.py"]
COMMON_SHA = EXPECTED_FILES["configs/qwen3_agentic_common.py"]
ORIGINAL_PLAN_SHA = EXPECTED_FILES["artifacts/training-plan/qwen3-32b-agentic-train-plan-v1.json"]
LOSS_PLAN_SHA = EXPECTED_FILES["artifacts/training-plan/qwen3-32b-agentic-loss-window-plan-v1.json"]
RUN_MANIFEST_SHA = EXPECTED_FILES["evidence/run-manifest.json"]
FINAL_MANIFEST_SHA = EXPECTED_FILES["evidence/checkpoint-000119/manifest.json"]


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    require(isinstance(payload, dict), f"JSON root is not an object: {path}")
    return payload


def verify_remote_snapshot(bundle: Path) -> dict[str, Any]:
    checked_bytes = 0
    for relative, expected in EXPECTED_FILES.items():
        path = bundle / relative
        require(path.is_file() and not path.is_symlink(), f"missing or unsafe frozen file: {relative}")
        actual = sha256_file(path)
        require(actual == expected, f"frozen file hash drift: {relative}: {actual}")
        checked_bytes += path.stat().st_size
    return {
        "files": len(EXPECTED_FILES),
        "bytes": checked_bytes,
        "sha256": dict(sorted(EXPECTED_FILES.items())),
    }


def snapshot_bundle_inventory(bundle: Path) -> dict[str, Any]:
    excluded = {"evidence/local-verification.json"}
    inventory: dict[str, str] = {}
    total_bytes = 0
    for path in sorted(item for item in bundle.rglob("*") if item.is_file()):
        relative = str(path.relative_to(bundle))
        if relative in excluded:
            continue
        inventory[relative] = sha256_file(path)
        total_bytes += path.stat().st_size
    return {
        "excluded": sorted(excluded),
        "files": len(inventory),
        "bytes": total_bytes,
        "sha256": inventory,
    }


def verify_no_payload(bundle: Path) -> dict[str, Any]:
    forbidden: list[str] = []
    symlinks: list[str] = []
    files = 0
    for path in bundle.rglob("*"):
        if path.is_symlink():
            symlinks.append(str(path.relative_to(bundle)))
        elif path.is_file():
            files += 1
            if path.suffix.lower() in WEIGHT_SUFFIXES:
                forbidden.append(str(path.relative_to(bundle)))
    require(not symlinks, f"bundle contains symlinks: {symlinks}")
    require(not forbidden, f"bundle contains model/checkpoint payload: {forbidden}")
    return {"files_scanned": files, "model_payload": "OMITTED_EXPECTED"}


def verify_model_metadata(bundle: Path) -> dict[str, Any]:
    verification = load_json(
        bundle / "artifacts/model-acquisition/qwen3-32b-bnb-7f721e74-verification.json"
    )
    require(verification.get("status") == "PASS", "model verification evidence did not PASS")
    require(
        verification.get("revision") == "7f721e74a6a8cc9ee352f7e49303a2c1705f9083",
        "model revision drift",
    )
    inventory = verification.get("file_sha256")
    require(isinstance(inventory, dict) and len(inventory) == 16, "model inventory evidence drift")
    weight_names = {
        f"model-{shard:05d}-of-00004.safetensors" for shard in range(1, 5)
    }
    metadata_names = set(inventory) - weight_names
    model_dir = bundle / "models/Qwen3-32B-bnb-4bit-7f721e74"
    require(model_dir.is_dir() and not model_dir.is_symlink(), "model metadata directory missing")
    actual_names = {
        path.name
        for path in model_dir.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    require(actual_names == metadata_names, f"model metadata inventory drift: {sorted(actual_names)}")
    for name in sorted(metadata_names):
        actual = sha256_file(model_dir / name)
        require(actual == inventory[name], f"model metadata hash drift: {name}: {actual}")
    require(not any((model_dir / name).exists() for name in weight_names), "weight shard unexpectedly bundled")
    return {
        "metadata_files": len(metadata_names),
        "metadata_bytes": sum((model_dir / name).stat().st_size for name in metadata_names),
        "weight_shards": "OMITTED_EXPECTED",
        "omitted_weight_bytes": 19_211_935_565,
    }


def verify_python_syntax(bundle: Path) -> dict[str, Any]:
    checked: list[str] = []
    for path in sorted(bundle.rglob("*.py")):
        source = path.read_bytes()
        compile(source, str(path), "exec")
        checked.append(str(path.relative_to(bundle)))
    return {"files": len(checked), "paths": checked}


def verify_json_syntax(bundle: Path) -> dict[str, Any]:
    checked: list[str] = []
    for path in sorted(bundle.rglob("*.json")):
        json.loads(path.read_bytes())
        checked.append(str(path.relative_to(bundle)))
    return {"files": len(checked), "paths": checked}


def verify_cli_contract(bundle: Path) -> dict[str, Any]:
    relative_paths = [
        "configs/qwen3_32b_agentic_formal_trainer_v2_cachebounded.py",
        "configs/guarded_process_controller_v7.py",
        "gates/qwen3_32b_accumulation_gate_cachebounded_v1.py",
        "tools/build_qwen3_32b_train_plan.py",
        "tools/build_qwen3_32b_loss_window_plan_v2.py",
    ]
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    checked: list[str] = []
    for relative in relative_paths:
        completed = subprocess.run(
            [sys.executable, "-B", str(bundle / relative), "--help"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
            check=False,
            text=True,
            timeout=15,
        )
        require(completed.returncode == 0, f"CLI help failed: {relative}: {completed.stdout[-500:]}")
        require("usage:" in completed.stdout, f"CLI help missing usage contract: {relative}")
        checked.append(relative)
    return {"files": len(checked), "paths": checked}


def verify_data(data_dir: Path) -> dict[str, Any]:
    require(data_dir.is_dir() and not data_dir.is_symlink(), f"data directory missing or unsafe: {data_dir}")
    all_task_ids: set[str] = set()
    split_report: dict[str, Any] = {}
    for split, (expected_rows, expected_sha) in EXPECTED_DATA.items():
        path = data_dir / f"{split}.jsonl"
        require(path.is_file() and not path.is_symlink(), f"missing split: {path}")
        actual_sha = sha256_file(path)
        require(actual_sha == expected_sha, f"{split} hash drift: {actual_sha}")
        rows = path.read_bytes().splitlines()
        require(len(rows) == expected_rows, f"{split} row-count drift: {len(rows)}")
        split_ids: set[str] = set()
        for line_number, raw in enumerate(rows, 1):
            row = json.loads(raw)
            require(row.get("schema_version") == "rdk_sft_sample.v1", f"{split}:{line_number}: schema drift")
            require(row.get("profile") == "agentic", f"{split}:{line_number}: profile drift")
            require(row.get("split") == split, f"{split}:{line_number}: split field drift")
            task_id = row.get("task_id")
            require(isinstance(task_id, str) and task_id, f"{split}:{line_number}: missing task_id")
            require(task_id not in split_ids, f"{split}: duplicate task_id: {task_id}")
            require(task_id not in all_task_ids, f"cross-split duplicate task_id: {task_id}")
            split_ids.add(task_id)
            all_task_ids.add(task_id)
        split_report[split] = {"rows": len(rows), "sha256": actual_sha}
    return {"directory": str(data_dir), "splits": split_report, "unique_tasks": len(all_task_ids)}


def verify_plan_contract(bundle: Path) -> dict[str, Any]:
    original = load_json(bundle / "artifacts/training-plan/qwen3-32b-agentic-train-plan-v1.json")
    loss = load_json(bundle / "artifacts/training-plan/qwen3-32b-agentic-loss-window-plan-v1.json")
    require(original.get("schema_version") == "qwen3_32b_agentic_train_plan.v1", "original plan schema drift")
    require(original.get("algorithm") == "capacity_constrained_lpt.v1", "original plan algorithm drift")
    require(loss.get("schema_version") == "qwen3_32b_agentic_loss_window_plan.v1", "loss plan schema drift")
    require(loss.get("algorithm") == "semantic_boundary_loss_windows.v1", "loss plan algorithm drift")
    source = loss.get("source", {})
    require(source.get("original_plan_sha256") == ORIGINAL_PLAN_SHA, "loss/original plan binding drift")
    require(source.get("common_script_sha256") == COMMON_SHA, "loss/common binding drift")
    require(source.get("split_sha256") == {key: value[1] for key, value in EXPECTED_DATA.items()}, "loss/data hash binding drift")
    require(source.get("split_rows") == {key: value[0] for key, value in EXPECTED_DATA.items()}, "loss/data row binding drift")
    contract = loss.get("execution_contract", {})
    require(contract.get("max_window_tokens") == 8192, "loss window size drift")
    require(contract.get("assistant_labels_covered_exactly_once") is True, "assistant-label coverage drift")
    require(contract.get("context_assistant_labels_masked") is True, "context masking drift")
    require(contract.get("causal_predecessor_required") is True, "causal predecessor drift")
    require(contract.get("packing") is False and contract.get("padding") is False, "packing/padding drift")
    splits = loss.get("splits", {})
    require(splits.get("train", {}).get("rows") == 946, "train plan row drift")
    require(splits.get("train", {}).get("windows") == 948, "train window-count drift")
    require(splits.get("train", {}).get("shifted_supervised_tokens", {}).get("total") == 534_734, "train token-count drift")
    require(splits.get("validation", {}).get("rows") == 116, "validation plan row drift")
    require(splits.get("validation", {}).get("windows") == 116, "validation window-count drift")
    require(splits.get("validation", {}).get("shifted_supervised_tokens", {}).get("total") == 66_181, "validation token-count drift")
    schedule = loss.get("schedule", {}).get("steps", [])
    require(len(schedule) == 119, f"optimizer-step schedule drift: {len(schedule)}")
    require([item.get("optimizer_step") for item in schedule] == list(range(1, 120)), "optimizer-step order drift")
    micro_windows = sum(len(item.get("micro_windows", [])) for item in schedule)
    shifted_tokens = sum(item.get("shifted_supervised_tokens", 0) for item in schedule)
    require(micro_windows == 948, f"scheduled micro-window drift: {micro_windows}")
    require(shifted_tokens == 534_734, f"scheduled supervised-token drift: {shifted_tokens}")
    return {
        "optimizer_steps": len(schedule),
        "train_micro_windows": micro_windows,
        "train_shifted_supervised_tokens": shifted_tokens,
        "max_window_tokens": 8192,
        "assistant_only": True,
    }


def zero_critical_events(payload: dict[str, Any]) -> bool:
    return all(payload.get(key, 0) == 0 for key in ("max", "oom", "oom_kill", "oom_group_kill"))


def verify_preflight_gate_evidence(bundle: Path) -> dict[str, Any]:
    authorization = load_json(bundle / "evidence/formal-restart-authorization.json")
    require(authorization.get("status") == "AUTHORIZED", "formal authorization status drift")
    bindings = authorization.get("bindings", {})
    require(bindings.get("trainer_sha256") == TRAINER_SHA, "authorization/trainer binding drift")
    require(bindings.get("controller_sha256") == CONTROLLER_SHA, "authorization/controller binding drift")
    require(
        bindings.get("gate_sha256")
        == EXPECTED_FILES["gates/qwen3_32b_accumulation_gate_cachebounded_v1.py"],
        "authorization/gate binding drift",
    )
    require(bindings.get("original_plan_sha256") == ORIGINAL_PLAN_SHA, "authorization/original-plan binding drift")
    require(bindings.get("loss_window_plan_sha256") == LOSS_PLAN_SHA, "authorization/loss-plan binding drift")
    require(bindings.get("data_train_sha256") == EXPECTED_DATA["train"][1], "authorization/train binding drift")
    require(bindings.get("data_validation_sha256") == EXPECTED_DATA["validation"][1], "authorization/validation binding drift")
    require(bindings.get("data_test_sha256") == EXPECTED_DATA["test"][1], "authorization/test binding drift")
    evidence = authorization.get("gate_evidence", {})
    require(evidence.get("all_required_gates_passed") is True, "authorization gate summary drift")
    gate_report: dict[str, Any] = {}
    for step in (6, 32):
        padded = f"{step:06d}"
        root = bundle / f"evidence/preflight-gates/step-{padded}-controller"
        controller_path = root / "controller-result.json"
        gate_path = root / "gate-result.json"
        telemetry_path = root / "telemetry.jsonl"
        controller = load_json(controller_path)
        gate = load_json(gate_path)
        frozen = evidence.get(str(step), {})
        require(controller.get("status") == "PASS", f"step {step} controller did not PASS")
        require(controller.get("gate_exit_code") == 0, f"step {step} gate exit drift")
        require(controller.get("breach") is None, f"step {step} resource breach")
        require(controller.get("monitor_error") is None and controller.get("postflight_error") is None, f"step {step} monitor/postflight error")
        require(controller.get("maximum_gpu_used_bytes", 0) < 42 * 1024**3, f"step {step} exceeded internal 42 GiB target")
        require(zero_critical_events(controller.get("post_exit_event_delta", {})), f"step {step} cgroup event drift")
        require(gate.get("status") == "PASS" and gate.get("schedule_step") == step, f"step {step} gate result drift")
        require(frozen.get("controller_result_sha256") == sha256_file(controller_path), f"step {step} authorization/controller hash drift")
        require(frozen.get("gate_result_sha256") == sha256_file(gate_path), f"step {step} authorization/gate hash drift")
        require(frozen.get("telemetry_sha256") == sha256_file(telemetry_path), f"step {step} authorization/telemetry hash drift")
        require(frozen.get("maximum_gpu_used_bytes") == controller.get("maximum_gpu_used_bytes"), f"step {step} GPU evidence drift")
        gate_report[str(step)] = {
            "status": "PASS",
            "maximum_gpu_used_bytes": controller["maximum_gpu_used_bytes"],
            "telemetry_lines": controller["telemetry"]["lines"],
        }
    return {"status": "PASS", "gates": gate_report}


def verify_execution_evidence(bundle: Path) -> dict[str, Any]:
    run_manifest = load_json(bundle / "evidence/run-manifest.json")
    require(run_manifest.get("schema_version") == "qwen3_32b_agentic_formal_run.v1", "run manifest schema drift")
    require(run_manifest.get("bindings", {}).get("trainer_sha256") == TRAINER_SHA, "run/trainer binding drift")
    require(run_manifest.get("bindings", {}).get("common_script_sha256") == COMMON_SHA, "run/common binding drift")
    require(run_manifest.get("bindings", {}).get("original_plan_sha256") == ORIGINAL_PLAN_SHA, "run/original-plan binding drift")
    require(run_manifest.get("bindings", {}).get("loss_plan_sha256") == LOSS_PLAN_SHA, "run/loss-plan binding drift")
    require(run_manifest.get("hyperparameters", {}).get("optimizer_steps") == 119, "run optimizer-step drift")
    require(run_manifest.get("hyperparameters", {}).get("per_micro_allocator_cache_release", {}).get("enabled") is True, "cache-release contract drift")

    phase1_controller = load_json(bundle / "evidence/phase1-controller/controller-result.json")
    phase1_gate = load_json(bundle / "evidence/phase1-controller/gate-result.json")
    require(phase1_controller.get("status") == "PASS", "phase1 controller did not PASS")
    require(phase1_controller.get("expected_exit_code") == 75 == phase1_controller.get("gate_exit_code"), "phase1 exit contract drift")
    require(phase1_controller.get("expected_result_status") == "RESTART_READY", "phase1 expected status drift")
    require(phase1_controller.get("breach") is None, "phase1 resource breach")
    require(phase1_controller.get("monitor_error") is None and phase1_controller.get("postflight_error") is None, "phase1 monitor/postflight error")
    require(phase1_controller.get("maximum_gpu_used_bytes", 0) < phase1_controller.get("gpu_limit_bytes", 0), "phase1 GPU guard failed")
    require(zero_critical_events(phase1_controller.get("post_exit_event_delta", {})), "phase1 cgroup event drift")
    require(phase1_gate.get("status") == "RESTART_READY", "phase1 gate status drift")
    require(phase1_gate.get("completed_optimizer_step") == 10 and phase1_gate.get("next_optimizer_step") == 11, "phase1 step contract drift")

    phase2_controller = load_json(bundle / "evidence/phase2-controller/controller-result.json")
    phase2_gate = load_json(bundle / "evidence/phase2-controller/gate-result.json")
    require(phase2_controller.get("status") == "PASS", "phase2 controller did not PASS")
    require(phase2_controller.get("expected_exit_code") == 0 == phase2_controller.get("gate_exit_code"), "phase2 exit contract drift")
    require(phase2_controller.get("expected_result_status") == "PASS", "phase2 expected status drift")
    require(phase2_controller.get("breach") is None, "phase2 resource breach")
    require(phase2_controller.get("monitor_error") is None and phase2_controller.get("postflight_error") is None, "phase2 monitor/postflight error")
    require(phase2_controller.get("maximum_gpu_used_bytes", 0) < phase2_controller.get("gpu_limit_bytes", 0), "phase2 GPU guard failed")
    require(phase2_controller.get("maximum_cpu_current_bytes", 0) < phase2_controller.get("cpu_limit_bytes", 0), "phase2 CPU guard failed")
    require(zero_critical_events(phase2_controller.get("post_exit_event_delta", {})), "phase2 cgroup event drift")
    require(phase2_gate.get("status") == "PASS" and phase2_gate.get("exit_code") == 0, "phase2 gate status drift")
    require(phase2_gate.get("completed_optimizer_step") == 119 and phase2_gate.get("next_optimizer_step") is None, "phase2 terminal-step drift")
    progress = phase2_gate.get("progress", {})
    require(progress.get("micro_windows") == 948, "phase2 micro-window total drift")
    require(progress.get("shifted_supervised_tokens") == 534_734, "phase2 supervised-token total drift")
    require(progress.get("per_micro_allocator_cache_release_executions") == 948, "phase2 cache-release count drift")

    checkpoint_manifest = load_json(bundle / "evidence/checkpoint-000119/manifest.json")
    checkpoint_state = load_json(bundle / "evidence/checkpoint-000119/state.json")
    checkpoint_complete = load_json(bundle / "evidence/checkpoint-000119/COMPLETE")
    require(checkpoint_manifest.get("optimizer_step") == 119, "final checkpoint manifest step drift")
    require(checkpoint_manifest.get("run_manifest_sha256") == RUN_MANIFEST_SHA, "final checkpoint/run binding drift")
    require(checkpoint_manifest.get("trainer_sha256") == TRAINER_SHA, "final checkpoint/trainer binding drift")
    require(checkpoint_complete.get("status") == "COMPLETE", "final checkpoint is incomplete")
    require(checkpoint_complete.get("manifest_sha256") == FINAL_MANIFEST_SHA, "COMPLETE/manifest binding drift")
    require(checkpoint_state.get("phase") == "phase2", "final checkpoint phase drift")
    require(checkpoint_state.get("completed_optimizer_step") == 119 and checkpoint_state.get("next_optimizer_step") == 120, "final checkpoint state step drift")
    require(checkpoint_state.get("trainer_sha256") == TRAINER_SHA, "final state/trainer binding drift")
    require(checkpoint_state.get("run_manifest_sha256") == RUN_MANIFEST_SHA, "final state/run binding drift")
    require(len(checkpoint_state.get("history", [])) == 119, "final training history length drift")
    require([item.get("optimizer_step") for item in checkpoint_state.get("validations", [])] == [0, 30, 60, 90, 119], "validation boundary drift")

    validation_cross_entropy: dict[str, float] = {}
    for step in (0, 30, 60, 90, 119):
        payload = load_json(bundle / f"evidence/validations/validation-step-{step:06d}.json")
        require(payload.get("status") == "PASS" and payload.get("optimizer_step") == step, f"validation {step} status drift")
        require(payload.get("run_manifest_sha256") == RUN_MANIFEST_SHA, f"validation {step}/run binding drift")
        value = payload.get("metrics", {}).get("all", {}).get("mean_cross_entropy")
        require(isinstance(value, (int, float)) and math.isfinite(value), f"validation {step} CE invalid")
        validation_cross_entropy[str(step)] = float(value)
    require(validation_cross_entropy["119"] < validation_cross_entropy["0"], "validation CE did not improve")
    best = phase2_gate.get("best_validation", {})
    require(best.get("optimizer_step") == 119 and best.get("checkpoint") == "checkpoint-000119", "best-checkpoint selection drift")
    require(math.isclose(best.get("mean_cross_entropy", math.inf), validation_cross_entropy["119"], rel_tol=0, abs_tol=1e-15), "best-validation metric drift")

    return {
        "formal_training_execution": "PASS",
        "phase1": "PASS_RESTART_READY",
        "phase2": "PASS",
        "completed_optimizer_step": 119,
        "best_checkpoint": "checkpoint-000119",
        "validation_mean_cross_entropy": validation_cross_entropy,
        "maximum_gpu_used_bytes": phase2_controller["maximum_gpu_used_bytes"],
        "maximum_cpu_current_bytes": phase2_controller["maximum_cpu_current_bytes"],
        "cgroup_critical_events": 0,
    }


def parse_args() -> argparse.Namespace:
    default_bundle = Path(__file__).resolve().parent.parent
    default_data = default_bundle.parent / "data-gen/data/releases/rdk-sft-v1-20260803/agentic"
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=default_bundle)
    parser.add_argument("--data-dir", type=Path, default=default_data)
    parser.add_argument("--write-report", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = args.bundle.resolve(strict=True)
    report = {
        "schema_version": "qwen3_32b_agentic_weight_free_bundle_verification.v1",
        "status": "PASS",
        "bundle_inventory": snapshot_bundle_inventory(bundle),
        "source_equivalence": verify_remote_snapshot(bundle),
        "syntax": verify_python_syntax(bundle),
        "json_syntax": verify_json_syntax(bundle),
        "cli_contract": verify_cli_contract(bundle),
        "no_model_payload": verify_no_payload(bundle),
        "model_metadata": verify_model_metadata(bundle),
        "data_contract": verify_data(args.data_dir.resolve(strict=True)),
        "plan_contract": verify_plan_contract(bundle),
        "preflight_gates": verify_preflight_gate_evidence(bundle),
        "execution_evidence": verify_execution_evidence(bundle),
        "proof_boundary": {
            "dependency_snapshot": "RECORDED_NOT_INSTALLED_LOCALLY",
            "formal_training_execution": "PASS_ON_BOUND_AMD_HOST",
            "model_payload": "OMITTED_EXPECTED",
            "fresh_launch_readiness": "NOT_RUN",
            "other_host_portability": "UNSUPPORTED_UNTIL_REVALIDATED",
            "agentic_quality": "PENDING_HELDOUT_PI_AB",
        },
    }
    encoded = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if args.write_report is not None:
        output = args.write_report
        require(output.is_absolute(), "--write-report must be absolute")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
        except BaseException:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    try:
        main()
    except (VerificationError, FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
