# YIJIAN Public Source

YIJIAN is an evidence-grounded Go review Agent for AMD Radeon and ROCm. This directory is a public-safe, allowlisted source snapshot: runtime code, tests, synthetic fixtures, schemas, training logic, deployment scripts, and validation tooling are included; private games, creator material, review comments, sealed cases, model weights, adapters, databases, logs, and credentials are not.

## One-command clean reproduction on Windows

Requirements: Windows 10/11, Python 3.13, and network access for the first dependency install.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/reproduce_public.ps1
```

The script creates a virtual environment under the system temporary directory, installs the pinned lock file, checks every public file hash, compiles all Python files, runs all 189 public backend and training tests, and imports the application health endpoint. A passing run prints `YIJIAN PUBLIC REPRODUCTION: PASS` and writes a JSON report outside the repository.

To install Chromium and run the optional browser check later:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/reproduce_public.ps1 -InstallBrowser
```

## Manual start

```powershell
py -3.13 -m venv $env:TEMP\yijian-repro-venv
& $env:TEMP\yijian-repro-venv\Scripts\python.exe -m pip install -r requirements-lock.txt
& $env:TEMP\yijian-repro-venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. With no model or KataGo installed, SGF import, board reconstruction, deterministic review, evidence validation, and safe fallback remain available.

## AMD Radeon PRO W7900 / ROCm path

See [`deploy/cloud/README.md`](deploy/cloud/README.md). The public path downloads the fixed Qwen3-14B revision and starts a localhost-only BF16 vLLM service without any private adapter. The measured competition path, private adapter gate, KataGo coexistence benchmark, and rollback scripts are also included. Published measurements are indexed one directory above in `EVIDENCE_INDEX.md`.

## Tests

```powershell
python -m pytest -q backend/tests
python -m pytest -q training/tests
```

The public snapshot validator deliberately uses synthetic fixtures and excludes tests bound to private game archives.

## Release truth

YIJIAN LoRA v3 was trained and frozen on the W7900, but it failed the final anonymous human release gate. The sealed-once set therefore remains unopened and the competition runtime stays on the stable 27B service. KataGo and the rules engine remain authoritative for both model routes.
