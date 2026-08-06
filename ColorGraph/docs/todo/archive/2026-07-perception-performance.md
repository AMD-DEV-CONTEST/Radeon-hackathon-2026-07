# 2026-07 Archive — 感知正确性与性能

> [TODO 入口](../../TODO.md) · [任务目录](../README.md)
> 本文件归档 2 个已完成任务。

## 感知正确性

- [x] **CG-SEM-001 — 修正语义类别映射和置信度语义**
  - `earth` 不再直接并入 vegetation。
  - mountain、rock、cliff、land、sand 等映射可配置并单独报告。
  - 置信度不再冒充准确率；保存阈值和模型版本。
  - 完成标准：逐类报告可解释，水面/树梢/山体边界没有因 alias 扩大而恶化。
  - 验收证据（2026-07-30）：
    - `colorgraph.semantic-label-map/v2` 将 `earth/land`、`tree/grass/...`、`mountain/hill`、`rock/stone`、`cliff` 和 `sand` 分成互斥、可替换配置的 target；重复 alias 或会同时解析到多个 target 的模型复合标签会直接报错。
    - 真实固定 revision SegFormer-B0 标签审计确认 `earth` 只映射到 land class 13，tree 只映射到 vegetation class 4，mountain/hill 与 rock 分离；当前 checkpoint 没有 cliff/snow class 时显式记录 `model_class_missing`，不伪造零蒙版为高置信“未检测到”。
    - 兼容字段 `confidence` 的语义固定为“阈值以上像素的平均模型概率”，明确 `is_accuracy=false`；每项资产持久化 probability threshold、模型 ID/revision、class IDs/labels、映射版本与 SHA-256。
    - planner 的 mountain/rock/cliff/land/sand 目标词和默认节点参数也已分离；语义映射专项 `9 passed`，后端全量 `222 passed`，真实模型逐类报告见 `output/evidence/semantic-mapping-audit.json`。

## 性能

- [x] **CG-PERF-001 — 每帧只计算一次光流并 remap 全部 mask**
  - 将 flow estimation 与 mask warp 分离。
  - anchor 帧无需为随后被覆盖的结果重复计算传播。
  - 记录默认 5 target 的 CPU 时间、总 mask FPS 和输出差异。
  - 完成标准：输出在误差阈值内等价，光流计算次数从每 target 一次降为每帧一次。
  - 验收证据（2026-07-29）：flow estimation 已从 mask warp 中分离；非 shot-start 帧只计算一次 backward flow 后 remap 全部 target，shot-start anchor 不再计算随后会被覆盖的传播。
  - 4 帧双镜头测试中只在帧 1、3 调用 flow，共 `2` 次；5 target 的逐 target 基线与共享 flow 输出逐位一致（最大/平均绝对差均为 `0`）。
  - Windows/OpenCV 4.13、单线程、640×360、默认 5 target 实测：CPU 中位数从 `156.25 ms/frame` 降至 `31.25 ms/frame`，总 mask FPS 从 `32` 提升至 `160`，flow 调用从 `5` 降至 `1`；报告见 `output/evidence/shared-optical-flow-benchmark.json`。
