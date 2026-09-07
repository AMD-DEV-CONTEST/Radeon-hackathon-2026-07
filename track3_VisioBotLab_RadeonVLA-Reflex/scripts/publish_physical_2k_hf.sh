#!/usr/bin/env bash
# Publish the strict Physical-2K dataset and cumulative-200K model only after the final gate passes.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

PYTHON_BIN="${PYTHON_BIN:-/workspace/radeonvla-venv/bin/python}"
HF_NAMESPACE="${HF_NAMESPACE:-}"
PRIVATE="${PRIVATE:-0}"
DATASET_ROOT="${DATASET_ROOT:-datasets/radeonvla_reflex_physical_2k}"
POLICY_PATH="${POLICY_PATH:-outputs/train/smolvla_radeonvla_reflex_physical_2k_continue_100k_to200k/checkpoints/100000/pretrained_model}"
VALIDATION_JSON="${VALIDATION_JSON:-artifacts/physical_2k_validation.json}"
ADDITIONAL_VALIDATION_JSON="${ADDITIONAL_VALIDATION_JSON:-artifacts/physical_additional_1k_validation.json}"
FIVE_EVAL="${FIVE_EVAL:-artifacts/evaluation.physical_2k_cumulative_200k_collected_five_fruit.json}"
FULL_EVAL="${FULL_EVAL:-artifacts/evaluation.physical_2k_cumulative_200k_collected_basic20.json}"
DECISION_JSON="${DECISION_JSON:-artifacts/physical_2k_cumulative_200k_release_decision.json}"
DATASET_CARD="${DATASET_CARD:-artifacts/DATASET_CARD.physical_2k.filled.md}"
MODEL_CARD="${MODEL_CARD:-artifacts/MODEL_CARD.physical_2k_cumulative_200k.filled.md}"
RECEIPT="${RECEIPT:-artifacts/huggingface_physical_2k_cumulative_200k_release.json}"

for path in \
  "$DATASET_ROOT/recording_manifest.json" \
  "$POLICY_PATH/model.safetensors" \
  "$VALIDATION_JSON" \
  "$ADDITIONAL_VALIDATION_JSON" \
  "$FIVE_EVAL" \
  "$FULL_EVAL" \
  "$DECISION_JSON"; do
  [[ -e "$path" ]] || die "Required release evidence missing: $path"
done

section "Verify the cumulative-200K release gate and bind release cards"
identity="$($PYTHON_BIN - <<'PY'
from huggingface_hub import whoami
print(whoami()["name"])
PY
)"
if [[ -z "$HF_NAMESPACE" ]]; then
  HF_NAMESPACE="$identity"
fi
DATASET_REPO="${DATASET_REPO:-${HF_NAMESPACE}/radeonvla_reflex_physical_2k}"
MODEL_REPO="${MODEL_REPO:-${HF_NAMESPACE}/radeonvla_reflex_smolvla_2k_200k}"

"$PYTHON_BIN" - \
  "$DATASET_ROOT" "$POLICY_PATH" "$VALIDATION_JSON" "$ADDITIONAL_VALIDATION_JSON" \
  "$FIVE_EVAL" "$FULL_EVAL" "$DECISION_JSON" "$DATASET_CARD" "$MODEL_CARD" \
  "$DATASET_REPO" "$MODEL_REPO" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

from radeonvla.artifact_io import atomic_write_text, sha256_path

(
    dataset_root_s,
    policy_path_s,
    validation_s,
    additional_validation_s,
    five_eval_s,
    full_eval_s,
    decision_s,
    dataset_card_s,
    model_card_s,
    dataset_repo,
    model_repo,
) = sys.argv[1:]

dataset_root = Path(dataset_root_s)
policy_path = Path(policy_path_s)
validation = json.loads(Path(validation_s).read_text(encoding="utf-8"))
additional_validation = json.loads(Path(additional_validation_s).read_text(encoding="utf-8"))
five = json.loads(Path(five_eval_s).read_text(encoding="utf-8"))
full = json.loads(Path(full_eval_s).read_text(encoding="utf-8"))
decision = json.loads(Path(decision_s).read_text(encoding="utf-8"))
manifest = json.loads((dataset_root / "recording_manifest.json").read_text(encoding="utf-8"))

