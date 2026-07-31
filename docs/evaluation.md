# InventoryDoc Agent — 验收与测试文档

> 版本：v1.0 | 适用阶段：Hackathon MVP & 企业试用

---

## 1. Ground Truth 验收

使用某供应链真实盘点数据，Agent 输出与人工分析完全一致：

| 指标 | Agent 输出 | 人工验证 | 容差 | 状态 |
|---|---|---|---|---|
| SKU 总数 | 528 | 528 | = | ✅ |
| 系统库存总计 | 21,144 件 | 21,144 件 | = | ✅ |
| 复盘总计 | 20,173 件 | 20,173 件 | = | ✅ |
| 净差异 | -971 件 | -971 件 | = | ✅ |
| 总体差异率 | 4.6% | 4.6% | ±0.1% | ✅ |
| 盘亏金额 | -1,146,805.36 元 | -1,146,805.36 元 | < 1 元 | ✅ |
| 盘盈金额 | 156,904.39 元 | 156,904.39 元 | < 1 元 | ✅ |
| 净差异金额 | -989,900.97 元 | -989,900.97 元 | < 1 元 | ✅ |
| 日志关联三分类 | 14 / 21 / 124 | 14 / 21 / 124 | = | ✅ |
| 异常品类识别 | 浴室家具 16.0%（严重异常） | 浴室家具 16.0% | ±0.1% | ✅ |
| 质量校验 | 7/7 通过 | 7/7 通过 | = | ✅ |

## 2. 功能测试

### 2.1 CLI 工作流

```bash
python3 run_full_workflow.py
```

预期验收：
- [ ] 10 步全部 success
- [ ] 质量校验 7/7 通过
- [ ] 输出文件生成：`analysis_result.json`、`盘点差异明细表.xlsx`、`盘点差异分析报告.md`
- [ ] 核心数字与 Ground Truth 一致

### 2.2 Grader 验证

```bash
python3 tests/test_workflow.py
```

预期验收：
- [ ] Test 1: MultiFileRAGEngine 加载文件
- [ ] Test 2: NoiseDetector 噪音检测（68 条 NOISE）
- [ ] Test 3: 基准选择三维论证（选定 02）
- [ ] Test 4: 盘点结果加载（21144 / 20173 / -971 / 4.6%）
- [ ] Test 5: 成本匹配（净差异金额 -989,900.97）
- [ ] Test 6: 质量校验（7 条必须通过）

### 2.3 Web UI

```bash
python3 start_ui.py
```

预期验收：
- [ ] 分析页：输入 `data/input` → 点击分析 → 显示结果
- [ ] 管理层报告页：点击生成 → mock/demo 报告输出
- [ ] 对话页：支持 10+ 类问答，回答带证据引用
- [ ] 端口可配置：`GRADIO_SERVER_PORT=7861 python3 start_ui.py`

### 2.4 管理层报告

```bash
# 演示模式（无需 LLM）
python3 scripts/generate_report.py --demo
# Mock 模式（无需 LLM）
python3 scripts/generate_report.py --mock
# 真实 LLM（需 LLM 服务）
python3 scripts/generate_report.py
```

预期验收：
- [ ] --demo 模式输出完整的 Markdown 报告
- [ ] --demo 模式保存 metadata：`report_generation_metadata.json`
- [ ] --mock 模式输出模拟 LLM 报告
- [ ] 默认模式：LLM 不可达时显示明确的错误信息，不崩溃
- [ ] 三种模式都不改变 `analysis_result.json`

## 3. 异常测试

| 场景 | 测试方法 | 预期 |
|---|---|---|
| 缺少必需文件 | 移除 data/input 中的某个必需文件 | 输入验证失败，不运行工作流 |
| 目录不存在 | 传入无效路径 | 友好错误提示 |
| LLM 不可达 | 不启动 LLM 服务，运行默认 generate_report | 明确错误信息，推荐 --demo/--mock |
| 端口 7860 占用 | GRADIO_SERVER_PORT 设置不同端口 | 绑定指定端口 |
| 空文件 | 放入空 CSV/XLSX | 加载成功（0 行）或显示失败信息 |

## 4. LLM 测试

### 4.1 服务健康检查

```bash
python3 scripts/benchmark_llm.py
```

预期验收：
- [ ] LLM 可达：显示模型列表、推理耗时、chars/sec
- [ ] LLM 不可达：退出码 1，显示明确错误
- [ ] 生成 `data/output/llm_benchmark.json`

### 4.2 报告质量验收

| 检查项 | 标准 |
|---|---|
| 管理层摘要 | 包含核心发现、关键数字 |
| 风险分级 | 覆盖 3 个维度（整体、品类、流程） |
| Top-5 SKU | 与 Excel 明细一致 |
| 行动建议 | 3-5 条可执行建议 |
| 事实错误 | 0 处编造数字 |

## 5. GPU 验收

| 检查项 | 方法 | 证据 |
|---|---|---|
| ROCm 可用 | `rocm-smi` | 截图 |
| LLM 服务可达 | `python3 scripts/benchmark_llm.py` | 模型列表 |
| 推理指标 | benchmark 输出 | latency, chars/sec |
| 报告生成 | `python3 scripts/generate_report.py` | metadata 文件 |

## 6. 安全验收

| 检查项 | 标准 |
|---|---|
| 数据不出域 | 所有数据本地存储和处理 |
| 依赖不上传 | `data/` gitignored |
| 模型文件不上传 | `qwen-model/` `*.gguf` gitignored |
| 敏感信息不暴露 | 无 `.env`、无 API key |
| 无外部 API 调用 | 零云端依赖 |

## 7. 回归测试标准

每次修改后必须验证：

1. `python3 tests/test_workflow.py` 全部通过
2. `python3 run_full_workflow.py` 输出数字与 Ground Truth 一致
3. `python3 scripts/generate_report.py --demo` 正常输出
4. `python3 scripts/generate_report.py --mock` 正常输出
5. UI 可启动、可分析、可对话

## 快速验证命令

```bash
# 一键回归
python3 tests/test_workflow.py && \
python3 run_full_workflow.py && \
python3 scripts/generate_report.py --demo && \
echo "All tests passed"
```

---

> 文档版本：v1.0 | 最后更新：2026-07-29 | 作者：QA Team
