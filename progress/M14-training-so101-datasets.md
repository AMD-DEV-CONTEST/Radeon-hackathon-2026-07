# M14 — Training 支持直接选择 Step4 的 so101 数据集

日期: 2026-04-21

## 背景

当前 Training 页的数据集下拉来源是 realtime 的 `/api/datasets`。
历史实现只扫描 `apps/realtime/datasets/recording_*`，因此用户在 Step4
通过 `lerobot-record` 录出来的 `botversex/so101-*`（实际落在
`~/.cache/huggingface/lerobot/botversex/`）看不到，也无法直接选中训练。

这会造成两个问题：

1. UI 认知错位：页面显示一堆 `recording_*`，用户真正可用的数据却是
   `so101-*`。
2. 训练路径断裂：即使前端传了 `owner/name` 风格 dataset id，后端训练
   仍只按 `apps/realtime/datasets/<id>` 拼路径，导致找不到目录。

## 本次变更

### 1) Realtime `/api/datasets` 合并两类数据源

文件: `apps/realtime/api/datasets.py`

- 保留旧源：`apps/realtime/datasets/recording_*`（botclaw + parquet）。
- 新增 LeRobot v3 源：扫描 `$HF_HOME/lerobot/<owner>/<name>/`，
  识别 `meta/info.json` + `data/**/*.parquet`。
- 对 LeRobot 目录输出统一摘要，关键字段：
  - `dataset_id = "<owner>/<name>"`（例如 `botversex/so101-20260422_0302`）
  - `source = "lerobot_hf_cache"`
  - `frame_count/fps_nominal/duration_s` 从 `meta/info.json` 推导。
- 两源合并后按时间倒序返回，Training 下拉可直接看到 `so101-*`。
- `GET /api/datasets/{dataset_id}` 改为 `{dataset_id:path}`，支持带 `/`
  的 HF 风格 id。
- 保持图片子路由优先注册，避免被 catch-all 路由吞掉。

### 2) API 训练入口支持解析 `owner/name`

文件:

- `apps/api/app/services/dataset_service.py`
- `apps/api/app/services/trainer.py`
- `apps/api/app/api/v1/endpoints/datasets.py`

改动点：

- 新增 `get_lerobot_cache_root()` 与 `resolve_dataset_dir(dataset_id)`：
  - `recording_*` -> `apps/realtime/datasets/<id>`
  - `owner/name` -> `$HF_HOME/lerobot/<owner>/<name>`
- 训练执行入口改用 `resolve_dataset_dir(...)`，不再仅依赖单一 storage root。
- datasets endpoint 的懒 upsert 同样改用 resolver，兼容 `owner/name`。

## 验证

本机扫描结果已命中并可解析以下数据集（示例）：

- `botversex/so101-20260422_0302`
- `botversex/so101-20260422_0237`
- `botversex/so101-20260422_0128`
- `botversex/so101-20260422_0059`
- `botversex/so101-20260422_0002`

并验证 resolver 能正确返回两类目录：

- HF cache: `botversex/so101-*`
- legacy: `recording_*`

## 影响与后续

- 用户可在 Training 页下拉中直接选择 Step4 真实录制的 `so101-*`。
- 选中后提交训练任务时，后端能正确定位目录，不再报 dataset path not found。
- 下一步建议：
  - 重启 realtime 与 api 服务并刷新 Training 页面确认 UI 已更新。
  - 先跑一次小规模任务（1~2 epoch）验证端到端训练提交流程。
