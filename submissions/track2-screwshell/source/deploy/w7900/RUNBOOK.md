# W7900 Deployment Runbook

Reproducible bring-up of ScrewShell on the AMD Radeon PRO W7900 (gfx1100) box.
Written 2026-08-02 after a full from-scratch redeploy; every command below was
actually executed on the live machine.

**Read this before trusting any other deploy doc in the repo.** `HOW_TO_OPEN.md`
and the old root-level `_run_roomy_server.sh` reference `/persistent/...`, which
does not exist. The real root is `/workspace/persistent/screwshell_run`.

---

## 0. Ground truth

| Thing | Value |
|---|---|
| Host | `ssh -p 31010 root@36.150.116.206` (publickey only) |
| Deploy root | `/workspace/persistent/screwshell_run` |
| Base model | `models/Qwen3.6-27B-Q4_K_M.gguf` (18 G) |
| llama.cpp | `/opt/llama.cpp` (or `.new`) — build at `/opt/llama.cpp*/build/bin/llama-server` |
| Inference | llama-server on `127.0.0.1:8080` (lifetime owned by llama-swap in gateway mode) |
| Gateway | llama-swap on `127.0.0.1:18080` (peers mode; proxies :8080). Binary `/opt/llama-swap/llama-swap` v246(22df230), SHA256 `a80a8aad...f14f9416` (23189302B). Config `/opt/llama-swap/poc/ls_phase2.yaml` |
| UI | Gradio on `127.0.0.1:7860` (set `MOL_LLAMACPP_URL=:18080` to go through the gateway) |
| Python | `/opt/venv/bin/python` |

Network caveat: the box has no CA bundle, so `git`/`pip` over HTTPS fail cert
verification. Workarounds that work:

```bash
GIT_SSL_NO_VERIFY=1 git clone https://github.com/ggml-org/llama.cpp /opt/llama.cpp.new
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn gradio
export HF_ENDPOINT=https://hf-mirror.com   # for huggingface-cli
```

---

## 1. Build llama.cpp with ROCm

```bash
GIT_SSL_NO_VERIFY=1 git clone https://github.com/ggml-org/llama.cpp /opt/llama.cpp.new
cd /opt/llama.cpp.new
HIPCXX="$(hipconfig -l)/clang" HIP_PATH="$(hipconfig -R)" \
  cmake -S . -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100 -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

Binary lands at `/opt/llama.cpp.new/build/bin/llama-server`.

---

## 2. The LoRA converter problem (the part that eats a day)

`--lora` only accepts **GGUF**. Three of the four experts ship as peft/safetensors
and must be converted. Two of them fail on stock llama.cpp — including the very
latest master:

```
NotImplementedError
  convert_lora_to_gguf.py -> LoraTorchTensor.reshape (line ~153)
  via TextModel._reorder_v_heads
```

**Root cause:** Qwen3.6 uses merged QKV projections. `_reorder_v_heads()` reshapes
the V slice, but a LoRA tensor is a lazy `LoraTorchTensor` (B@A pair) that cannot
be reshaped that way. Upstream fix is PR #24627 — **still unmerged**. Upgrading
llama.cpp does NOT solve this; that was verified and ruled out.

Why `cybersec` was never affected: it ships a prebuilt GGUF on HF and only touches
standard layers.

**Apply the patch:**

```bash
python3 deploy/w7900/patch_lora_converter.py /opt/llama.cpp.new/convert_lora_to_gguf.py
```

Idempotent, writes a `.orig` backup, and refuses to run if upstream moved the
anchor (in which case re-derive before proceeding).

---

## 3. Produce the three adapters

Layout is load-bearing: **the adapter key llama.cpp reports is the parent
directory name**, and the router matches it against `skill_map`. Use
`loras/<logical_name>/adapter.gguf`. A path like `loras/cybersec/GGUF/foo.gguf`
registers as adapter `"GGUF"` and silently never activates — degrading to base
with no error anywhere.

```bash
cd /opt/llama.cpp.new
BASE=/workspace/persistent/screwshell_run/models/Qwen3.6-27B-hf   # HF config dir
OUT=/workspace/persistent/screwshell_run/loras

# btl3  <- badtheorylabs/BTL-3               -> 446 M, 992 tensors
python3 convert_lora_to_gguf.py --base "$BASE" --outtype f16 \
  --outfile "$OUT/btl3/adapter.gguf" /path/to/badtheorylabs_BTL-3

# rag_n7 <- lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7 -> 1.8 G, 992 tensors
python3 convert_lora_to_gguf.py --base "$BASE" --outtype f16 \
  --outfile "$OUT/rag_n7/adapter.gguf" /path/to/rag_n7_lora

# cybersec <- prebuilt GGUF on HF, just place it correctly -> 153 M
#   hotdogs/qwen3.6-27b-cybersecurity-lora : GGUF/qwen36-27B-cyber-sft-v2-lora.gguf
mv qwen36-27B-cyber-sft-v2-lora.gguf "$OUT/cybersec/adapter.gguf"
```

`teichai_fable5_plan` has **no source weights anywhere** — `dl.sh` fetches only
three, and the skillpack contains a manifest only. The agent expert degrades to
base until weights are supplied. This is a data gap, not a bug.

---

## 4. Start

```bash
cp deploy/w7900/run_roomy_server.sh /workspace/persistent/screwshell_run/
nohup bash /workspace/persistent/screwshell_run/run_roomy_server.sh > llama_server.log 2>&1 &

