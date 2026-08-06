# 任意采集端与 Beaver Memory 接入协议

协议不限定智能眼镜。手机、胸针、摄像头、录音设备、桌面程序或自研硬件都可以
作为采集端；`device_id` 和 `client` 用于区分来源，不用于判断设备类型。

## 鉴权与时间

WebSocket 和 HTTP 上传都使用：

```http
Authorization: Bearer <DEVICE_TOKEN>
```

当配置 `USER_TOKENS_JSON` 时，Token 同时确定上传归属的用户。Gateway 在鉴权
成功后才选择用户运行时；原始媒体、设备在线状态、人物/物品、Capsule 和 EverOS
写入均按该用户隔离。Token 不得放进 URL，也不要让两位用户共用同一 Token。

Web 用户在 `/login` 输入自己的 Token，成功后使用 HttpOnly Cookie；设备仍使用
上述 Authorization Header。

Gateway 同时保存设备原始时间、基于同一 boot monotonic 锚点得到的校正时间和
服务端接收时间。单流顺序只由 `(device_id, boot_id, stream_id, sequence)` 决定；
设备时间、文件名和网络到达顺序都不能改变单流顺序。页面按 `Asia/Shanghai`
展示校正后的 Unix 毫秒时间，原始设备时间永不覆盖。

## 唯一媒体上传协议

新采集端统一使用：

```http
POST /api/v1/media/upload
Content-Type: application/octet-stream
Authorization: Bearer <token>
X-Device-Id: glasses-001
X-Boot-Id: 9f31c8a2
X-Stream-Id: microphone-main
X-Sequence: 47
X-Captured-At-Ms: 1785298215123
X-Monotonic-Ms: 65321
X-Clock-Synced: true
X-Duration-Ms: 5000
X-Filename: audio_20260729_093015_123_000047.wav
X-Media-Type: audio/wav
X-Content-Length: 160044
X-Content-Sha256: 900a0c7186f6...

<WAV/JPEG/PNG/NV12/MP4 bytes>
```

未校时时必须发送 `X-Clock-Synced: false`，并省略 `X-Captured-At-Ms`；
`X-Monotonic-Ms` 仍为必填。同一 boot 的音频、图片、视频必须使用独立
`X-Stream-Id`，例如 `microphone-main`、`camera-main`、`video-main`。Glass 原始
NV12 帧使用 `X-Media-Type: image/x-nv12`，并额外提交 `X-Width`、`X-Height`；
其他采集端优先提交 JPEG 或 PNG。

服务端在 `.part` 临时写入、`fsync`、SHA-256/长度校验、原子 rename 和 SQLite
唯一键提交全部成功后才返回 ACK：

- `201 accepted`：首次可靠接收；
- `200 already_accepted`：唯一键和 SHA-256 均相同，可视为成功；
- `409 sequence_conflict`：唯一键相同但内容不同，设备必须停止自动重试并告警；
- `400`：字段、长度、格式或 SHA 错误，不应无限重试。

### 图片批量回退

持续采集设备在并发 HTTP 不稳定时，可以把同一
`device_id + boot_id + camera stream_id` 的 1–6 张图片提交到：

```http
POST /api/v1/media/upload-batch
Content-Type: application/vnd.beaver.media-batch
Authorization: Bearer <token>
X-Device-Id: glasses-001
X-Boot-Id: 9f31c8a2
X-Stream-Id: camera-main
X-Batch-Count: 6
X-Batch-Content-Length: 123456

BMB1 + <uint32-le manifest length> + <JSON manifest> + <ordered image bytes>
```

Manifest 格式为 `{"version":1,"items":[...]}`。每个 item 必须独立携带
`sequence`、`captured_at_ms`、`monotonic_ms`、`clock_synced`、`duration_ms`、
`filename`、`media_type`、`content_length` 和 `sha256`；图片正文按 items 顺序紧随
manifest，不使用 Base64。批次仅接受 JPEG、PNG 或 NV12 图片。

响应为逐项 ACK。HTTP `200` 表示全部条目为 `accepted/already_accepted`；HTTP
`207` 表示部分成功。设备只能删除明确返回 `accepted` 或 `already_accepted` 的
本地文件；`retry: true` 或缺失 ACK 的条目必须保留重试，`sequence_conflict` 与
`invalid` 应隔离并告警。批量协议不改变单图协议的幂等键与可靠性语义。

上传状态与缺口可查询：

```http
GET /api/v1/media/status?device_id=glasses-001&boot_id=9f31c8a2&stream_id=microphone-main
```

技术流结束时调用 `POST /api/v1/media/end`，携带 `X-Device-Id`、`X-Boot-Id`、
`X-Monotonic-Ms` 和 `X-Reason`。该调用只封闭不足 30 秒的技术窗口，不构成
Semantic Session 边界，也不会因为推流暂停而自动合并记忆事件。

## 已移除：旧 WAV / HTTP 音频上传

`/v1/device/audio` 与 `/v1/device/audio/end` 不再注册，调用会得到 404。以下旧
报文只用于识别需要升级的客户端，不是可调用合同：

```http
POST /v1/device/audio
Content-Type: audio/wav
Authorization: Bearer <token>
X-Device-Id: glasses-001
X-Stream-Id: boot-session-001
X-Boot-Session-Key: glasses-001-boot-session-001
X-Sequence: 12
X-Device-Monotonic-Ms: 65000

<WAV bytes>
```

旧设备曾在结束采集时调用：

```http
POST /v1/device/audio/end
Authorization: Bearer <token>
X-Device-Id: glasses-001
X-Stream-Id: boot-session-001
X-Reason: shutdown
```

这些请求不会被静默映射到新协议，设备必须升级后再上传。

## WebSocket 控制

连接：

```text
ws://<gateway-host>:8788/v1/device/ws
```

连接后第一条消息必须是 `hello`，Gateway 返回 `hello.ok`、`session_id`、
心跳间隔、上传限制、服务器时间和时区。主要消息：

- `heartbeat`：电量、外部供电和采集状态；
- `wake.detected`、`audio.turn.*`：交互式问答链路，和持续记忆链路相互独立。

Glass 保留 WebSocket 做心跳、电量和交互式问答；连续音画只能走统一媒体接口。
旧 `capture.*` 消息会得到 `unknown_message`，不会进入记忆流水线。心跳状态可通过
`GET /v1/device/status` 查询。

## 已移除：旧图片上传

`/v1/device/photo` 不再注册，调用会得到 404。以下旧报文只用于识别待升级客户端：

```http
POST /v1/device/photo
Content-Type: application/octet-stream
Authorization: Bearer <token>
X-Device-Id: glasses-001
X-Stream-Id: boot-session-001
X-Image-Format: jpeg
X-Sequence: 12
X-Captured-At-Ms: 1780000000000
X-Device-Monotonic-Ms: 60000
X-Width: 1920
X-Height: 1080

<JPEG bytes>
```

旧请求不会被静默映射。图片必须携带完整 `boot_id + media stream + SHA-256 +
content length` 后通过统一接口提交。

## 电源门控

Glass 默认允许插线/外部供电状态继续记忆采集，便于长时间可靠性测试；需要省电
时可在设备配置中显式启用电源门控。
