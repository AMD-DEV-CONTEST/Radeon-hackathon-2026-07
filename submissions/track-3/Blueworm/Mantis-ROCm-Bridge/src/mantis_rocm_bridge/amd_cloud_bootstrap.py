"""Stage-1 AMD Radeon Cloud bootstrap: install only the official ROCm wheels.

Scope is deliberately limited to stage 1:

  * verify that exactly one Radeon GPU and at least one ROCm tool are present;
  * strictly validate the official ``torch`` / ``torchvision`` / ``torchaudio``
    / ``triton`` wheel paths and SHA-256 digests recorded in the stage-0
    inventory in a freshly versioned runtime contract;
  * create the virtual environment at the contract-selected persistent path;
  * install the ROCm PyTorch stack with a strict two-phase pip:
      1. a *controlled network* dependency install that may reach PyPI but is
         restricted to the whitelisted non-accelerated prerequisites
         (``filelock``, ``typing-extensions>=4.10.0``, ``sympy>=1.13.3``,
         ``networkx>=2.5.1``, ``jinja2``, ``fsspec>=0.8.5``, ``numpy==2.1.2``,
         ``pillow!=8.3.*,>=5.3.0``) and must never name
         torch/torchvision/torchaudio/triton/apex; and
      2. a strictly *offline* install (``--no-index --no-deps``) of the four
         explicit SHA-256-verified local instance wheels, so no accelerated
         wheel can ever be fetched from the network;
  * emit a bounded, secret-free JSON receipt, a bounded ``pip freeze`` and a
    torch HIP/device smoke that also records the installed torch/vision/audio/
    triton versions and checks them against the config targets.

This module must never train, never install Genesis or LeRobot (that is stage
2), and must fail closed on any verification failure. A receipt is written only
when every validation and execution check passes; a dry-run validates the plan
but never claims ``stage1_pass`` and never writes a file. The receipt existence
check happens *before* any venv or pip mutation, and receipts are written with
an atomic exclusive-create and are not overwritten by default.

All subprocess and ``PATH`` lookups are injected so the logic is unit-testable
without a GPU.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .contracts import ContractError


SCHEMA_VERSION = 1
STAGE = 1

# The four wheels that make up the stage-1 ROCm PyTorch stack. ``apex`` is
# recorded in the stage-0 inventory for traceability but is intentionally not
# installed here.
STAGE1_WHEEL_KEYS: tuple[str, ...] = ("torch", "torchvision", "torchaudio", "triton")

# ROCm tooling; the bootstrap only needs one of these on PATH.
ROCM_TOOLS: tuple[str, ...] = ("rocminfo", "amd-smi", "rocm-smi")

# Phase-1 (controlled-network) dependency specifications. These are exactly the
# non-accelerated prerequisites declared by the official torch/torchvision/
# torchaudio wheel METADATA that are NOT already present in the AMD base image
# (the image ships only setuptools 68.1.2 and wheel 0.42.0). Installing them up
# front lets phase 2 install the four ROCm wheels with --no-deps.
STAGE1_DEPENDENCY_SPECS: tuple[str, ...] = (
    "filelock",
    "typing-extensions>=4.10.0",
    "sympy>=1.13.3",
    "networkx>=2.5.1",
    "jinja2",
    "fsspec>=0.8.5",
    "numpy==2.1.2",
    "pillow!=8.3.*,>=5.3.0",
)

# Bare project names extracted from STAGE1_DEPENDENCY_SPECS; the phase-1 command
# may install these and only these.
STAGE1_DEPENDENCY_PACKAGE_NAMES: tuple[str, ...] = (
    "filelock",
    "typing-extensions",
    "sympy",
    "networkx",
    "jinja2",
    "fsspec",
    "numpy",
    "pillow",
)

# Accelerated ROCm packages that phase 1 must never name; they are installed
# offline from the local hashed wheels in phase 2. ``apex`` is included even
# though it is not installed in stage 1, so a stray ``pip install apex`` can
# never reach the network.
FORBIDDEN_ACCEL_PACKAGES: tuple[str, ...] = (
    "torch",
    "torchvision",
    "torchaudio",
    "triton",
    "apex",
)

# Human-readable description of the two-phase controlled network boundary,
# recorded verbatim in every receipt.
CONTROLLED_NETWORK_BOUNDARY = (
    "Two-phase controlled network boundary. Phase 1 (dependency install) is "
    "permitted to reach the network but is restricted to the whitelisted "
    "non-accelerated prerequisites filelock, typing-extensions>=4.10.0, "
    "sympy>=1.13.3, networkx>=2.5.1, jinja2, fsspec>=0.8.5, numpy==2.1.2, and "
    "pillow!=8.3.*,>=5.3.0, and must never name torch, torchvision, "
    "torchaudio, triton, or apex. Phase 2 (local ROCm install) is strictly "
    "offline (--no-index --no-deps) and installs only the four explicit "
    "SHA-256-verified local instance wheels, so no accelerated wheel can be "
    "fetched from PyPI."
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# rocminfo emits one ``Name:    gfxXXXX`` line per compute (GPU) agent; the
# host CPU agent reports a non-gfx name and is excluded by this match.
_GFX_NAME_RE = re.compile(r"^\s*Name:\s+gfx", re.IGNORECASE | re.MULTILINE)

# A "network accel install" is any pip target that names an accelerated
# package by version spec instead of a local wheel path, e.g. ``torch``,
# ``torch==2.9.1``, ``torchvision>=2``. Installing those can pull a CPU or CUDA
# build from PyPI and is strictly forbidden in the phase-2 local command. The
# leading ``(?:^|[\s=])`` and trailing ``(?=$|[\s<>=!~])`` boundaries avoid
# matching the package-name substring inside a local wheel path such as
# ``/torch-2.9.1+rocm7.2.1....whl`` (preceded by ``/`` and followed by ``-``).
_FORBIDDEN_NETWORK_TOKEN_RE = re.compile(
    r"(?:^|[\s=])(torch|torchvision|torchaudio|triton|apex)(?=$|[\s<>=!~])",
    re.IGNORECASE,
)

# Leading PEP 508 project-name prefix (letters, digits, ., -, _) of a token; a
# wheel path such as ``/torch-...whl`` starts with ``/`` and yields no name.
_NAME_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")

_PIP_FREEZE_MAX_CHARS = 200_000
_RECEIPT_MAX_DEVICES = 4

# Lines in pip freeze that look like secrets are redacted rather than recorded.
_SECRET_LINE_RE = re.compile(r"(token|password|secret|api[_.-]?key)", re.IGNORECASE)

# pip install flags that consume the following token as their value, so the
# value is not mistaken for a package name when scanning the phase-1 command.
_PIP_VALUE_FLAGS = frozenset(
    {
        "-c", "--constraint", "-e", "--editable", "-r", "--requirement",
        "-t", "--target", "-i", "--index-url", "--extra-index-url",
        "-f", "--find-links", "--prefix", "--src", "--no-binary",
        "--only-binary", "--config-settings", "--global-option",
        "--implementation", "--platform", "--python-version", "--abi",
        "--root", "--install-option", "--root-user-action",
    }
)

SubprocessRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
WhichLookup = Callable[[str], "str | None"]


# ---------------------------------------------------------------------------
# Inventory loading and wheel hashing
# ---------------------------------------------------------------------------


def load_stage1_inventory(config_path: str | Path) -> dict[str, Any]:
    """Load the runtime config and return the resolved stage-1 inventory.

    Raises :class:`ContractError` unless the config status is one of the
    monotonic stages ``stage0_inventory_verified`` or ``stage2_runtime_verified``
    and the four stage-1 wheels are present with absolute unix paths and valid
    SHA-256 digests. Rejects unknown or earlier invalid statuses (fail-closed).
    """

    from .contracts import load_json

    contract = load_json(config_path)
    accepted_statuses = ("stage0_inventory_verified", "stage2_runtime_verified")
    status = contract.get("status")
    if status not in accepted_statuses:
        raise ContractError(
            f"stage-1 bootstrap requires a freshly inventoried AMD runtime config "
            f"with status in {accepted_statuses}; got {status!r}"
        )
    inventory = contract.get("stage0_inventory")
    if not isinstance(inventory, dict):
        raise ContractError("stage0_inventory section is missing from the runtime config")
    official = inventory.get("official_wheels")
    if not isinstance(official, dict):
        raise ContractError("stage0_inventory.official_wheels is missing")
    wheels: list[dict[str, Any]] = []
    for key in STAGE1_WHEEL_KEYS:
        spec = official.get(key)
        if not isinstance(spec, dict):
            raise ContractError(f"official wheel spec for {key!r} is missing")
        path = spec.get("path")
        sha = spec.get("sha256")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ContractError(f"official wheel {key!r} path must be an absolute unix path")
        if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
            raise ContractError(f"official wheel {key!r} sha256 must be a 64-char lowercase hex digest")
        if spec.get("part_of_stage1_install") is not True:
            raise ContractError(f"official wheel {key!r} must be flagged part_of_stage1_install=true")
        wheels.append({"key": key, "path": path, "sha256": sha})

    gpu = inventory.get("gpu")
    if not isinstance(gpu, dict) or not isinstance(gpu.get("vram_bytes"), int):
        raise ContractError("stage0_inventory.gpu.vram_bytes must be an integer")
    platform = contract.get("platform")
    if not isinstance(platform, dict):
        raise ContractError("platform section is missing from the runtime config")
    venv_path = platform.get("virtual_environment")
    if not isinstance(venv_path, str) or not venv_path.startswith("/"):
        raise ContractError("platform.virtual_environment must be an absolute unix path")

    pytorch = contract.get("pytorch")
    if not isinstance(pytorch, dict):
        raise ContractError("pytorch section is missing from the runtime config")
    pytorch_targets: dict[str, str] = {}
    for key in STAGE1_WHEEL_KEYS:
        field = f"{key}_version"
        value = pytorch.get(field)
        if not isinstance(value, str) or not value:
            raise ContractError(f"pytorch.{field} must be a non-empty string")
        pytorch_targets[key] = value

    return {
        "runtime_id": contract.get("runtime_id"),
        "instance_id": inventory.get("instance_id"),
        "gpu": dict(gpu),
        "rocm_version": inventory.get("rocm_version"),
        "amd_smi_version": inventory.get("amd_smi_version"),
        "python_version": inventory.get("python_version"),
        "pip_version": inventory.get("pip_version"),
        "persistent_root": inventory.get("persistent_root"),
        "venv_path": venv_path,
        "pytorch_targets": pytorch_targets,
        "wheels": wheels,
    }


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, streaming in 1 MiB chunks."""

    path = Path(path)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractError(f"cannot hash required wheel {path}: {exc}") from exc
    return digest.hexdigest()


