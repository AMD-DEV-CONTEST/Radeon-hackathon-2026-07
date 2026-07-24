# Challenge 08: 性能优化与部署

**Estimated Time:** 90 minutes  
**Difficulty:** Expert

## Introduction

系统功能已经完整，但在生产环境中还需要考虑：

- **性能优化**：减少推理延迟，提高吞吐量
- **资源管理**：优化 GPU 显存使用
- **部署配置**：支持容器化部署
- **监控告警**：实时监控系统状态

本挑战将对系统进行全面优化，使其达到生产就绪状态。

## Prerequisites

- Challenge 07 完成 (Web UI)
- 完整的系统功能

## Description

优化供应链单据处理系统。您的目标是：

1. 实现 FP16 混合精度推理
2. 配置 vLLM 批处理参数
3. 优化 GPU 显存使用
4. 创建 Docker 部署配置
5. 实现系统监控

系统应在保持准确率的同时，显著提升处理性能。

## Success Criteria

- [ ] 实现 FP16 推理，GPU 显存占用 < 12GB
- [ ] 配置批处理参数，支持并发请求
- [ ] 单张处理时间 < 30 秒
- [ ] 创建可运行的 Docker 镜像
- [ ] 实现基本的性能监控（GPU 使用率、请求延迟）
- [ ] 编写性能测试报告

## Hints

<details>
<summary>Hint 1 (broad)</summary>
FP16 混合精度可以通过 PyTorch 的 `torch.float16` 或 `torch.bfloat16` 实现。在加载模型时指定 dtype。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
vLLM 批处理配置：
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct \
  --dtype half \
  --max-num-seqs 16 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.9
```
</details>

<details>
<summary>Hint 3 (almost there)</summary>
GPU 监控可以使用 `nvidia-smi` 或 Python 的 `pynvml` 库：
```python
import torch

def get_gpu_stats():
    if torch.cuda.is_available():
        return {
            "gpu_name": torch.cuda.get_device_name(0),
            "memory_used": torch.cuda.memory_allocated(0) / 1024**3,
            "memory_total": torch.cuda.get_device_properties(0).total_mem / 1024**3,
        }
    return None
```
</details>

## Learning Resources

- [FP16 训练指南](https://pytorch.org/docs/stable/amp.html)
- [vLLM 性能调优](https://docs.vllm.ai/en/latest/performance/benchmarking.html)
- [Docker 最佳实践](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- [PyTorch 显存管理](https://pytorch.org/docs/stable/notes/cuda.html#memory-management)

## Advanced Challenge (Optional)

实现生产级部署：
- 配置 Kubernetes 部署清单
- 实现自动扩缩容 (HPA)
- 集成 Prometheus 监控
- 配置日志收集 (ELK Stack)
