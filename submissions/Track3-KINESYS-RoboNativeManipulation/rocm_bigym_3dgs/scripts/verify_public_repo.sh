#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

for script in scripts/*.sh reconstruction/bin/*.sh reconstruction/reference/*.sh \
  evaluation/bigym-3dgs/bin/*.sh; do
  bash -n "$script"
done

python3 -m compileall -q scripts reconstruction/src \
  evaluation/bigym-3dgs/src evaluation/bigym-3dgs/tests
python3 - <<'PY'
import json
from pathlib import Path
paths = (
    sorted(Path("configs").glob("*.json"))
    + sorted(Path("evidence").glob("*.json"))
    + sorted(Path("data/manifests").glob("*.json"))
    + sorted(Path("evaluation/bigym-3dgs").glob("*.json"))
)
for path in paths:
    json.loads(path.read_text(encoding="utf-8"))
    print("JSON_OK", path)
PY

if command -v sha256sum >/dev/null; then
  sha256sum -c SHA256SUMS >/dev/null
else
  shasum -a 256 -c SHA256SUMS >/dev/null
fi

if rg -n --hidden \
  'BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_|AKIA[0-9A-Z]{16}|root@[0-9]+\.|36\.150\.116\.206|ccr-[A-Za-z0-9.-]+|poc\.config' \
  --glob '!.git/**' --glob '!.gitignore' --glob '!scripts/verify_public_repo.sh' .; then
  printf 'Potential credential or private endpoint found.\n' >&2
  exit 2
fi

if git ls-files | rg '\.(ply|pt|ckpt|zip|tar\.zst)$|^data/private/'; then
  printf 'Licensed source data, model assets, or checkpoints are tracked.\n' >&2
  exit 2
fi

python3 - <<'PY'
import json
import subprocess
from pathlib import Path

tracked = subprocess.check_output(
    ["git", "ls-files", "evaluation/bigym-3dgs/evidence/*.json"],
    text=True,
).splitlines()
if not tracked:
    print("NO_ACCEPTED_FORMAL_EVIDENCE_PUBLISHED")
for filename in tracked:
    path = Path(filename)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    benchmark = receipt.get("benchmark", {})
    gates = receipt.get("gates", {})
    assert receipt.get("publication_status") == "accepted_formal_evaluation", path
    assert benchmark.get("mode") == "formal", path
    assert isinstance(benchmark.get("n_episodes"), int), path
    assert benchmark["n_episodes"] > 0, path
    assert gates.get("recording_validation") is True, path
    assert gates.get("result_validation") is True, path
    assert gates.get("human_three_camera_review") is True, path
    print("ACCEPTED_FORMAL_EVIDENCE_OK", path)
PY

python3 - <<'PY'
import json
from pathlib import Path

source = json.loads(Path("data/manifests/dl3dv-kitchen-source.public.json").read_text())
assert source["source"]["archive_bytes"] == 910995448
assert source["source"]["archive_sha256"] == "9765ce6dd3661ba125b6689c0cc50717645480ec2ce5790a4636129521341adb"
assert source["source"]["scene_hash"] == "90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947"
assert source["redistribution"]["source_archive_in_repo"] is False
reconstruction = json.loads(Path("data/manifests/reference-reconstruction.public.json").read_text())
assert reconstruction["method"]["strategy"] == "mcmc scheduled-r20"
assert reconstruction["method"]["steps"] == 60000
assert len(reconstruction["shell_assets"]) == 4
dataset = json.loads(Path("data/manifests/cutlery32-dataset.public.json").read_text())
assert dataset["dataset_id"] == "bigym-3dgs-light-floor-replay-plan-v2-20260802"
assert dataset["summary"]["episodes"] == 32
assert dataset["summary"]["video_files"] == 3
assert dataset["status"] == "technical_pass_visual_approval_pending"
assert dataset["runtime"] == "reference-baseline"
reference_summary = json.loads(Path("evidence/reference-validation-summary.json").read_text())
assert reference_summary["role"] == "reference_validation_for_amd_main"
assert reference_summary["branch"] == "reference"
assert reference_summary["status"] == "reference_technical_pass_visual_approval_pending"
amd = json.loads(Path("evidence/amd-rocm-main-status.json").read_text())
assert amd["branch"] == "main"
assert amd["role"] == "amd_rocm_implementation"
assert amd["status"] == "amd_rocm_reproduction_passed"
assert amd["quality_status"] == "clear_heldout_pass_strict_photo_grade_target_not_met"
assert amd["target"]["vendor"] == "AMD"
assert amd["target"]["architecture"] == "gfx1100"
assert amd["target"]["device"] == "AMD Radeon PRO W7900D"
assert amd["canonical_inputs"]["images"] == 352
assert amd["reconstruction"]["steps"] == 15000
assert amd["reconstruction"]["cleaned_gaussians"] == 1458354
assert amd["reconstruction"]["cleanup"]["projected_streaks_removed"] == 11027
assert amd["reconstruction"]["heldout"]["psnr"] >= 27.5
assert amd["reconstruction"]["heldout"]["ssim"] >= 0.93
assert all(amd["technical_gates"].values())
assert not any(amd["strict_photo_grade_gates"].values())
assert amd["artifacts"]["cleaned_ply"]["sha256"] == "d49bcf7219f63a92ee0d40f8d86e618176892ec89853fecc5e217829bff42b9b"
assert "canonical_32_episode_package_reproduced_on_amd" in amd["not_claimed"]
preview = Path("docs/images/cutlery-cam-high-preview.gif")
assert preview.read_bytes()[:6] in {b"GIF87a", b"GIF89a"}
assert 1_000_000 < preview.stat().st_size < 10_000_000
amd_preview = Path("docs/images/amd-rocm-heldout-vs-reference.png")
assert amd_preview.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
assert 1_000_000 < amd_preview.stat().st_size < 10_000_000
runtime_demo = Path("docs/images/bigym-3dgs-runtime-demo.gif")
assert runtime_demo.read_bytes()[:6] in {b"GIF87a", b"GIF89a"}
assert 3_000_000 < runtime_demo.stat().st_size < 10_000_000
reference_video = Path("docs/videos/bigym-3dgs-shell-reference.mp4")
assert reference_video.read_bytes()[4:8] == b"ftyp"
assert 5_000_000 < reference_video.stat().st_size < 10_485_760
print("DATA_CONTRACT_OK")
PY

max_repo_size_limit_bytes=20M
allowed_large_files=(
  "./docs/images/20260806-205335.gif"
)

if find . -type f -size +"$max_repo_size_limit_bytes" -not -path './.git/*' -print0 | while IFS= read -r -d '' file; do
  skip=0
  for allowed in "${allowed_large_files[@]}"; do
    if [ "$file" = "$allowed" ]; then
      skip=1
      break
    fi
  done
  if [ "$skip" -eq 0 ]; then
    printf '%s\n' "$file"
  fi
done | grep -q .; then
  printf 'Unexpected file larger than 20 MiB:\n' >&2
  find . -type f -size +"$max_repo_size_limit_bytes" -not -path './.git/*' -print0 | while IFS= read -r -d '' file; do
    skip=0
    for allowed in "${allowed_large_files[@]}"; do
      if [ "$file" = "$allowed" ]; then
        skip=1
        break
      fi
    done
    [ "$skip" -eq 0 ] && printf '%s\n' "$file"
  done >&2
  exit 2
fi

printf 'PUBLIC_REPO_CHECK_OK\n'
