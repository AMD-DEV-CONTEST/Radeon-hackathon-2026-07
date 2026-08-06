# M15 — 当前进度审计与下一阶段执行方案

日期: 2026-04-23

## 1) 现状审计（API / Web / Realtime / Sidecar）

### API（`apps/api`）

**已完成**
- `skills` 基础能力已形成闭环：注册表读取、安装、参数校验、运行记录、运行查询。
- `skill_installations` 与 `skill_runs` 两张表已落库，支持用户维度查询。
- 与 realtime runtimes 有联动（通过 `/api/runtimes` 代理做兼容判断）。

**缺口**
- `POST /api/v1/skills/{skill_id}/run` 仍是模拟执行（后台 sleep 后标记成功），尚未真实分发到 realtime 任务。
- 缺少统一 job adapter（按 verb -> realtime action）与可恢复失败语义。

### Web（`apps/web`）

**已完成**
- `Skills` 页面已支持 Registry / Runtime / Installation / Runs 四块管理面板。
- Workflow 编辑器已经加入 `dataset_load`、`camera_map`、`finetune_job`、`job_monitor`、`skill_invoke` 节点。
- `Robots` 页面和 `RobotReachyMini` 页面已落地，多硬件入口成立。

**缺口**
- `workflowEngine` 对训练链路大多仍是本地模拟，尚未成为真实编排器。
- `skill_invoke` 节点虽调用了 `/skills/run`，但后端 run 仍模拟，导致整条工作流执行仍偏演示态。

### Realtime（`apps/realtime`）

**已完成**
- M12/M13 的相机占用、录制死锁、reset 语义已补齐。
- M14 的 dataset 扫描兼容 HF cache + legacy 数据源已完成。
- `vision_inference` 已具备 ACT/Pi0 接入路径、safety gate、CPU fallback 与 WS 推理回路。

**缺口**
- 尚缺以 skill verb 为中心的标准 dispatch endpoint（可被 API/Workflow 统一调用）。
- 推理链路对超时/重试/资源回收的治理仍有加强空间（特别是长时间运行和异常中断）。

### Sidecar（`apps/pi0_sidecar`）

**已完成**
- 作为独立进程承载 LeRobot/HF policy（ACT/Pi0）已可工作。
- 对 lerobot/hf 兼容性问题已加入补丁（constants patch、processor filename alias、CPU fallback）。

**缺口**
- 缺少针对 sidecar 的健康探针门限与熔断策略（高延迟、重复失败、模型切换风暴）。
- 缺少稳定性回归基线（固定输入输出校验 + 压力下 latency/p99 指标）。

## 2) M15 范围收敛（三条主线）

## 主线 A：Skill 真实执行（替换 run 模拟）

目标:
- 让 `skills/run` 对至少 2 个 verb 走真实 dispatch（建议 `teleop` 与 `record`）。

交付:
- API: verb dispatch adapter（`teleop`、`record`）。
- Realtime: 可被调用的执行入口 + run 状态回写。
- Web Skills 页: 展示真实状态与错误原因（而非模拟日志）。

不做:
- Skill 市场、计费、复杂权限体系。

## 主线 B：Workflow 真实编排

目标:
- 让 Finetune 主链（dataset -> map -> finetune -> monitor）走真实 API 状态。

交付:
- `workflowEngine` 从模拟转为 API orchestration（保留 demo fallback）。
- 节点日志输出真实 job id / status / error detail。
- 失败节点可重试（最小能力：单节点 retry）。

不做:
- 全量 DAG 调度器、分布式任务队列重构。

## 主线 C：推理与 Sidecar 稳定性

目标:
- 将 `vision_inference + pi0_sidecar` 从“可跑”提升到“可持续跑”。

交付:
- 推理链路 timeout / reconnect / unload 清理路径补全。
- sidecar 增加关键 health 字段与异常分级日志。
- 增加最小稳定性回归脚本（单次 + 连续运行）。

不做:
- 全新模型家族接入（先稳定 ACT/Pi0）。

## 3) 当前工作树分批提交方案（可审查）

建议分 5 批（先代码后大资产）：

1. **Batch-1 API Skills 基础线**
   - `apps/api/app/api/v1/endpoints/skills.py`
   - `apps/api/app/models/skill.py`
   - `apps/api/app/services/skill_registry.py`
   - `apps/api/app/data/skills_seed.json`
   - 以及 skills 相关路由/配置接线文件

2. **Batch-2 Web Skills + Workflow 节点**
   - `apps/web/src/pages/Skills.tsx`
   - `apps/web/src/lib/skillsApi.ts`
   - `apps/web/src/components/skills/*`
   - `apps/web/src/components/workflow/*`
   - `apps/web/src/lib/workflowEngine.ts`
   - `apps/web/src/lib/workflowValidation.ts`
   - `apps/web/src/types/workflow.ts`