def _resolve_under_root(wheel_path: str, root: str | Path) -> Path:
    """Resolve an absolute instance wheel path against a local root.

    On the real instance ``root`` is ``/`` so the path is unchanged. Tests pass
    a temporary directory so the same absolute layout points at fake wheels.
    """

    root = Path(root)
    if str(root) == os.sep:
        return Path(wheel_path)
    return root / wheel_path.lstrip(os.sep)


def verify_stage1_wheels(
    wheels: Sequence[Mapping[str, Any]],
    *,
    root: str | Path = os.sep,
) -> list[dict[str, Any]]:
    """Verify each stage-1 wheel exists on disk and matches its SHA-256.

    Fails closed (raises :class:`ContractError`) on any missing file or digest
    mismatch. Returns one verified record per wheel.
    """

    verified: list[dict[str, Any]] = []
    for spec in wheels:
        path_str = str(spec["path"])
        expected = str(spec["sha256"])
        resolved = _resolve_under_root(path_str, root)
        if not resolved.is_file():
            raise ContractError(
                f"required wheel missing on disk: {path_str} (resolved {resolved})"
            )
        actual = sha256_file(resolved)
        if actual != expected:
            raise ContractError(
                f"wheel {spec['key']!r} sha256 mismatch: expected {expected}, got {actual}"
            )
        verified.append(
            {"key": spec["key"], "path": path_str, "sha256": expected, "verified": True}
        )
    return verified


