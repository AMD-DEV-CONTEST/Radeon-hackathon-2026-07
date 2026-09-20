# 多轮记忆一致性测试框架

自动验收「量化交易 Agent 在三层记忆架构（工作/情景/语义）下，多轮回话不出现记忆混乱」。
每个场景给出逐轮精准 prompt，按声明式规则自动判定 PASS / FAIL。

## 快速开始

```bash
cd track2-agentic-ai

# ① 框架自检（零依赖，无需 LLM/GPU/网络）—— 10 场景应全 PASS
python -m tests.memory_consistency.runner --adapter mock

# ② 证明判定器能抓错 —— 注入"故意串台"回复，10 场景应全 FAIL
python -m tests.memory_consistency.runner --adapter mock --mock-mode confused

# ③ 接真实 ReAct Agent（AMD ROCm + vLLM 环境）
python -m tests.memory_consistency.runner --adapter react --max-iterations 8

# ④ 只跑关键场景 / 输出 markdown 报告
python -m tests.memory_consistency.runner --adapter mock --scenario S2,S4,S10
python -m tests.memory_consistency.runner --adapter mock --report-out artifacts/memory_report.md
```

pytest 集成（无外部依赖，CI 可直接跑）：

```bash
pytest tests/memory_consistency/ -v
```

## 场景总览

| ID | 场景 | 记忆层 | 核心风险 |
|----|------|--------|---------|
| S1 | 持仓参数记忆 | 工作 | 旧目标价残留 / 数字串台 |
| S2 | 策略参数 + 模糊指代 | 情景 | 静默回测旧版本（不确认歧义） |
| S3 | 跨会话检索 | 语义 | 冷启动丢失 / 数值记错 |
| S4 | 覆盖更新 | 工作 | 新旧仓位叠加 |
| S5 | 多标的防串台 | 工作 | 1680 vs 158 互串 |
| S6 | 观点/事实分离 | 情景 | 把用户观点当市场事实 |
| S7 | 抗干扰 | 工作+情景 | 无关话题导致任务重置 |
| S8 | 撤销生效 | 语义 | 撤销后 -8% 残留 |
| S9 | 多策略并行隔离 | 情景 | 改 A 联动污染 B |
| S10 | 最新指令优先 | 情景 | 冲突指令叠加（既多又空） |

## 判定规则（scenarios.json 内声明式）

- `must_contain`：每个关键词都必须出现
- `must_contain_any`：至少命中一个；也可写多组 `[["a","b"],["c"]]`，每组至少命中一个
- `must_not_contain`：出现任一即失败（防残留/串台）
- `require_confirm` + `confirm_keywords`：歧义场景必须确认或声明版本，否则判失败（防静默猜测）

## 适配器

- **mock**（`adapters/mock.py`）：`correct` 用理想回复 → 全 PASS，验证框架正确；
  `confused` 用典型记忆混乱回复 → 全 FAIL，验证判定器能抓错。
- **react**（`adapters/react.py`）：延迟 import `src.agent.core`，包装
  `run_agent_loop`。同一 session 累积 `[user, assistant]` 历史（AgentMemory 每次重建）；
  跨 session 重置历史但共享 `AGENT_MEMORY_DIR`（runner 每场景隔离到临时目录）——
  恰好验证 Tier-3 语义记忆的持久化。

## ✅ 架构缺口已修复（2026-08-02）

早期评测发现的三个缺口已全部补上，新增 `tests/test_memory_extract.py`（11 项）验证：

| 缺口 | 修复 | 验证 |
|------|------|------|
| S3：显式偏好（风险偏好/回撤容忍）不被持久化 | 新增 `src/agent/memory_extract.py`：白名单规则从对话提取 → `update_preferences` → 跨会话持久化；`core.py` 每轮用户消息后调用 | `test_cross_session_retrieval_s3` |
| S8：规则撤销不生效 | `SemanticMemory.remove_preference()` + 撤销动词检测（取消/撤销/不用…）；`format_for_prompt` 扩展输出自定义偏好 | `test_cancellation_persists_s8` |
| S2：LLM 静默猜测版本 | `prompts.py` 新增 `MEMORY_GUIDELINES` 六条守则（模糊指代先确认、最新值优先、观点/事实分离等），注入 REACT 系统提示 | 冒烟：渲染后守则唯一注入 |

防误伤设计：提取只认白名单短语（风险偏好/单日回撤/止损线），查询语句、用户观点、仓位等会话态一律不提取（`test_no_extract_on_queries/opinions/position_state`）。

## 使用

```bash
# 全量回归（新增 11 项 + 框架自检 3 项 + 现有 78 项）
pytest tests/test_memory_extract.py tests/memory_consistency/ tests/test_agent.py -q
```
