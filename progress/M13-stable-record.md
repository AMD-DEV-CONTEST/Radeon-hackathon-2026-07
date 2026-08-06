# M13 — Stable reproducible Step 1 – Step 4 recording

日期: 2026-04-21

## 背景

M11 打通了 Step 4 `lerobot-record` CLI wrapper，M12 硬化了相机 UX。
实战采集时仍然出现一串彼此强相关的顽固问题：

1. `lerobot-record` 子进程在第 2 条 episode 中途挂掉（`ConnectionError:
   Failed to sync read 'Present_Position'`），之后无法再启动：
   `Port /dev/ttyACM1 is currently in use by recording`。
2. 子进程挂掉后相机进入"看得见却打不开"状态，Step 1 显示
   "相机当前不可用 (/api/camera/devices 返回空)"，"release streams"
   即使有反应，preview 也只是一张冻结画面。
3. Step 4 的 `repoId` 默认沿用上一次的 dataset id，容易在下次采集时
   无意追加 / 覆盖老数据。
4. Step 4 启动前的相机检查只看 `useSetup.camera`，没有防御已经被
   收回 / 挪到新 index 的情况。

M13 的目标是把"Step 1 扫描 → Step 3 teleop → Step 4 record →
Step 4 又采一轮" 这条回路固化成**可复现的稳定态**，为后续批量数据
采集和云端训练打好地板。

## 本次变更

### Realtime 后端

- `apps/realtime/api/record_control.py`
  - `_RecordCLI` 在 `acquire()` 之前就构造好，`acquire()` 时直接带
    `process_id = sess.session_id`。关闭了 "acquire 成功但
    `register_process` 之前进程崩掉" 留下的永久死锁窗口。
  - 新增 `_reap_if_dead(sess)`：一旦发现上一次 record 会话已经死了，
    双通道 (`release_for_process` + `release(ports)`) 释放串口租约，
    并同时调用 `_stop_all_camera_streams()`。`_snapshot()` 每次被
    status endpoint 命中时都会走一遍，让系统在被"观察"时自愈。
  - `start_recording` 入口额外做一次死会话 reap；`stop_recording`
    也统一改为双通道释放，避免任何路径漏掉 lease。
  - 新增 `POST /api/recording/reset`：不挑进程归属，一律把所有
    tag 为 `recording` 的串口 lease 放掉、把所有 MJPEG/WS 预览流
    停掉。作为唯一的"救命"按钮暴露给 UI。

- `apps/realtime/api/camera.py`
  - 清理掉调试期临时加的 NDJSON 日志桩，保留 stream registry、
    `stop_all_streams` 的全部功能改动。

### Web 前端

- `apps/web/src/components/setup/steps/Step1Camera.tsx`
  - `loadDevices()` 开头先 `POST /api/camera/stop_streams` 再 delay
    150ms 再探测，避免自家 MJPEG preview 吃住 `/dev/video*`。
  - 扫描结束后无论当前 `selected` 是否变化都 `setStreamNonce(n+1)`，
    强制 `<img>` 丢掉缓存帧，避免"画面是冻的"。
  - "force reset" 按钮改成组合操作：
    `stop_streams` → `recording/reset` → 250ms 等 V4L2 → bump nonce
    → 重新探测。单次点击把相机 + 录制两条路径一起清干净。

- `apps/web/src/components/setup/steps/Step4Record.tsx`
  - `doStart()` 做主动相机 pre-flight：先 `stop_streams` + delay，
    再 `GET /api/camera/devices`；若 `useSetup.camera` 指向的 index
    已经不可用，自动回退到第一个 readable index 并 `setCamera(...)`
    把全局状态同步改过来；`fps` 按实际 camera 能力对齐。
  - `repoId` 初始值永远走 `suggestRepoId()`（带时间戳），不再
    默认沿用 `state.lastDatasetId`，彻底避免无意追加到旧 dataset。

## 复现契约 (Reproducibility contract)

录制回路遵守以下不变式，便于后续批量采集和 CI：

1. **Camera fallback**：Step 4 启动前会主动重新确认可用相机；若选中
   index 已失效，自动切换到第一个可用 index 且同步 `useSetup` 全局
   状态。用户不会再遇到 "看上去还选着 1 其实 1 已经没了" 的死局。
2. **Reset semantics**：`POST /api/recording/reset` 是唯一的救命按钮。
   它**只**做两件事：释放所有 `recording` 串口 lease、停掉所有
   camera 预览流。不重启服务、不改全局状态、对 idle 态也是 no-op
   安全。UI 上的 "force reset" 和 Step 4 的 pre-flight 复用同一条
   路径。
3. **Self-healing on observation**：即便用户没点任何按钮，只要前端
   再调一次 `/api/recording/status`，后端就会在 `_snapshot()` 里自行
   reap 死会话、放锁、停流。
4. **Dataset id uniqueness**：每次打开 Step 4 都会生成新的带时间戳
   的 `repoId`，避免无意覆写。
5. **启动约定不变**：api / realtime / web 的启动姿势与 M11/M12 一致；
   本次改动没有引入任何新的进程 / 环境变量依赖。

## 验证

- 连续 2 条 episode 采集成功，dataset 目录 `meta/info.json` 里
  `total_episodes` 递增。
- 故意 Ctrl-C 掉 `lerobot-record` 子进程后：
  - `/api/recording/status` 再被命中一次即自动放掉串口 lease。
  - Step 1 "force reset" 后 preview 恢复为实时画面（不再冻结）。
  - 紧接着启动 Step 3 teleop 不再报 "Port ... in use by recording"。
- 退出并重新登录后，Step 4 自动建议新的 dataset id，不会追加到
  上次的数据集。

## 后续

M13 把录制的"地板"铺平后，工作重心转到：

- **P1** — 按统一参数采两组 30 episode 数据集（pick & push）。
- **P2** — 推送到 HuggingFace Hub。
- **P3** — 先在 Qualia Studio 上云端训练 ACT / Pi0。
- **P4** — 把 checkpoint 拿回本地 AMD ROCm 盒子做推理。
- **P5** — 可选的本地训练探索，仅当云端训练 + 本地推理两条线都
  绿色后再尝试。
