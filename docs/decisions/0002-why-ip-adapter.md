# ADR 0002: 风格迁移用 IP-Adapter(不用 DreamBooth / ControlNet ref-only)

- **状态**: Accepted
- **日期**: 2026-07-16
- **决策者**: AMD Radeon Studio Team

## 背景

v0.1 的风格迁移模块需要在 1-3 秒内给一张内容图 + 一张风格图,产出一张融合图。候选方案:

| 方案 | 速度 | 训练? | 可控性 | 显存 |
|---|---|---|---|---|
| **IP-Adapter** | ⚡⚡(无需训练) | 否 | ⭐⭐⭐⭐ | +1.5GB |
| DreamBooth 微调 | ⚡(推理) / 慢(训练) | **是** | ⭐⭐⭐⭐⭐ | +2GB base |
| ControlNet reference-only | ⚡⚡⚡ | 否 | ⭐⭐ | +0.5GB |
| AdaIN(经典) | ⚡⚡⚡ | 否 | ⭐ | 极小 |
| InstantStyle | ⚡⚡ | 否 | ⭐⭐⭐⭐ | +1GB |

## 决策

**采用 IP-Adapter for SDXL(`h94/IP-Adapter`)做风格迁移。**

## 后果

### ✅ 优点
- **零训练** — 上传一张参考图就能用,无 fine-tune 流程
- **风格/内容解耦** — 不会把参考图的内容强塞到输出里
- **和 SDXL 天然兼容** — 只需加 cross-attention 层,不影响 base pipeline
- **社区成熟** — diffusers 0.30+ 一行代码集成

### ❌ 缺点
- 不能像 DreamBooth 那样"学"特定概念(比如你养的猫)
- 对极端风格(像素风/低多边形)效果一般
- 需要额外下载 IP-Adapter 权重(~1.5GB)

### 🔁 为什么不用 DreamBooth
- 训练需要 30+ 分钟 + GPU,**5 天冲刺没时间**
- 每个新风格都要训,**用户每次开新场景都要等**
- IP-Adapter 90% 场景够用

### 🔁 为什么不用 ControlNet reference-only
- 风格"迁移"效果弱,更像是"参考"
- 可控性差,prompt 主导一切

## 备注

- IP-Adapter 强度通过 `extra["ip_adapter_scale"]` 控制(0.0-1.0,默认 0.6)
- 如果后续要支持"训特定概念",再加 DreamBooth 路径(见 v0.2+ 路线)