# ---------------------------------------------------------------------------
# GPU / ROCm tool detection
# ---------------------------------------------------------------------------


def parse_visible_gpu_count(text: str) -> int:
    """Count discrete GPUs reported by rocminfo text."""

    return len(_GFX_NAME_RE.findall(text or ""))


def _default_runner(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        list(argv), capture_output=True, text=True, check=False, timeout=900
    )


def any_rocm_tool_present(*, which: WhichLookup | None = None) -> str | None:
    """Return the first available ROCm tool executable, or ``None``."""

    which = which or shutil.which
    for tool in ROCM_TOOLS:
        exe = which(tool)
        if exe:
            return exe
    return None


def detect_visible_gpu_count(
    *,
    runner: SubprocessRunner | None = None,
    which: WhichLookup | None = None,
) -> int:
    """Run ``rocminfo`` (the canonical GPU listing tool) and count dGPUs.

    Returns 0 when ``rocminfo`` is not on PATH, which then fails the single-GPU
    gate (fail closed on a non-ROCm host).
    """

    runner = runner or _default_runner
    which = which or shutil.which
    exe = which("rocminfo")
    if exe is None:
        return 0
    result = runner([exe])
    text = "\n".join([result.stdout or "", result.stderr or ""])
    return parse_visible_gpu_count(text)


