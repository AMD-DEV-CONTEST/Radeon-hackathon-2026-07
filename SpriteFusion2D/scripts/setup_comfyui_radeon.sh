#!/usr/bin/env bash
# setup_comfyui_radeon.sh -- luna-workpack R02.
#
# Installs a pinned ComfyUI checkout plus the SDXL-Turbo checkpoint into a
# Radeon Cloud persistent directory, in an independent venv that REUSES the
# image's mirrored ROCm PyTorch (via PYTHONPATH, same trick as
# scripts/start_comfyui.sh) instead of installing a fresh (CUDA) torch wheel.
#
# Explicit non-goals (do not add without a new task): no `apt`/`apt-get`
# calls of any kind (install or upgrade), no torch/torchvision/torchaudio
# install into the new venv, no auto-acceptance of the model license, no
# writing of secrets/tokens to disk.
#
# All root paths are overridable via environment variables so this script
# works from a clean persistent directory (see --help / README fragment
# scripts/setup_comfyui_radeon.md).
#
# This file is structured as function definitions + a guarded `main "$@"`
# call at the bottom, so tests can `source` it and exercise pure functions
# (sha256 compare, requirements filtering) without running any network or
# filesystem side effects. See tests/test_setup_comfyui_radeon_shell.py.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------

# Pinned, verified values. Source: docs/luna-workpack/PUBLIC_KNOWLEDGE.md
# section 3 ("Radeon 目标环境"), copied verbatim -- not invented here.
#   - ComfyUI version documented there: "0.30.0"
#   - Checkpoint filename: sd_xl_turbo_1.0_fp16.safetensors
#   - Checkpoint SHA-256: e869ac7d6942cb327d68d5ed83a40447aadf20e0c3358d98b2cc9e270db0da26
# PUBLIC_KNOWLEDGE.md records a version string, not a raw git commit SHA, so
# that exact string is used as the default pinned git ref below. If the
# upstream repo tags this release differently (e.g. "v0.30.0"), override
# SPRITE_WORKSHOP_COMFY_REF -- do not silently guess a different default here.
SPRITE_WORKSHOP_COMFY_REF="${SPRITE_WORKSHOP_COMFY_REF:-0.30.0}"
SPRITE_WORKSHOP_MODEL_SHA256="${SPRITE_WORKSHOP_MODEL_SHA256:-e869ac7d6942cb327d68d5ed83a40447aadf20e0c3358d98b2cc9e270db0da26}"
SPRITE_WORKSHOP_MODEL_FILENAME="${SPRITE_WORKSHOP_MODEL_FILENAME:-sd_xl_turbo_1.0_fp16.safetensors}"

# Upstream repo URL and the model download URL are NOT recorded in
# PUBLIC_KNOWLEDGE.md (only the checkpoint filename + hash are). These
# defaults point at the publicly known official sources and are fully
# overridable; treat them as best-effort defaults, not pinned facts.
SPRITE_WORKSHOP_COMFY_REPO="${SPRITE_WORKSHOP_COMFY_REPO:-https://github.com/comfyanonymous/ComfyUI.git}"
SPRITE_WORKSHOP_MODEL_URL="${SPRITE_WORKSHOP_MODEL_URL:-https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0_fp16.safetensors}"
SPRITE_WORKSHOP_MODEL_LICENSE_URL="${SPRITE_WORKSHOP_MODEL_LICENSE_URL:-https://huggingface.co/stabilityai/sdxl-turbo}"

# Root paths. Defaults match the layout already recorded in AMD_BOX.md /
# scripts/start_comfyui.sh so R03 (start/stop) does not need to change its
# own defaults.
SPRITE_WORKSHOP_COMFY_ROOT="${SPRITE_WORKSHOP_COMFY_ROOT:-/persistent/ComfyUI}"
SPRITE_WORKSHOP_COMFY_VENV="${SPRITE_WORKSHOP_COMFY_VENV:-/persistent/comfyui-venv}"
SPRITE_WORKSHOP_ROCM_SITE="${SPRITE_WORKSHOP_ROCM_SITE:-/opt/venv/lib/python3.12/site-packages}"
SPRITE_WORKSHOP_BASE_PYTHON="${SPRITE_WORKSHOP_BASE_PYTHON:-/opt/venv/bin/python}"
SPRITE_WORKSHOP_MODEL_DIR="${SPRITE_WORKSHOP_MODEL_DIR:-${SPRITE_WORKSHOP_COMFY_ROOT}/models/checkpoints}"

