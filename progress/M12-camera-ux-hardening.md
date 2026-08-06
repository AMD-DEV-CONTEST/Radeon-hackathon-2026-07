# M12 — Camera UX hardening (Step 1 / Step 4)

日期: 2026-04-21

## 背景

M11 上线 Step 4 数据采集后，用户实测反馈了一组一直互相强化的相机体验问题：

1. Step 1 扫描有时显示 "No camera detected"，但同时 `curl /api/camera/devices`
   明确返回 `index=1` 可用 → 前端状态和后端不同步。
2. Step 4 启动 `lerobot-record` 时日志固定 `index_or_path: 0`，直接命中
   `can't open camera by index` / `Camera index out of range`，recorder
   根本没进入 teleop loop，所以用户看到"主臂动从臂不动"。
3. Step 1 的 MJPEG preview 会抢占相机，等到 `lerobot-record` 派生子进程
   时相机还没被放开。
4. Setup readiness 里只有 `no_cameras` 一个档位，把"设备不在"和"设备在
   但被占用"混在了一起。

## 本次变更

### 后端

- `apps/realtime/api/camera.py`
  - 引入进程级 **stream registry**（MJPEG / WS 共享一个 `_StreamHandle`
    注册表），每个生成器循环顶部检查 `stop_event`，支持外部主动掐流。
  - 新增 `stop_all_streams(wait_s=1.5)`：signal-all + drain poll。
  - 新增 `POST /api/camera/stop_streams`：显式释放本进程持有的预览
    流（UI "release streams" 按钮 & `/api/recording/start` 前置调用）。
  - 新增 `GET /api/camera/status`：返回每个 `/dev/video*` 节点的
    `opened` / `readable` / 尺寸 / 后端，附 `present_count`,
    `usable_count`, `busy_count` → UI 用来区分 *busy* vs *absent*。
  - `_probe_devices` 改为只返回 **truly readable** 的设备（带 warm-up
    read），避免把只能 open 但不出帧的 V4L 节点塞进可选列表里。

- `apps/realtime/api/record_control.py`
  - `POST /api/recording/start` 前置两道校验：
    1. 用 `_probe_camera_status` 验证请求里的 `cameras[].index_or_path`
       是不是此刻真正可读；失败时返回 `HTTP 412` +
       `{code: "camera_unavailable", missing, available_indices}`，UI 可
       直接据此提示。
    2. 调用 `stop_all_streams(1.5)` 掐掉本服务自己的 MJPEG / WS，再
       `asyncio.sleep(0.3)` 等 V4L2 释放 handle。对齐 MakerMods
       `_stop_all_streams` 的流程。
  - 关键日志：启动时打印 `cameras=[(name, index_or_path), ...]`，方便
    日志里一眼看到"最终真正用了哪个 index"。

- `apps/realtime/api/setup.py`
  - `RealtimeHealth` 扩展 `camera_usable_count`, `camera_busy_count`
    两个字段，`/api/setup/health` 在有视频节点时异步跑 `_probe_status`
    补齐，无视频节点 / 无 OpenCV 时默认 0，保持原 endpoint 快速。

- `apps/api/app/api/v1/endpoints/setup.py`
  - 把 `no_cameras` 拆成三档：
    - `no_cameras`（warning）— `/dev/video*` 一个都没有。
    - `camera_busy`（warning）— 有节点但 `usable == 0 && busy > 0`。
    - `camera_unreadable`（warning）— 有节点能 open 但一帧都读不到
      （metadata-only V4L，或故障摄像头）。

### 前端

- `apps/web/src/components/setup/steps/Step1Camera.tsx`
  - 拉 `/api/camera/devices` 的同时并行拉 `/api/camera/status`（旧版
    后端 404 时静默降级）。
  - 修正"选中态与现实脱钩"：
    - `devices=[]` 时 **清空** `setup.camera`，避免 Step 4 继续用旧
      index 提交。
    - 记忆中的 index 在本次扫描结果里不存在时，自动回落到第一个可用
      index，并 bump `streamNonce` 重连预览。
    - `devices.length===1` 的特殊路径合并进同一个"fallback"分支。
  - "No camera detected" 根据 `status.busy_count` 渲染两种提示：
    - `busy_count>0` → 告诉用户是被别的进程占用，并给一颗 "release
      streams" 按钮（POST `/api/camera/stop_streams` + rescan）。
    - 否则保持原来"Plug in a USB camera..." 文案。

- `apps/web/src/components/setup/steps/Step4Record.tsx`
  - `doStart` 在真正 POST `/api/recording/start` 前先拉一次
    `/api/camera/devices`，校验 `state.camera.deviceIndex`：
    - 后端返回空 → 直接报错拦截，提示回 Step 1。
    - 返回非空但不含当前 index → 自动回落到第一个可用 index，并打
      warning。
  - 解析后端 412 `camera_unavailable` / 409 `port_in_use` detail，给
    出中文原因 + 可用 index 提示，而不是裸 `HTTP 412`.

## 验证

在真机（连了 2 个 `/dev/video*`, 只有 `index=1` 是真摄像头）重启 realtime
后验证：

```
GET /api/setup/health
→ "video_device_count":2, "camera_usable_count":1, "camera_busy_count":1, ...

GET /api/camera/status
→ {"present_count":2,"usable_count":1,"busy_count":1,
   "nodes":[{"index":1,"opened":true,"readable":true,...},
            {"index":2,"opened":false,"readable":false,...}]}

GET /api/camera/devices
→ {"devices":[{"index":1,"path":"/dev/video1","width":640,"height":480,
              "fps":25.0,"backend":"V4L2","busy":false,"readable":true}]}

POST /api/camera/stop_streams
→ {"stopped":[],"count":0}   # 当前无 preview，符合预期
```

## 待做

- UI: MJPEG preview 失败时自动提示用户调 `/api/camera/stop_streams`
  重试（今天只在"No camera detected"分支里提供了按钮）。
- Step 4 需要在真机把 `lerobot-record` 跑完一条 episode（M11 追加
  验收），至此 Phase 2 闭环，可以进 Phase 3（Step 5 Train）。