def assert_single_visible_gpu(count: int) -> None:
    """Fail closed unless exactly one discrete GPU is visible."""

    if not isinstance(count, int) or count != 1:
        raise ContractError(
            f"stage-1 bootstrap requires exactly one visible GPU, detected {count}"
        )


# ---------------------------------------------------------------------------
# Command building (pure)
# ---------------------------------------------------------------------------


def _requirement_name(token: str) -> str:
    """Return the lowercased PEP 508 project name at the start of a token.

    A local wheel path such as ``/torch-2.9.1+rocm7.2.1....whl`` begins with
    ``/`` and therefore yields an empty name, so it is never mistaken for a
    package-name requirement.
    """

    match = _NAME_PREFIX_RE.match(str(token))
    return match.group(0).lower() if match else ""


def _dependency_requirement_names(argv: Sequence[str]) -> list[str]:
    """Return the lowercased package names a ``pip install`` command targets.

    Flags (and the value consumed by a value-taking flag) are skipped so a
    mirror URL passed to ``--index-url`` is not mistaken for a package.
    """

    tokens = [str(token) for token in argv]
    try:
        start = tokens.index("install") + 1
    except ValueError:
        start = 0
    names: list[str] = []
    skip_next = False
    for token in tokens[start:]:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if "=" not in token and token in _PIP_VALUE_FLAGS:
                skip_next = True
            continue
        name = _requirement_name(token)
        if name:
            names.append(name)
    return names


def _base_version(value: Any) -> str:
    """Strip the PEP 440 local segment (``+...``) so ``2.9.1+rocm7.2.1`` -> ``2.9.1``."""

    if not isinstance(value, str):
        return ""
    return value.split("+", 1)[0].strip()


def build_venv_argv(python_exe: str, venv_path: str | Path) -> list[str]:
    return [python_exe, "-m", "venv", str(venv_path)]


def assert_dependency_command_is_non_accel(argv: Sequence[str]) -> None:
    """Fail closed unless the phase-1 dependency command is whitelist-only.

    The command may reach the network but must install exactly the whitelisted
    non-accelerated prerequisites and must never name an accelerated ROCm
    package (torch/torchvision/torchaudio/triton/apex).
    """

    names = set(_dependency_requirement_names(argv))
    forbidden = {name.lower() for name in FORBIDDEN_ACCEL_PACKAGES}
    allowed = {name.lower() for name in STAGE1_DEPENDENCY_PACKAGE_NAMES}
    hit_forbidden = sorted(names & forbidden)
    if hit_forbidden:
        raise ContractError(
            "stage-1 dependency install must not name an accelerated ROCm package "
            f"(found {', '.join(hit_forbidden)}); install "
            "torch/torchvision/torchaudio/triton/apex only from the local "
            "SHA-256-verified wheels"
        )
    unexpected = sorted(names - allowed)
    if unexpected:
        raise ContractError(
            "stage-1 dependency install may only install the whitelisted "
            "non-accelerated prerequisites; unexpected packages: "
            f"{', '.join(unexpected)}"
        )
    missing = sorted(allowed - names)
    if missing:
        raise ContractError(
            "stage-1 dependency install must install every whitelisted "
            f"non-accelerated prerequisite; missing: {', '.join(missing)}"
        )