if decision.get("gate_passed") is not True:
    raise SystemExit("Final cumulative-200K gate did not pass; refusing Hugging Face publication")
if float(decision.get("cumulative_200k_five_fruit_success", -1)) <= 0.4:
    raise SystemExit("Five-fruit result does not satisfy the strict >40% gate")
if float(decision.get("cumulative_200k_basic20_success", -1)) < 0.6:
    raise SystemExit("Basic-20 result does not satisfy the >=60% gate")
for name, report, expected, quota in (
    ("Physical-2K", validation, 2000, 100),
    ("additional Physical-1K", additional_validation, 1000, 50),
):
    if report.get("errors") or report.get("warnings"):
        raise SystemExit(f"{name} validation is not clean")
    if int(report.get("num_episodes", -1)) != expected:
        raise SystemExit(f"{name} episode count is not {expected}")
    counts = report.get("certified_successes_per_task", {})
    if len(counts) != 20 or set(map(int, counts.values())) != {quota}:
        raise SystemExit(f"{name} does not have exact 20x{quota} certified coverage")
if manifest.get("strict_physics") is not True or int(manifest.get("successes", -1)) != 2000:
    raise SystemExit("Physical-2K manifest is not a strict 2,000-success release")
for name, report, expected_tasks in (("five-fruit", five, 5), ("basic-20", full, 20)):
    config = report.get("config", {})
    if config.get("instruction_source") != "collected" or len(config.get("tasks", [])) != expected_tasks:
        raise SystemExit(f"{name} evaluation is not the exact collected-language task set")
    if int(report.get("summary", {}).get("num_episodes", -1)) != expected_tasks:
        raise SystemExit(f"{name} evaluation episode count is invalid")

policy_sha = sha256_path(policy_path)
dataset_sha = sha256_path(dataset_root)
expected_sha = str(decision.get("checkpoint_sha256", ""))
if not expected_sha or policy_sha != expected_sha:
    raise SystemExit("Release checkpoint does not match the final decision SHA256")
for report in (five, full):
    if report.get("checkpoint", {}).get("sha256") != policy_sha:
        raise SystemExit("Evaluation checkpoint SHA256 does not match the release policy")

source_commits = manifest.get("source_commits") or [manifest.get("source_commit")]
source_commits = sorted(str(item) for item in source_commits if item)
if len(source_commits) < 2:
    raise SystemExit("Merged Physical-2K manifest does not preserve both audited collection revisions")
source_lines = "\n".join(f"  - `{commit}`" for commit in source_commits)
num_frames = int(validation["num_frames"])
certificate_count = int(validation["strict_certificate_count"])

dataset_card = f"""---
license: cc-by-4.0
task_categories:
  - robotics
tags:
  - lerobot
  - robotics
  - imitation-learning
  - vision-language-action
  - amd-rocm
  - genesis
---

# RadeonVLA-Reflex Physical-2K

Validated strict-physics training data for language-conditioned Franka fruit sorting.

## Release evidence

- Episodes: **2,000 successful episodes**
- Frames: **{num_frames:,}**
- Coverage: **20 tasks × 100 episodes**
- Strict success certificates: **{certificate_count:,}**
- Validation: `errors=[]`, `warnings=[]`
- Local dataset tree SHA256: `{dataset_sha}`
- Public URL: https://huggingface.co/datasets/{dataset_repo}
- Audited collection revisions:
{source_lines}

The 20 tasks are five fruits (apple, banana, lemon, orange, and plum) crossed with
blue/white bowls on the left/right. Language is preserved from collection, including
the deterministic `Pick the ... and place it ...` and `Sort the ... into ...` forms.

## Observation and action schema

| Field | Shape/type | Description |
|---|---|---|
| `observation.images.world` | 240×320 RGB video | World camera |
| `observation.images.wrist` | 240×320 RGB video | Wrist camera |
| `observation.state` | 9-D float32 | Panda joints 1–7 and finger joints 1–2 |
| `action` | 9-D float32 | Absolute joint-position target |

Collection runs at 20 Hz with appearance, object-color, friction, mass, and runtime
domain randomization. Kinematic grasp assist and placement nudges are disabled. Failed
episodes are discarded; every committed episode has an atomic certificate proving zero
interventions and a strict physical success verdict. The dataset is simulation-only and
real-robot transfer is outside this release's measured scope.
"""