# Optional secret. Read from the environment ONLY, used in-memory for a
# single curl Authorization header, never written to a file or logged.
SPRITE_WORKSHOP_HF_TOKEN="${SPRITE_WORKSHOP_HF_TOKEN:-${HF_TOKEN:-}}"

DRY_RUN=0

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

log() {
  printf '[setup-comfyui-radeon] %s\n' "$*" >&2
}

die() {
  printf '[setup-comfyui-radeon] ERROR: %s\n' "$*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

# run <argv...> -- executes the command, or in --dry-run mode prints a
# shell-quoted rendering of it and does nothing. Every MUTATING action
# (clone, checkout, venv creation, pip install, download, mkdir, mv, rm)
# must go through this so --dry-run has zero filesystem/network side
# effects. Read-only checks (test -f, sha256 of an existing file, git
# rev-parse) are allowed to run directly even under --dry-run.
run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

# sha256_of <path> -- prints the lowercase hex digest of a file. Tries
# sha256sum, then shasum -a 256, then a Python fallback, so this works both
# on the Radeon box and on a dev machine that only has one of those tools.
sha256_of() {
  local path="$1"
  if have_cmd sha256sum; then
    sha256sum -- "$path" | awk '{print $1}'
  elif have_cmd shasum; then
    shasum -a 256 -- "$path" | awk '{print $1}'
  elif have_cmd python3; then
    python3 - "$path" <<'PY'
import hashlib
import sys

h = hashlib.sha256()
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
  else
    die "no sha256sum, shasum, or python3 available to hash $path"
  fi
}

# verify_model_file <path> <expected_sha256>
# Pure, side-effect-free (besides reading the file) status check used both
# by main() and by tests. Prints one word and returns a distinct exit code:
#   missing   -> 10  (file does not exist yet)
#   ok        -> 0   (exists, hash matches -- safe to skip download)
#   mismatch  -> 20  (exists, hash does NOT match -- must fail, not overwrite)
verify_model_file() {
  local path="$1" expected="$2" actual
  if [[ ! -f "$path" ]]; then
    echo "missing"
    return 10
  fi
  actual="$(sha256_of "$path")"
  if [[ "$actual" == "$expected" ]]; then
    echo "ok"
    return 0
  fi
  echo "mismatch actual=$actual expected=$expected"
  return 20
}

# filter_requirements <src-file>
# Prints src-file with any top-level torch / torchvision / torchaudio
# requirement line removed (case-insensitive, allows version specifiers),
# so `pip install -r <filtered>` can never pull a fresh (CUDA) torch wheel.
# Comments and blank lines pass through untouched.
filter_requirements() {
  local src="$1"
  grep -Eiv '^[[:space:]]*(torch|torchvision|torchaudio)[[:space:]]*([<>=!~].*)?$' -- "$src"
}

print_help() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run] [--help]

Installs a pinned ComfyUI checkout + SDXL-Turbo checkpoint into a Radeon
Cloud persistent directory, reusing the image's mirrored ROCm PyTorch
instead of installing a fresh torch wheel. Idempotent: re-running with the
same environment skips steps that are already correctly done, and refuses
to overwrite a checkpoint whose hash does not match.

Options:
  --dry-run   Print every command this script would run, without running
              it or touching the filesystem/network. Use this to review
              exactly what will happen before running for real.
  --help      Show this message and exit.

