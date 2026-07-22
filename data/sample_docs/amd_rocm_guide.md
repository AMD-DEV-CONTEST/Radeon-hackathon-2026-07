# AMD ROCm 平台简介

## 什么是 ROCm

ROCm（Radeon Open Compute）是 AMD 推出的开源 GPU 计算平台，类似于 NVIDIA 的 CUDA。
ROCm 支持主流的 AI/ML 框架，包括 PyTorch、TensorFlow 和 JAX。

## 支持的 GPU

- AMD Radeon RX 7900 XTX
- AMD Radeon RX 7900 XT
- AMD Radeon RX 7800 XT
- AMD Radeon PRO W7900
- AMD Instinct MI250X/MI300X

## 安装 ROCm

```bash
# Ubuntu 22.04
sudo apt update
sudo apt install -y wget gnupg2
wget -qO - https://repo.radeon.com/rocm/rocm.gpg.key | sudo apt-key add -
echo 'deb [arch=amd64] https://repo.radeon.com/rocm/apt/6.0 jammy main' | sudo tee /etc/apt/sources.list.d/rocm.list
sudo apt update
sudo apt install -y rocm-dev
```

## PyTorch with ROCm

```python
import torch
print(torch.cuda.is_available())  # True
print(torch.version.hip)  # 显示 ROCm 版本
```

## 优势

- 开源：完整的开源软件栈，无供应商锁定
- 性能：针对大模型推理优化，支持 FP16/BF16
- 生态：兼容主流 AI 框架，迁移成本低
