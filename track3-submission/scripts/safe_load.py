"""Safe checkpoint loading helpers (CWE-502 hardening).

Every TorchScript / pickled checkpoint load in this repo must go through these
helpers so that:

  - the file is checked to exist with a plausible size before deserialization,
  - ``torch.load`` is always called with ``weights_only=True``,
  - CLI-supplied model paths are normalized and must resolve to a known model
    directory (repo or the sanctioned remote workspace) or to a file whose
    SHA-256 matches the known-good allowlist, otherwise loading is refused.

TorchScript (``torch.jit.load``) has no ``weights_only`` option; its risk is
mitigated by the path / size / hash checks above.  Bundled checkpoints produced
by the repo itself are unaffected: they live under ``models/``, ``runs/`` or
``track3-data/`` and load exactly as before.
"""

from __future__ import annotations

import hashlib
import os

# Known-good model allowlist (SHA-256).  Populate as bundled models change.
KNOWN_MODEL_HASHES = {
    "t1_walk.pt": "ef1d61e19082b83405f4320a08f4cfc2d7d7f003ed3790dab013778ba442dec7",
}

# Sane upper bound for a checkpoint file (512 MB).
MAX_MODEL_BYTES = 512 * 1024 * 1024

# Directory names, relative to any trusted root, that may hold checkpoints.
TRUSTED_DIR_NAMES = ("models", "runs", "track3-data")

# Sanctioned remote-workspace roots (Radeon Cloud convention).  The repo's own
# artifacts also live under these trees on the GPU instance.
TRUSTED_ROOTS = ("/workspace", "/workspace/radeon-repo")

# Remote deploy trees for the frozen Booster walk model.
TRUSTED_DEPLOY_TREES = (
    ("booster_deploy", "tasks", "locomotion", "models"),
    ("booster", "booster_deploy", "tasks", "locomotion", "models"),
)

# scripts/ -> repo root (works for both the top-level and amd-physical-ai-soccer trees).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256_file(path, chunk_size=1024 * 1024):
    """Return the lowercase SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path, root):
    """True if `path` equals `root` or lies under it."""
    if path == root:
        return True
    return path.startswith(root + os.sep)


def _is_trusted_location(path, repo_root):
    for base in (repo_root,) + TRUSTED_ROOTS:
        base = os.path.normpath(base)
        if not _is_within(path, base):
            continue
        rel = os.path.relpath(path, base)
        parts = rel.split(os.sep)
        if not parts:
            return False
        if parts[0] in TRUSTED_DIR_NAMES:
            return True
        for tree in TRUSTED_DEPLOY_TREES:
            if len(parts) >= len(tree) + 1 and tuple(parts[: len(tree)]) == tree:
                return True
    return False


def resolve_trusted_model_path(path, repo_root=None):
    """Normalize a checkpoint path and require it to be a known artifact.

    Relative paths are resolved against the repo root.  The resolved path must
    exist, have a plausible size, and either live under a known model directory
    or match a known-good SHA-256.  Raises FileNotFoundError / ValueError
    otherwise (callers treat this as "refuse to deserialize").
    """
    if repo_root is None:
        repo_root = _REPO_ROOT
    path = os.path.expanduser(os.fspath(path))
    if not os.path.isabs(path):
        path = os.path.join(repo_root, path)
    path = os.path.normpath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"checkpoint not found: {path}")
    size = os.path.getsize(path)
    if size <= 0 or size > MAX_MODEL_BYTES:
        raise ValueError(f"checkpoint has implausible size ({size} bytes): {path}")
    if _is_trusted_location(path, repo_root):
        return path
    try:
        if sha256_file(path) in KNOWN_MODEL_HASHES.values():
            return path
    except OSError:
        pass
    raise ValueError(
        "refusing to load untrusted checkpoint path (must live under a known "
        f"model directory or match a recorded SHA-256): {path}"
    )


def _basic_check(path):
    """Existence + size sanity check without the trusted-location policy.

    Relative paths follow the process working directory (same semantics as the
    original torch.jit.load call that wrote/read the file).
    """
    path = os.path.expanduser(os.fspath(path))
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    path = os.path.normpath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"checkpoint not found: {path}")
    size = os.path.getsize(path)
    if size <= 0 or size > MAX_MODEL_BYTES:
        raise ValueError(f"checkpoint has implausible size ({size} bytes): {path}")
    return path


def safe_jit_load(path, map_location=None, require_trusted=True, repo_root=None, **kwargs):
    """torch.jit.load guarded by file + path (or hash) validation."""
    checked = (
        resolve_trusted_model_path(path, repo_root=repo_root)
        if require_trusted
        else _basic_check(path)
    )
    import torch

    return torch.jit.load(checked, map_location=map_location, **kwargs)


def safe_torch_load(path, map_location=None, require_trusted=True, repo_root=None, **kwargs):
    """torch.load with weights_only=True enforced, plus path validation."""
    checked = (
        resolve_trusted_model_path(path, repo_root=repo_root)
        if require_trusted
        else _basic_check(path)
    )
    kwargs.pop("weights_only", None)
    kwargs["weights_only"] = True
    import torch

    return torch.load(checked, map_location=map_location, **kwargs)
