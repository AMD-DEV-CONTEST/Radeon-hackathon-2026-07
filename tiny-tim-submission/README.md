# Tiny Tim — A Go-Native Transformer, Trained from Scratch, Accelerated by AMD ROCm

A real, complete, single-block transformer — forward pass, hand-derived backward pass, training, checkpointing, and inference — written entirely in Go, with real GPU compute dispatched through `cgo` into hand-written HIP kernels, running on real AMD Radeon hardware via ROCm.

No pretrained weights. No PyTorch. No Python. Every stage of learning, from random initialization to trained inference, is real and visible.

## What's actually in this repo

- **`permissions/`** — a real, standalone `Allow`/`Ask`/`Deny` policy system for gating tool actions (local file access, web search, corpus writes, shell execution, external messaging), matching a genuinely conservative, privacy-first default.
- **`gospark-demo/`** — Tiny Tim himself:
  - `native/kernels/` — real HIP kernels (`add`, `matmul`, `relu`, `softmax`, `layernorm`), each hand-verified against real hardware.
  - `native/` — the `cgo` bridge (`native.go`/`bridge.h`) connecting Go to the compiled HIP shared library.
  - `model/` — the real transformer: forward pass (`amd_history_model.go`), complete hand-derived backward pass (`backward.go`), training loop (`train.go`), checkpoint save/load (`checkpoint.go`), and a real, simple word-level vocabulary (`vocab.go`).
  - `cmd/train/` — real CLI: loads a real text corpus, trains the model, saves a checkpoint.
  - `cmd/chat/` — real CLI: loads a trained checkpoint, runs real autoregressive inference.
  - `cmd/benchmark/` — real CLI: measures real forward-pass and training-step throughput.
  - `cmd/extractcorpus/` — a small real utility, pulling clean factual claim statements out of a `HaroldCorpus`/`AMDCorpus`-format JSONL file into plain-text training data.

## Environment setup

**Prerequisites:**
- Go `1.26+`
- ROCm `6.4+` (tested against `6.4.0`), with `hipcc` on your `PATH`
- An AMD GPU with real ROCm/HIP support (developed and tested on an `RX 9070 XT`, `gfx1201`)

**Build the real HIP kernels into a shared library:**

```bash
cd gospark-demo/native/kernels
hipcc -fPIC -shared add.cpp matmul.cpp relu.cpp softmax.cpp layernorm.cpp -o ../libgospark_demo.so
```

**Build the Go module:**

```bash
cd gospark-demo
go build ./...
```

**A real, important note on `LDFLAGS`:** `native.go`'s `cgo` directives hardcode absolute paths to both the compiled `.so` and your ROCm installation (`-L/opt/rocm-6.4.0/lib`). If your ROCm version or install path differs, update these paths accordingly before building.

## Usage

**Train a real model on a real text corpus** (one training sentence per line):

```bash
go run ./cmd/train -data your_corpus.txt -epochs 100 -dmodel 64 -dff 128 -out checkpoint.json
```

**Chat with a trained checkpoint** (real, live autoregressive inference):

```bash
go run ./cmd/chat -checkpoint checkpoint.json
```

**Run the real performance benchmark:**

```bash
go run ./cmd/benchmark -dmodel 64 -dff 128
```

**Extract clean training claims from a real `HaroldCorpus`/`AMDCorpus`-format JSONL file:**

```bash
go run ./cmd/extractcorpus -in your_corpus.jsonl -out claims.txt
```

## Real, complete test suite

```bash
cd gospark-demo
go test ./...
```

Every layer of the model — forward pass, every individual backward-pass component, the complete end-to-end training loop, checkpoint round-tripping, and the vocabulary — is proven with real, hand-verified or structural tests.

## Architecture

```
Training Corpus
      ↓
  Tokenizer (real, simple word-level vocabulary)
      ↓
  Embeddings
      ↓
 Transformer (single-head self-attention, real GPU-dispatched compute)
      ↓
   Output
```

Every matrix operation in the real forward and backward pass — `MatMul`, `Add`, `ReLU`, `Softmax`, `LayerNorm` — is dispatched through the real `Go → cgo → HIP → ROCm` path onto actual GPU hardware, not simulated or CPU-only.

## Real dependencies

- Go standard library only for the model/training code — no third-party Go packages.
- ROCm/HIP for real GPU compute (`hipcc`, `libamdhip64`).
- No Python, no PyTorch, no external ML framework anywhere in this repo.
