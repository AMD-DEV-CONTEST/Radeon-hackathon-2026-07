# 演示视频

**主播放地址：** [B 站 - BV1t3up6iEhy](https://www.bilibili.com/video/BV1t3up6iEhy/)

**备用播放/下载地址：** [百度云 MP4 直链](https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd)

**本地母版：** `submission/en/amd-hackathon-2026-07.mp4`

**媒体检查：** 3 分 07.2 秒、1920x1080、H.264 视频与 AAC 音频、174,000,121 字节（约 165.9 MiB）。

**SHA-256：** `0cba7eec725a4c8d7e76a3b762c56ce1c96cc8edd9321daf0a2342c0cd0a0a4f`

**建议 PR 标签：** `Demo video - 3-5 minutes`

视频时长符合 3–5 分钟要求。2026-08-06 外网检查中，B 站页面返回 HTTP 200，百度云端点对 Range 请求返回 HTTP 206 与 `video/mp4`。本地母版不进入普通 Git，提交使用上面的两个公网地址。

## 建议的 3–5 分钟章节清单

| 时间 | 内容 | 必需证据 |
| --- | --- | --- |
| 0:00-0:25 | 问题与产品 | 自然语言 → 经测试的机器人能力。 |
| 0:25-0:50 | 系统架构 | 私有模型、RDK Agent、`sophonctl`、RDK X5。 |
| 0:50-1:15 | 开发板只读证明 | `ping`、`state` 和 `plugins list`。 |
| 1:15-2:45 | 机器人开发模式 | 意图门控；测试 → 编码 → 验证；release 与 Skill 安装。 |
| 2:45-3:30 | 验收 | 先进行 CLI 调用，再进行自然语言 Skill 调用；展示物理结果。 |
| 3:30-4:15 | AMD 执行 | 参赛者控制的 Radeon Cloud 实例、经脱敏的 ROCm/vLLM/模型证据、流式响应，以及经脱敏的运行时证据。 |
| 4:15-4:40 | 安全与价值 | allowlist、离线测试、证据门控、方向保护。 |
| 4:40-5:00 | 结尾 | 源代码、可复现性与项目价值。 |

## 隐私复核

- 对 API key、SSH key、私有 URL、电子邮件地址、MAC 地址及非必要的内网 IP 进行模糊处理或裁切。
- 不要展示 `~/.pi/agent/auth.json` 的内容或私有 `apiKey` 字段。
- 展示模型配置时，请使用 `submission/zh/config/` 中的脱敏示例。
- 明确区分 AI 生成的封面插图与真实硬件画面。
