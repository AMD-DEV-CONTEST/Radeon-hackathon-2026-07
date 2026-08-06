# MagicBox 数据管线示例包（小而完整，可离线复现）

这是 `data-gen` 数据采集/导出闭环的公开示例包：用**冻结的小型输入**驱动**与正式产线完全相同的导出与校验代码**，产出**逐字节可复现**的 SFT 样本。不联网、不连开发板、不调用教师模型。

```bash
npm run check
```

一条命令依次完成：

1. 从 `fixtures/` 重新生成 QA 三 split 与 Agentic 样本（`out/`）；
2. 独立复验：JSON Schema、tool-call/result 因果链、唯一 task_id、semantic group 的 split 隔离；
3. 与 `expected/` 逐字节比对，证明确定性；
4. 运行单元与负向测试（篡改快照、缺失板端证据、孤立 tool result、注入密钥都必须 fail-closed）；
5. 全树 secret / 本地路径扫描。

依赖：Node >= 22.19，Python 3 + `pip install -r requirements.txt`（仅 jsonschema）。

## 目录

```text
schemas/     rdk_collection_task.v1 / rdk_collection_record.v1 / rdk_sft_sample.v1（与产线逐字节一致）
scripts/     export_qa_dataset.mjs、validate_dataset.py、validate_native_pi_dataset.py（产线原件）
             + export_agentic_fixture.mjs、check.mjs、scan_tree.py、python.sh（本示例新增）
src/         native_pi_export.mjs（产线原件：native Pi 轨迹 -> rdk_sft_sample.v1）
fixtures/    3 条真实 QA 任务 + 微型冻结知识快照 + 1 条合成 native Pi 轨迹
expected/    上述输入的钦定输出（train/validation/test、manifest、审计报告）
gallery/     4 条脱敏实物展示：eligible / needs-review / rejected / synthetic repair 各 1 条
test/        产线单测原件 + 本示例负向测试
source-manifest.json  每个文件的来源、SHA-256、筛选规则与脱敏变换
```

## 数据流

```text
3 条 QA task + 微型知识快照 ──> QA exporter ──┐
                                              ├──> rdk_sft_sample.v1
1 条合成 native Pi trace ──> Agentic exporter ─┘
        └──> Schema / 因果 / secret 校验 ──> train/validation/test + manifest + audit
```

## “完整跑通”的准确边界

`npm run check` 证明的是**离线 fixture/replay -> 导出 -> 校验 -> 报告**这条闭环，以及它对坏输入的 fail-closed 行为。它**不**代表重新调用了教师模型、连接了真实开发板或验证了物理效果；真实采集轨迹与全量数据集见仓库根 README 指向的源目录与 `data/releases/`。

- `expected/qa/test.jsonl` 只是格式样例，不冒充任何隐藏评测集。
- `fixtures/native_pi_trace.fixture.json` 是合成轨迹：结构与真实 `before_provider_request` 捕获一致，但主机、证据路径均为占位符。
- `gallery/` 中标注 `sanitized` 的行把本地绝对项目根替换为 `/srv/rdk-data-gen`；原行的 SHA-256 记录在 `source-manifest.json`，可回源核对。
