# ADR 0001: 选 SDXL 作为基础文生图模型

- **状态**: Accepted
- **日期**: 2026-07-16
- **决策者**: AMD Radeon Studio Team

## 背景

v0.1 的文生图模块需要选一个 diffusion base model。候选:
- **Stable Diffusion 1.5**
- **Stable Diffusion XL (SDXL) base**
- **FLUX.1-schnell**
- **SD3-medium**
- **SD-Turbo**(蒸馏快版)

## 决策

**采用 SDXL base(`stabilityai/stable-diffusion-xl-base-1.0`)作为默认开发与生产模型;`stabilityai/sd-turbo` 仅在 env_check 烟雾测试中加载(2GB,快)。**

## 后果

### ✅ 优点
- **ROCm 兼容性最稳** — SDXL 在 ROCm 6.1+ 上跑了 1 年多,生态成熟
- **生态最全** — IP-Adapter、ControlNet、LoRA 都有官方 SDXL 权重
- **质量/速度平衡** — 30 步即可出好图,FLUX 要 50 步且显存占用更大
- **可蒸馏/优化** — 后续上 SD-Turbo 蒸馏版做"快速模式",无需换架构

### ❌ 缺点
- 比 SD-Turbo 慢(30 步 vs 2-4 步)
- 模型文件 ~6.5GB,首加载慢
- 在 8GB 显存卡上需要开 `enable_model_cpu_offload()`

### 🔁 替代方案对比

| 模型 | ROCm | 速度 | 质量 | 显存 | 生态 | 选? |
|---|---|---|---|---|---|---|
| SD 1.5 | ✅ | ⚡⚡ | ⭐⭐ | 4GB | ⚠️ 老 | ❌ 质量/生态都过时 |
| **SDXL base** | ✅ | ⚡ | ⭐⭐⭐⭐ | 6.5GB | ⭐⭐⭐⭐⭐ | ✅ **选这个** |
| SD-Turbo | ✅ | ⚡⚡⚡ | ⭐⭐⭐ | 2GB | ⭐⭐⭐⭐ | 仅烟雾测试 |
| FLUX.1-schnell | ✅ | ⚡⚡ | ⭐⭐⭐⭐⭐ | 24GB | ⭐⭐ | 显存大 |
| SD3-medium | ⚠️ | ⚡ | ⭐⭐⭐⭐ | 5GB | ⭐⭐ | ROCm 兼容性差 |

## 备注

- IP-Adapter 也选 SDXL 版(`h94/IP-Adapter`)— 见 ADR 0002
- 显存不够时降级到 SD-Turbo,见 `src/models/text2image.py` 的 fallback 逻辑
