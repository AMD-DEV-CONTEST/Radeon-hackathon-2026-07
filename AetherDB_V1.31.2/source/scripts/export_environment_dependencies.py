"""Export sanitized, reproducible dependency snapshots for release work."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.version import APP_VERSION, APP_VERSION_LABEL


DEFAULT_OUTPUT_DIR = ROOT / "markdown文件存放区" / "环境依赖快照"
DEFAULT_REMOTE_SNAPSHOT = (
    ROOT
    / "local_agent_runs"
    / "ACCEPT2-01"
    / "env-raw"
    / f"amd-rocm-environment-{APP_VERSION_LABEL.lower()}.json"
)
PROJECT_DEPENDENCY_FILES = (
    ROOT / "requirements.txt",
    ROOT / "requirements-test.txt",
    ROOT / "requirements-desktop-build.txt",
    ROOT / "requirements-tts-kokoro.txt",
    ROOT / "frontend" / "package.json",
    ROOT / "frontend" / "pnpm-lock.yaml",
    ROOT / "frontend" / "src-tauri" / "Cargo.lock",
)
FORBIDDEN_REMOTE_KEYS = {
    "hostname",
    "host",
    "ip",
    "address",
    "username",
    "user",
    "home",
    "path",
    "identity_file",
    "target",
    "environment_variables",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0].strip() if output else None


def _local_python_packages() -> list[dict[str, str]]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
    )
    packages = json.loads(result.stdout)
    return sorted(
        (
            {"name": str(item["name"]), "version": str(item["version"])}
            for item in packages
        ),
        key=lambda item: item["name"].lower(),
    )


def _validate_remote_snapshot(value: Any, key: str | None = None) -> None:
    if key is not None and key.lower() in FORBIDDEN_REMOTE_KEYS:
        raise ValueError(f"Remote dependency snapshot contains forbidden key: {key}")
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _validate_remote_snapshot(child_value, str(child_key))
    elif isinstance(value, list):
        for item in value:
            _validate_remote_snapshot(item)


def _file_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]


def _dependency_file_manifest() -> list[dict[str, Any]]:
    rows = []
    for path in PROJECT_DEPENDENCY_FILES:
        if not path.is_file():
            raise FileNotFoundError(path)
        rows.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


def _write_package_list(path: Path, packages: list[dict[str, str]]) -> None:
    lines = [
        "# Sanitized package snapshot: package names and versions only.",
        f"# AetherDB {APP_VERSION_LABEL}",
        *(f"{item['name']}=={item['version']}" for item in packages),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_file_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# SHA256  SIZE_BYTES  RELATIVE_PATH",
        *(f"{row['sha256']}  {row['size_bytes']}  {row['path']}" for row in rows),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_markdown(snapshot: dict[str, Any], output_dir: Path) -> str:
    remote = snapshot["amd_rocm_environment"]
    accelerator = remote["accelerator"]
    os_info = remote["os"]
    tools = snapshot["windows_development_environment"]["tools"]
    dependency_files = snapshot["project_dependency_files"]
    dependency_table = "\n".join(
        f"| `{row['path']}` | `{row['sha256']}` |" for row in dependency_files
    )
    wheel_rows = snapshot["tts_offline_wheelhouse"]
    model_rows = snapshot["kokoro_model_artifacts"]
    offline_archive = snapshot["tts_offline_archive"]
    total_vram_gib = accelerator["device_total_memory_bytes"] / (1024**3)
    relative_snapshot_dir = output_dir.relative_to(ROOT / "markdown文件存放区")
    return f"""# AetherDB {APP_VERSION_LABEL} 项目环境与依赖快照

> 生成时间：{snapshot["captured_at_utc"]}
> 用途：发行打包、比赛环境复现、Windows/AMD ROCm 差异分析
> 安全边界：仅记录版本、能力和哈希；不记录主机名、IP、SSH 参数、密钥、环境变量值或本地配置内容。

## 1. 环境分层

- Windows 开发环境：主要面向桌面应用、FastAPI、Vue/Tauri 开发与通用测试。
- AMD ROCm 基础环境：比赛服务器上的后端与 GPU 验收基线。
- TTS Worker 环境：独立 Python 环境，只在 Worker 子进程中加载 Kokoro 和语音依赖。
- 模型与离线 wheelhouse：外置缓存和发行素材，不进入源码提交，也不加载进 FastAPI 进程。

## 2. Windows 开发环境

- OS：{snapshot["windows_development_environment"]["os"]["system"]} {snapshot["windows_development_environment"]["os"]["release"]}，{snapshot["windows_development_environment"]["os"]["architecture"]}
- Python：{snapshot["windows_development_environment"]["python"]["version"]}
- Node：{tools.get("node") or "未安装"}
- pnpm：{tools.get("pnpm") or "未安装"}
- 前端包管理约束：`pnpm >=10.0.0`，`pnpm-lock.yaml` lockfile 9.0
- Rust：{tools.get("rustc") or "未安装"}
- Cargo：{tools.get("cargo") or "未安装"}
- Python 包数：{len(snapshot["windows_development_environment"]["python_packages"])}

完整包清单：`{relative_snapshot_dir.as_posix()}/windows-dev-python-packages-{APP_VERSION_LABEL.lower()}.txt`

## 3. AMD ROCm 验收环境

- OS：{os_info["distribution"]}，kernel {os_info["kernel"]}，{os_info["architecture"]}
- Python：{remote["python"]["version"]}
- PyTorch：{accelerator["torch_version"]}
- HIP：{accelerator["hip_version"]}
- 设备：{accelerator["device_name"]}，约 {total_vram_gib:.1f} GiB
- 实测执行提供者：`{accelerator["execution_provider_verified"]}`
- 基础 Python 包数：{len(remote["base_python_packages"])}
- TTS Worker Python 包数：{len(remote["tts_worker_python_packages"])}
- ROCm 相关系统包数：{len(remote["rocm_packages"])}

