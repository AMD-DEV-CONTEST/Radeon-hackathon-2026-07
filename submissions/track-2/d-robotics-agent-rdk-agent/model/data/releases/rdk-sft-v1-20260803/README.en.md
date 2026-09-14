> Chinese version: [README.md](README.md)

# rdk-sft-v1-20260803 (compact repository edition)

Original frozen hashes for the three agentic splits in the official `rdk-sft-v1-20260803` release:

| File | Lines | SHA-256 (original frozen artifact) | This repository |
|---|---:|---|---|
| agentic/train.jsonl | 946 | `707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58` | Removed; see below |
| agentic/validation.jsonl | 116 | `d4bbc65d196e0e073e75f275dd06b21727259c333046412f18a14b1ee1db666f` | Removed; see below |
| agentic/test.jsonl | 113 | `d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283` | **Retained** |

**Public train/validation access**: [ModelScope · ming01/RDK-Agentic-SFT-Sanitized-v1](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/files). Note that the public edition has been **privacy-sanitized** and therefore differs byte-for-byte from the frozen originals listed above (platform-side SHA: train `40522e4e…`, validation `68ac3053…`). The frozen originals remain in the project source directory `data-gen/data/releases/`; use the hashes in the table above if byte-for-byte verification is required.

**Why test.jsonl is public in this repository**: It was historically held out during the original evaluation and was not used for training. It was released after evaluation so judges can independently rescore the Base/SFT raw outputs with `benchmark/`. It remains excluded from the ModelScope train/validation dataset, but now that it is public, it must not be reused as a clean future evaluation set.

`schema/rdk_sft_sample.v1.schema.json` is byte-for-byte identical to the schema in the public dataset (`19854de1…`). See [`RELEASE_README.orig.en.md`](RELEASE_README.orig.en.md) for the dataset composition, promoted-sample markers, and rollback procedure.
