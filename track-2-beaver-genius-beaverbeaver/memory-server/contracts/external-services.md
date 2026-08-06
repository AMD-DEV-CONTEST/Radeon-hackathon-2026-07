# 外部推理服务合同

## 通用规则

- HTTP JSON；所有受保护端点使用 `Authorization: Bearer <token>`。
- 自建感知服务提供 `GET /health`；第三方网关可不开放模型列表，部署检查会向
  目标推理端点发送最小合同请求。
- Gateway 发送 `contract_version: beaver-external-inference-v1` 和明确模型名。
- 图片默认不超过 10 MiB，音频默认不超过 32 MiB。
- 请求日志不得打印 `data_base64` 或 Authorization。
- 本地 `image_path`、`audio_path` 只允许存在于 Gateway 内部持久队列，绝不
  出现在跨主机请求。

媒体对象：

```json
{
  "media_type": "image/jpeg",
  "data_base64": "/9j/2Q==",
  "sha256": "32461d5bd1773012ea387e9965da4d50e769a6f8385553e4c8baad294b6008bf",
  "size_bytes": 4
}
```

服务必须先验证 Base64、长度、MIME 和 SHA-256，再写入请求级临时文件；请求
结束立即清理。后续可增加短时签名 URL，但不能改变证据 ID 和校验语义。

## YOLOE

`POST /v1/detections`

```json
{
  "contract_version": "beaver-external-inference-v1",
  "model": "yoloe-26s",
  "job_id": "object:...",
  "media": {"media_type": "image/jpeg", "data_base64": "...", "sha256": "...", "size_bytes": 1234},
  "width": 1920,
  "height": 1080,
  "vocabulary": ["cup", "power bank"],
  "vocabulary_hash": "..."
}
```

响应保留 `job_id`，并返回 `status`、`input_width`、`input_height`、
`latency_ms` 和 `detections`。每项 detection 至少包含 `label`、
`confidence` 和 bbox。

## 人脸

`POST /v1/faces/recognize`

请求包含 `job_id`、`evidence_id`、`model`、媒体、
`expected_model_revision`、`expected_config_version`。响应返回输入尺寸、
模型版本和 observations。Embedding 属于受保护数据，不得通过 Web 公共 API
返回。

## 声纹

`POST /v1/voices/analyze`

请求包含 `audio_evidence_id`、媒体、`speech_present`、模型与配置版本。响应
返回 `turns`、speaker 数量、采样率和时长。原始音频仍由 Gateway 保存。

## Qwen / DashScope 服务

`qwen3.5-omni-flash` 使用 OpenAI Chat Completions。一个场景窗口把时序
`image_url`、原始 WAV 的 `input_audio`（含 `format: wav`）和文字提示放在同一
条 user message 中；Qwen-Omni 请求必须启用 `stream`，Gateway 将 SSE 增量
重新拼成一个严格 JSON 结果。它只负责第一人称 caption 和独立物品卡片。

`qwen3.7-flash` 使用 `POST /v1/chat/completions`，负责跨窗口稳定、承诺、日报、
物品搜索裁决和 EverOS 文本任务。请求显式发送 `enable_thinking: false`。

以下三个能力不是普通 OpenAI 路径，不能发送 `/audio/transcriptions`、
`/embeddings` 或 `/rerank` 的旧请求体：

- ASR：`POST /dashscope/asr`，顶层为 `model/input/parameters`，音频位于
  `input.messages[].content[].input_audio.data`；
- VL Embedding：`POST /dashscope/qwen3-vl-embedding`，输入位于
  `input.contents`，并固定 `parameters.dimension=1024` 以匹配 EverOS 索引；
- VL Rerank：`POST /dashscope/qwen3-vl-rerank`，query/documents 位于
  `input`，`top_n` 和 `return_documents` 位于 `parameters`。

Beaver 的搜索客户端直接使用上述原生合同。EverOS 仍调用 OpenAI embedding 和
vLLM rerank 形状，因此由 `beaver-provider-bridge` 在 `127.0.0.1:8792` 做本机
协议翻译；该桥不加载模型、不保存媒体，实际推理仍在外部服务。

## 错误

- `401`：Bearer Token 不正确；
- `409`：合同或模型/配置版本不一致；
- `413`：媒体超过服务限制；
- `422`：媒体校验或音频解码失败；
- `503`：模型不可用、OOM 或临时服务故障。

Gateway 会保留 durable job 并按策略重试；推理错误不能删除已保存证据。
