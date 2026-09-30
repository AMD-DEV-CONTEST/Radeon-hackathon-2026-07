# Caprigo on AMD — ROCm Delta Benchmark Results

**Credit:** b_Radford · Vibes-Coded · [caprigoai.com](https://caprigoai.com)  
**Track:** Track 2 — Agentic AI · Hackathon 2026-08  
**Cloud:** measured on `u-14549-080f238e` · **destroyed after capture**  
**Scrap re-confirm:** RX 580 Vulkan Ollama · 2026-08-04 (post-reboot)

---

## Headline delta (matched method · ~7B class)

Same user prompt (“Write a short paragraph about AMD ROCm GPUs.”), **128** completion tokens, **temperature=0**, model **already loaded**:

| | Scrap RX 580 · Ollama · Vulkan | ROCm · gfx1100 · vLLM |
|--|--------------------------------|------------------------|
| Model | `qwen2.5-coder:7b` | `Qwen/Qwen2.5-7B-Instruct` |
| tok/s | **13.73** wall · **14.34** eval | **29.21** wall |
| Uplift | | **~2.1×** (29.21 / 13.73) |

Supporting lived-proof (separate workload): 7B Q4 @32k ≈ **19** tok/s on scrap ([rx580-vulkan-agents](https://github.com/doteyeso-ops/rx580-vulkan-agents)).  
ROCm vs that headline remains ~**1.5×**; vs **same-day matched prompt** ≈ **2.1×**.

CSV: [`artifacts/delta.csv`](../artifacts/delta.csv) · Log: [`MEASUREMENT_LOG.md`](MEASUREMENT_LOG.md)

---

## 1. Scrap baseline (RX 580 Polaris — Vulkan)

| Workload | Result |
|----------|--------|
| Matched prompt · 7B warm (2026-08-04) | **14.34** eval tok/s · **13.73** wall tok/s |
| 3B coder (`b_Radford-coder-3b-128k`) | **22.68** eval tok/s (swap load excluded from eval) |
| Lived proof 7B Q4 @32k | **~19** tok/s · ~5.1 GB VRAM |
| Caprigo Session lean | **~31 s** OK · 17 tools (`artifacts/bench-agent-delta.csv`) |

Ollama confirmed **Vulkan0 · Radeon RX 580 Series** after reboot.

Demo: https://github.com/doteyeso-ops/caprigo/blob/main/docs/demo/Caprigo_AMD_Demo.mp4

---

## 2. ROCm Radeon Cloud (2026-08-04)

| Property | Value |
|----------|-------|
| GPU | gfx1100 · DID `0x744b` |
| Image | `vllm-dev:rocm7.2.1_navi…vllm_0.16.0` |
| 7B load | 14.37 GiB · ~165 s |
| Timed chat | 128 tok / 4.382 s → **29.21** tok/s |

Also: 0.5B smoke **215** tok/s (path proof).

---

## 3. Caprigo / Track 2 optimization hooks

- **`CAPRIGO_LEAN_TOOLS=1`** — ~170 → ~17 schemas (scrap Session evidence attached).
- Backend-agnostic gateway — Ollama or vLLM OpenAI URL.
- Repeatable scripts: scrap Ollama generate · `scripts/measure_vllm_toks.py` on ROCm.

---

## 4. Reproduce

**Scrap (this lab):** Ollama Vulkan · warm `qwen2.5-coder:7b` · `num_predict=128` · same prompt.  
**ROCm:** see `REPRODUCTION_README.md` · `measure_vllm_toks.py`.

— b_Radford / Vibes-Coded · Aug 6, 2026 8:59 AM PDT deadline