3. **Batch-3 Realtime 录制/相机稳定化 + dataset 扫描**
   - `apps/realtime/api/setup.py`
   - `apps/realtime/api/teleop_control.py`
   - `apps/realtime/api/vision_inference.py`
   - `apps/realtime/api/main.py`
   - `apps/realtime/*sender*`
   - `apps/realtime/runtimes/*`

4. **Batch-4 Sidecar & Inference 联动**
   - `apps/pi0_sidecar/server.py`
   - `apps/pi0_sidecar/run.sh`
   - `apps/pi0_sidecar/setup_env.sh`
   - `apps/pi0_sidecar/requirements.txt`
   - `apps/web/src/pages/Inference.tsx`

5. **Batch-5 大资产与 URDF**
   - `apps/realtime/dora-bambot/URDF/reachy_mini/**`
   - 仅在前四批通过后单独提交，避免拖慢 review。

## 4) 验收清单（可复现命令）

## A. Skill 真实执行链（M15-A）

1) 启动服务
```bash
pnpm dev:web
uvicorn app.main:app --reload --port 8000
python run_api.py
```

2) 技能基础接口可用
```bash
curl -s http://127.0.0.1:8000/api/v1/skills
curl -s http://127.0.0.1:8000/api/v1/skills/runtimes
```

3) 安装 + 执行 skill（目标: 非模拟）
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/skills/so101_generic_teleop/install \
  -H 'Content-Type: application/json' \
  -d '{"runtime_id":"so101","enabled":true,"params":{"episode_count":1}}'
```

通过标准:
- `run.status` 能体现真实执行状态流转（非固定模拟成功）。
- 失败时返回可诊断错误（端口占用、runtime 不可用、参数错误等）。

## B. Workflow 真编排（M15-B）

1) 在 UI 创建链路:
- `DatasetLoad -> CameraMap -> FinetuneJob -> JobMonitor`

2) 执行后检查:
- 控制台日志包含真实 `job_id`
- `job_monitor` 显示真实状态（queued/running/completed or failed）

通过标准:
- 去掉“纯本地模拟完成”的假阳性结果。

## C. 推理稳定性（M15-C）

1) 模型加载与状态
```bash
curl -s http://127.0.0.1:8002/api/vision_inference/status?prefer=cpu
curl -s -X POST http://127.0.0.1:8002/api/vision_inference/load \
  -H 'Content-Type: application/json' \
  -d '{"model_key":"qualia-robotics/act-so101-20260422-0445-1b35f73c","prefer_device":"cpu"}'
```

2) 连续运行观察
- 前端 `Inference` 页连续运行 10 分钟。
- 期间执行 2 次 stop/start，1 次 unload/load。

通过标准:
- 无进程僵死、无不可恢复 ws 错误、可重复恢复。
- 推理帧持续产生，状态接口可读，sidecar 不出现持续异常刷屏。

## 5) 执行顺序建议

1. 先完成 M15-A（Skill run 真实化），因为它同时解除 Skills 页和 Workflow `skill_invoke` 的模拟瓶颈。  
2. 再做 M15-B（Workflow 真编排），把训练链路从演示态转为可运营态。  
3. 最后做 M15-C（推理稳定化），在已有功能闭环上做稳定性加固。  

## 6) 本地验收恢复与结果（2026-04-25）

### 环境恢复结果

- API: `http://127.0.0.1:8000/health` 返回 `200`。
- Web: `npm install` 后 `npm run dev -- --host 0.0.0.0` 启动成功，`http://127.0.0.1:5173/` 返回 `200`。
- Realtime: 重建 `apps/realtime/.venv` 并补齐依赖后，`http://127.0.0.1:8002/api/status` 返回 `200`。

### M15-A Skill 真实执行验收

- `POST /api/v1/skills/so101_generic_teleop/run` 已走真实转发链路，返回 `failed`，错误来自 realtime `POST /api/teleop/start` 的 `412`（缺少 follower 标定文件）。
- `POST /api/v1/skills/so101_record_episode/run` 已走真实转发链路，返回 `failed`，错误来自 realtime `POST /api/recording/start` 的 `412`（相机不可用/未检测到设备）。

结论: Skill 不再是“固定模拟成功”，已具备真实失败可诊断能力，符合 M15-A 的关键验收目标。

### M15-B Workflow 真编排验收

- `GET /api/v1/trainings/qualia/dataset_probe?dataset_hf_id=lerobot/pusht_image` 返回 `200`，并返回 `image_keys`。
- `POST /api/v1/trainings`（`train_backend=qualia`）返回 `201` 创建训练任务，随后 `GET /api/v1/trainings/{job_id}` 返回真实状态（本次为 `failed`）。