MOL_BACKEND=llamacpp nohup /opt/venv/bin/python -m screwshell.ui.app \
  --workspace /workspace/persistent/screwshell_run/demo_workspace \
  --base /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
  --port 7860 --no-ra > ui.log 2>&1 &
```

Expected UI log line:

```
llama.cpp backend ready; server=http://127.0.0.1:8080; preloaded=['btl3', 'cybersec', 'rag_n7']
```

---

## 5. Verify — and verify *properly*

Listing adapters only proves they loaded, not that they do anything. A broken
adapter loads fine and changes nothing. Use a **deterministic** A/B:

```bash
curl -s http://127.0.0.1:8080/lora-adapters   # keys must be btl3 / cybersec / rag_n7
```

Then, with `seed=42, temperature=0`, run the same prompt twice — once with all
scales at 0, once with one adapter at 1.0. Identical output means the adapter is
inert. Observed on this box:

- all-off  → `# Secure Password Hashing ... Use bcrypt`
- cybersec → `Here's a thinking process ...`

Different ⇒ **LoRA genuinely effective**, not silently dead.

**Reset scales to 0 when done testing.** A leftover `scale: 1.0` stays globally
active and contaminates every subsequent base / other-expert call:

```bash
curl -s -X POST http://127.0.0.1:8080/lora-adapters -H 'Content-Type: application/json' \
  -d '[{"id":0,"scale":0.0},{"id":1,"scale":0.0},{"id":2,"scale":0.0}]'
```

---

## 6. Gateway mode (llama-swap, peers)

ScrewShell can sit behind llama-swap (`:18080`) instead of talking to llama-server
(`:8080`) directly. The gateway proxies the existing server — it does **not** own
the llama-server lifecycle in peers mode (that is the unadopted managed mode; see
`HANDOFF_GATEWAY_POC.md` §9.2, which found managed-mode streaming broken in
llama-swap v246).

**Why bother:** API-key auth, request correlation ids, clean model alias, and a
unified `/logs` `/metrics` surface. The ScrewShell side of this is the thin adapter
in `screwshell/core/mol_engine_llamacpp.py` (P1): it injects `Authorization`,
`X-Request-Id`, `X-Run-Id`, and resolves the gateway model id. None of this rewrites
messages/tools/SSE.

**Start the gateway** (the production llama-server on :8080 must already be up):

```bash
setsid /opt/llama-swap/llama-swap \
  --config /opt/llama-swap/poc/ls_phase2.yaml \
  --listen 127.0.0.1:18080 > /opt/llama-swap/poc/ls_phase2.log 2>&1 < /dev/null &
```

**Start the UI through the gateway** (env contract, see `run_ui_gw.sh`):

```bash
MOL_BACKEND=llamacpp \
MOL_LLAMACPP_URL=http://127.0.0.1:18080 \
MOL_LLAMACPP_API_KEY=screwshell-poc \
MOL_LLAMACPP_MODEL='roomy//workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf' \
nohup /opt/venv/bin/python -m screwshell.ui.app \
  --workspace /workspace/persistent/screwshell_run/demo_workspace \
  --base /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
  --port 7860 --no-rag > ui.log 2>&1 &
```

| Env | Meaning | Default |
|---|---|---|
| `MOL_LLAMACPP_URL` | engine endpoint | `http://127.0.0.1:8080` (direct) |
| `MOL_LLAMACPP_API_KEY` | bearer token sent to gateway (empty = none) | `` |
| `MOL_LLAMACPP_MODEL` | gateway model id; peers mode needs the full GGUF path, not `m` | `m` |

> `screwshell-poc` is the **POC** key baked into the gateway config — rotate and
> move to a secret store before any non-POC use.

**Verify the gateway path:**

```bash
curl -s -H 'Authorization: Bearer screwshell-poc' http://127.0.0.1:18080/v1/models
# -> id "roomy//workspace/.../Qwen3.6-27B-Q4_K_M.gguf", type=peer
```

Rollback to direct mode: unset the three `MOL_LLAMACPP_*` vars (or use the
un-gateway `run_ui.sh`) and point the UI at `:8080`.

---

## Failure modes seen, and their tells

| Symptom | Cause | Fix |
|---|---|---|
| `Permission denied (publickey)` | local pubkey not whitelisted | append `~/.ssh/id_ed25519.pub` to server `authorized_keys` |
| Startup fails, paths missing | doc drift: `/persistent/...` vs real `/workspace/persistent/screwshell_run` | use this runbook |
| `NotImplementedError` in convert | Qwen3.6 merged QKV + unmerged PR #24627 | §2 patch |
| Only the last adapter mounted | repeated `--lora` is deprecated | one comma-separated `--lora` |
| Adapter named `GGUF`, never activates | `.gguf` nested one level too deep | `loras/<name>/adapter.gguf` |
| Output identical with/without LoRA | adapter inert, or scales never set | §5 deterministic A/B |
| Base answers where an expert was expected | leftover `scale: 1.0`, or teichai missing | reset scales; teichai has no weights |

---

## Standing lesson

The converter patch previously existed **only on the instance**. Wiping the
instance destroyed it, and the knowledge survived only in
`docs/_archive/PATH_D_HANDOFF.md` — recovered by luck. Anything that has to be
true for a deploy to work belongs in the repo, not in a running box. Hence
`deploy/w7900/`.
