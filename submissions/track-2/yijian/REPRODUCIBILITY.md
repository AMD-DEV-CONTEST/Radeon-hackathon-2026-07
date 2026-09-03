# Reproducibility

This submission separates three reproducibility levels so evaluators can distinguish public execution from restricted training artifacts.

## Level 1 - Clean public reproduction (no GPU or private data required)

Requirements:

- Windows 10/11 or Linux;
- CPython 3.13;
- network access for the first package installation.

Clone the exact submission branch:

```bash
git clone --branch codex/yijian-track2-submission https://github.com/almq666/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/submissions/track-2/yijian/source
```

On Windows, run one command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/reproduce_public.ps1
```

Expected result:

```text
YIJIAN PUBLIC REPRODUCTION: PASS
```

The script creates its virtual environment and JSON report in the system temporary directory, leaving the checkout clean. It installs `requirements-lock.txt`, verifies every allowlisted file hash, compiles all Python source, runs all 189 public backend and training tests, imports the FastAPI application, and calls its health function.

Manual Linux equivalent:

```bash
python3.13 -m venv /tmp/yijian-public-repro-venv
/tmp/yijian-public-repro-venv/bin/python -m pip install -r requirements-lock.txt
/tmp/yijian-public-repro-venv/bin/python scripts/validate_public_submission_snapshot.py \
  --snapshot . --output /tmp/yijian-public-reproduction-report.json
/tmp/yijian-public-repro-venv/bin/python -m uvicorn app:app \
  --app-dir backend --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Without model services or KataGo, SGF import, board reconstruction, deterministic review, evidence validation, and safe fallback remain available.

## Level 2 - Public AMD Radeon PRO W7900 / ROCm model path

The public path does not require the restricted adapter:

1. provision a Radeon PRO W7900 / gfx1100 host with ROCm;
2. run `source/deploy/cloud/install_qwen3_14b_vllm.sh`;
3. download Qwen3-14B revision `40c069824f4251a91eefaf281ebe4c544efd3e18` with `source/training/remote/download_qwen3_14b.sh`;
4. start the localhost-only BF16 service with `source/deploy/cloud/start_qwen3_14b_base.sh`;
5. point `YIJIAN_LOCAL_LLM_URL` at `http://127.0.0.1:8083/v1`;
6. run the application and the synthetic benchmark fixtures.

The measured environment was vLLM `0.20.2rc1.dev15+g321fa2d6d.rocm721` at commit `321fa2d6d1644629ac39d173f6393f37e14bf7b4`, inference Torch `2.10.0+git8514f05`, Transformers `5.14.1`, ROCm 7.2.1, and gfx1100. All model services bind to localhost.

## Level 3 - Authorized private training replay

The repository includes the SFT compiler, schemas, split/leakage checks, BF16 LoRA trainer, evaluation code, freeze logic, and release gates. It does not publish creator-authorized text, private games, review comments, sealed prompts, weights, or adapters.

An authorized maintainer can place the frozen 720-record training package and registered source artifacts at the documented private paths, then run smoke, micro, full, freeze, runtime evaluation, blind review, and coexistence scripts. Each stage validates the base revision, data hash, tokenizer length, BF16 capability, task mix, and memory ceiling before using the GPU. Smoke, micro, and full each start from the original base.

The v3 full run used seed `20260803`, batch size 1, gradient accumulation 16, learning rate `3e-5`, LoRA rank 8 / alpha 16 / dropout 0.10, target modules `q_proj`, `k_proj`, `v_proj`, `o_proj`, and exactly two epochs. Immutable aggregate evidence and hashes are in `evidence/`; restricted rows are not.

## Integrity and expected boundaries

- `source/public-snapshot-manifest.json` binds every public source file by SHA-256.
- `evidence/submission/public-snapshot-validation.json` records the passing 141-file / 189-test clean-snapshot validation.
- `submission-status.json` is the machine-readable metric source of truth.
- `EVIDENCE_INDEX.md` maps every published performance claim to an evidence file.
- no credentials, absolute user paths, private games, databases, weights, adapters, raw media, reviewer comments, or sealed cases are present.

The 14B LoRA passed training and machine runtime gates but failed the final anonymous human gate. Therefore the sealed-once set remains unopened and the stable 27B route remains the competition alias. Reproduction must preserve this release decision rather than silently promoting the failed candidate.