Environment variables (all optional, defaults shown):
  SPRITE_WORKSHOP_COMFY_ROOT      ComfyUI checkout directory
                                   (default: /persistent/ComfyUI)
  SPRITE_WORKSHOP_COMFY_VENV      Independent ComfyUI venv directory
                                   (default: /persistent/comfyui-venv)
  SPRITE_WORKSHOP_ROCM_SITE       Mirrored ROCm torch site-packages to
                                   reuse (never installed into or copied)
                                   (default: /opt/venv/lib/python3.12/site-packages)
  SPRITE_WORKSHOP_BASE_PYTHON     Python used to create the ComfyUI venv
                                   (default: /opt/venv/bin/python)
  SPRITE_WORKSHOP_COMFY_REPO      ComfyUI git remote URL
                                   (default: https://github.com/comfyanonymous/ComfyUI.git)
  SPRITE_WORKSHOP_COMFY_REF       Pinned ComfyUI git ref/tag/commit
                                   (default: 0.30.0, from PUBLIC_KNOWLEDGE.md)
  SPRITE_WORKSHOP_MODEL_DIR       Checkpoint directory
                                   (default: \$SPRITE_WORKSHOP_COMFY_ROOT/models/checkpoints)
  SPRITE_WORKSHOP_MODEL_FILENAME  Checkpoint filename
                                   (default: sd_xl_turbo_1.0_fp16.safetensors)
  SPRITE_WORKSHOP_MODEL_URL       Checkpoint download URL
                                   (default: official stabilityai/sdxl-turbo HF resolve URL)
  SPRITE_WORKSHOP_MODEL_SHA256    Expected checkpoint SHA-256
                                   (default: value pinned in PUBLIC_KNOWLEDGE.md)
  SPRITE_WORKSHOP_MODEL_LICENSE_URL  License/model card URL shown before download
  SPRITE_WORKSHOP_HF_TOKEN / HF_TOKEN
                                   Hugging Face token used ONLY in-memory for
                                   the download Authorization header. Never
                                   written to disk. You must accept the
                                   model license yourself at
                                   SPRITE_WORKSHOP_MODEL_LICENSE_URL first --
                                   this script never accepts it for you.

Disk requirement: budget roughly 10-15 GB free under the persistent root
(ComfyUI checkout + independent venv + the ~6.9 GB SDXL-Turbo fp16
checkpoint). See scripts/setup_comfyui_radeon.md for details.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --help | -h)
        print_help
        exit 0
        ;;
      *)
        die "unknown argument: $1 (see --help)"
        ;;
    esac
  done
}

# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

ensure_comfyui_repo() {
  if [[ -f "${SPRITE_WORKSHOP_COMFY_ROOT}/main.py" && -d "${SPRITE_WORKSHOP_COMFY_ROOT}/.git" ]]; then
    local current_ref=""
    if [[ "$DRY_RUN" -eq 0 ]]; then
      current_ref="$(git -C "$SPRITE_WORKSHOP_COMFY_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
    fi
    log "ComfyUI already checked out at ${SPRITE_WORKSHOP_COMFY_ROOT} (HEAD ${current_ref:-unknown}); fetching pinned ref ${SPRITE_WORKSHOP_COMFY_REF}"
    run git -C "$SPRITE_WORKSHOP_COMFY_ROOT" fetch --tags origin
    run git -C "$SPRITE_WORKSHOP_COMFY_ROOT" checkout "$SPRITE_WORKSHOP_COMFY_REF"
    return 0
  fi

  if [[ -e "$SPRITE_WORKSHOP_COMFY_ROOT" ]]; then
    die "${SPRITE_WORKSHOP_COMFY_ROOT} exists but is not a ComfyUI git checkout (no main.py/.git); refusing to overwrite it"
  fi

  log "cloning ${SPRITE_WORKSHOP_COMFY_REPO} @ ${SPRITE_WORKSHOP_COMFY_REF} into ${SPRITE_WORKSHOP_COMFY_ROOT}"
  run mkdir -p "$(dirname "$SPRITE_WORKSHOP_COMFY_ROOT")"
  run git clone "$SPRITE_WORKSHOP_COMFY_REPO" "$SPRITE_WORKSHOP_COMFY_ROOT"
  run git -C "$SPRITE_WORKSHOP_COMFY_ROOT" checkout "$SPRITE_WORKSHOP_COMFY_REF"
}

