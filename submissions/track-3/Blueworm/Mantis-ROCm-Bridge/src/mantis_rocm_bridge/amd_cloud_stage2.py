"""Stage-2 AMD Radeon Cloud bootstrap: Genesis, LeRobot and runtime smoke.

Stage 2 assumes a successful stage-1 receipt (persistence-contract venv with the
official ROCm PyTorch wheels installed). Its scope is deliberately limited to:

  * validate the stage-1 receipt matches the same instance_id, has stage1_pass=true,
    and the venv reports torch HIP with exactly one visible AMD GPU;
  * ensure the persistence-contract Genesis root exists and is a clean git repo
    (clone if missing,
    reject if dirty, never delete/overwrite);
  * install Genesis (local editable install from the checked-out repository),
    LeRobot 0.4.4, and the required model dependencies (transformers, accelerate,
    safetensors, matplotlib, Pillow, jupyter, nbconvert, ipykernel, num2words,
    modelscope, scikit-image>=0.22) into the persistence-contract venv using accelerator
    constraints to protect torch==2.9.1, torchvision==0.24.0, torchaudio==2.9.0,
    triton==3.5.1, and numpy==2.1.2. No pip command may explicitly install bare
    torch/torchvision/torchaudio/triton or any CUDA wheel/index;
  * run a smoke test via the same venv that checks:
    - torch HIP backend and device_count=1
    - Genesis revision, version, and import
    - LeRobot version 0.4.4 import
    - numpy and scikit-image versions
    - ffmpeg executable availability
    - a minimal Genesis gs.amdgpu headless scene build+step that outputs JSON
      (fail closed if the API does not support this, no fallback);
  * emit a bounded, secret-free JSON receipt recording commands, git commit,
    pip freeze, smoke results, and stage boundaries.

A receipt is written only when every validation and execution check passes.
A dry-run validates the plan but never claims stage2_pass and never writes
a file. The receipt existence check happens before any venv mutation or git
operation, and receipts are written with an atomic exclusive-create and are
not overwritten by default.

All subprocess and PATH lookups are injected so the logic is unit-testable
without a GPU. This module must never train.
"""

from __future__ import annotations

import datetime as _dt
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
STAGE = 2

# Genesis repository and installation policy
GENESIS_REPO = "https://github.com/Genesis-Embodied-AI/Genesis.git"
GENESIS_INSTALL_ROOT = "/workspace/persistent/mantis-track3/src/Genesis"

# Target versions from the runtime config
LEROBOT_TARGET_VERSION = "0.4.4"
NUMPY_TARGET_VERSION = "2.1.2"
SCIKIT_IMAGE_MIN_VERSION = "0.22.0"
TORCH_TARGET_VERSION = "2.9.1"
TORCHVISION_TARGET_VERSION = "0.24.0"
TORCHAUDIO_TARGET_VERSION = "2.9.0"
TRITON_TARGET_VERSION = "3.5.1"

# Constraints file configuration
DEFAULT_CONSTRAINTS_PATH = (
    "/workspace/persistent/mantis-track3/evidence/bootstrap/"
    "mantis_amd_stage2_constraints_v2.txt"
)
CONSTRAINTS_CONTENT = f"""torch=={TORCH_TARGET_VERSION}
torchvision=={TORCHVISION_TARGET_VERSION}
torchaudio=={TORCHAUDIO_TARGET_VERSION}
triton=={TRITON_TARGET_VERSION}
numpy=={NUMPY_TARGET_VERSION}
"""

# Stage-2 non-accelerated packages (may reach network)
STAGE2_PACKAGES: tuple[str, ...] = (
    "lerobot==0.4.4",
    "packaging",
    "transformers",
    "accelerate",
    "safetensors",
    "matplotlib",
    "Pillow",
    "jupyter",
    "nbconvert",
    "ipykernel",
    "num2words",
    "modelscope",
    "scikit-image>=0.22",
)

# Accelerated packages that must never be explicitly installed in stage 2
# (they are already installed from the local ROCm wheels in stage 1)
FORBIDDEN_ACCEL_PACKAGES: tuple[str, ...] = (
    "torch",
    "torchvision",
    "torchaudio",
    "triton",
)

# pip install flags that consume the following token as their value
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

# Forbidden pip tokens that would pull CUDA wheels
_FORBIDDEN_CUDA_TOKEN_RE = re.compile(
    r"--extra-index-url.*cuda.*index|CUDA.*=.*1|torch.*cu[0-9]|torch.*cuda",
    re.IGNORECASE,
)

# Leading PEP 508 project-name prefix
_NAME_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")  # git commit SHA
_SECRET_LINE_RE = re.compile(r"(token|password|secret|api[_.-]?key)", re.IGNORECASE)
_PIP_FREEZE_MAX_CHARS = 200_000

SubprocessRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
WhichLookup = Callable[[str], "str | None"]


# ---------------------------------------------------------------------------
# Stage-1 receipt validation
# ---------------------------------------------------------------------------


def load_and_validate_stage1_receipt(
    receipt_path: str | Path,
    instance_id: str,
) -> dict[str, Any]:
    """Load and validate the stage-1 receipt.

    Raises ContractError unless:
      * schema_version == 1
      * stage == 1
      * instance_id matches
      * stage1_pass == true
      * gpu.count == 1
    """

    from .contracts import load_json

    receipt = load_json(receipt_path)

    if receipt.get("schema_version") != 1:
        raise ContractError(
            f"stage-1 receipt schema_version must be 1, got {receipt.get('schema_version')}"
        )
    if receipt.get("stage") != 1:
        raise ContractError(
            f"expected stage-1 receipt, got stage={receipt.get('stage')}"
        )
    if receipt.get("instance_id") != instance_id:
        raise ContractError(
            f"stage-1 receipt instance_id mismatch: expected {instance_id}, "
            f"got {receipt.get('instance_id')}"
        )
    if not receipt.get("stage1_pass"):
        raise ContractError(
            "stage-1 receipt must have stage1_pass=true to proceed with stage 2"
        )
    gpu = receipt.get("gpu", {})
    if not isinstance(gpu, dict) or gpu.get("count") != 1:
        raise ContractError(
            f"stage-1 receipt must report exactly one GPU, got count={gpu.get('count')}"
        )

    venv_path = receipt.get("platform", {}).get("venv_path")
    if not isinstance(venv_path, str) or not venv_path:
        raise ContractError("stage-1 receipt must include a valid venv_path")

    return receipt


# ---------------------------------------------------------------------------
# Genesis repository handling
# ---------------------------------------------------------------------------


def genesis_repo_exists(path: str | Path) -> bool:
    """Return True if path exists and is a valid git repository."""

    p = Path(path)
    if not p.is_dir():
        return False
    # Check for .git directory
    if not (p / ".git").is_dir():
        return False
    return True


def genesis_repo_is_dirty(
    path: str | Path,
    *,
    runner: SubprocessRunner | None = None,
    which: WhichLookup | None = None,
) -> bool:
    """Check if the Genesis repository has uncommitted changes."""

    runner = runner or _default_runner
    which = which or shutil.which
    git_exe = which("git")
    if not git_exe:
        raise ContractError("git executable not found on PATH")

    result = runner([git_exe, "-C", str(path), "status", "--porcelain"])
    if result.returncode != 0:
        raise ContractError(f"git status failed for Genesis repository: {result.stderr}")
    return bool(result.stdout and result.stdout.strip())


def get_genesis_head_commit(
    path: str | Path,
    *,
    runner: SubprocessRunner | None = None,
    which: WhichLookup | None = None,
) -> str:
    """Get the current HEAD commit SHA of the Genesis repository."""

    runner = runner or _default_runner
    which = which or shutil.which
    git_exe = which("git")
    if not git_exe:
        raise ContractError("git executable not found on PATH")

    result = runner([git_exe, "-C", str(path), "rev-parse", "HEAD"])
    if result.returncode != 0:
        raise ContractError(f"git rev-parse HEAD failed: {result.stderr}")
    sha = (result.stdout or "").strip()
    if not _SHA1_RE.fullmatch(sha):
        raise ContractError(f"git rev-parse HEAD returned invalid SHA: {sha}")
    return sha


def clone_genesis_repo(
    repo_url: str,
    target_path: str | Path,
    *,
    runner: SubprocessRunner | None = None,
    which: WhichLookup | None = None,
) -> str:
    """Clone Genesis repository with depth 1 and return the HEAD commit SHA."""

    runner = runner or _default_runner
    which = which or shutil.which
    git_exe = which("git")
    if not git_exe:
        raise ContractError("git executable not found on PATH")

    target = Path(target_path)
    if target.exists():
        raise ContractError(
            f"target path already exists, refusing to clone: {target}"
        )

    # Clone with depth 1
    result = runner([git_exe, "clone", "--depth", "1", repo_url, str(target)])
    if result.returncode != 0:
        raise ContractError(f"git clone failed: {result.stderr}")

    return get_genesis_head_commit(target, runner=runner, which=which)