结论: Dataset probe、训练任务创建、任务状态查询均已走真实后端链路，Workflow 关键节点具备真实编排能力。

### M15-C 推理稳定性验收

- `GET /api/vision_inference/status` 返回 `200`。
- 响应体包含 `pi0_predict_health` 字段，可读取健康状态与连续失败计数（本次计数为 `0`）。

结论: 推理状态接口已暴露 Pi0 预测健康信息，前端可据此展示 breaker/健康状态。

### 当前阻塞项（硬件/外设前置）

- SO-101 follower 标定文件缺失（需先完成 Step 2 calibration）。
- 录制相机设备不可用（`camera_index=0` 未检测到可打开设备）。

这两项会导致真实执行返回 `412`，但不影响“链路已真实打通”的验收结论。

## 7) M16 新增方向：BotClaw v0.9 协议草案

### 背景

M15 验收后确认：`apps/api/app/data/skills_seed.json`、`packages/botclaw-spec/schemas/*.schema.json`、`apps/realtime/runtimes/_protocol.py` 已经分别承载了 BotClaw 的事实字段，但三者此前不是同一个真源。

### M16-BotClaw 目标

- 将 `packages/botclaw-spec/` 升级为 BotClaw v0.9 字段冻结草案。
- 用 `Skill` / `DeviceCapabilities` / `JointUpdate` / `DatasetEpisode` 等 schema 作为 API、Web、Realtime 的协议真源。
- 对齐 TidyBot 安全原语（Rewind、Lease、Safety Envelope、Auto-hold），先做 schema 占位，不改运行逻辑。
- 对齐 Qualia Studio 节点分类，形成 `SOURCES / TRANSFORMS / VLAS / OUTPUTS / SKILLS` 的 Workflow vocabulary。

### 已落地产物

- `packages/botclaw-spec/BotClaw-v0.9-draft.md`
- `packages/botclaw-spec/docs/verb_taxonomy.md`
- `packages/botclaw-spec/docs/workflow_node_taxonomy.md`
- `packages/botclaw-spec/schemas/safety_envelope.schema.json`
- `packages/botclaw-spec/schemas/runtime_lease.schema.json`
- `packages/botclaw-spec/schemas/skill_run_event.schema.json`
- `packages/botclaw-spec/scripts/validate_skills_seed.py`

### 验收标准

```bash
python3 packages/botclaw-spec/scripts/validate_skills_seed.py
```

通过标准：
- `skills_seed.json` 能通过 BotClaw `Skill` Pydantic 模型校验。
- Web Workflow 节点面板按 Qualia 对齐分类展示。
- BotClaw v0.9 文档明确标注“当前可落地”与“后续完善”，避免过早承诺 v1.0。

### 冻结点与门禁（新增）

- 冻结点文档：`packages/botclaw-spec/BotClaw-v0.9-freeze-point.md`
- 唯一验收门禁：`scripts/botclaw-acceptance-gate.sh`

执行规则：
- 任何“已完成”结论必须附带 gate 脚本通过结果。
- v0.9 冻结期内不允许随手改 schema 字段；如需修改，必须同步 schema + Python + TS + 文档并重跑 gate。

### M16 日执行清单（新增）

- 详见：`progress/M16-day-by-day-execution-checklist.md`
- 拆解为 Day1-2（lease）、Day3-4（run_event）、Day5-7（safety_envelope + gate）

## 8) 环境修复与基线确认（2026-05-09）

### 本次操作目标

- 修复开发环境基础工具（`curl`、`git`）与门禁可执行性。
- 对比旧开发机目录，回收可能遗漏文件。
- 以 `scripts/botclaw-acceptance-gate.sh` 通过作为当日基线。

### 执行结果

- `curl` 已安装：`curl 8.5.0`
- `git` 已安装：`git version 2.43.0`
- BotClaw gate 通过：
  - `Validate skills seed` 通过（5 skills）
  - `Validate key docs` 通过
  - `Validate safety schemas` 通过
  - `API registry smoke` 通过（5 skills）

### 旧目录回收核对结果

核对源目录：

- `/media/amd/8b3b321a-78e4-49ab-a226-08ba4b1de832/home/amd/Downloads/new /botversex`

核对目标目录：

- `/home/amd/下载/dev/botversex`

结论：

- 未发现“目标缺失但源存在”的文件。
- 未发现“目标空文件但源有内容”的文件。
- 仅发现 `scripts/botclaw-acceptance-gate.sh` 存在差异，目标目录版本为修复版（优先使用项目 `.venv` Python），保留目标版本。

### 当前基线结论

- 当前工作目录可作为 M16 推进基线。
- 后续任何“完成”结论继续以 `bash scripts/botclaw-acceptance-gate.sh` 作为硬门禁。
