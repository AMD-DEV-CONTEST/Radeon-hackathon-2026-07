# rdk-sft-v1-20260803(本仓库精简版)

正式发布 `rdk-sft-v1-20260803` 的 agentic 三 split 原始冻结哈希:

| 文件 | 行数 | SHA-256(冻结原件) | 本仓库 |
|---|---:|---|---|
| agentic/train.jsonl | 946 | `707435c094badb91411ec09f88a473a158c5114c5cad1bc5cf151c047f4b9a58` | 已移除,见下 |
| agentic/validation.jsonl | 116 | `d4bbc65d196e0e073e75f275dd06b21727259c333046412f18a14b1ee1db666f` | 已移除,见下 |
| agentic/test.jsonl | 113 | `d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283` | **保留** |

**train/validation 的公开获取**:[ModelScope · ming01/RDK-Agentic-SFT-Sanitized-v1](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/files)。注意公开版经过**隐私脱敏**,与上表冻结原件字节不同(平台侧 SHA:train `40522e4e…`、validation `68ac3053…`);冻结原件保存在项目源目录 `data-gen/data/releases/`,如需逐字节复核以上表哈希为准。

**test.jsonl 为何随本仓库公开**:它在原始评测时 historically held out,没有进入训练;评测完成后公开,让评委可用 `benchmark/` 对 Base/SFT raw 独立重评分。它仍不进入 ModelScope 的 train/validation 数据集,但公开后不应再作为未来无污染评测集使用。

`schema/rdk_sft_sample.v1.schema.json` 与公开数据集中的 schema 逐字节一致(`19854de1…`)。数据构成、promoted 样本标记与回退方法见 `RELEASE_README.orig.md`。
