#!/usr/bin/env bash
# Bind release-card metadata from measured artifacts and publish Physical-1K privately.
#
# Prerequisites:
#   - datasets/radeonvla_reflex_physical_1k exists and has passed strict validation
#   - optional checkpoint under outputs/train/smolvla_radeonvla_reflex_physical_1k
#   - HF_TOKEN with WRITE permission under the authenticated user namespace
#   - token is never passed on the CLI; use HF_TOKEN env or `hf auth login`
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

PYTHON_BIN="${PYTHON_BIN:-/workspace/radeonvla-venv/bin/python}"
HF_NAMESPACE="${HF_NAMESPACE:-}"
DATASET_ROOT="${DATASET_ROOT:-datasets/radeonvla_reflex_physical_1k}"
TRAIN_OUTPUT="${TRAIN_OUTPUT:-outputs/train/smolvla_radeonvla_reflex_physical_1k}"
POLICY_PATH="${POLICY_PATH:-}"
SOURCE_COMMIT="${SOURCE_COMMIT:-dbc12b69e88be787b679bb41cf2026ca43e0eda6}"
SKIP_MODEL="${SKIP_MODEL:-0}"
PRIVATE="${PRIVATE:-1}"

if [[ "$SKIP_MODEL" != "1" && -z "$POLICY_PATH" ]]; then
  POLICY_PATH="$(latest_pretrained_model "$TRAIN_OUTPUT")" \
    || die "No pretrained model found below $TRAIN_OUTPUT/checkpoints"
fi

section "Resolve Hugging Face identity"
identity="$("$PYTHON_BIN" - <<'PY'
from huggingface_hub import whoami
info = whoami()
print(info["name"])
print(",".join(org.get("name", "") for org in info.get("orgs", []) if org.get("name")))
PY
)"
user_name="$(printf '%s\n' "$identity" | sed -n '1p')"
orgs="$(printf '%s\n' "$identity" | sed -n '2p')"
if [[ -z "$HF_NAMESPACE" ]]; then
  HF_NAMESPACE="$user_name"
fi
log "Authenticated as $user_name (orgs=${orgs:-none}); publishing under $HF_NAMESPACE"
if [[ "$HF_NAMESPACE" != "$user_name" && ",$orgs," != *",$HF_NAMESPACE,"* ]]; then
  die "HF_NAMESPACE=$HF_NAMESPACE is not the authenticated user or one of its orgs"
fi

# LeRobot / Hub style: lowercase + underscores (not mixed hyphens).
DATASET_REPO="${DATASET_REPO:-${HF_NAMESPACE}/radeonvla_reflex_physical_1k}"
MODEL_REPO="${MODEL_REPO:-${HF_NAMESPACE}/radeonvla_reflex_smolvla_1k}"
VALIDATION_JSON="${VALIDATION_JSON:-artifacts/physical_1k_validation.json}"
MANIFEST_JSON="${MANIFEST_JSON:-$DATASET_ROOT/recording_manifest.json}"
DATASET_CARD="${DATASET_CARD:-docs/DATASET_CARD.md}"
MODEL_CARD="${MODEL_CARD:-docs/MODEL_CARD.md}"
FILLED_DATASET_CARD="${FILLED_DATASET_CARD:-artifacts/DATASET_CARD.filled.md}"
FILLED_MODEL_CARD="${FILLED_MODEL_CARD:-artifacts/MODEL_CARD.filled.md}"

[[ -d "$DATASET_ROOT" ]] || die "Dataset root missing: $DATASET_ROOT"
[[ -f "$MANIFEST_JSON" ]] || die "Manifest missing: $MANIFEST_JSON"

section "Bind measured release metadata"
"$PYTHON_BIN" - <<PY
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

dataset_root = Path("$DATASET_ROOT")
manifest = json.loads(Path("$MANIFEST_JSON").read_text(encoding="utf-8"))
validation_path = Path("$VALIDATION_JSON")
validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.is_file() else {}
source_commit = str(manifest.get("source_commit") or "$SOURCE_COMMIT")
successes = int(manifest.get("successes", 0))
dataset_sha = hashlib.sha256()
for path in sorted(p for p in dataset_root.rglob("*") if p.is_file()):
    dataset_sha.update(path.relative_to(dataset_root).as_posix().encode())
    dataset_sha.update(path.read_bytes())
dataset_digest = dataset_sha.hexdigest()