ensure_comfyui_venv() {
  if [[ -x "${SPRITE_WORKSHOP_COMFY_VENV}/bin/python" ]]; then
    log "independent venv already present at ${SPRITE_WORKSHOP_COMFY_VENV}; skipping creation"
    return 0
  fi

  if [[ "$DRY_RUN" -eq 0 && ! -x "$SPRITE_WORKSHOP_BASE_PYTHON" ]]; then
    die "base python not found or not executable: $SPRITE_WORKSHOP_BASE_PYTHON (override SPRITE_WORKSHOP_BASE_PYTHON)"
  fi

  log "creating independent venv at ${SPRITE_WORKSHOP_COMFY_VENV} (isolated; ROCm torch is reused via PYTHONPATH, never copied or reinstalled)"
  run "$SPRITE_WORKSHOP_BASE_PYTHON" -m venv "$SPRITE_WORKSHOP_COMFY_VENV"
}

install_minimal_requirements() {
  local req_src="${SPRITE_WORKSHOP_COMFY_ROOT}/requirements.txt"
  local req_filtered="${SPRITE_WORKSHOP_COMFY_VENV}/.setup-requirements.filtered.txt"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "would filter torch/torchvision/torchaudio out of ${req_src} and pip install the rest into ${SPRITE_WORKSHOP_COMFY_VENV}, with PYTHONPATH=${SPRITE_WORKSHOP_ROCM_SITE} so the mirrored ROCm torch satisfies any transitive torch dependency"
    printf '[dry-run] %q\n' "filter_requirements '$req_src' > '$req_filtered'"
    run env "PYTHONPATH=${SPRITE_WORKSHOP_ROCM_SITE}" \
      "${SPRITE_WORKSHOP_COMFY_VENV}/bin/python" -m pip install --no-input -r "$req_filtered"
    return 0
  fi

  [[ -f "$req_src" ]] || die "requirements.txt not found at $req_src (did the ComfyUI checkout step run?)"
  filter_requirements "$req_src" > "$req_filtered"
  log "installing minimal ComfyUI dependencies (torch stack excluded) into ${SPRITE_WORKSHOP_COMFY_VENV}"
  env "PYTHONPATH=${SPRITE_WORKSHOP_ROCM_SITE}" \
    "${SPRITE_WORKSHOP_COMFY_VENV}/bin/python" -m pip install --no-input -r "$req_filtered"

  log "verifying the venv can see the mirrored ROCm torch via PYTHONPATH (not installed, not copied)"
  if ! env "PYTHONPATH=${SPRITE_WORKSHOP_ROCM_SITE}" \
    "${SPRITE_WORKSHOP_COMFY_VENV}/bin/python" -c 'import torch; print("torch", torch.__version__, "hip" if getattr(torch.version, "hip", None) else "no-hip")'; then
    die "could not import torch via PYTHONPATH=${SPRITE_WORKSHOP_ROCM_SITE}; check SPRITE_WORKSHOP_ROCM_SITE points at the image's mirrored ROCm torch install"
  fi
}

print_license_notice() {
  cat <<EOF
[setup-comfyui-radeon] SDXL-Turbo checkpoint license notice:
  Source:  ${SPRITE_WORKSHOP_MODEL_URL}
  License: ${SPRITE_WORKSHOP_MODEL_LICENSE_URL}
  This script does NOT accept the model license on your behalf. Open the
  license URL above, accept the terms with your own Hugging Face account,
  then set SPRITE_WORKSHOP_HF_TOKEN (or HF_TOKEN) to a token from that
  account before re-running without --dry-run. The token is used only for
  a single in-memory download request header; it is never written to disk.
EOF
}

