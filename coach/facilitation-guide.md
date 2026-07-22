# 教练引导指南

## 活动概述

**主题**: AMD AI DevMaster Hackathon - Supply Chain DocAgent  
**时长**: 约 6 小时  
**参赛者水平**: 中级 AI/ML 开发者

## 时间安排

| 时间段 | 挑战 | 内容 |
|--------|------|------|
| 0:00 - 0:30 | Challenge 00 | 环境搭建与验证 |
| 0:30 - 1:00 | Challenge 01 | LLM 推理服务部署 |
| 1:00 - 1:40 | Challenge 02 | RAG 引擎构建 |
| 1:40 - 1:50 | - | 休息 |
| 1:50 - 2:35 | Challenge 03 | 单据分类 Agent |
| 2:35 - 3:20 | Challenge 04 | 字段提取 Agent |
| 3:20 - 3:30 | - | 休息 |
| 3:30 - 4:30 | Challenge 05 | 三单校验引擎 |
| 4:30 - 5:30 | Challenge 06 | 多 Agent 编排 |
| 5:30 - 5:40 | - | 休息 |
| 5:40 - 6:25 | Challenge 07 | Web UI 集成 |
| 6:25 - 7:55 | Challenge 08 | 性能优化与部署 |

## 每个挑战的教练要点

### Challenge 00: 环境搭建

**常见问题**:
- ROCm 驱动未正确安装
- PyTorch 安装了 CUDA 版本而非 ROCm 版本
- 用户未加入 render/video 组

**检查点**:
```bash
rocm-smi
python -c "import torch; print(torch.cuda.is_available())"
```

**辅导策略**:
- 如果 GPU 不可用，引导检查 `dmesg | grep amdgpu`
- 推荐使用 Docker 环境作为备选方案

---

### Challenge 01: LLM 推理服务

**常见问题**:
- 模型下载失败
- GPU 显存不足
- vLLM 启动错误

**检查点**:
```bash
curl http://localhost:8000/v1/models
curl http://localhost:8000/v1/chat/completions -d '...'
```

**辅导策略**:
- 如果显存不足，建议使用 4-bit 量化
- 提供离线模型下载方案

---

### Challenge 02: RAG 引擎

**常见问题**:
- BGE 模型下载失败
- 文档分块过大或过小
- 向量索引构建失败

**检查点**:
```python
query_engine = index.as_query_engine()
response = query_engine.query("测试查询")
print(response)
```

**辅导策略**:
- 引导调整 `chunk_size` 和 `chunk_overlap` 参数
- 提供预处理的文档向量作为参考

---

### Challenge 03: 单据分类

**常见问题**:
- Prompt 设计不当导致分类不准确
- LLM 返回格式不符合预期
- 未知类型处理不当

**检查点**:
- 上传 `po_sample.txt`，验证返回 `purchase_order`
- 上传 `delivery_sample.txt`，验证返回 `delivery_note`

**辅导策略**:
- 提供 Prompt 模板示例
- 引导添加 Few-shot 示例

---

### Challenge 04: 字段提取

**常见问题**:
- JSON 解析失败
- 字段名不匹配
- 数据类型错误

**检查点**:
```python
result = agent.extract(content, "purchase_order")
assert "po_number" in result
assert "quantity" in result
```

**辅导策略**:
- 提供 JSON 解析的错误处理代码
- 引导使用正则表达式提取 JSON

---

### Challenge 05: 三单校验

**常见问题**:
- 数值比较精度问题
- 容差设置不当
- 规则匹配逻辑错误

**检查点**:
- 使用 `delivery_sample_mismatch.txt` 测试异常检测
- 验证数量差异被正确识别

**辅导策略**:
- 提供数值比较的代码框架
- 引导使用 `Decimal` 类型处理精度

---

### Challenge 06: 多 Agent 编排

**常见问题**:
- Agent 间数据传递错误
- 异常处理流程不完整
- 执行顺序混乱

**检查点**:
- 上传三份单据，验证完整处理流程
- 检查校验结果是否正确触发后续流程

**辅导策略**:
- 提供编排器的代码框架
- 引导设计清晰的数据流转机制

---

### Challenge 07: Web UI

**常见问题**:
- Gradio 端口冲突
- 文件上传处理错误
- 界面响应慢

**检查点**:
- 访问 `http://localhost:7860`
- 上传文件并查看处理结果

**辅导策略**:
- 提供 Gradio 基础代码模板
- 引导优化异步处理

---

### Challenge 08: 性能优化

**常见问题**:
- FP16 精度问题
- 批处理参数不当
- Docker 构建失败

**检查点**:
- GPU 显存占用 < 12GB
- 单张处理时间 < 30 秒
- Docker 镜像成功运行

**辅导策略**:
- 提供性能基准测试脚本
- 引导分析 GPU 使用率

---

## 处理落后的团队

1. **识别瓶颈**: 确定团队卡在哪个挑战
2. **提供提示**: 给出该挑战的 Hint 2 或 Hint 3
3. **简化目标**: 如果时间不足，建议跳过 Advanced Challenge
4. **提供代码片段**: 对于基础薄弱的团队，提供部分代码框架

## 处理超前的团队

1. **鼓励 Advanced Challenge**: 引导完成挑战的扩展部分
2. **代码审查**: 提供代码质量反馈
3. **架构优化**: 讨论生产级部署方案
4. **创新扩展**: 鼓励添加新功能（如图像识别）

## 常见技术问题

### ROCm 相关
- Q: `torch.cuda.is_available()` 返回 False
- A: 检查 ROCm 驱动、用户组、环境变量

### vLLM 相关
- Q: 模型加载失败
- A: 检查 GPU 显存、模型路径、网络连接

### LangChain 相关
- Q: Agent 执行报错
- A: 检查 API Key、模型配置、Prompt 格式

## 评估要点

| 维度 | 权重 | 评估内容 |
|------|------|----------|
| 功能完整性 | 30% | 所有挑战完成度 |
| 代码质量 | 20% | 代码结构、错误处理、可读性 |
| 性能表现 | 20% | 推理速度、资源使用 |
| 创新性 | 15% | 项目创意、扩展功能 |
| 文档完整 | 15% | README、技术报告、演示视频 |
