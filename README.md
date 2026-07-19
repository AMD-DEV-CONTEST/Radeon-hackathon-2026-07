# Aetheris + VTE

A fully local AI ecosystem for AMD Radeon GPUs. See [`PROJECT_SPECIFICATION.md`](PROJECT_SPECIFICATION.md) for the architecture, capabilities, model list, and inference-speed optimization writeup.

Two independent pieces in this repository:

- **`VTE/`**: the inference engine. Hand-written HIP kernels, runs any supported GGUF model directly on an AMD Radeon GPU. Usable completely on its own (CLI or HTTP server), with no dependency on Aetheris.
- **`Aetheris Studio/`**: the agent application (Flutter desktop UI + Python backend) that uses VTE as its inference engine. Depends on VTE being installed.

Pick the section below that matches what you want to run.

## Prerequisites (all paths)

- Python 3.10+
- An AMD Radeon GPU with the HIP runtime available:
  - **Windows**: AMD HIP SDK installed (provides `amdhip64_*.dll`)
  - **Linux**: ROCm installed (provides `libamdhip64.so`, normally under `/opt/rocm`)
- Enough VRAM for whatever model you load (see the model table in `PROJECT_SPECIFICATION.md`; models range from ~0.4 GB to ~29 GB on disk)

VTE auto-detects the HIP runtime and the GPU's compute-unit count / architecture at startup; no manual GPU configuration is needed beyond having the driver/SDK installed.

---

## Option A: Run VTE standalone (no UI, CLI/HTTP only)

Works identically on Windows and Linux. Tested on both: RX 7600 (Windows, gfx1102) and an AMD Radeon PRO W7900 (Linux/ROCm 7.2.1, gfx1100).

```bash
cd VTE
python -m venv .venv

# Windows
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -e .

# Linux
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

Pull a model (downloads a public GGUF from Hugging Face into `VTE/Model/`):

```bash
# Windows
.venv\Scripts\vte pull qwen2.5:1.5b-q4_k_m

# Linux
.venv/bin/vte pull qwen2.5:1.5b-q4_k_m
```

Run `vte list` to see every curated model name and its source repository.

**Interactive CLI / one-off generation:**

```python
from vte.core.model import VTEModel

model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", context_length=4096)
for token in model.generate("Explain what ROCm is in one sentence.", max_tokens=100):
    print(token, end="", flush=True)
```

**HTTP server (OpenAI-compatible `/v1/chat/completions`), the same entry point Aetheris uses internally:**

```bash
# Windows
.venv\Scripts\vte-server --gguf-path Model\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --port 8011

# Linux
.venv/bin/vte-server --gguf-path Model/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --port 8011
```

Poll `GET http://127.0.0.1:8011/health` until `{"status": "ready"}`, then talk to it exactly like any OpenAI-compatible endpoint.

**Development extras** (`pytest`, `mypy`, `pyinstaller`, which are not needed just to run inference):

```bash
.venv\Scripts\pip install -e ".[dev]"      # Windows
.venv/bin/pip install -e ".[dev]"          # Linux
```

`hip-python` (used only by one struct-validation dev script, `tools/validate_structs.py`) is intentionally not pinned as a hard dependency, since the version that actually matches your installed ROCm build ships through AMD's own package index, not public PyPI. Install it by hand only if you're re-running that specific script.

---

## Option B: Run the full Aetheris + VTE app (Windows)

1. **Install VTE as an editable package** inside Aetheris's own virtual environment (this is what wires the two projects together; Aetheris spawns `vte-server` as a subprocess and expects `vte` to be importable):

   ```bash
   cd "Aetheris Studio"
   python -m venv .venv
   .venv\Scripts\pip install --upgrade pip
   .venv\Scripts\pip install -e "..\VTE"
   .venv\Scripts\pip install -r requirements.txt
   ```

2. **Get a model** into `VTE\Model\` (see Option A's `vte pull` step, run from inside `VTE\` with the same venv or a separate one; either works, `pip install -e` just needs to point at the `VTE` folder).

3. **Build the Flutter UI:**

   ```bash
   cd aetheris_ui
   flutter pub get
   flutter run -d windows
   ```

   The UI launches `app.py` itself on startup (polls `http://127.0.0.1:8001/`, spawns it if not already running); you don't need to start the Python backend by hand. `app.py` in turn spawns `vte-server` on the first chat message (or immediately, if you pick a model in the model selector, which calls `/api/vte/warmup`).

4. **First run: login.** No account exists until the backend's first boot; it generates one automatically and writes it to `Aetheris Studio\GENERATED_LOGIN_READ_AND_DELETE.txt`. Open that file, log in with the printed username/password, then delete the file (the plaintext password is not recoverable once it's gone; only a salted hash is stored). Every later run reuses that same account; nothing regenerates unless you delete `Aetheris Studio\core\data\auth_local.json`.

### Running VTE and Aetheris from two separate machines/checkouts

VTE has no compiled/frozen dependency on Aetheris; a `pip install -e` pointing at any VTE checkout works, editable installs just need the path to resolve at import time. There is no requirement that the two live side by side; the layout above (`VTE/` and `Aetheris Studio/` as siblings) is a convenience, not a hard coupling.