failure_counts = Counter()
for episode in full.get("episodes", []):
    for event in episode.get("events", []):
        if event.get("type") == "terminal_failure":
            failure_counts[str(event.get("reason", "unknown"))] += 1
failure_text = ", ".join(f"{key}: {value}" for key, value in sorted(failure_counts.items())) or "none"
env = full.get("environment", {})
five_rate = float(five["summary"]["final_success"])
full_rate = float(full["summary"]["final_success"])
summary = full["summary"]
model_card = f"""---
license: other
library_name: lerobot
base_model: lerobot/smolvla_base
tags:
  - robotics
  - vision-language-action
  - imitation-learning
  - amd-rocm
  - genesis
---

# RadeonVLA-Reflex SmolVLA Physical-2K cumulative-200K

## Verified checkpoint

- Training data: https://huggingface.co/datasets/{dataset_repo}
- Cumulative training: **200,000 optimizer steps** (100K base history + 100K Physical-2K continuation)
- Checkpoint tree SHA256: `{policy_sha}`
- Public URL: https://huggingface.co/{model_repo}
- Instructions: exact language collected in the dataset
- Five-fruit gate evaluation: **{five_rate:.0%}** (required >40%)
- Full 20-task gate evaluation: **{full_rate:.0%}** (required ≥60%)
- Final gate: **passed**

## Runtime and evaluation

| Item | Measured value |
|---|---|
| GPU | {env.get('gpu', 'AMD Radeon')} |
| ROCm | {env.get('rocm', 'recorded in evaluation JSON')} |
| PyTorch | {env.get('torch', 'recorded in evaluation JSON')} |
| Five-fruit episodes | {int(five['summary']['num_episodes'])} |
| Full-suite episodes | {int(full['summary']['num_episodes'])} |
| P50 inference latency | {float(summary['p50_inference_latency_ms']):.3f} ms |
| P95 inference latency | {float(summary['p95_inference_latency_ms']):.3f} ms |
| Observed terminal failures | {failure_text} |

The checkpoint consumes world/wrist RGB images, a 9-D Panda state, and a natural-language
instruction, and predicts 9-D absolute joint-position actions. The immutable evaluation
JSON, strict dataset validation reports, and release decision are included under
`evaluation/` in this repository. Results cover Genesis simulation only; they do not
claim real-robot transfer or tasks outside the registered 20-task fruit/bowl suite.

The upstream base repository did not declare license metadata at the frozen revision, so
this card uses Hugging Face's `other` marker rather than inventing a license.
"""

for text, destination in ((dataset_card, Path(dataset_card_s)), (model_card, Path(model_card_s))):
    if any(marker in text for marker in ("Release status: pre-release", "TBD", "[PENDING]")):
        raise SystemExit("Generated release card still contains a draft marker")
    atomic_write_text(destination, text)
print(f"[release] gate passed; checkpoint={policy_sha}; cards are bound")
PY

section "Publish Physical-2K and cumulative-200K checkpoint"
args=(
  -m radeonvla.publish_hf
  --dataset-repo "$DATASET_REPO"
  --dataset-root "$DATASET_ROOT"
  --dataset-card "$DATASET_CARD"
  --dataset-validation "$VALIDATION_JSON"
  --expected-episodes 2000
  --episodes-per-task 100
  --model-repo "$MODEL_REPO"
  --policy-path "$POLICY_PATH"
  --model-card "$MODEL_CARD"
  --model-evidence "$ADDITIONAL_VALIDATION_JSON"
  --model-evidence "$VALIDATION_JSON"
  --model-evidence "$FIVE_EVAL"
  --model-evidence "$FULL_EVAL"
  --model-evidence "$DECISION_JSON"
  --receipt "$RECEIPT"
)
if [[ "$PRIVATE" == "1" ]]; then
  args+=(--private)
else
  args+=(--public --confirm-public-release)
fi
run_py "${args[@]}"

ok "Published and immutable-revision reloaded: $DATASET_REPO and $MODEL_REPO"