完整清单：

- `{relative_snapshot_dir.as_posix()}/amd-rocm-base-python-packages-{APP_VERSION_LABEL.lower()}.txt`
- `{relative_snapshot_dir.as_posix()}/amd-rocm-tts-worker-python-packages-{APP_VERSION_LABEL.lower()}.txt`
- `{relative_snapshot_dir.as_posix()}/amd-rocm-environment-{APP_VERSION_LABEL.lower()}.json`

## 4. 锁文件与声明文件

| 文件 | SHA-256 |
|---|---|
{dependency_table}

这些声明文件是发行依赖的权威输入；环境快照用于复现实测状态，不替代项目锁文件。

## 5. TTS 离线素材

- Wheel 数：{len(wheel_rows)}
- Wheel 总体积：{sum(row["size_bytes"] for row in wheel_rows)} bytes
- 模型文件数：{len(model_rows)}
- 模型总体积：{sum(row["size_bytes"] for row in model_rows)} bytes
- 模型 revision：`f3ff3571791e39611d31c381e3a41a3af07b4987`
- 最终离线归档：`{offline_archive["name"]}`，{offline_archive["size_bytes"]} bytes
- 离线归档 SHA-256：`{offline_archive["sha256"]}`
- 权重与声音文件必须逐项通过大小和 SHA-256 校验后才允许安装。

完整清单：

- `{relative_snapshot_dir.as_posix()}/tts-wheelhouse-sha256-{APP_VERSION_LABEL.lower()}.txt`
- `{relative_snapshot_dir.as_posix()}/kokoro-model-sha256-{APP_VERSION_LABEL.lower()}.txt`

## 6. 打包边界

- 不把 AMD ROCm 依赖强塞进 Windows 通用安装包。
- 不把 CUDA 与 ROCm wheel 混装；不同 GPU 后端使用独立发行配置。
- 不把模型权重、真实数据库、日志、密钥或 `config.yaml` 放入源码包。
- TTS 依赖存在不等于 FastAPI 加载 TTS；权重只能由 AetherDB Audio Worker 子进程加载。
- Kokoro 82M 是已验证的轻量双语基线，不等于最终高性能双语模型选型。
- macOS、CUDA、三系统图形化安装仍需各自实机生成独立快照。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--remote-snapshot", type=Path, default=DEFAULT_REMOTE_SNAPSHOT)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--offline-archive", type=Path, required=True)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    remote = json.loads(args.remote_snapshot.resolve().read_text(encoding="utf-8"))
    _validate_remote_snapshot(remote)
    local_packages = _local_python_packages()
    wheel_manifest = _file_manifest(args.wheelhouse.resolve())
    model_manifest = _file_manifest(args.model_root.resolve())
    offline_archive = args.offline_archive.resolve()
    if not offline_archive.is_file():
        raise FileNotFoundError(offline_archive)

    snapshot = {
        "schema_version": 1,
        "project_version": APP_VERSION,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "windows_development_environment": {
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "architecture": platform.machine(),
            },
            "python": {
                "version": platform.python_version(),
                "implementation": platform.python_implementation(),
            },
            "tools": {
                "node": _run_version(["node", "--version"]),
                "pnpm": _run_version(["pnpm", "--version"]),
                "rustc": _run_version(["rustc", "--version"]),
                "cargo": _run_version(["cargo", "--version"]),
            },
            "python_packages": local_packages,
        },
        "amd_rocm_environment": remote,
        "project_dependency_files": _dependency_file_manifest(),
        "tts_offline_wheelhouse": wheel_manifest,
        "kokoro_model_artifacts": model_manifest,
        "tts_offline_archive": {
            "name": offline_archive.name,
            "size_bytes": offline_archive.stat().st_size,
            "sha256": _sha256(offline_archive),
        },
    }

    label = APP_VERSION_LABEL.lower()
    _write_package_list(
        output_dir / f"windows-dev-python-packages-{label}.txt",
        local_packages,
    )
    _write_package_list(
        output_dir / f"amd-rocm-base-python-packages-{label}.txt",
        remote["base_python_packages"],
    )
    _write_package_list(
        output_dir / f"amd-rocm-tts-worker-python-packages-{label}.txt",
        remote["tts_worker_python_packages"],
    )
    _write_file_manifest(
        output_dir / f"tts-wheelhouse-sha256-{label}.txt",
        wheel_manifest,
    )
    _write_file_manifest(
        output_dir / f"kokoro-model-sha256-{label}.txt",
        model_manifest,
    )
    (output_dir / f"amd-rocm-environment-{label}.json").write_text(
        json.dumps(remote, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"project-environment-{label}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    guide_path = ROOT / "markdown文件存放区" / (
        f"PROJECT_ENVIRONMENT_DEPENDENCIES_{APP_VERSION_LABEL}.md"
    )
    guide_path.write_text(_render_markdown(snapshot, output_dir), encoding="utf-8")

    print(
        json.dumps(
            {
                "guide": str(guide_path.relative_to(ROOT)),
                "snapshot_dir": str(output_dir.relative_to(ROOT)),
                "windows_packages": len(local_packages),
                "amd_base_packages": len(remote["base_python_packages"]),
                "amd_tts_packages": len(remote["tts_worker_python_packages"]),
                "wheel_files": len(wheel_manifest),
                "model_files": len(model_manifest),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
