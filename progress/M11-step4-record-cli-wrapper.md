# M11 — Step 4 数据采集：lerobot-record CLI 包装 + 中文 UI

- **日期**：2026-04-21
- **目标阶段**：Plan A v2 · 阶段 2（数据采集环闭）

---

## 完成了什么

让 6 步向导里的 **Step 4 "采集数据"** 真正能跑通 —— 点一下按钮就启动官方 `lerobot-record`
子进程，N 条 episode 录完自动停，数据落到 `~/.cache/huggingface/lerobot/<repo_id>/`，直接喂给 Step 5 训练。

三个新后端模块：
- `apps/realtime/api/_cli_process.py`：通用 subprocess 基类。把原来 `teleop_control._TeleopCLIProcess`
  里成熟的 subprocess 管理逻辑抽出来（process group、stdin 喂 `\n` 自动跳过 calibration 提示、
  ANSI 清理、2 阶段 readiness gate、SIGTERM → SIGKILL 关停），给后续所有 CLI 包装器共用。
- `apps/realtime/api/port_lock.py`：照搬 MakerMods 的 `port_lock_manager`，防止遥操作
  和录制同时占用 `/dev/ttyACM*`。
- `apps/realtime/api/record_control.py`：四条路由 —— `/api/recording/start`、`/stop`、
  `/status`、`/dataset_check`。内部直接 spawn `lerobot-record` 并透传 `--robot.*` /
  `--teleop.*` / `--dataset.*` / `--robot.cameras` 参数。

前端：`Step4Record.tsx` 从原来的"跳外链到 /teleop"换成**内嵌表单**：
数据集名、任务描述、episode 数、单条时长、条间复位、FPS —— 全中文，带日志面板、进度条、错误气泡、
`/api/recording/dataset_check` 冲突检查。

同时 `teleop_control.py` 的 `/start` 也接入了 `port_lock_manager`，这样后续 Step 5（训练）
或并发操作都不会和 Step 3 / Step 4 抢端口。

---

## 解决了什么问题

1. **Step 4 原来是个外链占位页**：UI 上只有一个"Open Teleop to record"按钮，要用户自己去别的
   页面录完再回来复制数据集名 —— 典型的拼凑感流程，新手根本玩不转。
2. **后端没有真正的 lerobot-record 包装器**：`/api/record` 是老 M8 时代的代码，只会把 WebSocket
   关节流写 JSON，不支持相机、不落 parquet、不能被 lerobot-train 直接消费。
3. **不同 feature 并发时的端口冲突**：之前遥操作一旦开起来，相机 MJPEG 预览、录制、calibration
   都可能撞上同一个 `/dev/ttyACM*`，造成 Feetech bus 死锁。现在用 `port_lock_manager` 做中央记账，
   冲突时直接 409 + 告诉用户是谁占着。
4. **subprocess 代码重复**：原先 `teleop_control.py` 里 200 行 subprocess 管理是散的，record
   / train 再各写一份会爆炸。现在抽成 `CLIProcess` 基类，`_RecordCLI` 只需要 20 行重写。

---

## 关键命令 / 配置

### 启动后端（验证路由）

```bash
cd /home/amd/Downloads/botversex/apps/realtime
source rocm_env.sh               # 阶段 1 的 env 脚本
export BOTVERSEX_LEADER_DEVICE_ID=ethan_leader
export BOTVERSEX_FOLLOWER_DEVICE_ID=ethan_follower
python run_api.py &
```

### 验证 /api/recording/* 上线

```bash
curl -sf http://127.0.0.1:8002/openapi.json | python -c "
import sys, json
spec = json.load(sys.stdin)
for p in sorted(spec['paths']):
    if '/api/recording' in p:
        print(p)
"
# -> /api/recording/dataset_check
# -> /api/recording/start
# -> /api/recording/status
# -> /api/recording/stop
```

### 直接命中 /api/recording/start（不用 UI）

```bash
curl -sS -X POST http://127.0.0.1:8002/api/recording/start \
  -H 'content-type: application/json' \
  -d '{
    "leader_port": "/dev/ttyACM1",
    "follower_port": "/dev/ttyACM0",
    "cameras": [{"name":"top","index_or_path":0,"fps":30}],
    "repo_id": "botversex/pick-test",
    "single_task": "抓取积木",
    "num_episodes": 3,
    "episode_time_s": 20,
    "reset_time_s": 3,
    "fps": 30,
    "push_to_hub": false
  }'
```

后端会 spawn 完整的 `lerobot-record` 命令，等价于下面这条：

```
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM0 --robot.id=ethan_follower \
  --robot.calibration_dir=~/.cache/huggingface/lerobot/calibration/robots/so101_follower \
  --robot.cameras='{"top":{"type":"opencv","index_or_path":0,"width":640,"height":480,"fps":30}}' \
  --teleop.type=so101_leader \
  --teleop.port=/dev/ttyACM1 --teleop.id=ethan_leader \
  --teleop.calibration_dir=~/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader \
  --dataset.repo_id=botversex/pick-test --dataset.single_task=抓取积木 \
  --dataset.num_episodes=3 --dataset.episode_time_s=20 --dataset.reset_time_s=3 \
  --dataset.fps=30 --dataset.push_to_hub=false --display_data=false
```

---

## 最终结果

```
--- recording routes registered ---
/api/recording/dataset_check
/api/recording/start
/api/recording/status
/api/recording/stop
/api/teleop/alignment_check
/api/teleop/release_torque
/api/teleop/start
/api/teleop/status
/api/teleop/stop

--- recording status ---
{"running":false,"session_id":null,"pid":null,"returncode":null,"started_at":null,
 "log_tail":[],"last_error":null,"current_episode":null,"total_episodes":null,
 "dataset_dir":null,"repo_id":null}
```

- ✅ 后端路由全部注册
- ✅ `Step4Record.tsx` TypeScript 类型检查通过（无新增错误）
- ✅ 端口锁 (`port_lock_manager`) 在 teleop 和 record 之间生效：两边抢同一个
  `/dev/ttyACM*` 会直接 409 而不是让 Feetech bus 死锁

**待用户实机验证**（下一步用户上机操作）：
- 从 UI 点"开始采集"，观察 `lerobot-record` 日志在界面上滚
- 录完 N 条 episode 后 `state.lastDatasetId` 自动填充，Step 5 的"下一步"按钮能点亮
- `~/.cache/huggingface/lerobot/<repo_id>/meta/info.json` 里 `total_episodes` 正确

---

## 下一步

进入 **阶段 3：Step 5 本地训练**
- 新建 `apps/realtime/api/train_control.py`：复用 `CLIProcess` 基类，包 `lerobot-train`
- subprocess env 里注入 `LD_PRELOAD=/opt/rocm/lib/libhsa-runtime64.so.1`（阶段 1 的技巧），
  这样 training child 继承后就自动用 ROCm 7.2.2 HSA runtime
- 先跑通 MLP / Vision MLP，再跑 SmolVLA（SmolVLA 会 pull 预训练权重）
- Step 5 UI：策略选择 + 训练参数 + 实时进度条 + loss 曲线（tail log 解析，先不上 TB 依赖）
