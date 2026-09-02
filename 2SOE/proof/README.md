# Benchmark results

Raw output of `scripts/benchmark.py`, reproducible with the commands in the main
README, section 5. Each file lists the 20 cases, their stability verdict, their
correctness score and per-case timings.

The bench judges itself: the core already emits the signals it checks — RAG
status, domain, abstention reason, article presence, document produced. No human
annotation is involved, and no case is scored on the model's prose.

---

> **A 40-second unedited capture of the W7900 runs** — hardware, environment
> and both benchmarks — is available at https://youtu.be/meM1-1A_l4w
> It also shows the 91 % run described at the bottom of this page.

## What each file proves

| File | Mode | Hardware | Correctness | Time |
|---|---|---|---|---|
| `r9700-sequential.json` | sequential | 2× Radeon AI PRO R9700, gfx1201, TP=2, Docker | **100 %** (20/20) | 3m10 |
| `r9700-parallel6.json` | 6 concurrent | same | **100 %** (20/20) | 0m45 |
| `w7900-sequential.json` | sequential | 1× Radeon PRO W7900, gfx1100, TP=1, **no Docker** | **100 %** (20/20) | 7m46 |
| `w7900-parallel6.json` | 6 concurrent | same | **100 %** (20/20) | 1m50 |
| `w7900-missing-libreoffice.json` | sequential | same, **missing dependency** | 91 % (17/20) | 7m42 |

---

## Three things these runs establish

### 1. Correctness does not move — form does

Across two GPU architectures, two GPU counts, two deployment modes and five runs
of the reference model, **correctness is 100 % every time**. What varies is the
stability verdict: 14 to 18 identical runs out of 20, the rest being rewordings
that say the same thing.

That separation is deliberate. A `CONTRADICTORY` verdict is not a defect in
itself — some legal questions admit several correct answers (a landlord's notice
period differs for repossession, sale or location), so two runs may foreground
different facets and both be right. Stability and correctness are therefore
scored on two independent axes.

### 2. The package is portable, and it was verified the hard way

The W7900 runs were produced on a **freshly provisioned cloud instance**, from a
`git clone` of this very repository. Nothing was carried over from the
development machine.

```
different GPU architecture     gfx1100 instead of gfx1201
half the GPUs                  TP=1 instead of TP=2
no Docker daemon               every service started natively
no path variable set           only service URLs and credentials
```

Data paths are anchored on each file's own location, so the package follows the
repository wherever it is cloned. The generated PDF came out under
`relay/framework/primitives/../../out/` — a relative path, on a machine that
shares nothing with the development host.

Concurrency gives a **4.2× speed-up on a single GPU** with no loss of
correctness and no cross-session leakage — the same ratio observed on the
two-GPU machine.

### 3. Reliability comes from governance, not from parameter count

The same suite was run against a **20-billion parameter model** on the same core,
the same corpus and the same workflow. Each model receives its own security socle
(the `modele_cible` field in Qdrant), so the comparison is made on equal terms.

```
Mistral 7B     100 %   3m10
gpt-oss 20B     94 %   7m35
```

Three times the parameters, twice the wall-clock time, two cases missed — both on
the same article (`L145-4`, commercial leases), reproducibly across runs. Swapping
the model is a one-line change in `.env`; the guarantees do not move with it.

*(Raw output for that run is not included here — reproduce it by setting
`VLLM_MODEL` and re-running the suite.)*

---

## The 91 % run is included on purpose

`w7900-missing-libreoffice.json` was produced before installing LibreOffice on
the cloud instance. Two cases require a generated document; both failed with
`acte=False`.

The core's own error message names the missing dependency:

> `RuntimeError: LibreOffice (soffice) absent du container : conversion PDF
> impossible. Installer libreoffice-writer-nogui dans l'image du relay.`

**The system did not produce a half-finished document and call it done.** It
stopped, and said what to install. Once the dependency was present, the same
suite returned 100 % — see `w7900-sequential.json`.

This file is published because a submission that only shows its best runs
invites the question of what the others looked like.

---

## One difference to be explicit about

On the cloud platform, **TEI could not be installed**: its release binaries are
unreachable from that network and it is not published on PyPI. It was replaced
by a minimal `sentence-transformers` server exposing the same `POST /embed`
endpoint with the same **BGE-M3** model and the same 1024-dimension output.

The embeddings are BGE-M3 either way; the serving implementation differs. The
R9700 runs use the real TEI container.

---

## Reproducing

```bash
export EXEC_TOKEN=$(grep '^EXEC_TOKEN=' .env | cut -d= -f2)
python3 scripts/benchmark.py lancer my-run 0     # sequential
python3 scripts/benchmark.py lancer my-run 6     # 6 concurrent
```

Cases and expected facts are in `data-seed/benchmark_cas.json` — shipped with
this repository, so the scoring can be inspected rather than trusted.

*Runs dated 2026-07-27 (R9700) and 2026-07-28 (W7900).*
