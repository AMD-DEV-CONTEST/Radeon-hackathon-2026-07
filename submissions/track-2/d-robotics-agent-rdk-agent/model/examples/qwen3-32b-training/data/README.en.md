> Chinese version: [README.md](README.md)

# Data Contract

The training data is not duplicated in this directory. The canonical local data is located at:

```text
/Users/d-robotics/project_robo/amd-rl/data-gen/data/releases/rdk-sft-v1-20260803/agentic
```

The canonical remote layout is:

```text
/workspace/qwen36-agentic-sft/data/rdk-sft-v1-20260803-agentic
```

| Split | Rows | SHA256 |
|---|---:|---|
| train | 946 | `707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58` |
| validation | 116 | `d4bbc65d196e0e073e75f275dd06b21727259c333046412f18a14b1ee1db666f` |
| test | 113 | `d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283` |

The trainer reads only `train.jsonl` and `validation.jsonl`. A digest of `test.jsonl` is present in the frozen plan, but the canonical trainer does not read the Test text or labels. The Test is used only for held-out evaluation after training.
