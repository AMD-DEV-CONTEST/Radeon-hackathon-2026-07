"""Load and validate the frozen robot-port and task contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


class ContractError(ValueError):
    """Raised when a contract is internally inconsistent."""


def load_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load JSON contract {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"contract root must be an object: {path}")
    return data


def validate_rocm_container_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema_version") != 1:
        raise ContractError("ROCm container schema_version must be 1")
    if contract.get("role") != "portable_fallback_candidate":
        raise ContractError("ROCm container must remain a portable fallback")
    if contract.get("status") != "superseded_for_official_radeon_cloud_main_path":
        raise ContractError("ROCm container official-cloud status changed")
    if contract.get("official_cloud_runtime_contract") != (
        "configs/amd-cloud-runtime-v1.json"
    ):
        raise ContractError("ROCm container official-cloud pointer changed")
    expected_scalars = {
        "base_image": (
            "rocm/pytorch:"
            "rocm6.4.1_ubuntu22.04_py3.10_pytorch_release_2.6.0"
        ),
        "python_version": "3.10",
        "rocm_version": "6.4.1",
        "torch_version": "2.6.0",
        "torchvision_version": "0.21.0",
        "numpy_version": "1.26.4",
        "asset_strategy": (
            "bind_mount_nonredistributable_robot_and_dataset_assets"
        ),
    }
    for field, expected in expected_scalars.items():
        if contract.get(field) != expected:
            raise ContractError(f"ROCm container {field} changed")
    genesis = contract.get("genesis")
    if not isinstance(genesis, dict) or genesis != {
        "version": "1.2.3",
        "tag": "v1.2.3",
        "tag_revision": "6d2d19ecb734b35f51ab5e8862b954b780cfed09",
        "backend": "gs.amdgpu",
    }:
        raise ContractError("ROCm container Genesis boundary changed")
    lerobot = contract.get("lerobot")
    if not isinstance(lerobot, dict) or lerobot != {
        "repository": "https://github.com/huggingface/lerobot.git",
        "revision": "d9e74a9d374a8f26582ad326c699740a227b483c",
        "version": "0.4.2",
    }:
        raise ContractError("ROCm container LeRobot boundary changed")
    gpu_access = contract.get("gpu_access")
    if not isinstance(gpu_access, dict):
        raise ContractError("ROCm container gpu_access must be an object")
    if gpu_access.get("device_nodes") != ["/dev/kfd", "/dev/dri"]:
        raise ContractError("ROCm container device nodes changed")
    if gpu_access.get("group_add") != ["video"]:
        raise ContractError("ROCm container video group changed")
    if gpu_access.get("ipc") != "host" or gpu_access.get("shm_size") != "8g":
        raise ContractError("ROCm container IPC boundary changed")
    if gpu_access.get("cap_add") != ["SYS_PTRACE"]:
        raise ContractError("ROCm container capability boundary changed")
    if gpu_access.get("security_opt") != ["seccomp=unconfined"]:
        raise ContractError("ROCm container security boundary changed")
    for field in ("runtime_receipt_required", "image_digest_required_for_claim"):
        if contract.get(field) is not True:
            raise ContractError(f"ROCm container {field} must remain true")
    claim_boundary = contract.get("claim_boundary")
    if (
        not isinstance(claim_boundary, str)
        or "portable fallback candidate only" not in claim_boundary
        or "AMD execution may be claimed only" not in claim_boundary
    ):
        raise ContractError("ROCm container claim boundary changed")


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ContractError(f"missing {context}.{key}")
    return mapping[key]


def _unique_strings(values: Any, context: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ContractError(f"{context} must be a non-empty list")
    if not all(isinstance(value, str) and value for value in values):
        raise ContractError(f"{context} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise ContractError(f"{context} contains duplicates")
    return values


def validate_competition_resources_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema_version") != 1:
        raise ContractError("competition resources schema_version must be 1")
    if contract.get("authority_order") != [
        "modelscope_official_event_rules",
        "github_official_submission_repository",
        "training_camp_operational_guides",
    ]:
        raise ContractError("competition authority order changed")

    event = contract.get("event")
    if not isinstance(event, dict):
        raise ContractError("competition event must be an object")
    if event.get("official_url") != "https://modelscope.cn/events/299":
        raise ContractError("official event URL changed")
    if event.get("submission_deadline") != "2026-08-06T23:59:00+08:00":
        raise ContractError("submission deadline changed")
    hardware = event.get("hardware_execution_rule")
    if not isinstance(hardware, dict):
        raise ContractError("hardware execution rule must be an object")
    if hardware.get("required_visible_gpu_count") != 1:
        raise ContractError("Track 3 final path must use one visible GPU")
    if hardware.get("gpu_vendor") != "AMD" or hardware.get("software_stack") != "ROCm":
        raise ContractError("Track 3 AMD/ROCm boundary changed")
    if hardware.get("required_stages") != [
        "environment_execution",
        "model_training",
        "realtime_inference",
    ]:
        raise ContractError("Track 3 required execution stages changed")
    scores = event.get("score_weights")
    if not isinstance(scores, dict) or sum(scores.values()) != 100:
        raise ContractError("competition score weights must sum to 100")

    submission = contract.get("submission")
    if not isinstance(submission, dict):
        raise ContractError("competition submission must be an object")
    if submission.get("repository") != (
        "https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07"
    ):
        raise ContractError("official submission repository changed")
    if submission.get("method") != "fork_and_pull_request":
        raise ContractError("submission method changed")
    language = submission.get("language_rules")
    if not isinstance(language, dict) or language.get("project_decision") != (
        "english_primary_with_chinese_mirror"
    ):
        raise ContractError("submission language decision changed")
    video = submission.get("video_rules")
    if not isinstance(video, dict) or video.get("project_target_seconds") != 180:
        raise ContractError("submission video target changed")

    cloud = contract.get("cloud")
    if not isinstance(cloud, dict):
        raise ContractError("competition cloud must be an object")
    if cloud.get("portal") != "https://radeon-global.anruicloud.com/":
        raise ContractError("Radeon Cloud portal changed")
    if cloud.get("recommended_template") != "proxy":
        raise ContractError("Radeon Cloud template changed")
    if cloud.get("persistent_root") != "/workspace":
        raise ContractError("Radeon Cloud persistent root changed")
    cloud_status = cloud.get("instance_creation_status")
    attempted = cloud.get("instance_creation_attempted_in_this_snapshot")
    allowed_cloud_states = {
        "deferred_platform_maintenance": False,
        "official_single_gpu_instance_used_for_verified_training_inference_and_g3": True,
    }
    if cloud_status not in allowed_cloud_states:
        raise ContractError("unsupported competition cloud instance status")
    if attempted is not allowed_cloud_states[cloud_status]:
        raise ContractError(
            "competition cloud instance status and creation-attempt flag disagree"
        )

    references = contract.get("references")
    if not isinstance(references, list):
        raise ContractError("competition references must be a list")
    reference_ids = [item.get("id") for item in references if isinstance(item, dict)]
    expected_ids = {
        "training_materials",
        "submission_guide",
        "faq",
        "official_event",
        "amd_developer_program_china",
        "official_submission_repository",
        "cloud_access_guide_zh",
    }
    if set(reference_ids) != expected_ids or len(reference_ids) != len(expected_ids):
        raise ContractError("competition reference set changed")
    claim = contract.get("claim_boundary")
    if not isinstance(claim, str) or "Re-check" not in claim:
        raise ContractError("competition dated-snapshot boundary missing")


def validate_amd_cloud_runtime_contract(contract: dict[str, Any]) -> None:
    schema_version = contract.get("schema_version")
    if schema_version not in {1, 2, 3}:
        raise ContractError("AMD cloud runtime schema_version must be 1, 2, or 3")
    if contract.get("status") not in {
        "awaiting_platform_recovery",
        "ready_for_bootstrap",
        "runtime_validated",
        "stage0_inventory_verified",
        "stage2_runtime_verified",
        "persistence_contract_frozen_cloud_unverified",
        "persistence_mount_and_writability_verified",
    }:
        raise ContractError("unsupported AMD cloud runtime status")

    platform = contract.get("platform")
    if not isinstance(platform, dict):
        raise ContractError("AMD cloud platform must be an object")
    persistence_aware = schema_version in {2, 3}
    persistent_root = {
        1: "/workspace",
        2: "/workspace/persistence",
        3: "/workspace/persistent",
    }[schema_version]
    project_root = (
        f"{persistent_root}/mantis-track3" if persistence_aware else None
    )
    virtual_environment = (
        f"{project_root}/envs/rdna" if persistence_aware else "/workspace/rdna"
    )
    expected_platform = {
        "portal": "https://radeon-global.anruicloud.com/",
        "persistent_storage": "PVC",
        "persistent_root": persistent_root,
        "virtual_environment": virtual_environment,
        "required_visible_gpu_count": 1,
    }
    for field, expected in expected_platform.items():
        if platform.get(field) != expected:
            raise ContractError(f"AMD cloud platform {field} changed")
    if persistence_aware:
        expected_layout = {
            2: "configs/amd-persistence-layout-v1.json",
            3: "configs/amd-persistence-layout-v2.json",
        }[schema_version]
        if contract.get("persistence_layout_contract") != expected_layout:
            raise ContractError("AMD cloud persistence layout reference changed")
        if platform.get("project_root") != project_root:
            raise ContractError("AMD cloud platform project_root changed")
        if platform.get("mount_verification_required") is not True:
            raise ContractError("AMD persistence mount verification must be required")
        if schema_version == 2:
            if (
                contract.get("status")
                != "persistence_contract_frozen_cloud_unverified"
            ):
                raise ContractError(
                    "schema v2 is locally frozen only until a fresh cloud inventory exists"
                )
            if platform.get("instance_creation_attempted") is not False:
                raise ContractError(
                    "unverified persistence runtime cannot claim instance creation"
                )
        if schema_version == 3:
            if (
                contract.get("status")
                != "persistence_mount_and_writability_verified"
            ):
                raise ContractError(
                    "schema v3 requires verified persistence mount and writability"
                )
            if platform.get("instance_creation_attempted") is not True:
                raise ContractError(
                    "verified persistence runtime must record instance creation"
                )
            if platform.get("resolved_mount_root") != "/persistent":
                raise ContractError("AMD resolved persistence mount root changed")
            for field in (
                "mount_verification_passed",
                "writability_canary_passed",
            ):
                if platform.get(field) is not True:
                    raise ContractError(f"AMD cloud platform {field} must be true")
            if (
                platform.get("persistence_across_restart_or_recreation_verified")
                is not False
            ):
                raise ContractError(
                    "persistence across restart or recreation must remain unverified"
                )
            if platform.get("direct_local_ssd_claim_supported") is not False:
                raise ContractError("direct-local-SSD claim must remain unsupported")
    if (
        contract.get("status") == "awaiting_platform_recovery"
        and platform.get("instance_creation_attempted") is not False
    ):
        raise ContractError("maintenance runtime cannot claim instance creation")

    # Validate stage0_inventory requirements for statuses that depend on stage0
    # (stage0_inventory_verified, stage2_runtime_verified, and any future stages)
    if contract.get("status") in {
        "stage0_inventory_verified",
        "stage2_runtime_verified",
    }:
        if platform.get("required_visible_gpu_count") != 1:
            raise ContractError("stage0_inventory_verified requires exactly 1 GPU")

        # Check actual_template vs planned_template divergence is recorded
        if "actual_template" not in platform or "planned_template" not in platform:
            raise ContractError("stage0_inventory_verified requires actual_template and planned_template")
        if platform.get("actual_template") == platform.get("planned_template"):
            raise ContractError("stage0_inventory_verified requires actual_template != planned_template when divergence exists")
        if "template_divergence_note" not in platform:
            raise ContractError("stage0_inventory_verified requires template_divergence_note")

        # Validate stage0_inventory section
        stage0 = contract.get("stage0_inventory")
        if not isinstance(stage0, dict):
            raise ContractError("stage0_inventory_verified requires stage0_inventory object")

        # Check schema_version
        if stage0.get("schema_version") != 1:
            raise ContractError("stage0_inventory schema_version must be 1")

        # Check verified_at is a string (date)
        verified_at = stage0.get("verified_at")
        if not isinstance(verified_at, str) or not verified_at:
            raise ContractError("stage0_inventory.verified_at must be a non-empty string")

        # Check instance_id
        if not isinstance(stage0.get("instance_id"), str) or not stage0.get("instance_id"):
            raise ContractError("stage0_inventory.instance_id must be a non-empty string")

        # Validate GPU inventory
        gpu = stage0.get("gpu")
        if not isinstance(gpu, dict):
            raise ContractError("stage0_inventory.gpu must be an object")

        # gpu.count must be 1
        if gpu.get("count") != 1:
            raise ContractError("stage0_inventory.gpu.count must be 1")

        # gpu.family must be a non-empty string
        if not isinstance(gpu.get("family"), str) or not gpu.get("family"):
            raise ContractError("stage0_inventory.gpu.family must be a non-empty string")

        # gpu.arch must be a non-empty string
        if not isinstance(gpu.get("arch"), str) or not gpu.get("arch"):
            raise ContractError("stage0_inventory.gpu.arch must be a non-empty string")

        # gpu.name must be a non-empty string
        if not isinstance(gpu.get("name"), str) or not gpu.get("name"):
            raise ContractError("stage0_inventory.gpu.name must be a non-empty string")

        # gpu.vram_bytes must be a positive integer
        vram = gpu.get("vram_bytes")
        if not isinstance(vram, int) or vram <= 0:
            raise ContractError("stage0_inventory.gpu.vram_bytes must be a positive integer")

        # gpu.uuid_recorded must be false
        if gpu.get("uuid_recorded") is not False:
            raise ContractError("stage0_inventory.gpu.uuid_recorded must be false")

        # Validate ROCm version
        if not isinstance(stage0.get("rocm_version"), str) or not stage0.get("rocm_version"):
            raise ContractError("stage0_inventory.rocm_version must be a non-empty string")

        # Validate Python version
        if not isinstance(stage0.get("python_version"), str) or not stage0.get("python_version"):
            raise ContractError("stage0_inventory.python_version must be a non-empty string")

        # Validate pip version
        if not isinstance(stage0.get("pip_version"), str) or not stage0.get("pip_version"):
            raise ContractError("stage0_inventory.pip_version must be a non-empty string")

        # Validate persistent_root
        if stage0.get("persistent_root") != persistent_root:
            raise ContractError(
                f"stage0_inventory.persistent_root must be {persistent_root}"
            )

        # Validate official_wheels
        wheels = stage0.get("official_wheels")
        if not isinstance(wheels, dict):
            raise ContractError("stage0_inventory.official_wheels must be an object")

        required_wheels = {"apex", "torch", "torchvision", "torchaudio", "triton"}
        if set(wheels.keys()) != required_wheels:
            raise ContractError(f"stage0_inventory.official_wheels must contain exactly {required_wheels}")

        # Validate each wheel
        for wheel_name, wheel_spec in wheels.items():
            if not isinstance(wheel_spec, dict):
                raise ContractError(f"stage0_inventory.official_wheels.{wheel_name} must be an object")

            # path must be absolute (starts with /)
            path = wheel_spec.get("path")
            if not isinstance(path, str) or not path.startswith("/"):
                raise ContractError(f"stage0_inventory.official_wheels.{wheel_name}.path must be an absolute path")

            # sha256 must be 64-character lowercase hex
            sha256 = wheel_spec.get("sha256")
            if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ContractError(f"stage0_inventory.official_wheels.{wheel_name}.sha256 must be 64-character lowercase hex")

            # part_of_stage1_install must be boolean
            if not isinstance(wheel_spec.get("part_of_stage1_install"), bool):
                raise ContractError(f"stage0_inventory.official_wheels.{wheel_name}.part_of_stage1_install must be boolean")

        # Stage 1 packages (torch, torchvision, torchaudio, triton) must have part_of_stage1_install=true
        stage1_packages = {"torch", "torchvision", "torchaudio", "triton"}
        for pkg in stage1_packages:
            if wheels[pkg].get("part_of_stage1_install") is not True:
                raise ContractError(f"stage0_inventory.official_wheels.{pkg}.part_of_stage1_install must be true")

        # apex must have part_of_stage1_install=false
        if wheels["apex"].get("part_of_stage1_install") is not False:
            raise ContractError("stage0_inventory.official_wheels.apex.part_of_stage1_install must be false")

        # Validate actual_template is recorded in stage0_inventory
        if not isinstance(stage0.get("actual_template"), str) or not stage0.get("actual_template"):
            raise ContractError("stage0_inventory.actual_template must be a non-empty string")

    pytorch = contract.get("pytorch")
    if not isinstance(pytorch, dict):
        raise ContractError("AMD cloud PyTorch must be an object")
    expected_pytorch = {
        "rocm_version": "7.2.1",
        "torch_version": "2.9.1",
        "torchvision_version": "0.24.0",
        "torchaudio_version": "2.9.0",
        "triton_version": "3.5.1",
        "installation_policy": (
            "reinventory_then_install_only_instance_provided_rocm_wheels"
            if persistence_aware
            else "install_only_instance_provided_rocm_wheels"
        ),
        "plain_pip_install_torch_forbidden": True,
    }
    for field, expected in expected_pytorch.items():
        if pytorch.get(field) != expected:
            raise ContractError(f"AMD cloud PyTorch {field} changed")
    wheel_globs = pytorch.get("instance_wheel_globs")
    if not isinstance(wheel_globs, list) or len(wheel_globs) != 4:
        raise ContractError("AMD cloud wheel inventory changed")
    if not all("rocm7.2.1" in wheel for wheel in wheel_globs):
        raise ContractError("AMD cloud wheels must remain ROCm 7.2.1 builds")

    genesis = contract.get("genesis")
    if not isinstance(genesis, dict):
        raise ContractError("AMD cloud Genesis must be an object")
    if genesis.get("backend") != "gs.amdgpu":
        raise ContractError("AMD cloud Genesis backend changed")
    expected_genesis_root = (
        f"{project_root}/src/Genesis" if persistence_aware else "/workspace/Genesis"
    )
    if genesis.get("install_root") != expected_genesis_root:
        raise ContractError("AMD cloud Genesis install root changed")
    if genesis.get("revision_policy") != (
        "resolve_and_record_current_main_revision_at_install"
    ):
        raise ContractError("AMD cloud Genesis revision policy changed")

    lerobot = contract.get("lerobot")
    if not isinstance(lerobot, dict) or lerobot.get("version") != "0.4.4":
        raise ContractError("AMD cloud LeRobot target changed")
    if lerobot.get("compatibility_status") not in {
        "awaiting_cloud_runtime_validation",
        "stage2_import_and_version_verified",
        "validated",
    }:
        raise ContractError("AMD cloud LeRobot compatibility status changed")

    numeric = contract.get("numeric_and_video_stack")
    if not isinstance(numeric, dict):
        raise ContractError("AMD cloud numeric stack must be an object")
    if numeric.get("numpy_version") != "2.1.2":
        raise ContractError("AMD cloud NumPy target changed")
    if numeric.get("scikit_image_constraint") != ">=0.22":
        raise ContractError("AMD cloud scikit-image target changed")

    cache_root = f"{project_root}/cache" if persistence_aware else "/workspace/cache"
    expected_cache = {
        "HF_HOME": f"{cache_root}/huggingface",
        "HF_LEROBOT_HOME": f"{cache_root}/huggingface/lerobot",
        "MODELSCOPE_CACHE": f"{cache_root}/modelscope",
    }
    if contract.get("persistent_cache_environment") != expected_cache:
        raise ContractError("AMD cloud persistent cache boundary changed")
    receipts = contract.get("required_receipts_before_promotion")
    required_receipts = {
        "instance_wheel_names_and_sha256",
        "torch_hip_version",
        "visible_device_name_and_count",
        "genesis_revision_and_gs_amdgpu_smoke",
        "lerobot_0_4_4_import_and_mantis_adapter_smoke",
        "project_contract_and_unit_test_results",
    }
    if not isinstance(receipts, list) or not required_receipts.issubset(receipts):
        raise ContractError("AMD cloud promotion receipts are incomplete")
    claim = contract.get("claim_boundary")
    if not isinstance(claim, str):
        raise ContractError("AMD cloud claim boundary must be a string")
    # For stage0_inventory_verified, check for stage0-specific language; for stage2_runtime_verified check for Stage 1/2 completion language
    if contract.get("status") == "stage0_inventory_verified":
        if not ("Stage 0 inventory" in claim and "remain unexecuted" in claim):
            raise ContractError("stage0_inventory_verified claim boundary must mention Stage 0 inventory completion")
    elif contract.get("status") == "stage2_runtime_verified":
        if not ("Stage 1" in claim and "Stage 2" in claim and "runtime availability" in claim):
            raise ContractError("stage2_runtime_verified claim boundary must mention Stage 1/2 completion and runtime availability only")
    elif contract.get("status") == "persistence_contract_frozen_cloud_unverified":
        if "not AMD execution evidence" not in claim:
            raise ContractError(
                "unverified persistence contract must disclaim AMD execution evidence"
            )
    elif contract.get("status") == "persistence_mount_and_writability_verified":
        if "not AMD execution evidence" not in claim:
            raise ContractError(
                "persistence verification must disclaim AMD execution evidence"
            )
    elif "not AMD execution evidence" not in claim:
        raise ContractError("AMD cloud claim boundary missing AMD execution evidence disclaimer")


def validate_port_contract(contract: dict[str, Any]) -> list[str]:
    if contract.get("schema_version") != 1:
        raise ContractError("port schema_version must be 1")

    status = _require(contract, "status", "port")
    if status not in {"provisional_blocked", "ready"}:
        raise ContractError("port.status must be provisional_blocked or ready")

    port = _require(contract, "port", "port")
    if not isinstance(port, dict):
        raise ContractError("port.port must be an object")
    port_mode = _require(port, "mode", "port.port")
    allowed_modes = {"same_robot_new_scene", "new_robot_same_task", "new_robot_new_scene"}
    if port_mode not in allowed_modes:
        raise ContractError(f"unsupported port mode: {port_mode}")

    source = _require(contract, "source", "port")
    target = _require(contract, "target", "port")
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise ContractError("port.source and port.target must be objects")
    source_robot = _require(source, "robot_id", "source")
    target_robot = _require(target, "robot_id", "target")
    source_task = _require(source, "task_id", "source")
    target_task = _require(target, "task_id", "target")
    if port_mode == "same_robot_new_scene" and source_robot != target_robot:
        raise ContractError("same_robot_new_scene requires identical robot_id values")
    if port_mode == "new_robot_same_task" and source_task != target_task:
        raise ContractError("new_robot_same_task requires identical task_id values")

    source_joints = _unique_strings(_require(source, "joint_order", "source"), "source.joint_order")
    target_joints = _unique_strings(_require(target, "joint_order", "target"), "target.joint_order")
    for side_name, side, joints in (
        ("source", source, source_joints),
        ("target", target, target_joints),
    ):
        state_dim = _require(side, "state_dim", side_name)
        action_dim = _require(side, "action_dim", side_name)
        if state_dim != len(joints) or action_dim != len(joints):
            raise ContractError(
                f"{side_name} dimensions must equal its joint_order length ({len(joints)})"
            )

    physical_joints = _unique_strings(
        _require(target, "physical_joint_order", "target"), "target.physical_joint_order"
    )
    if target.get("physical_state_dim") != len(physical_joints):
        raise ContractError("target.physical_state_dim must equal physical_joint_order length")
    if target.get("physical_action_dim") != len(physical_joints):
        raise ContractError("target.physical_action_dim must equal physical_joint_order length")

    joint_map = _require(contract, "joint_map", "port")
    if not isinstance(joint_map, dict):
        raise ContractError("joint_map must be an object")
    if set(joint_map) != set(source_joints):
        raise ContractError("joint_map keys must exactly cover source.joint_order")
    if set(joint_map.values()) != set(target_joints):
        raise ContractError("joint_map values must exactly cover target.joint_order")

    source_cameras = _unique_strings(
        _require(source, "runtime_camera_order", "source"), "source.runtime_camera_order"
    )
    target_cameras = _unique_strings(
        _require(target, "camera_order", "target"), "target.camera_order"
    )
    camera_map = _require(contract, "camera_map", "port")
    if not isinstance(camera_map, dict):
        raise ContractError("camera_map must be an object")
    if set(camera_map) != set(source_cameras):
        raise ContractError("camera_map keys must exactly cover source runtime cameras")
    if set(camera_map.values()) != set(target_cameras):
        raise ContractError("camera_map values must exactly cover target cameras")

    camera_specs = _require(target, "camera_specs", "target")
    if not isinstance(camera_specs, dict) or set(camera_specs) != set(target_cameras):
        raise ContractError("target.camera_specs must exactly cover target.camera_order")
    for camera_name, spec in camera_specs.items():
        if not isinstance(spec, dict):
            raise ContractError(f"camera spec for {camera_name} must be an object")
        for field in ("width", "height", "fps"):
            if not isinstance(spec.get(field), int) or spec[field] <= 0:
                raise ContractError(f"camera {camera_name} has invalid {field}")

    training = _require(contract, "training", "port")
    if not isinstance(training, dict):
        raise ContractError("training must be an object")
    if training.get("normalization_strategy") != "recompute_target_from_mantis_dataset":
        raise ContractError("target normalization strategy must recompute from the Mantis dataset")
    if not isinstance(training.get("normalization_recomputed"), bool):
        raise ContractError("training.normalization_recomputed must be boolean")
    if training.get("policy_chunk_size") != training.get("deployment_chunk_size"):
        raise ContractError("policy and deployment chunk sizes must match")

    assets = _require(contract, "assets", "port")
    if not isinstance(assets, dict):
        raise ContractError("assets must be an object")
    profile = _require(assets, "fixed_base_profile", "assets")
    if not isinstance(profile, dict):
        raise ContractError("assets.fixed_base_profile must be an object")
    selected_joints = _unique_strings(
        _require(profile, "selected_joint_order", "fixed_base_profile"),
        "assets.fixed_base_profile.selected_joint_order",
    )
    if selected_joints != physical_joints:
        raise ContractError("fixed-base selected joints must equal target physical joint order")
    if profile.get("expected_joint_count") != len(physical_joints):
        raise ContractError("fixed-base expected_joint_count disagrees with physical joint order")
    if profile.get("expected_link_count") != len(physical_joints) + 1:
        raise ContractError("a tree profile must contain exactly one more link than joint")

    physical_grippers = _unique_strings(
        _require(assets, "physical_gripper_joint_order", "assets"),
        "assets.physical_gripper_joint_order",
    )
    gripper_mapping = _require(assets, "virtual_gripper_mapping", "assets")
    if not isinstance(gripper_mapping, dict):
        raise ContractError("assets.virtual_gripper_mapping must be an object")
    mapping_statuses = {
        "candidate_unverified",
        "sim_verified_hardware_unverified",
        "verified",
    }
    if gripper_mapping.get("status") not in mapping_statuses:
        raise ContractError("virtual gripper status is unsupported")
    coefficients = _require(gripper_mapping, "coefficients", "virtual_gripper_mapping")
    offsets = _require(gripper_mapping, "offsets", "virtual_gripper_mapping")
    if not isinstance(coefficients, dict) or not coefficients:
        raise ContractError("virtual gripper coefficients must be a non-empty object")
    if not isinstance(offsets, dict) or set(offsets) != set(coefficients):
        raise ContractError("virtual gripper offsets must cover the coefficient keys")
    virtual_grippers = set(coefficients)
    if not virtual_grippers.issubset(target_joints):
        raise ContractError("virtual gripper names must be target policy joints")
    mapped_physical: list[str] = []
    for virtual_name, physical_map in coefficients.items():
        if not isinstance(physical_map, dict) or len(physical_map) < 2:
            raise ContractError(f"{virtual_name} must drive at least two physical joints")
        physical_offsets = offsets[virtual_name]
        if not isinstance(physical_offsets, dict) or set(physical_offsets) != set(physical_map):
            raise ContractError(f"offsets for {virtual_name} must cover its physical joints")
        for physical_name, coefficient in physical_map.items():
            if not isinstance(coefficient, (int, float)) or coefficient == 0:
                raise ContractError(f"invalid gripper coefficient for {physical_name}")
            if not isinstance(physical_offsets[physical_name], (int, float)):
                raise ContractError(f"invalid gripper offset for {physical_name}")
            mapped_physical.append(physical_name)
    if mapped_physical != physical_grippers:
        raise ContractError("gripper coefficient order must equal physical_gripper_joint_order")
    physical_arm_joints = [name for name in target_joints if name not in virtual_grippers]
    if set(physical_joints) != set(physical_arm_joints + physical_grippers):
        raise ContractError("physical joint order must cover policy arm joints and physical grippers")

    blockers = _require(contract, "blockers", "port")
    if not isinstance(blockers, list):
        raise ContractError("port.blockers must be a list")
    if not all(isinstance(blocker, str) and blocker for blocker in blockers):
        raise ContractError("port.blockers must contain non-empty strings")
    if len(blockers) != len(set(blockers)):
        raise ContractError("port.blockers contains duplicates")
    mapping_unverified = gripper_mapping.get("status") != "verified"
    if mapping_unverified != ("gripper_mapping_unverified" in blockers):
        raise ContractError("gripper mapping status and blocker must agree")
    normalization_pending = training["normalization_recomputed"] is False
    if normalization_pending != ("normalization_stats_not_generated" in blockers):
        raise ContractError("normalization status and blocker must agree")
    camera_extrinsics = _require(target, "camera_extrinsics", "target")
    if not isinstance(camera_extrinsics, dict) or set(camera_extrinsics) != set(target_cameras):
        raise ContractError("target.camera_extrinsics must exactly cover target cameras")
    camera_mount_pending = any(
        not isinstance(extrinsic, dict) or extrinsic.get("status") == "unresolved_hardware_mount"
        for extrinsic in camera_extrinsics.values()
    )
    if camera_mount_pending != ("target_camera_extrinsics_not_frozen" in blockers):
        raise ContractError("camera extrinsic status and blocker must agree")
    task_asset = assets.get("task_asset_materialization")
    task_asset_ready = (
        isinstance(task_asset, dict)
        and task_asset.get("status") == "materialized_remote_cpu_verified"
        and task_asset.get("distribution_allowed") is True
        and re.fullmatch(r"[0-9a-f]{64}", task_asset.get("manifest_sha256", "")) is not None
        and re.fullmatch(r"[0-9a-f]{64}", task_asset.get("urdf_sha256", "")) is not None
    )
    scene_runtime = contract.get("runtime_validation", {}).get("genesis_scene_cpu", {})
    scene_gate_passed = (
        isinstance(scene_runtime, dict)
        and scene_runtime.get("status") == "passed"
        and scene_runtime.get("table_contact_gate_pass") is True
        and scene_runtime.get("wrist_camera_attachment_gate_pass") is True
        and scene_runtime.get("hardware_camera_claim") is False
    )
    bowl_pending = "bowl_asset_not_materialized_for_genesis" in blockers
    if bowl_pending == (task_asset_ready and scene_gate_passed):
        raise ContractError("bowl materialization/runtime status and blocker must agree")
    if status == "ready" and blockers:
        raise ContractError("a ready contract cannot contain blockers")
    return blockers


def validate_task_contract(contract: dict[str, Any]) -> None:
    if contract.get("schema_version") != 1:
        raise ContractError("task schema_version must be 1")
    if not isinstance(contract.get("policy_hz"), (int, float)) or contract["policy_hz"] <= 0:
        raise ContractError("task.policy_hz must be positive")
    if not isinstance(contract.get("max_policy_steps"), int) or contract["max_policy_steps"] <= 0:
        raise ContractError("task.max_policy_steps must be a positive integer")
    stable_frames = contract.get("success_stable_frames")
    if not isinstance(stable_frames, int) or stable_frames <= 0:
        raise ContractError("task.success_stable_frames must be a positive integer")
    predicate = _require(contract, "success_predicate", "task")
    if not isinstance(predicate, dict):
        raise ContractError("task.success_predicate must be an object")
    if predicate.get("objects_stable_for_policy_frames") != stable_frames:
        raise ContractError("success predicate and success_stable_frames disagree")
    if contract.get("protocol_version") != "competition_strict_v1":
        raise ContractError("target task must use competition_strict_v1")
    if contract.get("source_compatibility_protocol") != "legacy_source_v1":
        raise ContractError("target task must name the legacy source protocol")
    if contract.get("protocol_comparability") != "not_directly_comparable":
        raise ContractError("legacy and strict protocols must not be marked directly comparable")
    if predicate.get("position_sort") != "ascending_z":
        raise ContractError("stack evaluator must sort bowl positions by ascending z")
    for field in (
        "xy_axis_alignment_tolerance_m",
        "height_absolute_tolerance_m",
        "maximum_linear_speed_m_s",
        "maximum_angular_speed_rad_s",
        "minimum_gripper_open_fraction",
    ):
        value = predicate.get(field)
        if not isinstance(value, (int, float)) or value <= 0:
            raise ContractError(f"success predicate has invalid {field}")
    heights = predicate.get("target_heights_m")
    if (
        not isinstance(heights, list)
        or len(heights) != 3
        or not all(isinstance(value, (int, float)) for value in heights)
    ):
        raise ContractError("success predicate must define three numeric target heights")
    if predicate.get("no_safety_failure") is not True:
        raise ContractError("success predicate must reject safety failures")
    if predicate.get("no_physics_divergence") is not True:
        raise ContractError("success predicate must reject physics divergence")

    _unique_strings(_require(contract, "stages", "task"), "task.stages")
    policy_observations = _unique_strings(
        _require(contract, "policy_observations", "task"), "task.policy_observations"
    )
    if any(key.startswith("privileged.") for key in policy_observations):
        raise ContractError("privileged state cannot be a policy observation")
    _unique_strings(
        _require(contract, "privileged_evaluator_state", "task"),
        "task.privileged_evaluator_state",
    )

    evaluation = _require(contract, "evaluation", "task")
    failure_taxonomy = _unique_strings(
        _require(evaluation, "failure_taxonomy", "evaluation"),
        "evaluation.failure_taxonomy",
    )
    required_failures = {"collision_safety", "physics_divergence", "runtime_error"}
    if not required_failures.issubset(failure_taxonomy):
        raise ContractError("evaluation.failure_taxonomy misses required failures")

    seed_sets = _require(evaluation, "seed_sets", "evaluation")
    if not isinstance(seed_sets, dict) or not seed_sets:
        raise ContractError("evaluation.seed_sets must be a non-empty object")
    all_seeds: list[int] = []
    for gate, seeds in seed_sets.items():
        if not isinstance(seeds, list) or not seeds:
            raise ContractError(f"seed set {gate} must be a non-empty list")
        if not all(isinstance(seed, int) and seed >= 0 for seed in seeds):
            raise ContractError(f"seed set {gate} contains an invalid seed")
        if len(seeds) != len(set(seeds)):
            raise ContractError(f"seed set {gate} contains duplicates")
        all_seeds.extend(seeds)
    if len(all_seeds) != len(set(all_seeds)):
        raise ContractError("evaluation seeds overlap across gates")

    rules = _require(evaluation, "promotion_rules", "evaluation")
    for gate, rule in rules.items():
        if gate not in seed_sets or not isinstance(rule, dict):
            raise ContractError(f"promotion rule {gate} has no seed set")
        if "minimum_success_rate" in rule and not 0 <= rule["minimum_success_rate"] <= 1:
            raise ContractError(f"promotion rule {gate} has invalid minimum_success_rate")
        if "required_episodes" in rule and rule["required_episodes"] != len(seed_sets[gate]):
            raise ContractError(f"promotion rule {gate} required_episodes disagrees with seeds")


def validate_source_task_contract(contract: dict[str, Any]) -> None:
    """Validate the frozen read-only RoboTwin source-task evidence boundary."""

    if contract.get("schema_version") != 1:
        raise ContractError("source task schema_version must be 1")
    if contract.get("task_id") != "stack_bowls_three":
        raise ContractError("source task must be stack_bowls_three")
    revision = _require(contract, "source_revision", "source_task")
    if not isinstance(revision, dict) or not revision:
        raise ContractError("source_task.source_revision must be a non-empty object")
    for name, digest in revision.items():
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ContractError(f"source revision {name} is not a SHA-256 digest")

    objects = _require(contract, "objects", "source_task")
    if not isinstance(objects, dict) or objects.get("count") != 3:
        raise ContractError("source task must contain exactly three bowls")
    asset = _require(objects, "asset", "source_task.objects")
    if asset.get("license_status") != "mit_dataset_pinned_materialization_allowed":
        raise ContractError("source bowl asset must retain its pinned MIT evidence")
    if asset.get("materialization_plan") != "configs/bowl-asset-plan.json":
        raise ContractError("source bowl asset must reference its materialization plan")

    reset = _require(contract, "reset_distribution", "source_task")
    if reset.get("sample_count") != 3 or reset.get("domain_randomization_enabled") is not False:
        raise ContractError("source reset distribution must retain three unrandomized samples")
    if reset.get("x_uniform_m") != [-0.3, 0.3] or reset.get("y_uniform_m") != [-0.15, 0.15]:
        raise ContractError("source bowl XY sampling bounds changed")
    if reset.get("z_m") != 0.741 or reset.get("table_height_m") != 0.74:
        raise ContractError("source bowl/table height changed")

    protocols = _require(contract, "evaluation_protocols", "source_task")
    legacy = protocols.get("legacy_source_v1") if isinstance(protocols, dict) else None
    if not isinstance(legacy, dict):
        raise ContractError("source task misses legacy_source_v1")
    if legacy.get("height_comparison") != "actual_z_minus_target_z_strict_less_than_0.02":
        raise ContractError("legacy one-sided height comparison must be preserved")
    if legacy.get("stable_frame_requirement") != 0:
        raise ContractError("legacy source protocol must not invent a stability-frame gate")
    boundary = _require(contract, "evidence_boundary", "source_task")
    if "not directly comparable" not in boundary.get("comparability", ""):
        raise ContractError("source evidence must separate legacy and strict protocols")


def validate_control_resampling_contract(
    contract: dict[str, Any], port: dict[str, Any]
) -> None:
    if contract.get("schema_version") != 1:
        raise ContractError("control resampling schema_version must be 1")
    if contract.get("protocol_version") != "topp_dense_to_mantis_30hz_v1":
        raise ContractError("unsupported control resampling protocol")
    source = _require(contract, "source", "control_resampling")
    target = _require(contract, "target", "control_resampling")
    algorithm = _require(contract, "algorithm", "control_resampling")
    if source.get("physics_hz") != 250.0 or source.get("physics_dt_s") != 0.004:
        raise ContractError("control resampling source clock must remain 250Hz")
    if source.get("requires_explicit_timestamps") is not True:
        raise ContractError("control resampling must require explicit dense timestamps")
    if source.get("missing_dense_trace_policy") != (
        "reject_do_not_infer_duration_from_policy_step_index"
    ):
        raise ContractError("control resampling must reject endpoint-only source records")
    if target.get("control_hz") != port["target"]["control_hz"]:
        raise ContractError("control resampling target clock disagrees with port contract")
    if target.get("joint_order") != port["target"]["joint_order"]:
        raise ContractError("control resampling joint order disagrees with port contract")
    limits = target.get("velocity_limits_per_s")
    if (
        not isinstance(limits, list)
        or len(limits) != len(target["joint_order"])
        or not all(isinstance(value, (int, float)) and value > 0 for value in limits)
    ):
        raise ContractError("control resampling velocity limits are invalid")
    if algorithm.get("semantic_reorder_before_resampling") is not True:
        raise ContractError("semantic reorder must occur before control resampling")
    if algorithm.get("retiming") != (
        "uniform_time_stretch_by_max_source_segment_velocity_to_target_limit_ratio"
    ):
        raise ContractError("control resampling retiming rule changed")


def validate_camera_extrinsics_contract(
    contract: dict[str, Any], port: dict[str, Any]
) -> None:
    if contract.get("schema_version") != 1:
        raise ContractError("camera extrinsics schema_version must be 1")
    if port["target"].get("camera_extrinsics_contract") != "configs/camera-extrinsics-v1.json":
        raise ContractError("port does not reference the frozen camera extrinsics contract")
    from .camera_mounts import genesis_wrist_mounts

    mounts = genesis_wrist_mounts(contract)
    target_extrinsics = port["target"]["camera_extrinsics"]
    for name, resolved in mounts.items():
        if target_extrinsics[name].get("parent") != resolved["parent"]:
            raise ContractError(f"port camera parent disagrees for {name}")
        source_mount = contract["mounts"][name]
        if target_extrinsics[name].get("xyz_m") != source_mount.get("xyz_m"):
            raise ContractError(f"port camera xyz disagrees for {name}")
        if target_extrinsics[name].get("rpy_rad") != source_mount.get("rpy_rad"):
            raise ContractError(f"port camera rpy disagrees for {name}")


def validate_bowl_asset_plan(plan: dict[str, Any], port: dict[str, Any]) -> None:
    if plan.get("schema_version") != 1:
        raise ContractError("bowl asset plan schema_version must be 1")
    if plan.get("status") != "licensed_ready_to_materialize":
        raise ContractError("bowl asset plan must be licensed and ready")
    if port["assets"].get("task_asset_plan") != "configs/bowl-asset-plan.json":
        raise ContractError("port does not reference the bowl asset plan")
    source = _require(plan, "source", "bowl_asset_plan")
    if source.get("license") != "MIT":
        raise ContractError("bowl dataset license must be MIT")
    for field in ("dataset_revision", "archive_lfs_sha256", "license_file_sha256"):
        value = source.get(field)
        expected_length = 40 if field == "dataset_revision" else 64
        if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{expected_length}}}", value) is None:
            raise ContractError(f"bowl source has invalid {field}")
    files = _require(plan, "files", "bowl_asset_plan")
    if not isinstance(files, dict) or set(files) != {"visual", "collision", "metadata", "license"}:
        raise ContractError("bowl asset file roles are incomplete")
    for role, spec in files.items():
        if not isinstance(spec, dict) or re.fullmatch(r"[0-9a-f]{64}", spec.get("sha256", "")) is None:
            raise ContractError(f"bowl asset has invalid {role} hash")
    physics = _require(plan, "source_physics_receipt", "bowl_asset_plan")
    if not isinstance(physics.get("mass_kg"), (int, float)) or physics["mass_kg"] <= 0:
        raise ContractError("bowl source mass must be positive")
    if plan.get("materialization", {}).get("distribution_allowed") is not True:
        raise ContractError("licensed bowl materialization must retain distribution permission")


def validate_scene_gate_contracts(
    port: dict[str, Any],
    control_resampling: dict[str, Any],
    camera_extrinsics: dict[str, Any],
    bowl_asset_plan: dict[str, Any],
) -> None:
    validate_control_resampling_contract(control_resampling, port)
    validate_camera_extrinsics_contract(camera_extrinsics, port)
    validate_bowl_asset_plan(bowl_asset_plan, port)


def validate_fixed_base_plan(plan: dict[str, Any], port: dict[str, Any]) -> None:
    if plan.get("schema_version") != 1:
        raise ContractError("fixed-base plan schema_version must be 1")
    if plan.get("status") not in {"planned_not_materialized", "materialized_local_only", "ready"}:
        raise ContractError("fixed-base plan has an unsupported status")
    assets = port["assets"]
    target = port["target"]
    source = plan.get("source")
    topology = plan.get("topology")
    meshes = plan.get("meshes")
    limits = plan.get("joint_limits")
    gates = plan.get("gates")
    if not all(isinstance(section, dict) for section in (source, topology, meshes, limits, gates)):
        raise ContractError("fixed-base plan sections must be objects")
    if source.get("revision") != assets.get("description_revision"):
        raise ContractError("fixed-base source revision disagrees with port contract")
    if source.get("urdf") != assets.get("candidate_full_urdf"):
        raise ContractError("fixed-base source URDF disagrees with port contract")
    if topology.get("root_link") != assets["fixed_base_profile"].get("root_link"):
        raise ContractError("fixed-base root link disagrees with port contract")
    if topology.get("selected_joint_order") != target.get("physical_joint_order"):
        raise ContractError("fixed-base joint order disagrees with physical joint order")
    if topology.get("selected_joint_count") != len(target["physical_joint_order"]):
        raise ContractError("fixed-base selected_joint_count is inconsistent")
    if topology.get("selected_link_count") != topology.get("selected_joint_count") + 1:
        raise ContractError("fixed-base topology must be a single tree")
    resolved_meshes = meshes.get("resolved_files")
    if not isinstance(resolved_meshes, list) or len(resolved_meshes) != meshes.get("unique_count"):
        raise ContractError("fixed-base mesh count is inconsistent")
    if len(resolved_meshes) != len(set(resolved_meshes)):
        raise ContractError("fixed-base mesh list contains duplicates")
    if set(limits) != set(target["physical_joint_order"]):
        raise ContractError("fixed-base limits must exactly cover physical joints")
    for joint_name, limit in limits.items():
        if not isinstance(limit, dict):
            raise ContractError(f"joint limit for {joint_name} must be an object")
        lower = limit.get("lower")
        upper = limit.get("upper")
        if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
            raise ContractError(f"joint {joint_name} must have numeric lower and upper limits")
        if lower >= upper:
            raise ContractError(f"joint {joint_name} has a non-positive range")
        if not isinstance(limit.get("velocity"), (int, float)) or limit["velocity"] <= 0:
            raise ContractError(f"joint {joint_name} has invalid velocity limit")
    if gates.get("all_selected_joints_present") is not True:
        raise ContractError("fixed-base plan did not resolve every selected joint")
    if gates.get("all_selected_meshes_resolved") is not True:
        raise ContractError("fixed-base plan did not resolve every selected mesh")
    if plan.get("status") == "ready" and not gates.get("distribution_allowed"):
        raise ContractError("a ready fixed-base plan must be distributable")


def validate_rim_support_overlay_plan(plan: dict[str, Any], port: dict[str, Any]) -> None:
    if plan.get("schema_version") != 1 or plan.get("status") != "local_prototype_ready":
        raise ContractError("rim-support overlay plan schema or status changed")
    if plan.get("porting_mode") != "new_robot_same_task":
        raise ContractError("rim-support overlay must preserve new_robot_same_task mode")
    if plan.get("task_id") != port["target"]["task_id"]:
        raise ContractError("rim-support overlay task disagrees with the port contract")
    assets = port["assets"]
    if assets.get("rim_support_overlay_plan") != "configs/mantis-rim-support-overlay-v4.json":
        raise ContractError("port contract does not pin the rim-support overlay plan")
    source = plan.get("source_asset", {})
    for field in ("manifest_sha256", "output_urdf_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", source.get(field, "")) is None:
            raise ContractError(f"rim-support source {field} is not a SHA-256")
    if source.get("output_urdf") != "urdf/mantis_fixed_base.urdf":
        raise ContractError("rim-support parent URDF path changed")
    if source.get("required_distribution_allowed") is not False:
        raise ContractError("rim-support source distribution boundary changed")
    geometry = plan.get("geometry", {})
    if geometry.get("shape") != "box":
        raise ContractError("rim-support geometry must be a box primitive")
    if geometry.get("target_links") != ["left_clamp_left_link", "right_clamp_left_link"]:
        raise ContractError("rim-support target links changed")
    if geometry.get("size_xyz_m") != [0.022, 0.014, 0.004]:
        raise ContractError("rim-support primitive size changed")
    if geometry.get("origin_xyz_m") != [0.061, 0.007, -0.006]:
        raise ContractError("rim-support primitive origin changed")
    if geometry.get("origin_rpy_rad") != [0.0, 0.0, 0.0]:
        raise ContractError("rim-support primitive orientation changed")
    if geometry.get("per_link_origin_rpy_rad") != {
        "left_clamp_left_link": [0.6108652381980153, 0.0, 0.0],
        "right_clamp_left_link": [0.6108652381980153, 0.0, 0.0],
    }:
        raise ContractError("rim-support per-link orientations changed")
    licensing = plan.get("licensing", {})
    if licensing.get("upstream_mantis_distribution_allowed") is not False:
        raise ContractError("rim-support plan may not relax the upstream license boundary")
    if licensing.get("materialized_output_distribution_allowed") is not False:
        raise ContractError("rim-support materialized output must remain local-only")
    materialization = plan.get("materialization", {})
    if materialization.get("overwrite_allowed") is not False:
        raise ContractError("rim-support materialization must be non-overwriting")
    if materialization.get("output_urdf") != "urdf/mantis_fixed_base_rim_support_v4.urdf":
        raise ContractError("rim-support output URDF changed")
    if plan.get("gates", {}).get("claim_boundary") != (
        "local CPU prototype geometry only; no hardware, AMD, task-success, G1, or redistribution claim"
    ):
        raise ContractError("rim-support claim boundary changed")


#: The deterministic contiguous training-seed pool for stack_bowls_three.
#: portability_smoke is the first 3, initial_capture the first 10, and
#: expansion_capture all 50.  This is a planned allocation only.
TRAINING_SEED_POOL: list[int] = list(range(1001, 1051))

#: Frozen manifest identity and contract-bearing scalar fields.  Every field
#: below is pinned by exact equality so the checked-in manifest cannot drift.
TRAINING_SEED_MANIFEST_VERSION = "training-seeds-v1"
TRAINING_SEED_STATUS = "planned_allocation_frozen"
TRAINING_SEED_POOL_RANGE: list[int] = [1001, 1050]
TRAINING_SEED_ALLOCATION_RULE = (
    "deterministic contiguous pool 1001..1050; portability_smoke is the first 3, "
    "initial_capture the first 10, expansion_capture all 50"
)
TRAINING_SEED_DISJOINTNESS = (
    "every seed in this manifest is disjoint from every evaluation seed set in "
    "configs/task-pack-v1.json, including g1_smoke"
)
#: The full no-claim boundary.  Pinned by exact equality so removing task
#: success, multi-seed robustness, AMD/ROCm, learned-policy, collection, or the
#: explicit no-run/capture/export/train sentence cannot pass.
TRAINING_SEED_CLAIM_BOUNDARY = (
    "This is a planned and frozen training-seed allocation only. "
    "It makes no episode collection, task success, multi-seed robustness, "
    "learned-policy, or AMD/ROCm execution claim. "
    "No episode has been run, captured, exported, or trained against these seeds."
)

#: Required seed-set sizes for the training-seed manifest.
_TRAINING_SEED_SET_SIZES = {
    "portability_smoke": 3,
    "initial_capture": 10,
    "expansion_capture": 50,
}

#: Frozen contract-bearing manifest scalars compared by exact equality.
_TRAINING_SEED_SCALARS = {
    "manifest_version": TRAINING_SEED_MANIFEST_VERSION,
    "status": TRAINING_SEED_STATUS,
    "allocation_rule": TRAINING_SEED_ALLOCATION_RULE,
    "disjointness": TRAINING_SEED_DISJOINTNESS,
    "claim_boundary": TRAINING_SEED_CLAIM_BOUNDARY,
}


def validate_training_seed_manifest(
    manifest: dict[str, Any], task: dict[str, Any]
) -> None:
    """Validate the frozen training-seed manifest for stack_bowls_three.

    This is a pure structural validator.  The manifest is a planned and frozen
    seed allocation only; it makes no episode collection, task success,
    multi-seed robustness, learned-policy, or AMD/ROCm execution claim.
    """
    if manifest.get("schema_version") != 1:
        raise ContractError("training-seed manifest schema_version must be 1")
    if manifest.get("task_id") != "stack_bowls_three":
        raise ContractError("training-seed manifest task_id must be stack_bowls_three")
    if manifest.get("task_id") != task.get("task_id"):
        raise ContractError("training-seed manifest task_id disagrees with task contract")
    if manifest.get("protocol_version") != "competition_strict_v1":
        raise ContractError("training-seed manifest must use competition_strict_v1")
    if manifest.get("protocol_version") != task.get("protocol_version"):
        raise ContractError("training-seed manifest protocol_version disagrees with task contract")
    if manifest.get("source_compatibility_protocol") != task.get("source_compatibility_protocol"):
        raise ContractError(
            "training-seed manifest source_compatibility_protocol disagrees with task contract"
        )
    if manifest.get("protocol_comparability") != task.get("protocol_comparability"):
        raise ContractError(
            "training-seed manifest protocol_comparability disagrees with task contract"
        )
    if manifest.get("seed_pool_range") != TRAINING_SEED_POOL_RANGE:
        raise ContractError("training-seed manifest seed_pool_range changed")

    for field, expected in _TRAINING_SEED_SCALARS.items():
        if manifest.get(field) != expected:
            raise ContractError(f"training-seed manifest {field} changed")

    seed_sets = _require(manifest, "seed_sets", "training_seed_manifest")
    if not isinstance(seed_sets, dict) or set(seed_sets) != set(_TRAINING_SEED_SET_SIZES):
        raise ContractError("training-seed manifest seed-set names changed")

    expected_pool = list(TRAINING_SEED_POOL)
    for name, size in _TRAINING_SEED_SET_SIZES.items():
        seeds = seed_sets.get(name)
        if not isinstance(seeds, list):
            raise ContractError(f"training-seed manifest {name} must be a list")
        if len(seeds) != size:
            raise ContractError(
                f"training-seed manifest {name} must contain exactly {size} seeds"
            )
        if not all(isinstance(seed, int) and not isinstance(seed, bool) and seed > 0 for seed in seeds):
            raise ContractError(f"training-seed manifest {name} contains an invalid seed")
        if len(seeds) != len(set(seeds)):
            raise ContractError(f"training-seed manifest {name} contains duplicates")
        if seeds != sorted(seeds):
            raise ContractError(f"training-seed manifest {name} must be sorted ascending")
        if seeds != expected_pool[:size]:
            raise ContractError(
                f"training-seed manifest {name} must be the deterministic pool prefix "
                f"{expected_pool[:size]}"
            )

    # Nested allocation: portability_smoke subset of initial_capture subset of
    # expansion_capture.  Follows from the deterministic prefixes above, but is
    # asserted explicitly so a future allocation rule change cannot silently
    # break the nesting invariant.
    smoke = set(seed_sets["portability_smoke"])
    initial = set(seed_sets["initial_capture"])
    expansion = set(seed_sets["expansion_capture"])
    if not (smoke <= initial <= expansion):
        raise ContractError("training-seed manifest seed sets must be nested")

    # Disjointness from every evaluation seed set in the task contract,
    # including g1_smoke as an explicit extra safety condition.
    evaluation = _require(task, "evaluation", "task")
    eval_seed_sets = _require(evaluation, "seed_sets", "evaluation")
    g1 = eval_seed_sets.get("g1_smoke")
    if not isinstance(g1, list) or g1 != [1]:
        raise ContractError("task g1_smoke must be exactly [1]")
    eval_seeds: set[int] = set()
    for gate, seeds in eval_seed_sets.items():
        if not isinstance(seeds, list):
            raise ContractError(f"task seed set {gate} must be a list")
        eval_seeds.update(seeds)
    if set(g1) & expansion:
        raise ContractError("training-seed manifest leaks into g1_smoke")
    if eval_seeds & expansion:
        raise ContractError("training-seed manifest leaks into an evaluation seed set")


def validate_contract_pair(
    port: dict[str, Any],
    task: dict[str, Any],
    source_task: Optional[dict[str, Any]] = None,
) -> list[str]:
    blockers = validate_port_contract(port)
    validate_task_contract(task)
    target_observations = port["target"]["policy_observation_keys"]
    if target_observations != task["policy_observations"]:
        raise ContractError("port and task policy observation orders disagree")
    if port["target"]["control_hz"] != task["policy_hz"]:
        raise ContractError("port target control_hz and task policy_hz disagree")
    if port["target"]["task_id"] != task["task_id"]:
        raise ContractError("port target task_id and task task_id disagree")
    if source_task is not None:
        validate_source_task_contract(source_task)
        if port["source"]["task_id"] != source_task["task_id"]:
            raise ContractError("port source task_id and source task contract disagree")
        if task.get("baseline_distribution", {}).get("contract") != port["source"].get("task_contract"):
            raise ContractError("target baseline must reference the frozen source task contract")
    return blockers