def build_dependency_install_argv(
    pip_exe: str, *, specs: Sequence[str] = STAGE1_DEPENDENCY_SPECS
) -> list[str]:
    """Build the phase-1 controlled-network dependency install command.

    The command is allowed to reach PyPI (no ``--no-index``) but is restricted
    to the whitelisted non-accelerated prerequisites; the guard rejects any
    accelerated package name.
    """

    argv: list[str] = [pip_exe, "-m", "pip", "install", *specs]
    assert_dependency_command_is_non_accel(argv)
    return argv


def assert_install_command_is_offline(
    argv: Sequence[str], wheels: Sequence[Mapping[str, Any]]
) -> None:
    """Fail closed unless the phase-2 command installs wheels offline.

    ``--no-index`` forbids any PyPI fetch and ``--no-deps`` forbids any
    dependency resolution, so the four explicit local wheel paths are the only
    thing pip can touch. A bare accelerated package token is also rejected as
    defense in depth (it would not match a local wheel path).
    """

    argv = [str(token) for token in argv]
    if "--no-index" not in argv:
        raise ContractError(
            "stage-1 local ROCm install must use --no-index (no PyPI fetch)"
        )
    if "--no-deps" not in argv:
        raise ContractError(
            "stage-1 local ROCm install must use --no-deps (no dependency resolution)"
        )
    for spec in wheels:
        if str(spec["path"]) not in argv:
            raise ContractError(
                f"stage-1 local ROCm install must reference the local wheel path for {spec['key']!r}"
            )
    rendered = " ".join(argv)
    match = _FORBIDDEN_NETWORK_TOKEN_RE.search(rendered)
    if match:
        raise ContractError(
            f"stage-1 local ROCm install must not contain a bare '{match.group(1)}' "
            "package token (use the local SHA-256-verified ROCm wheel paths only)"
        )