def fill(text: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        text = text.replace(key, value)
    # Release cards must contain measured metadata before publication.
    leftovers = [m for m in ("Release status: pre-release", "TBD", "[PENDING]") if m in text]
    if leftovers:
        raise SystemExit(f"Card still contains {leftovers}")
    return text

dataset_map = {
    "Version: Assigned by release workflow": f"Version: physical-1k-{successes}",
    "Generator commit: Bound from the dataset manifest at release": f"Generator commit: \`{source_commit}\`",
    "Public URL: Published by release workflow": f"Public URL: https://huggingface.co/datasets/$DATASET_REPO",
    "SHA256 or dataset revision: Computed at release": f"SHA256 (local tree): \`{dataset_digest}\`",
}
dataset_card = Path("$DATASET_CARD").read_text(encoding="utf-8")
dataset_card = dataset_card.replace("> Release status: pre-release. Publication metadata is bound by the validated release workflow.\n\n", "")
dataset_card = dataset_card.replace(
    "Episode counts, frame counts, source revision, and checksums\nare bound to the published card only after the 1,000-episode validator passes.",
    "Episode counts, frame counts, source revision, and checksums are bound to this card from the validated release artifacts.",
)
dataset_card = fill(dataset_card, dataset_map)
Path("$FILLED_DATASET_CARD").parent.mkdir(parents=True, exist_ok=True)
Path("$FILLED_DATASET_CARD").write_text(dataset_card, encoding="utf-8")
print(f"[publish] wrote $FILLED_DATASET_CARD")

policy = Path("$POLICY_PATH")
if policy.is_dir():
    policy_sha = hashlib.sha256()
    for path in sorted(p for p in policy.rglob("*") if p.is_file()):
        policy_sha.update(path.relative_to(policy).as_posix().encode())
        policy_sha.update(path.read_bytes())
    env_path = Path("artifacts/environment.remote.json")
    env = json.loads(env_path.read_text(encoding="utf-8")) if env_path.is_file() else {}
    train_summary_path = Path("artifacts/train_summary.json")
    train_steps = "see train logs"
    if train_summary_path.is_file():
        train_steps = str(json.loads(train_summary_path.read_text(encoding="utf-8")).get("steps", train_steps))
    model_map = {
        "Fine-tuned checkpoint: Selected from the validated release run": f"Fine-tuned checkpoint: \`$POLICY_PATH\`",
        "Public URL: Published by release workflow": f"Public URL: https://huggingface.co/$MODEL_REPO",
        "SHA256: Computed at release": f"SHA256 (local tree): \`{policy_sha.hexdigest()}\`",
        "Training commit: Bound from the dataset manifest at release": f"Training commit: \`{source_commit}\`",
        "Dataset version: Bound from the validated dataset at release": f"Dataset version: physical-1k-{successes}",
        "| Radeon GPU | Recorded from release artifacts |": f"| Radeon GPU | {env.get('gpu_name', 'AMD Radeon (ROCm)')} |",
        "| ROCm | Recorded from release artifacts |": f"| ROCm | {env.get('rocm_version', 'see environment receipt')} |",
        "| PyTorch | Recorded from release artifacts |": f"| PyTorch | {env.get('torch_version', 'see environment receipt')} |",
        "| Precision | Recorded from training configuration |": "| Precision | bf16/fp32 per train config |",
        "| Batch size | Recorded from training configuration |": "| Batch size | 4 |",
        "| Gradient accumulation | Recorded from training configuration |": "| Gradient accumulation | train config default |",
        "| Training steps | Recorded from training summary |": f"| Training steps | {train_steps} |",
        "| Training time | Recorded from training summary |": f"| Training time | recorded at {datetime.now(UTC).isoformat()} |",
        "| Peak VRAM | Recorded from release artifacts |": f"| Peak VRAM | {env.get('peak_vram', 'see train logs')} |",
    }
    model_card = Path("$MODEL_CARD").read_text(encoding="utf-8")
    model_card = model_card.replace("> Release status: pre-release. Publication metadata is bound by the validated release workflow.\n\n", "")
    model_card = fill(model_card, model_map)
    Path("$FILLED_MODEL_CARD").write_text(model_card, encoding="utf-8")
    print(f"[publish] wrote $FILLED_MODEL_CARD")
else:
    print(f"[publish] policy path missing ({policy}); dataset-only publish")
PY

section "Publish to Hugging Face (private by default)"
PUBLISH_ARGS=(
  -m radeonvla.publish_hf
  --dataset-repo "$DATASET_REPO"
  --dataset-root "$DATASET_ROOT"
  --dataset-card "$FILLED_DATASET_CARD"
  --dataset-validation "$VALIDATION_JSON"
  --expected-episodes 1000
  --episodes-per-task 50
  --receipt artifacts/huggingface_release.json
)
if [[ "$PRIVATE" == "1" ]]; then
  PUBLISH_ARGS+=(--private)
else
  PUBLISH_ARGS+=(--public --confirm-public-release)
fi
if [[ "$SKIP_MODEL" != "1" && -d "$POLICY_PATH" ]]; then
  PUBLISH_ARGS+=(
    --model-repo "$MODEL_REPO"
    --policy-path "$POLICY_PATH"
    --model-card "$FILLED_MODEL_CARD"
  )
fi
run_py "${PUBLISH_ARGS[@]}"
if [[ "$SKIP_MODEL" == "1" ]]; then
  ok "Published dataset $DATASET_REPO (dataset only)"
else
  ok "Published dataset $DATASET_REPO"
fi
if [[ "$SKIP_MODEL" != "1" && -d "$POLICY_PATH" ]]; then
  ok "Published model $MODEL_REPO"
fi