ensure_model_checkpoint() {
  local target="${SPRITE_WORKSHOP_MODEL_DIR}/${SPRITE_WORKSHOP_MODEL_FILENAME}"
  local partial="${target}.partial"

  if [[ "$DRY_RUN" -eq 0 && -f "$target" ]]; then
    local status rc
    set +e
    status="$(verify_model_file "$target" "$SPRITE_WORKSHOP_MODEL_SHA256")"
    rc=$?
    set -e
    case "$rc" in
      0)
        log "checkpoint already present and SHA-256 verified at ${target}; skipping download (idempotent)"
        return 0
        ;;
      20)
        die "checkpoint at ${target} exists but SHA-256 does NOT match the pinned value (${status}); refusing to overwrite it. Remove or move the file yourself, then re-run."
        ;;
      *)
        die "unexpected checkpoint verification status: ${status}"
        ;;
    esac
  fi

  print_license_notice

  if [[ "$DRY_RUN" -eq 1 ]]; then
    run mkdir -p "$SPRITE_WORKSHOP_MODEL_DIR"
    printf '[dry-run] %q\n' "curl -fL --retry 3 -H 'Authorization: Bearer <redacted>' -o '${partial}' '${SPRITE_WORKSHOP_MODEL_URL}'"
    printf '[dry-run] %q\n' "verify sha256('${partial}') == ${SPRITE_WORKSHOP_MODEL_SHA256}, then mv '${partial}' '${target}'"
    return 0
  fi

  [[ -n "$SPRITE_WORKSHOP_HF_TOKEN" ]] || die "SPRITE_WORKSHOP_HF_TOKEN (or HF_TOKEN) is not set; accept the license at ${SPRITE_WORKSHOP_MODEL_LICENSE_URL} and provide your own token first"
  have_cmd curl || die "curl is required to download the checkpoint"

  mkdir -p "$SPRITE_WORKSHOP_MODEL_DIR"
  log "downloading checkpoint to ${partial} (this is the real ~6.9 GB download; not run under --dry-run)"
  if ! curl -fL --retry 3 -H "Authorization: Bearer ${SPRITE_WORKSHOP_HF_TOKEN}" -o "$partial" "$SPRITE_WORKSHOP_MODEL_URL"; then
    rm -f "$partial"
    die "download failed; no partial file left behind"
  fi

  local status rc
  set +e
  status="$(verify_model_file "$partial" "$SPRITE_WORKSHOP_MODEL_SHA256")"
  rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    rm -f "$partial"
    die "downloaded checkpoint failed SHA-256 verification (${status}); deleted the bad download, target left untouched"
  fi

  mv "$partial" "$target"
  log "checkpoint downloaded and SHA-256 verified at ${target}"
}

print_summary() {
  cat <<EOF
[setup-comfyui-radeon] Summary
  ComfyUI checkout : ${SPRITE_WORKSHOP_COMFY_ROOT} @ ${SPRITE_WORKSHOP_COMFY_REF}
  ComfyUI venv     : ${SPRITE_WORKSHOP_COMFY_VENV} (independent; ROCm torch reused via PYTHONPATH=${SPRITE_WORKSHOP_ROCM_SITE})
  Checkpoint       : ${SPRITE_WORKSHOP_MODEL_DIR}/${SPRITE_WORKSHOP_MODEL_FILENAME}
  Checkpoint SHA256: ${SPRITE_WORKSHOP_MODEL_SHA256}
  Next step        : scripts/start_comfyui.sh (R03) starts/stops the service.
EOF
}

main() {
  parse_args "$@"
  log "dry-run=${DRY_RUN} comfy_root=${SPRITE_WORKSHOP_COMFY_ROOT} comfy_venv=${SPRITE_WORKSHOP_COMFY_VENV} rocm_site=${SPRITE_WORKSHOP_ROCM_SITE} ref=${SPRITE_WORKSHOP_COMFY_REF}"
  ensure_comfyui_repo
  ensure_comfyui_venv
  install_minimal_requirements
  ensure_model_checkpoint
  print_summary
}

# Only run main when executed directly, not when sourced (e.g. by tests that
# want to call the pure helper functions above in isolation).
if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" ]]; then
  main "$@"
fi