def build_local_rocm_install_argv(
    pip_exe: str, wheels: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Build the phase-2 strictly-offline ROCm wheel install command.

    ``--no-index --no-deps`` plus the four explicit local wheel paths means pip
    performs no resolution at all, so no accelerated wheel can ever be fetched
    from the network even if a dependency were missing.
    """

    argv: list[str] = [pip_exe, "-m", "pip", "install", "--no-index", "--no-deps"]
    for spec in wheels:
        argv.append(str(spec["path"]))
    assert_install_command_is_offline(argv, wheels)
    return argv


TORCH_SMOKE_SCRIPT = (
    "import json,sys\n"
    "import torch, torchvision, torchaudio\n"
    "try:\n"
    "    import triton\n"
    "    triton_version = getattr(triton, '__version__', None)\n"
    "except Exception:\n"
    "    triton_version = None\n"
    "avail = torch.cuda.is_available()\n"
    "count = int(torch.cuda.device_count()) if avail else 0\n"
    "out = {\n"
    "    'torch_version': torch.__version__,\n"
    "    'torchvision_version': torchvision.__version__,\n"
    "    'torchaudio_version': torchaudio.__version__,\n"
    "    'triton_version': triton_version,\n"
    "    'hip_version': getattr(torch.version, 'hip', None),\n"
    "    'cuda_available': bool(avail),\n"
    "    'device_count': count,\n"
    "    'device_name': (torch.cuda.get_device_name(0) if count > 0 else None),\n"
    "}\n"
    "sys.stdout.write(json.dumps(out))"
)


def _venv_python(venv_path: str | Path) -> str:
    """Return the venv interpreter path for POSIX venv layouts."""

    return str(Path(venv_path) / "bin" / "python")


# ---------------------------------------------------------------------------
# Bounded output helpers
# ---------------------------------------------------------------------------


def _bound_text(text: str, limit: int = _PIP_FREEZE_MAX_CHARS) -> str:
    text = text or ""
    if len(text) > limit:
        text = text[:limit] + f"\n...[truncated at {limit} chars]"
    return text


def redact_freeze(text: str) -> str:
    """Redact lines that look like secrets and bound the total length."""

    redacted: list[str] = []
    for line in (text or "").splitlines():
        if _SECRET_LINE_RE.search(line):
            redacted.append(f"{line.split('==', 1)[0]}==<redacted>")
        else:
            redacted.append(line)
    return _bound_text("\n".join(redacted))


# ---------------------------------------------------------------------------
# Atomic receipt write (exclusive-create by default)
# ---------------------------------------------------------------------------


def write_receipt_atomic(
    receipt: Mapping[str, Any], path: str | Path, *, overwrite: bool = False
) -> None:
    """Write the receipt with an atomic exclusive-create.

    Raises :class:`ContractError` if the target already exists and
    ``overwrite`` is False, so prior receipts are never silently clobbered.
    """

    path = Path(path)
    rendered = json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n"
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ContractError(
            f"receipt already exists, refusing to overwrite without explicit consent: {path}"
        )
    fd, temp_path = tempfile.mkstemp(
        dir=str(parent), prefix=".tmp_stage1_receipt_", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temp_path, str(path))
        else:
            try:
                os.link(temp_path, str(path))
            except FileExistsError as exc:
                raise ContractError(
                    f"receipt was created concurrently, refusing to overwrite: {path}"
                ) from exc
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _utc_now_iso(now: _dt.datetime | None = None) -> str:
    moment = now or _dt.datetime.now(_dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return moment.astimezone(_dt.timezone.utc).isoformat()


def build_stage1_receipt(
    *,
    inventory: Mapping[str, Any],
    verified_wheels: Sequence[Mapping[str, Any]],
    gpu_count: int,
    rocm_tool: str | None,
    dependency_install_argv: Sequence[str],
    local_rocm_install_argv: Sequence[str],
    venv_argv: Sequence[str],
    venv_path: str,
    pip_freeze: str | None,
    torch_smoke: Mapping[str, Any] | None,
    executed: bool = True,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Assemble the bounded stage-1 receipt and its pass verdict.

    Validation checks (inventory, GPU, hashes, offline command) gate validation_pass
    in every mode. Execution checks (venv, install, smoke) gate stage1_pass only when
    ``executed`` is True, so a dry-run validates without mutating the system but
    never claims full stage1_pass.
    """

    smoke = dict(torch_smoke or {})
    pytorch_targets = inventory.get("pytorch_targets", {})

    # Version validation checks - compare base versions against config targets.
    # All four checks are always present; missing smoke versions yield False.
    version_checks: dict[str, bool] = {}
    if smoke.get("torch_version"):
        torch_base = _base_version(smoke.get("torch_version"))
        target_base = _base_version(pytorch_targets.get("torch", ""))
        version_checks["torch_version_matches_target"] = torch_base == target_base
    else:
        version_checks["torch_version_matches_target"] = False
    if smoke.get("torchvision_version"):
        vision_base = _base_version(smoke.get("torchvision_version"))
        target_base = _base_version(pytorch_targets.get("torchvision", ""))
        version_checks["torchvision_version_matches_target"] = vision_base == target_base
    else:
        version_checks["torchvision_version_matches_target"] = False
    if smoke.get("torchaudio_version"):
        audio_base = _base_version(smoke.get("torchaudio_version"))
        target_base = _base_version(pytorch_targets.get("torchaudio", ""))
        version_checks["torchaudio_version_matches_target"] = audio_base == target_base
    else:
        version_checks["torchaudio_version_matches_target"] = False
    if smoke.get("triton_version"):
        triton_base = _base_version(smoke.get("triton_version"))
        target_base = _base_version(pytorch_targets.get("triton", ""))
        version_checks["triton_version_matches_target"] = triton_base == target_base
    else:
        version_checks["triton_version_matches_target"] = False

    validation_checks = {
        "single_rocm_tool_present": bool(rocm_tool),
        "single_gpu_visible": gpu_count == 1,
        "wheel_hashes_verified": bool(verified_wheels)
        and all(w.get("verified") for w in verified_wheels),
        "install_command_offline": bool(local_rocm_install_argv),
        "no_network_torch_install": True,
        "training_forbidden": True,
        "genesis_lerobot_not_installed": True,
    }

    execution_checks = {
        "venv_created": bool(executed),
        "offline_rocm_wheel_stack_installed": bool(executed),
        "torch_hip_smoke_passed": bool(executed)
        and bool(smoke.get("hip_version"))
        and smoke.get("hip_version") != "",
        "single_amd_device_visible_to_torch": bool(executed)
        and int(smoke.get("device_count") or 0) == 1,
        **version_checks,
    }

    checks = {**validation_checks, **execution_checks}
    validation_pass = all(validation_checks.values())
    stage1_pass = validation_pass and (all(execution_checks.values()) if executed else False)

    gpu = dict(inventory.get("gpu") or {})
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE,
        "captured_at_utc": _utc_now_iso(now),
        "runtime_id": inventory.get("runtime_id"),
        "instance_id": inventory.get("instance_id"),
        "platform": {
            "template": "Blank OpenCode Workspace (launched from Gallery)",
            "persistent_root": inventory.get("persistent_root"),
            "venv_path": venv_path,
        },
        "gpu": {
            "count": gpu_count,
            "family": gpu.get("family"),
            "arch": gpu.get("arch"),
            "name": gpu.get("name"),
            "vram_bytes": gpu.get("vram_bytes"),
            "uuid_recorded": False,
        },
        "rocm_version": inventory.get("rocm_version"),
        "amd_smi_version": inventory.get("amd_smi_version"),
        "python_version": inventory.get("python_version"),
        "pip_version": inventory.get("pip_version"),
        "verified_wheels": [dict(w) for w in verified_wheels],
        "dependency_install_argv": [str(token) for token in dependency_install_argv],
        "local_rocm_install_argv": [str(token) for token in local_rocm_install_argv],
        "controlled_network_boundary": CONTROLLED_NETWORK_BOUNDARY,
        "venv_argv": [str(token) for token in venv_argv],
        "torch_smoke": {
            "torch_version": smoke.get("torch_version"),
            "torchvision_version": smoke.get("torchvision_version"),
            "torchaudio_version": smoke.get("torchaudio_version"),
            "triton_version": smoke.get("triton_version"),
            "hip_version": smoke.get("hip_version"),
            "cuda_available": bool(smoke.get("cuda_available")),
            "device_count": int(smoke.get("device_count") or 0),
            "device_name": smoke.get("device_name"),
        },
        "pip_freeze_bounded": redact_freeze(pip_freeze) if pip_freeze is not None else None,
        "executed": bool(executed),
        "validation_pass": validation_pass,
        "checks": checks,
        "stage1_pass": stage1_pass,
        "claim_boundary": (
            "Stage 1 only: verifies the stage-0 inventory, creates the "
            "contract-selected persistent venv, "
            "installs the official local ROCm PyTorch wheels offline, and records a torch "
            "HIP/device smoke. This receipt makes no training, inference, Genesis, LeRobot, "
            "multi-seed, or task-success claim. No account email, token, password, or GPU UUID "
            "is recorded."
        ),
    }


