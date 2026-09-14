# Data contract

训练数据没有在本目录重复一份。本地正式数据位于：

```text
/Users/d-robotics/project_robo/amd-rl/data-gen/data/releases/rdk-sft-v1-20260803/agentic
```

正式远端布局为：

```text
/workspace/qwen36-agentic-sft/data/rdk-sft-v1-20260803-agentic
```

| Split | Rows | SHA256 |
|---|---:|---|
| train | 946 | `707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58` |
| validation | 116 | `d4bbc65d196e0e073e75f275dd06b21727259c333046412f18a14b1ee1db666f` |
| test | 113 | `d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283` |

Trainer 只读取 `train.jsonl` 和 `validation.jsonl`。`test.jsonl` 的摘要存在于冻结计划中，但测试原文与标签不会被正式 trainer 读取；Test 只用于训练后的 held-out 评测。

