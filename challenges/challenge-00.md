# Challenge 00: 环境搭建与验证

**Estimated Time:** 30 minutes  
**Difficulty:** Setup

## Introduction

供应链单据智能处理系统需要在 AMD Radeon GPU 上运行 LLM 推理。在开始构建之前，必须确保开发环境正确配置，包括 ROCm 驱动、PyTorch GPU 支持、以及必要的 Python 依赖。

本挑战将帮助您验证环境是否就绪，为后续的 Agent 开发奠定基础。

## Prerequisites

- AMD Radeon GPU (推荐 RX 7900 XTX 或更高)
- Ubuntu 22.04 LTS (推荐)
- Python 3.10+
- 基础命令行操作能力

## Description

搭建并验证供应链单据处理系统的开发环境。您的目标是：

1. 确认 AMD GPU 和 ROCm 驱动正确安装
2. 验证 PyTorch 能够使用 GPU 进行计算
3. 安装项目所需的全部 Python 依赖
4. 运行环境检查脚本，确认所有组件就绪

系统必须能够在 GPU 上执行基本的张量运算，且 PyTorch 报告的 GPU 名称应为 AMD Radeon 系列。

## Success Criteria

- [ ] `rocm-smi` 命令能够显示 AMD GPU 信息
- [ ] `python -c "import torch; print(torch.cuda.is_available())"` 返回 `True`
- [ ] `python -c "import torch; print(torch.cuda.get_device_name(0))"` 显示 AMD GPU 名称
- [ ] `pip install -r requirements.txt` 成功完成，无错误
- [ ] 运行 `python scripts/check_env.py` 显示所有检查项通过

## Hints

<details>
<summary>Hint 1 (broad)</summary>
如果您使用的是 Windows，需要通过 WSL2 安装 Ubuntu。ROCm 原生支持 Linux，不直接支持 Windows。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
安装 PyTorch 时需要使用 ROCm 专用的 wheel，而不是 CUDA 版本。访问 PyTorch 官网选择 ROCm 6.x 版本。
</details>

<details>
<summary>Hint 3 (almost there)</summary>
如果 `torch.cuda.is_available()` 返回 False，请检查：
1. ROCm 驱动是否安装：`apt list --installed | grep rocm`
2. 用户是否在 render 和 video 组：`groups $USER`
3. 环境变量是否设置：`echo $ROCR_VISIBLE_DEVICES`
</details>

## Learning Resources

- [AMD ROCm 安装指南](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/)
- [PyTorch ROCm 安装](https://pytorch.org/get-started/locally/)
- [ROCm 兼容 GPU 列表](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/reference/system-requirements.html)

## Advanced Challenge (Optional)

配置 Docker 环境，使用 AMD ROCm 容器运行 PyTorch：
```bash
docker pull rocm/pytorch:latest
docker run --it --privileged --device=/dev/kfd --device=/dev/dri --group-add video rocm/pytorch:latest
```
验证容器内 GPU 可用，并能执行矩阵乘法运算。