def ensure_genesis_repo(
    repo_url: str,
    target_path: str | Path,
    *,
    runner: SubprocessRunner | None = None,
    which: WhichLookup | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ensure Genesis repository exists and is clean.

    Returns a dict with:
      - existed: bool (whether repo was already present)
      - commit: str (HEAD SHA, or None if dry-run and repo doesn't exist)
      - path: str (absolute path)
      - planned_clone: bool (whether clone would be needed in non-dry-run)

    Raises ContractError if:
      - path exists but is not a valid git repo
      - repo has uncommitted changes
      - any git operation fails
    """

    target = Path(target_path)
    if genesis_repo_exists(target):
        if genesis_repo_is_dirty(target, runner=runner, which=which):
            raise ContractError(
                f"Genesis repository exists but has uncommitted changes: {target}"
            )
        commit = get_genesis_head_commit(target, runner=runner, which=which)
        return {"existed": True, "commit": commit, "path": str(target), "planned_clone": False}
    else:
        if target.exists():
            raise ContractError(
                f"target path exists but is not a valid git repository: {target}"
            )
        if dry_run:
            # In dry-run, don't clone, just plan it
            return {
                "existed": False,
                "commit": None,
                "path": str(target),
                "planned_clone": True,
            }
        commit = clone_genesis_repo(repo_url, target, runner=runner, which=which)
        return {"existed": False, "commit": commit, "path": str(target), "planned_clone": False}


# ---------------------------------------------------------------------------
# FFmpeg ensure flow
# ---------------------------------------------------------------------------


def ensure_ffmpeg(
    *,
    runner: SubprocessRunner | None = None,
    which: WhichLookup | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ensure ffmpeg is available on the system.

    Returns a dict with:
      - existed: bool (whether ffmpeg was already present on PATH)
      - path: str | None (final PATH to ffmpeg, or None if dry-run and missing)
      - planned_apt_update: bool (whether apt-get update would be needed)
      - planned_apt_install_argv: list[str] | None (the apt-get install command, if planned)
      - apt_update_argv: list[str] | None (the apt-get update command, if executed)
      - apt_install_argv: list[str] | None (the apt-get install command, if executed)
      - apt_update_success: bool | None (whether apt-get update succeeded)
      - apt_install_success: bool | None (whether apt-get install succeeded)

    In dry-run mode:
      - If ffmpeg exists, records it as existed=True with path
      - If ffmpeg is missing, records planned commands without executing

    In execute mode:
      - If ffmpeg exists, records it as existed=True with path
      - If ffmpeg is missing, requires apt-get, runs update then install sequentially,
        fails closed on any failure

    Raises ContractError if:
      - apt-get is required but not found on PATH
      - apt-get update fails in execute mode
      - apt-get install ffmpeg fails in execute mode
    """
    runner = runner or _default_runner
    which = which or shutil.which

    ffmpeg_exe = which("ffmpeg")
    apt_get_exe = which("apt-get")

    if ffmpeg_exe:
        return {
            "existed": True,
            "path": ffmpeg_exe,
            "planned_apt_update": False,
            "planned_apt_install_argv": None,
            "apt_update_argv": None,
            "apt_install_argv": None,
            "apt_update_success": None,
            "apt_install_success": None,
        }

    # ffmpeg is missing
    apt_update_argv = [str(apt_get_exe), "update"] if apt_get_exe else None
    apt_install_argv = [str(apt_get_exe), "install", "-y", "ffmpeg"] if apt_get_exe else None

    if dry_run:
        # In dry-run, record planned commands without executing
        return {
            "existed": False,
            "path": None,
            "planned_apt_update": True,
            "planned_apt_install_argv": apt_install_argv,
            "apt_update_argv": None,
            "apt_install_argv": None,
            "apt_update_success": None,
            "apt_install_success": None,
        }

    # Execute mode: require apt-get
    if not apt_get_exe:
        raise ContractError(
            "ffmpeg is missing and apt-get is not available on PATH; cannot install ffmpeg"
        )

    # Run apt-get update first
    if apt_update_argv:
        update_result = runner(apt_update_argv)
        update_success = update_result.returncode == 0
        if not update_success:
            raise ContractError(
                f"apt-get update failed (exit {update_result.returncode}): "
                f"{(update_result.stderr or '').strip()[:800]}"
            )
    else:
        update_success = None

    # Run apt-get install ffmpeg
    if apt_install_argv:
        install_result = runner(apt_install_argv)
        install_success = install_result.returncode == 0
        if not install_success:
            raise ContractError(
                f"apt-get install ffmpeg failed (exit {install_result.returncode}): "
                f"{(install_result.stderr or '').strip()[:800]}"
            )
    else:
        install_success = None

    # Verify ffmpeg is now available
    final_ffmpeg_path = which("ffmpeg")
    if not final_ffmpeg_path:
        raise ContractError(
            "apt-get install ffmpeg reported success but ffmpeg is still not found on PATH"
        )

    return {
        "existed": False,
        "path": final_ffmpeg_path,
        "planned_apt_update": True,
        "planned_apt_install_argv": apt_install_argv,
        "apt_update_argv": apt_update_argv,
        "apt_install_argv": apt_install_argv,
        "apt_update_success": update_success,
        "apt_install_success": install_success,
    }


# ---------------------------------------------------------------------------
# Stage-2 installation
# ---------------------------------------------------------------------------


def write_constraints_file(
    path: str | Path,
    content: str,
    *,
    runner: SubprocessRunner | None = None,
) -> dict[str, Any]:
    """Atomically write the constraints file and return its metadata.

    Raises ContractError if the file exists with different content.
    Returns dict with path, hash, and content.
    """
    import hashlib

    target_path = Path(path)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Check if file exists with different content
    if target_path.exists():
        existing_content = target_path.read_text(encoding="utf-8")
        existing_hash = hashlib.sha256(existing_content.encode("utf-8")).hexdigest()
        if existing_hash != content_hash:
            raise ContractError(
                f"constraints file exists with different content: {target_path}"
            )
        return {"path": str(target_path), "hash": existing_hash, "content": existing_content}

    # Atomically write the file
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        dir=str(parent), prefix=".tmp_constraints_", suffix=".txt"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temp_path, str(target_path))
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise

    return {"path": str(target_path), "hash": content_hash, "content": content}


def _requirement_name(token: str) -> str:
    """Return the lowercased PEP 508 project name at the start of a token."""

    match = _NAME_PREFIX_RE.match(str(token))
    return match.group(0).lower() if match else ""


def _install_requirement_names(argv: Sequence[str]) -> list[str]:
    """Return the lowercased package names a pip install command targets."""

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


def build_stage2_install_argv(
    pip_exe: str,
    genesis_root: str,
    constraints_path: str,
) -> list[str]:
    """Build the stage-2 install command with accelerator constraints.

    The command:
      * may reach the network for non-accelerated packages
      * uses constraints file to protect torch/torchvision/torchaudio/triton versions
      * must not explicitly install bare torch/torchvision/torchaudio/triton
      * must not use any CUDA wheel/index
      * installs Genesis as editable using two separate tokens

    Args:
        pip_exe: Path to the pip executable
        genesis_root: Path to the Genesis repository
        constraints_path: Path to the constraints file

    Returns:
        List of argv tokens for the pip install command
    """

    argv: list[str] = [
        pip_exe, "-m", "pip", "install",
        # Add constraints file to protect accelerated stack versions
        "-c", str(constraints_path),
        # Install Genesis as editable from the local checkout (two separate tokens)
        "--editable", str(genesis_root),
        # Install LeRobot and model dependencies
        *STAGE2_PACKAGES,
    ]

    # Validate the command
    _assert_stage2_command_is_safe(argv)
    return argv


def _assert_stage2_command_is_safe(argv: Sequence[str]) -> None:
    """Fail closed unless the stage-2 command respects all safety constraints."""

    names = set(_install_requirement_names(argv))
    forbidden = {name.lower() for name in FORBIDDEN_ACCEL_PACKAGES}
    hit_forbidden = sorted(names & forbidden)
    if hit_forbidden:
        raise ContractError(
            "stage-2 install must not explicitly install accelerated ROCm packages "
            f"(found {', '.join(hit_forbidden)}); these are already installed from "
            "the local stage-1 wheels"
        )

    rendered = " ".join(argv)
    cuda_match = _FORBIDDEN_CUDA_TOKEN_RE.search(rendered)
    if cuda_match:
        raise ContractError(
            f"stage-2 install must not use CUDA wheels or indices (found: {cuda_match.group(0)})"
        )


def _default_runner(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        list(argv), capture_output=True, text=True, check=False, timeout=900
    )


def _venv_python(venv_path: str | Path) -> str:
    """Return the venv interpreter path for POSIX venv layouts."""
    return str(Path(venv_path) / "bin" / "python")


# ---------------------------------------------------------------------------
# Stage-2 smoke tests
# ---------------------------------------------------------------------------


STAGE2_SMOKE_SCRIPT = """
import json
import sys
import shutil
import torch
import torchvision
import numpy as np
import importlib.metadata
from packaging.version import Version

# Strict version targets
TORCH_TARGET = "2.9.1"
TORCHVISION_TARGET = "0.24.0"
TORCHAUDIO_TARGET = "2.9.0"
TRITON_TARGET = "3.5.1"
LEROBOT_TARGET = "0.4.4"
NUMPY_TARGET = "2.1.2"
SCIKIT_IMAGE_MIN = "0.22.0"

def get_base_version(version_string):
    '''Extract base version by stripping local version suffix (+local)'''
    if version_string is None:
        return None
    return version_string.split('+')[0]

def version_matches(version_string, target):
    '''Check if version exactly matches target using packaging.version.Version'''
    if version_string is None:
        return False
    base = get_base_version(version_string)
    try:
        return Version(base) == Version(target)
    except Exception:
        return False

def get_version(package_name):
    '''Robustly get package version using importlib.metadata'''
    try:
        return importlib.metadata.version(package_name)
    except Exception:
        return None

# Check torch HIP backend
hip_available = torch.cuda.is_available()
device_count = torch.cuda.device_count() if hip_available else 0
device_name = torch.cuda.get_device_name(0) if device_count > 0 else None
hip_version = getattr(torch.version, 'hip', None)

# Check torch version matches stage1 target
torch_version = torch.__version__
torch_version_matches = version_matches(torch_version, TORCH_TARGET)

# Check torchvision version
torchvision_version = torchvision.__version__
torchvision_version_matches = version_matches(torchvision_version, TORCHVISION_TARGET)

# Check torch dependencies still at stage1 targets
torchaudio_version = get_version('torchaudio')
torchaudio_matches = version_matches(torchaudio_version, TORCHAUDIO_TARGET)

triton_version = get_version('triton')
triton_matches = version_matches(triton_version, TRITON_TARGET)

# Check numpy version
numpy_version = np.__version__
numpy_matches = version_matches(numpy_version, NUMPY_TARGET)

# Check scikit-image (NOT sklearn) - use Version for proper comparison
skimage_version = get_version('scikit-image')
skimage_satisfies = False
if skimage_version is not None:
    try:
        skimage_satisfies = Version(get_base_version(skimage_version)) >= Version(SCIKIT_IMAGE_MIN)
    except Exception:
        pass

# Check Genesis - prefer gs.__version__, fallback to importlib.metadata
try:
    import genesis as gs
    genesis_version = getattr(gs, '__version__', None)
    if genesis_version is None or genesis_version == '':
        genesis_version = get_version('genesis-world')
    has_amdgpu = hasattr(gs, 'amdgpu')
except Exception as e:
    genesis_version = None
    has_amdgpu = False
    genesis_error = str(e)

# Check LeRobot version using metadata
lerobot_version = get_version('lerobot')
lerobot_matches = version_matches(lerobot_version, LEROBOT_TARGET)

# Check ffmpeg
ffmpeg_path = shutil.which('ffmpeg')

# Strict version verification
all_checks_pass = (
    torch_version_matches and
    torchvision_version_matches and
    torchaudio_matches and
    triton_matches and
    numpy_matches and
    lerobot_matches and
    skimage_satisfies and
    hip_available and
    device_count == 1 and
    has_amdgpu and
    genesis_version is not None and
    ffmpeg_path is not None
)

result = {
    "torch_version": torch_version,
    "torch_version_matches_target": torch_version_matches,
    "torchvision_version": torchvision_version,
    "torchvision_version_matches_target": torchvision_version_matches,
    "hip_version": hip_version,
    "hip_available": hip_available,
    "device_count": device_count,
    "device_name": device_name,
    "torchaudio_version": torchaudio_version,
    "torchaudio_version_matches_target": torchaudio_matches,
    "triton_version": triton_version,
    "triton_version_matches_target": triton_matches,
    "numpy_version": numpy_version,
    "numpy_version_matches_target": numpy_matches,
    "scikit_image_version": skimage_version,
    "scikit_image_satisfies_min": skimage_satisfies,
    "genesis_version": genesis_version,
    "genesis_has_amdgpu_backend": has_amdgpu,
    "lerobot_version": lerobot_version,
    "lerobot_version_matches_target": lerobot_matches,
    "ffmpeg_available": ffmpeg_path is not None,
    "ffmpeg_path": ffmpeg_path,
    "all_strict_checks_pass": all_checks_pass,
}

if 'genesis_error' in locals():
    result['genesis_import_error'] = genesis_error

sys.stdout.write(json.dumps(result))
"""

GENESIS_SCENE_SMOKE_SCRIPT = """
import json
import sys

try:
    import genesis as gs

    # Init with amdgpu backend and warning-level logging
    gs.init(backend=gs.amdgpu, logging_level="warning")

    # Create minimal scene with SimOptions (not sim_options)
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01),
        show_viewer=False,
    )

    # Add a simple plane
    plane = scene.add_entity(
        gs.morphs.Plane(),
    )

    # Build the scene first
    scene.build()

    # Then step the simulation
    scene.step()

    success = True
    error = None
except Exception as e:
    success = False
    error = str(e)

result = {
    "genesis_scene_smoke_success": success,
    "genesis_scene_smoke_error": error,
}

sys.stdout.write(json.dumps(result))
"""


def run_stage2_smoke(
    pip_exe: str,
    *,
    runner: SubprocessRunner | None = None,
) -> dict[str, Any]:
    """Run the stage-2 smoke test and return the results."""

    runner = runner or _default_runner
    result = runner([pip_exe, "-c", STAGE2_SMOKE_SCRIPT])
    if result.returncode != 0:
        raise ContractError(
            f"stage-2 smoke test failed (exit {result.returncode}): {result.stderr}"
        )
    try:
        return json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise ContractError(f"stage-2 smoke test did not return JSON: {exc}") from exc


def run_genesis_scene_smoke(
    pip_exe: str,
    *,
    runner: SubprocessRunner | None = None,
) -> dict[str, Any]:
    """Run the Genesis scene smoke test and return the results."""

    runner = runner or _default_runner
    result = runner([pip_exe, "-c", GENESIS_SCENE_SMOKE_SCRIPT])
    if result.returncode != 0:
        raise ContractError(
            f"Genesis scene smoke test failed (exit {result.returncode}): {result.stderr}"
        )
    try:
        return json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise ContractError(f"Genesis scene smoke test did not return JSON: {exc}") from exc


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
# Receipt handling
# ---------------------------------------------------------------------------


def write_receipt_atomic(
    receipt: Mapping[str, Any], path: str | Path, *, overwrite: bool = False
) -> None:
    """Write the receipt with an atomic exclusive-create.

    Raises ContractError if the target already exists and overwrite is False.
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
        dir=str(parent), prefix=".tmp_stage2_receipt_", suffix=".json"
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


def build_stage2_receipt(
    *,
    stage1_receipt: Mapping[str, Any],
    genesis_info: Mapping[str, Any],
    stage2_install_argv: Sequence[str],
    pip_freeze: str | None,
    smoke_results: Mapping[str, Any] | None,
    genesis_smoke_results: Mapping[str, Any] | None,
    constraints_info: Mapping[str, Any] | None,
    ffmpeg_info: Mapping[str, Any] | None,
    executed: bool = True,
    now: _dt.datetime | None = None,
    genesis_install_root: str = GENESIS_INSTALL_ROOT,
) -> dict[str, Any]:
    """Assemble the bounded stage-2 receipt and its pass verdict."""

    smoke = dict(smoke_results or {})
    genesis_smoke = dict(genesis_smoke_results or {})
    constraints = dict(constraints_info or {})
    ffmpeg = dict(ffmpeg_info or {})

    validation_checks = {
        "stage1_receipt_valid": bool(stage1_receipt),
        "stage1_instance_id_match": True,
        "stage1_stage1_pass_true": stage1_receipt.get("stage1_pass", False) if stage1_receipt else False,
        "genesis_repo_valid": bool(genesis_info.get("commit")) or genesis_info.get("planned_clone", False),
        "install_command_safe": bool(stage2_install_argv),
        "no_cuda_wheels": True,
        "constraints_file_valid": bool(constraints.get("hash")),
    }

    execution_checks = {
        "genesis_repo_present": bool(executed) and bool(genesis_info.get("path")),
        "stage2_packages_installed": bool(executed),
        "constraints_applied": bool(executed) and bool(constraints.get("path")),
        "torch_hip_available": bool(executed) and smoke.get("hip_available", False),
        "single_amd_gpu_visible": bool(executed) and int(smoke.get("device_count", 0)) == 1,
        "torch_version_matches_target": bool(executed) and smoke.get("torch_version_matches_target", False),
        "torchvision_version_matches_target": bool(executed) and smoke.get("torchvision_version_matches_target", False),
        "torchaudio_version_matches_target": bool(executed) and smoke.get("torchaudio_version_matches_target", False),
        "triton_version_matches_target": bool(executed) and smoke.get("triton_version_matches_target", False),
        "lerobot_version_matches_target": bool(executed) and smoke.get("lerobot_version_matches_target", False),
        "numpy_version_matches_target": bool(executed) and smoke.get("numpy_version_matches_target", False),
        "scikit_image_satisfies_min": bool(executed) and smoke.get("scikit_image_satisfies_min", False),
        "genesis_import_success": bool(executed) and smoke.get("genesis_version") is not None,
        "genesis_has_amdgpu_backend": bool(executed) and smoke.get("genesis_has_amdgpu_backend", False),
        "ffmpeg_available": bool(executed) and smoke.get("ffmpeg_available", False),
        "genesis_scene_smoke_passed": bool(executed) and genesis_smoke.get("genesis_scene_smoke_success", False),
    }

    checks = {**validation_checks, **execution_checks}
    validation_pass = all(validation_checks.values())
    stage2_pass = validation_pass and (all(execution_checks.values()) if executed else False)

    gpu = dict(stage1_receipt.get("gpu", {})) if stage1_receipt else {}

    return {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE,
        "captured_at_utc": _utc_now_iso(now),
        "runtime_id": stage1_receipt.get("runtime_id") if stage1_receipt else None,
        "instance_id": stage1_receipt.get("instance_id") if stage1_receipt else None,
        "platform": {
            "template": "Blank OpenCode Workspace (launched from Gallery)",
            "persistent_root": stage1_receipt.get("platform", {}).get("persistent_root") if stage1_receipt else None,
            "venv_path": stage1_receipt.get("platform", {}).get("venv_path") if stage1_receipt else None,
            "genesis_install_root": genesis_install_root,
        },
        "gpu": {
            "count": gpu.get("count"),
            "family": gpu.get("family"),
            "arch": gpu.get("arch"),
            "name": gpu.get("name"),
            "vram_bytes": gpu.get("vram_bytes"),
            "uuid_recorded": False,
        },
        "stage1_reference": {
            "schema_version": stage1_receipt.get("schema_version") if stage1_receipt else None,
            "stage": stage1_receipt.get("stage") if stage1_receipt else None,
            "stage1_pass": stage1_receipt.get("stage1_pass") if stage1_receipt else None,
            "captured_at_utc": stage1_receipt.get("captured_at_utc") if stage1_receipt else None,
        },
        "genesis": {
            "repository": GENESIS_REPO,
            "install_root": genesis_install_root,
            "commit": genesis_info.get("commit"),
            "existed_at_start": genesis_info.get("existed"),
            "planned_clone": genesis_info.get("planned_clone", False),
        },
        "constraints": {
            "path": constraints.get("path"),
            "sha256": constraints.get("hash"),
            "content": constraints.get("content"),
        },
        "ffmpeg": {
            "existed": ffmpeg.get("existed"),
            "path": ffmpeg.get("path"),
            "planned_apt_update": ffmpeg.get("planned_apt_update"),
            "planned_apt_install_argv": ffmpeg.get("planned_apt_install_argv"),
            "apt_update_argv": ffmpeg.get("apt_update_argv"),
            "apt_install_argv": ffmpeg.get("apt_install_argv"),
            "apt_update_success": ffmpeg.get("apt_update_success"),
            "apt_install_success": ffmpeg.get("apt_install_success"),
        },
        "stage2_install_argv": [str(token) for token in stage2_install_argv],
        "smoke": {
            "torch_version": smoke.get("torch_version"),
            "torch_version_matches_target": smoke.get("torch_version_matches_target"),
            "torchvision_version": smoke.get("torchvision_version"),
            "torchvision_version_matches_target": smoke.get("torchvision_version_matches_target"),
            "hip_version": smoke.get("hip_version"),
            "hip_available": smoke.get("hip_available"),
            "device_count": smoke.get("device_count"),
            "device_name": smoke.get("device_name"),
            "torchaudio_version": smoke.get("torchaudio_version"),
            "torchaudio_version_matches_target": smoke.get("torchaudio_version_matches_target"),
            "triton_version": smoke.get("triton_version"),
            "triton_version_matches_target": smoke.get("triton_version_matches_target"),
            "numpy_version": smoke.get("numpy_version"),
            "numpy_version_matches_target": smoke.get("numpy_version_matches_target"),
            "scikit_image_version": smoke.get("scikit_image_version"),
            "scikit_image_satisfies_min": smoke.get("scikit_image_satisfies_min"),
            "genesis_version": smoke.get("genesis_version"),
            "genesis_has_amdgpu_backend": smoke.get("genesis_has_amdgpu_backend"),
            "lerobot_version": smoke.get("lerobot_version"),
            "lerobot_version_matches_target": smoke.get("lerobot_version_matches_target"),
            "ffmpeg_available": smoke.get("ffmpeg_available"),
            "ffmpeg_path": smoke.get("ffmpeg_path"),
            "genesis_scene_smoke_success": genesis_smoke.get("genesis_scene_smoke_success"),
            "genesis_scene_smoke_error": genesis_smoke.get("genesis_scene_smoke_error"),
        },
        "pip_freeze_bounded": redact_freeze(pip_freeze) if pip_freeze is not None else None,
        "executed": bool(executed),
        "validation_pass": validation_pass,
        "checks": checks,
        "stage2_pass": stage2_pass,
        "claim_boundary": (
            "Stage 2 only: validates stage-1 receipt, ensures Genesis repository is present "
            "and clean, installs Genesis, LeRobot 0.4.4, and model dependencies with "
            "accelerator constraints, and runs smoke tests (torch HIP, Genesis import/scene, "
            "LeRobot version, numpy/scikit-image, ffmpeg). This receipt makes no training, "
            "inference, multi-seed, or task-success claim. No account email, token, password, "
            "or GPU UUID is recorded."
        ),
    }


def run_stage2_bootstrap(
    *,
    stage1_receipt_path: str | Path,
    receipt_path: str | Path | None = None,
    instance_id: str | None = None,
    genesis_repo_url: str = GENESIS_REPO,
    genesis_install_root: str = GENESIS_INSTALL_ROOT,
    constraints_path: str | None = None,
    overwrite: bool = False,
    execute: bool = True,
    runner: SubprocessRunner | None = None,
    which: WhichLookup | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Run stage 2 end to end and (optionally) write the bounded receipt.

    With execute=False (dry-run) the function validates the stage-1 receipt,
    builds the planned commands, and returns the would-be receipt without
    installing packages, running smoke tests, or writing a file.

    Fails closed on any verification failure: no partial receipt is written.
    """

    runner = runner or _default_runner
    which = which or shutil.which
    dry_run = not execute

    # Load and validate stage-1 receipt
    stage1_receipt = load_and_validate_stage1_receipt(
        stage1_receipt_path,
        instance_id or json.loads(Path(stage1_receipt_path).read_text(encoding="utf-8")).get("instance_id"),
    )

    resolved_instance_id = instance_id or stage1_receipt["instance_id"]
    venv_path = stage1_receipt["platform"]["venv_path"]

    # Reject existing receipt before any runner calls
    if receipt_path is not None:
        receipt_target = Path(receipt_path)
        if receipt_target.exists() and not overwrite:
            raise ContractError(
                f"receipt already exists, refusing to overwrite without explicit consent: {receipt_target}"
            )

    pip_exe = _venv_python(venv_path)

    # Ensure Genesis repository is present and clean (or planned in dry-run)
    genesis_info = ensure_genesis_repo(
        genesis_repo_url,
        genesis_install_root,
        runner=runner,
        which=which,
        dry_run=dry_run,
    )

    # Write constraints file (only in execute mode)
    constraints_info: dict[str, Any] | None = None
    actual_constraints_path = constraints_path or DEFAULT_CONSTRAINTS_PATH

    if not dry_run:
        constraints_info = write_constraints_file(
            actual_constraints_path,
            CONSTRAINTS_CONTENT,
            runner=runner,
        )
    else:
        # In dry-run, just record the planned constraints
        import hashlib
        constraints_hash = hashlib.sha256(CONSTRAINTS_CONTENT.encode("utf-8")).hexdigest()
        constraints_info = {
            "path": actual_constraints_path,
            "hash": constraints_hash,
            "content": CONSTRAINTS_CONTENT,
        }

    # Build stage-2 install command with explicit parameters
    stage2_install_argv = build_stage2_install_argv(
        pip_exe=pip_exe,
        genesis_root=genesis_install_root,
        constraints_path=actual_constraints_path,
    )

    # Ensure ffmpeg is available (before any writes)
    ffmpeg_info = ensure_ffmpeg(
        runner=runner,
        which=which,
        dry_run=dry_run,
    )

    pip_freeze: str | None = None
    smoke_results: dict[str, Any] | None = None
    genesis_smoke_results: dict[str, Any] | None = None

    if execute:
        # Run stage-2 install
        install_result = runner(stage2_install_argv)
        if install_result.returncode != 0:
            raise ContractError(
                f"stage-2 package install failed (exit {install_result.returncode}): "
                f"{(install_result.stderr or '').strip()[:800]}"
            )

        # Run smoke tests
        smoke_results = run_stage2_smoke(pip_exe, runner=runner)
        genesis_smoke_results = run_genesis_scene_smoke(pip_exe, runner=runner)

        # pip freeze
        freeze_result = runner([pip_exe, "-m", "pip", "freeze"])
        if freeze_result.returncode != 0:
            raise ContractError(
                f"pip freeze failed (exit {freeze_result.returncode}): "
                f"{(freeze_result.stderr or '').strip()[:800]}"
            )
        pip_freeze = freeze_result.stdout or ""

    receipt = build_stage2_receipt(
        stage1_receipt=stage1_receipt,
        genesis_info=genesis_info,
        stage2_install_argv=stage2_install_argv,
        pip_freeze=pip_freeze,
        smoke_results=smoke_results,
        genesis_smoke_results=genesis_smoke_results,
        constraints_info=constraints_info,
        ffmpeg_info=ffmpeg_info,
        executed=execute,
        now=now,
        genesis_install_root=genesis_install_root,
    )

    if execute and not receipt["validation_pass"]:
        raise ContractError(
            f"stage-2 validation did not pass; refusing to write receipt: {receipt['checks']}"
        )

    if execute and receipt["stage2_pass"] and receipt_path is not None:
        write_receipt_atomic(receipt, receipt_path, overwrite=overwrite)
    elif execute and not receipt["stage2_pass"]:
        raise ContractError(
            f"stage-2 verification did not pass; refusing to write receipt: {receipt['checks']}"
        )

    return receipt
