# Running Determinex

The complete working source, shipped here rather than only linked. 1,545 Python modules and
471 test files.

## Check it works before you install anything

```bash
cd ..            # the submission directory
bash verify.sh
```

About two seconds, no GPU, no network, no API key. It proves the oracle rejects broken code as
well as accepting correct code, that a request too vague to verify is refused before a model
is called, and that the shipped reference implementations are exact across all 256 inputs of
their domain.

```bash
bash verify.sh --selftest
```

Breaks each of those checks on purpose and requires every one to turn the run red. A green
suite is evidence only if it could have been red.

## Environment

Python 3.11 or newer.

```bash
pip install -r requirements.txt
```

For inference-only use, `pip install -r scripts/requirements.txt` is smaller.

## Run the tests

```bash
python -m pytest tests/ -q
```

## Serve a model on the Radeon

```bash
# On a Radeon Cloud instance, ROCm 7.2.1
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --max-model-len 4096
```

Do not pass `--enforce-eager`: it disables HIP graph capture and measured ~8 tok/s against
~32 tok/s on identical hardware.

## Reproduce the measurements

```bash
python scripts/determinex_calibrate.py          # sweeps the machine, derives K from what it measures
python ../demo_run.sh                           # the full demo, ~4 minutes
```

## Build something, verified

```bash
python scripts/determinex_build_from_idea.py --idea ../idea.md
```

Synthesises an oracle from the idea, generates against it, and returns a program only if the
oracle passed. If no sound oracle can be built from the description, it refuses and says why —
that refusal is the feature, not a failure.

## The pieces, if you would rather read than run

| Module | Lines | What it does |
|---|---:|---|
| `scripts/determinex_oracle.py` | 2,139 | ground-truth oracle registry; an oracle never silently passes |
| `scripts/determinex_corpus_api.py` | 1,263 | local retrieval over the corpus built from its own verified solves |
| `scripts/determinex_calibrate.py` | 774 | sweeps the machine and derives K from measured throughput |
| `scripts/determinex_hive.py` | 722 | orchestrator: plan, build, verify, retry on failure |
| `scripts/determinex_synthesize.py` | 635 | turns an idea into a sound oracle, or refuses |
| `scripts/determinex_verified_search.py` | 616 | best-of-K against the oracle — the code behind the GPU claim |
| `scripts/determinex_case_memory.py` | 139 | verified-only memory; a failed case never enters |
| `scripts/determinex_decompose.py` | 128 | multi-step task planning |

## The data and models this was built from

Both are published, not described:

- **Corpus** — [`LunarianData/determinex-corpus`](https://huggingface.co/datasets/LunarianData/determinex-corpus).
  The knowledge layer the retrieval reads: pinned upstream commits, per-tool build recipes,
  `build_knowledge.json`, and the verdict corpus every oracle-verified solve is distilled into.
  Trees whose license text could not be recovered from their pinned commit are withheld and
  listed with the reason — redistribution is redistribution regardless of host.
- **Models** — [`LunarianData/determinex-model-archive`](https://huggingface.co/LunarianData/determinex-model-archive).
  The LoRA-distilled generations: a 1.5B Builder, a 3B Monitor, a 7B Architect.

Neither is required to run the verification above, which is the point — the checks stand on
their own without downloading anything.
