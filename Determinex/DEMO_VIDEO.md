# Demo Video

**Link:** _(to be added — YouTube/Drive, unlisted is fine)_

**Runtime target:** 4 minutes.

---

## Shot list

Every command below is real and was executed on the Radeon instance on 2026-07-31. Nothing
here is a mock-up; the numbers on screen should be the numbers in `PROJECT_SPEC.md`.

### 0:00–0:30 — The AMD GPU is real

Show the Radeon Cloud instance page: `1 GPU`, image
`amd-oneclick-base:rocm7.2.1-py3.12-v20260416`, status Ready. Then the server's own
telemetry, which is stronger evidence than a dashboard screenshot:

```bash
curl -s "$ROOT/metrics" -H "Authorization: Bearer $AMD_API_KEY" | grep cache_config_info
```

Point at `num_gpu_blocks="31504"` and say the line out loud: *31,504 KV blocks is 26.9 GiB
of KV cache on the Radeon, plus 14 GiB of weights — about 46 GiB of device memory.*

### 0:30–1:15 — The thesis, on one slide

> Determinex never lets a model judge its own work. A compiler or a real test suite is the
> only oracle. That means accuracy comes from *sampling K candidates and verifying each* —
> `P = 1 − (1 − p)^K` — so the system's correctness is bounded by **GPU batch throughput**,
> not by model quality.

### 1:15–2:00 — The measurement that matters

Run the benchmark live (it takes ~35 s, so start it and talk over it):

```bash
python amd_bench.py 6
```

Land on the result:

```
single stream          : 512 tok in 17.05s = 30.0 tok/s
K=6 concurrent         : 3072 tok in 18.41s = 166.9 tok/s aggregate
aggregate speedup      : 5.56x
```

Say the punchline plainly: **6 candidates cost 8% more wall clock than 1.** At p=0.3 that
takes the solve rate from 30% to 88.2% for an 8% time premium.

### 2:00–3:15 — The bug the AMD run exposed *(the strongest 75 seconds — do not cut)*

Show the first run's output:

```
result: not solved  samples=12
[vs] r1 s1/6 t=0.0 gen 9s verify 1s -> 1 fail (score 0.00)     (×12)
```

Then show one of the rejected candidates and let it sit on screen — it is *correct* RLE.

Explain: every candidate was right, wrapped in a ```` ```python ```` fence that the
harness's own prompt demands. Fence-stripping lived inside the Ollama generator only, so
Ollama worked and every other provider fed markdown to the oracle, where the module failed
to import. The system reported a verdict about a model that had been right twelve times.

Then the same command after the one-line fix:

```
result: SOLVED  samples=1
proof: program PASSES all 4 synthesized checks (oracle-verified, 1 samples).
```

Close it with the general rule, because that is the transferable part:

> A uniform 0.00 across every sample **and** every temperature is a harness signature, not a
> capability signature. A genuinely weak model fails in *varied* ways.

### 3:15–3:45 — It learned

Show that the finding is not just fixed but absorbed:

```bash
python scripts/determinex_corpus_api.py search "candidate scores 0.00 not solved fenced"
```

Top hit is `fenced_candidate_not_stripped`, with symptom, fix and proof. The next occurrence
gets this applied first-shot.

Then the guard, negative-controlled:

```bash
python -m pytest tests/test_generation_failure_is_not_a_verdict.py -q      # 31 passed
```

Mention that the *pre-existing* test already fed fenced code — and asserted only that no
generation error occurred, never that the build solved. That is how a green suite carried
the bug, and why the new tests assert outcomes.

### 3:45–4:00 — Close

```bash
python scripts/determinex_build_from_idea.py --idea idea.md --provider vllm --k 6
```

Idea in, oracle-verified program out, on AMD hardware, with no cloud vendor in the loop.
State the honest boundary on camera: ProgramBench is 0/200 under the methodology that
survived a provenance audit, and that zero is deliberate.

---

## Recording notes

- Redact the API key — it appears in `$AMD_API_KEY` and in any `curl` you paste. Use
  `-H "Authorization: Bearer $AMD_API_KEY"` with the variable, never the literal.
- The instance dies when credits run out; capture everything in one session.
- Terminal at a large font. Judges watch these small.
