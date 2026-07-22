# Challenge 01: LLM 推理服务部署

**Estimated Time:** 30 minutes  
**Difficulty:** Easy

## Introduction

供应链单据处理的核心是理解非结构化文档内容。我们需要一个强大的语言模型来完成单据分类、字段提取等任务。

vLLM 是一个高性能的 LLM 推理引擎，支持 AMD GPU 和 ROCm。本挑战将帮助您部署 Llama-3.1-8B 模型，为后续的 Agent 开发提供推理服务。

## Prerequisites

- Challenge 00 完成
- 至少 16GB GPU 显存 (推荐 24GB)

## Description

部署一个基于 vLLM 的 LLM 推理服务。您的目标是：

1. 安装 vLLM 和相关依赖
2. 下载 Llama-3.1-8B-Instruct 模型
3. 启动 vLLM 服务，配置 ROCm 后端
4. 验证服务能够接受请求并返回响应

服务应监听本地端口，支持 OpenAI 兼容的 API 格式。

## Success Criteria

- [ ] vLLM 服务成功启动，无错误日志
- [ ] 模型加载完成，显示 GPU 显存占用
- [ ] 使用 `curl` 发送测试请求，返回有效响应
- [ ] 响应时间在可接受范围内 (< 5 秒/请求)
- [ ] 服务支持 streaming 输出

## Hints

<details>
<summary>Hint 1 (broad)</summary>
vLLM 支持通过命令行启动服务，指定模型名称和 GPU 设备。查看 vLLM 文档了解 `vllm serve` 命令。
</details>

<details>
<summary>Hint 2 (more specific)</summary>
启动命令格式：
```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --device cuda --dtype half
```
如果使用 AMD GPU，确保 `ROCR_VISIBLE_DEVICES` 环境变量正确设置。
</details>

<details>
<summary>Hint 3 (almost there)</summary>
测试请求可以使用 curl：
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "meta-llama/Llama-3.1-8B-Instruct", "messages": [{"role": "user", "content": "Hello"}]}'
```
</details>

## Learning Resources

- [vLLM 文档](https://docs.vllm.ai/)
- [vLLM ROCm 支持](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/rocm.html)
- [Llama-3.1 模型卡](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct)

## Advanced Challenge (Optional)

配置 vLLM 的批处理参数，优化吞吐量：
- 调整 `--max-num-seqs` 参数
- 启用 `--enforce-eager` 模式测试
- 测量不同并发数下的请求延迟
