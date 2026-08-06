# M23 — 摄像头 + head-tracker 代理

里程碑: M23
日期: 2026-07-02
状态: ✅ 已完成（端到端真实跑通：本机摄像头检测到人脸 → Reachy 头部 yaw/pitch 实时跟随）
规划: [M21-reachy-open-capabilities-roadmap.md](./M21-reachy-open-capabilities-roadmap.md) §9

## 目标

让 BotverseX 用户在云端 UI 看到本机摄像头画面，并一键开启「头部跟踪」——Reachy 用摄像头识别用户脸部，实时调头部 yaw/pitch 跟随。

## 关键决策

**Allan fork 不暴露 HTTP camera 端点**（见 M21 附录 C）。所以 Local Agent 自己用 `cv2.VideoCapture` 打开 `/dev/video*`，不依赖 daemon。这与规划文档 §9 一致。

**人脸检测用 cv2 Haar cascade**，不引 mediapipe——零额外依赖，cv2 自带 haarcascade_frontalface_default.xml。MVP 精度足够跟踪用，未来可换 mediapipe FaceMesh 提升鲁棒性。

## 落地变更

### 后端 `apps/realtime/api/reachy_camera.py`（新文件，~270 行）

新增独立模块，含 HTTP router (`/api/reachy/camera/*`) + WS router (`/ws/reachy/camera`)：

- `GET /api/reachy/camera/devices` — 复用 camera.py 的 `_probe_devices()` 列出 V4L2 设备
- `GET /api/reachy/camera/snapshot?device=0&w=640&h=480` — 单帧 JPEG
- `WS /ws/reachy/camera?device=0&fps=15&w=640&h=480` — MJPEG-style 二进制 JPEG 流
- `POST /api/reachy/camera/head-tracker/start?device=0` — 启动后台 head tracker
- `POST /api/reachy/camera/head-tracker/stop` — 停止
- `GET /api/reachy/camera/head-tracker/status` — `{running, device, fps, last_face_at, last_target, last_error}`

**Head tracker 实现**（`_head_tracker_loop`）：
- 单进程 asyncio 后台任务（singleton + asyncio.Lock 保护）
- 8 fps 取帧，cv2 Haar cascade 检测最大脸
- 脸中心 (cx, cy) 归一化到 [-1, 1]，映射到 `yaw = -gain * max_yaw * (2cx-1)` / `pitch = gain * max_pitch * (2cy-1)`
- 每 150ms POST `/api/move/set_target` 到 daemon，1s 无脸则回正 (0, 0)
- 限幅：max_yaw=0.7rad (~40°)、max_pitch=0.4rad (~23°)、gain=0.8（柔和跟随）
- 启动前检查 daemon TCP 可达，否则 502

### 后端 `apps/realtime/api/main.py`
- 注册 `reachy_camera_router` + `reachy_camera_ws_router`

### 前端 `apps/web/src/lib/reachyApi.ts`（+~50 行）
- 类型：`ReachyCameraDevice`, `ReachyHeadTrackerStatus`
- 函数：`listReachyCameras / reachyCameraSnapshotUrl / startReachyHeadTracker / stopReachyHeadTracker / getReachyHeadTrackerStatus`

### 前端 `apps/web/src/components/reachy/ReachyCameraPanel.tsx`（新建，~210 行）
- 设备下拉（带分辨率 + busy 标记）+ 刷新按钮
- 4:3 预览框：开关切换 /dev/video* MJPEG 实时刷新（500ms 间隔）
- 头部跟踪开关：启动/停止按钮 + 当前 yaw/pitch 数值显示 + 「检测到脸」绿标
- 错误横幅 + 友好提示
- 守护进程未连接时显示占位

### 前端 `apps/web/src/pages/RobotReachyMini.tsx`
- 在 ConversationPanel 下方插入 `<ReachyCameraPanel daemonOnline={daemonOnline} />`

## 端到端验证

| 验证项 | 结果 |
|--------|------|
| `realtime` 重启无报错，新 router 自动挂载 | ✅ |
| `GET /api/reachy/camera/devices` 返回 3 个 V4L2 设备 | ✅ |
| `GET /api/reachy/camera/snapshot?device=0` 返回真实 640×480 JPEG（23KB） | ✅ |
| `POST /api/reachy/camera/head-tracker/start?device=0` 返回 `ok:true, device:0, fps:8` | ✅ |
| `GET /api/reachy/camera/head-tracker/status` 显示 `running:true, last_face_at:311930.40, last_target:{yaw:-0.054, pitch:-0.047}` — **真实检测到人脸并算出 target** | ✅ |
| `POST /api/reachy/camera/head-tracker/stop` 干净返回 `running:false` | ✅ |
| 前端 `tsc --noEmit` | ✅ |
| 前端 `eslint` ConversationPanel/ReachyCameraPanel clean | ✅ |

## 未做（已知限制）

- **WS MJPEG 流未在 UI 用**：当前前端用 HTTP `/snapshot` 500ms 轮询，足够预览。WS 路径已留好，等真要 30fps 推流时切过去。
- **人脸检测精度**：cv2 Haar 在低光/侧脸时易丢，未来可换 mediapipe（需 `pip install mediapipe`）。
- **跟踪参数硬编码**：yaw/pitch 限幅与 gain 写在模块顶部常量，未来可暴露成 `start` 接口的 query 参数。
- **多摄像头同时跟踪**：当前 singleton，只支持一个 tracker 同时跑。多 Reachy 场景留待后续。

## 文件改动清单

```
apps/realtime/api/reachy_camera.py                              (新建, ~270 行)
apps/realtime/api/main.py                                       (+3 行)
apps/web/src/lib/reachyApi.ts                                   (+~50 行)
apps/web/src/components/reachy/ReachyCameraPanel.tsx            (新建, ~210 行)
apps/web/src/pages/RobotReachyMini.tsx                          (+2 行: 插入 CameraPanel)
progress/M23-reachy-camera-head-tracker.md                      (本文件)
```

## 下一步

M24：官方 HF 动作库 + Workflow 节点 + 训练管线接入。
