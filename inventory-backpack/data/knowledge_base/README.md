# AMD Radeon GPU 技术简介

## 概述

AMD Radeon 是 AMD 公司推出的图形处理器产品线，广泛应用于游戏、专业可视化和人工智能领域。

## ROCm 平台

ROCm（Radeon Open Compute）是 AMD 的开源 GPU 计算平台，支持：

- **HIP**：类 CUDA 的编程接口
- **MIOpen**：深度学习库
- **rocBLAS/rocFFT**：基础数学库

## 主要型号

| 型号 | 架构 | 显存 | 适用场景 |
|------|------|------|----------|
| RX 7900 XTX | RDNA 3 | 24GB | 高端游戏、AI推理 |
| RX 7900 XT | RDNA 3 | 20GB | 高端游戏 |
| RX 7800 XT | RDNA 3 | 16GB | 中高端游戏 |
| RX 7600 | RDNA 3 | 8GB | 主流游戏 |

## AI 推理优化

AMD Radeon GPU 在 AI 推理方面的优化技术：

1. **量化支持**：INT8/INT4 量化减少显存占用
2. **内存优化**：通过环境变量调整显存分配
3. **并行计算**：利用大量计算单元加速矩阵运算

## 参考资料

- AMD 官网：https://www.amd.com
- ROCm 文档：https://rocm.docs.amd.com