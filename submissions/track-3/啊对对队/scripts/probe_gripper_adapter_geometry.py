#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.config import ExperimentConfig, load_config
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.randomization import DomainRandomizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build matched stock and parcel-adapter Panda scenes and report the "
            "resulting finger geometry."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/catalog_v2.toml",
    )
    parser.add_argument("--profile", default="large_narrow_carton")
    parser.add_argument("--episode", type=int, default=4_120_001)
    parser.add_argument("--extension-m", type=float, default=0.030)
    parser.add_argument("--density-kg-m3", type=float, default=1240.0)
    parser.add_argument("--backend", choices=("cpu", "rocm"), default="rocm")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _flat_list(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "reshape"):
        value = value.reshape(-1)
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def _asset_path(env: GenesisParcelEnv) -> Path:
    path = Path(env._robot_mjcf_path)
    if path.is_absolute():
        return path
    return Path(env.gs.__file__).resolve().parent / "assets" / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _adapter_geometries(path: Path) -> list[dict[str, str]]:
    root = ET.parse(path).getroot()
    return [
        dict(geom.attrib)
        for geom in root.iter("geom")
        if "_parcel_adapter_" in geom.attrib.get("name", "")
    ]


def _finger_inertials(path: Path) -> dict[str, dict[str, str]]:
    root = ET.parse(path).getroot()
    rows = {}
    for finger_name in ("left_finger", "right_finger"):
        finger = root.find(f".//body[@name='{finger_name}']")
        if finger is None or finger.find("inertial") is None:
            raise ValueError(f"MJCF is missing {finger_name} inertial data")
        rows[finger_name] = dict(finger.find("inertial").attrib)
    return rows


def _variant(
    config: ExperimentConfig,
    sample: Any,
    *,
    backend: str,
    enabled: bool,
    extension_m: float,
    density_kg_m3: float,
) -> dict[str, Any]:
    variant_config = replace(
        config,
        task=replace(
            config.task,
            parcel_gripper_adapter_enabled=enabled,
            parcel_gripper_adapter_extension_m=extension_m,
            parcel_gripper_adapter_density_kg_m3=density_kg_m3,
        ),
    )
    variant_config.validate()
    with GenesisParcelEnv(variant_config, sample, backend=backend) as env:
        fingers = {}
        for finger_name, finger in (
            ("left_finger", env.left_finger),
            ("right_finger", env.right_finger),
        ):
            aabb = [_flat_list(corner) for corner in finger.get_AABB()]
            fingers[finger_name] = {
                "geometry_count": len(finger.geoms),
                "reported_geometry_count": int(finger.n_geoms),
                "aabb_m": aabb,
                "aabb_span_m": [
                    upper - lower
                    for lower, upper in zip(aabb[0], aabb[1], strict=True)
                ],
            }
        asset_path = _asset_path(env).resolve()
        return {
            "adapter_enabled": enabled,
            "extension_m": extension_m,
            "effective_density_kg_m3": density_kg_m3,
            "adapter_mass_per_finger_kg": env._robot_adapter_mass_per_finger_kg,
            "robot_asset_source": env._robot_asset_source,
            "mjcf_path": str(asset_path),
            "mjcf_sha256": _sha256(asset_path),
            "finger_inertials": _finger_inertials(asset_path),
            "adapter_geometries": (
                _adapter_geometries(asset_path) if enabled else []
            ),
            "fingers": fingers,
        }


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    randomizer = DomainRandomizer(
        config.randomization,
        config.seed,
        config.parcel_profiles,
    )
    sample = randomizer.sample_profile(args.profile, args.episode)
    stock = _variant(
        config,
        sample,
        backend=args.backend,
        enabled=False,
        extension_m=args.extension_m,
        density_kg_m3=args.density_kg_m3,
    )
    adapter = _variant(
        config,
        sample,
        backend=args.backend,
        enabled=True,
        extension_m=args.extension_m,
        density_kg_m3=args.density_kg_m3,
    )

    geometry_count_delta = {
        name: (
            adapter["fingers"][name]["geometry_count"]
            - stock["fingers"][name]["geometry_count"]
        )
        for name in ("left_finger", "right_finger")
    }
    validation = {
        # Genesis exposes collision geoms through RigidLink.geoms; the matching
        # contype=0 visual box remains present in the generated MJCF only.
        "expected_collision_geometry_count_delta_per_finger": 1,
        "geometry_count_delta_per_finger": geometry_count_delta,
        "generated_adapter_geometry_count": len(adapter["adapter_geometries"]),
    }
    validation["passed"] = (
        all(value == 1 for value in geometry_count_delta.values())
        and len(adapter["adapter_geometries"]) == 4
    )
    return {
        "schema_version": 1,
        "backend": args.backend,
        "config": str(args.config.resolve()),
        "profile": args.profile,
        "episode": args.episode,
        "sample": asdict(sample),
        "stock": stock,
        "adapter": adapter,
        "validation": validation,
    }


def main() -> int:
    args = parse_args()
    result = run(args)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