def run_stage1_bootstrap(
    *,
    config_path: str | Path,
    receipt_path: str | Path | None = None,
    venv_path: str | Path | None = None,
    find_links_root: str | Path = os.sep,
    python_exe: str | None = None,
    overwrite: bool = False,
    execute: bool = True,
    runner: SubprocessRunner | None = None,
    which: WhichLookup | None = None,
    root: str | Path = os.sep,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Run stage 1 end to end and (optionally) write the bounded receipt.

    With ``execute=False`` (dry-run) the function validates inventory, GPU and
    wheel hashes, builds the planned commands, and returns the would-be receipt
    without creating the venv, installing, running smoke, or writing a file.

    Fails closed on any verification failure: no partial receipt is written.
    """

    runner = runner or _default_runner
    which = which or shutil.which

    inventory = load_stage1_inventory(config_path)
    resolved_venv = str(venv_path or inventory["venv_path"])
    python_exe = python_exe or sys.executable

    # Reject existing receipt before any runner calls (unless overwrite=True)
    if receipt_path is not None:
        receipt_target = Path(receipt_path)
        if receipt_target.exists() and not overwrite:
            raise ContractError(
                f"receipt already exists, refusing to overwrite without explicit consent: {receipt_target}"
            )

    rocm_tool = any_rocm_tool_present(which=which)
    if not rocm_tool:
        raise ContractError(
            "no ROCm tool found on PATH (rocminfo/amd-smi/rocm-smi); cannot verify GPU"
        )
    gpu_count = detect_visible_gpu_count(runner=runner, which=which)
    assert_single_visible_gpu(gpu_count)

    verified_wheels = verify_stage1_wheels(inventory["wheels"], root=root)

    venv_argv = build_venv_argv(python_exe, resolved_venv)
    pip_exe = _venv_python(resolved_venv)

    # Build both phase-1 (dependency) and phase-2 (local ROCm) install commands
    dependency_install_argv = build_dependency_install_argv(pip_exe)
    local_rocm_install_argv = build_local_rocm_install_argv(pip_exe, inventory["wheels"])

    pip_freeze: str | None = None
    torch_smoke: dict[str, Any] | None = None
    if execute:
        venv_result = runner(venv_argv)
        if venv_result.returncode != 0:
            raise ContractError(
                f"venv creation failed (exit {venv_result.returncode}): "
                f"{(venv_result.stderr or '').strip()[:500]}"
            )

        # Phase 1: controlled network dependency install
        dep_result = runner(dependency_install_argv)
        if dep_result.returncode != 0:
            raise ContractError(
                f"phase-1 dependency install failed (exit {dep_result.returncode}): "
                f"{(dep_result.stderr or '').strip()[:800]}"
            )

        # Phase 2: offline local ROCm wheel install
        rocm_result = runner(local_rocm_install_argv)
        if rocm_result.returncode != 0:
            raise ContractError(
                f"phase-2 offline ROCm wheel install failed (exit {rocm_result.returncode}): "
                f"{(rocm_result.stderr or '').strip()[:800]}"
            )

        # pip freeze to capture installed packages (check returncode)
        freeze_result = runner([pip_exe, "-m", "pip", "freeze"])
        if freeze_result.returncode != 0:
            raise ContractError(
                f"pip freeze failed (exit {freeze_result.returncode}): "
                f"{(freeze_result.stderr or '').strip()[:800]}"
            )
        pip_freeze = freeze_result.stdout or ""

        # Torch HIP smoke test
        smoke_result = runner([pip_exe, "-c", TORCH_SMOKE_SCRIPT])
        if smoke_result.returncode != 0:
            raise ContractError(
                f"torch HIP/device smoke failed (exit {smoke_result.returncode}): "
                f"{(smoke_result.stderr or '').strip()[:800]}"
            )
        try:
            torch_smoke = json.loads(smoke_result.stdout or "")
        except json.JSONDecodeError as exc:
            raise ContractError(f"torch smoke did not return JSON: {exc}") from exc

    receipt = build_stage1_receipt(
        inventory=inventory,
        verified_wheels=verified_wheels,
        gpu_count=gpu_count,
        rocm_tool=rocm_tool,
        dependency_install_argv=dependency_install_argv,
        local_rocm_install_argv=local_rocm_install_argv,
        venv_argv=venv_argv,
        venv_path=resolved_venv,
        pip_freeze=pip_freeze,
        torch_smoke=torch_smoke,
        executed=execute,
        now=now,
    )

    # In dry-run mode (execute=False), allow validation_pass=False since smoke data is expected to be missing.
    # In execute mode, validation must pass or we raise an error.
    if execute and not receipt["validation_pass"]:
        raise ContractError(
            f"stage-1 validation did not pass; refusing to write receipt: {receipt['checks']}"
        )

    # Only write receipt on full stage1_pass (not just validation_pass)
    if execute and receipt["stage1_pass"] and receipt_path is not None:
        write_receipt_atomic(receipt, receipt_path, overwrite=overwrite)
    elif execute and not receipt["stage1_pass"]:
        raise ContractError(
            f"stage-1 verification did not pass; refusing to write receipt: {receipt['checks']}"
        )
    return receipt
