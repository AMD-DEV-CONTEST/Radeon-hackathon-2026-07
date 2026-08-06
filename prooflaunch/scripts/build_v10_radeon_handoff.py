from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist/radeon-v10"
ARCHIVE = OUTPUT / "prooflaunch-radeon-v10.tar.gz"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def part_index(path: Path) -> int:
    try:
        return int(path.name.rsplit("-", 1)[-1])
    except ValueError as error:
        raise ValueError(f"invalid Radeon archive part name: {path.name}") from error


def main() -> int:
    checksum = OUTPUT / "prooflaunch-radeon-v10.sha256"
    expected = checksum.read_text(encoding="utf-8").split()[0]
    archive_sha = sha256(ARCHIVE)
    parts = sorted(
        OUTPUT.glob("prooflaunch-radeon-v10.part-*"),
        key=part_index,
    )
    concatenated = hashlib.sha256()
    for part in parts:
        with part.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                concatenated.update(block)
    with tarfile.open(ARCHIVE, "r:gz") as bundle:
        names = bundle.getnames()
    required = (
        "prooflaunch_submission/notebooks/prooflaunch_cortex_x_v10_radeon.ipynb",
        "prooflaunch_submission/scripts/capture_v10_radeon_live_preflight.py",
        "prooflaunch_submission/scripts/run_v10_clean_radeon_instance.sh",
        "prooflaunch_submission/data/v10_cpt_corpus/manifest.json",
        "prooflaunch_submission/data/v10_sft_corpus/manifest.json",
        "prooflaunch_submission/data/v10_agency_trajectories/manifest.json",
        "prooflaunch_submission/data/v10_repair_corpus/manifest.json",
        "prooflaunch_submission/data/v10_curated_human_audit/manifest.json",
        "prooflaunch_submission/evidence/v10/curated-1500-human-audit-gate.json",
        "prooflaunch_submission/config/cortex_x_v10_final_locks.json",
    )
    failures = []
    if expected != archive_sha or concatenated.hexdigest() != archive_sha:
        failures.append("archive_or_part_reassembly_hash")
    failures.extend(f"missing:{name}" for name in required if name not in names)
    if any(name.startswith("prooflaunch_submission/data/tokenfactory_teacher_v10/") for name in names):
        failures.append("private_tokenfactory_outputs_present")
    forbidden_hidden_roots = (
        "prooflaunch_submission/.prooflaunch-runtime/",
        "prooflaunch_submission/.prooflaunch-secrets/",
        "prooflaunch_submission/.super-site-10x/",
    )
    private_runtime_entries = [
        name
        for name in names
        if name.startswith(forbidden_hidden_roots)
    ]
    if private_runtime_entries:
        failures.append("private_runtime_entries_present")
    manifest = {
        "schema": "ProofLaunchRadeonHelloROCmHandoffV1",
        "status": "passed_local_handoff_integrity_not_radeon_run" if not failures else "failed",
        "recommended_template": "Hello ROCm",
        "expected_image_tag": "amd-oneclick-base:rocm7.2.1-py3.12-v20260416",
        "archive": {
            "name": ARCHIVE.name,
            "bytes": ARCHIVE.stat().st_size,
            "sha256": archive_sha,
            "file_count": len(names),
        },
        "parts": [
            {"name": part.name, "bytes": part.stat().st_size, "sha256": sha256(part)}
            for part in parts
        ],
        "part_reassembly_sha256": concatenated.hexdigest(),
        "checksum_file": checksum.name,
        "required_entries_present": not any(item.startswith("missing:") for item in failures),
        "private_tokenfactory_outputs_present": False,
        "private_runtime_entries_present": bool(private_runtime_entries),
        "official_model_api": {
            "required_before_local_training": True,
            "endpoint": "https://developer.amd.com.cn/radeon/api/v1/chat/completions",
            "credential_environment_variable": "RADEON_TOKEN_FACTORY_API_KEY",
            "credential_persisted": False,
            "execution_observed_in_this_receipt": False,
            "api_response_counts_as_local_training": False,
        },
        "failure_count": len(failures),
        "failures": failures,
        "radeon_execution_observed": False,
        "truth_boundary": "This receipt proves local archive, part reassembly, required-file, and privacy integrity only; the Hello ROCm instance and GPU execution remain unobserved.",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT / "HANDOFF.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    markdown = f"""# ProofLaunch V10 → Hello ROCm handoff

Upload either the complete archive plus checksum, or all {len(parts)} parts plus checksum.

## Reassemble parts when needed

```bash
cat prooflaunch-radeon-v10.part-* > prooflaunch-radeon-v10.tar.gz
sha256sum -c prooflaunch-radeon-v10.sha256
```

Expected archive SHA-256: `{archive_sha}`

## Extract without overwriting another project

```bash
mkdir -p prooflaunch-radeon-v10-run
tar -xzf prooflaunch-radeon-v10.tar.gz -C prooflaunch-radeon-v10-run
cd prooflaunch-radeon-v10-run/prooflaunch_submission
```

## Capture the real Radeon runtime first

```bash
PYTHONPATH=src python scripts/capture_v10_radeon_live_preflight.py \
  --output evidence/v10/radeon-live-preflight.json
```

Do not continue to model loading unless `preflight_passed=true`, `hip_version` is non-null, and at least one Radeon device is recorded.

## Run the official AMD model route before local training

In the Jupyter kernel, enter the key through a hidden prompt. Never paste it into a
Notebook cell, repository file, terminal history, screenshot, or chat:

```python
from getpass import getpass
import os
os.environ["RADEON_TOKEN_FACTORY_API_KEY"] = getpass("AMD Token Factory API key: ")
```

Then run cell 30 of `notebooks/prooflaunch_cortex_x_v10_radeon.ipynb`. It calls
`https://developer.amd.com.cn/radeon/api/v1/chat/completions`, tries the frozen
official model order, and writes a redacted route receipt without persisting the
credential or visible response. A successful receipt proves official model API
inference only.

Use official outputs for teacher generation, critique, ranking, and repair. Admit
the visible outputs into CPT/SFT/distillation training only when the exact AMD
program terms or written authorization explicitly permit output training use.
Otherwise keep the official model as an evaluator and train Gemma locally from
the rights-cleared project corpus. In every case, the actual LoRA/CPT/SFT step and
at least one key inference must run on the Radeon/ROCm device and produce runtime
receipts; an API response is never labeled as local training.

## Verify the portable project

```bash
PYTHONPATH=src python scripts/run_v10_local_suite.py \
  --output evidence/v10/local-test-report.hello-rocm.json
```

The canonical clean-instance script additionally requires the real control-plane container digest; do not substitute a placeholder digest.

## Persistence before destroying the instance

Download the new runtime receipt, model/adapter checkpoints, logs, evaluation outputs, and updated manifest before clicking **Destroy Instance**. Never place API keys inside the archive or Notebook.

## Boundary

{manifest['truth_boundary']}
"""
    atomic_write_text(OUTPUT / "HANDOFF.md", markdown)
    print(json.dumps(manifest, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
