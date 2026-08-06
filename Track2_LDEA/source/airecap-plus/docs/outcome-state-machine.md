# Outcome 状态机 + 聚合规则（S→M 档）

> 目标：在会话进行中维护“实际做成了什么”的可核验账本。  
> 原则：规则判真伪与升降级；LLM 只做命名、归并建议、叙事。  
> L0 不可变；L1 可重算；L2 只投影。  
> **决策已锁定**（见文末 §12）。`RULES_VER = rules@1.2`。

---

## 0. 实体与字段（规则依赖的最小模型）

### 0.1 Event（L0，append-only）

```text
Event {
  id:            string
  ts:            datetime
  session_id:    string
  actor:         user | agent | tool | system
  kind:          goal_set | claim_made | file_change | command_result
                 | test_result | decision_made | verification_result
                 | blocker_found | outcome_upsert | compact
  payload:       object          // kind-specific，见附录 A
  refs:          Ref[]           // file/commit/test/message/url...
  signal:        high | low      // 默认由 kind 推导，可覆盖
}
```

**S 档只消费 `signal=high`。** low-signal（普通 read/search）留 L0，不进热路径聚合。

### 0.2 Goal

```text
Goal {
  id:                 string
  session_id:         string
  stable_key:         string?         // 跨 session 可选，如 "epic:auth"
  statement:          string
  success_criteria:   string[]
  non_goals:          string[]
  status:             open | achieved | abandoned | superseded
  outcome_ids:        string[]
  supersedes:         string?         // 被替代的旧 goal id
  created_at:         datetime
  updated_at:         datetime
}
```

### 0.3 OutcomeCandidate（L1 真相源）

```text
OutcomeCandidate {
  id:                 string
  session_id:         string
  goal_id:            string?
  stable_key:         string?         // 跨 session，如 "feature:oauth-login"
  type:               feature | bugfix | problem | decision | spike
                      | refactor | chore | docs | investigation
  title:              string
  status:             claimed | evidenced | verified
                      | contradicted | abandoned | superseded
  confidence:         float           // 0.0 ~ 1.0，§3.3 clamp 后展示值
  confidence_raw:     float           // §3.2 公式输出（clamp 前）
  clamp_reason:       none | ceiling_claimed | floor_evidenced
                      | ceiling_evidenced | floor_verified
                      | ceiling_contradicted | feat_verified_cap
  evidence_links:     EvidenceLink[]
  counter_evidence:   EvidenceLink[]
  scope:              Scope
  started_at:         datetime
  updated_at:         datetime
  verified_at:        datetime?
  terminal_reason:    string?         // abandoned/contradicted/superseded 时必填
  merge_of:           string[]        // 被合并进来的旧 id
  superseded_by:      string?
  aggregator_version: string          // 如 "rules@1.2"
  summary_blob:       string          // 短摘要，供增量 LLM / recap
  links:              { issue?, pr?, commit?, test? }
  tags:               string[]
}

// SessionStore 焦点（L1 快照字段，非 Outcome 内嵌）
// focus_outcome_id: string?   // 当前 work-stream；见 §4.0

EvidenceLink {
  event_id:     string
  relation:     supports | refutes | defines | verifies | scopes
  method:       structured | user | focus | time_scope | llm
  confidence:   float                 // 该条关联自身的置信度
  note:         string?
}

Scope {
  paths:        string[]              // 文件/目录 glob
  symbols:      string[]
  services:     string[]
  commands:     string[]              // 关联的 repro/test 命令
}
```

### 0.4 类型职责（避免把 progress 当原子 outcome）

| type | 含义 | 典型强信号 |
|------|------|------------|
| feature | 新增用户/系统可观察能力 | 新入口、新 API、新页面、新模型 + 测试 |
| bugfix | 修复缺陷 | fail→pass 闭环 |
| problem | 解决阻塞（环境/集成/设计卡点） | blocker + 解法 + 验证 |
| decision | 关键取舍（含被否决方案） | decision_made + 后续遵从证据 |
| spike / investigation | 探查，结论可无代码 | 有结论/有否决即可 |
| refactor | 无行为变化的结构改善 | diff 大、无新入口、测试保持绿 |
| chore | 工具链/依赖/CI/配置 | 构建/配置文件变化 |
| docs | 文档 | 仅文档路径 |

**progress 不是 type。**  
`Goal` 的进度由子 outcome 聚合投影（见 §6）。

---

## 1. 状态机

### 1.1 状态定义

| 状态 | 含义 | 是否终端 | 能否进 recap“做成了” |
|------|------|----------|----------------------|
| `claimed` | 仅有口头/文本声明，无足够状态差分 | 否 | 否（最多进“声称”区） |
| `evidenced` | 有相关状态差分支撑，尚未闭合验证 | 否 | 谨慎：标为“有证据，未验证” |
| `verified` | 验证闭合，可信完成 | **是**（可被后期 contradicted 拉回） | **是** |
| `contradicted` | 曾成立的证据被推翻/回滚/复现仍在 | 是（可复活，见下） | 否；进“曾声称/已推翻” |
| `abandoned` | 明确放弃或目标切换后不再推进 | 是 | 否；进“未完成/放弃” |
| `superseded` | 被更准确的 outcome 替代（merge/重述） | 是 | 否；不展示或折叠进新 outcome |

> **设计选择：`verified` 不是绝对终态。**  
> 允许 `verified → contradicted`（回归、复现重现、revert）。  
> 这是“可核验账本”的必要诚实性；L2 应用时间限定语（“当时验证通过，后回归”）。

### 1.2 合法转移

```text
                 claim_made
                     │
                     ▼
                 claimed
                /   |   \
               /    |    \
              /     |     \
             ▼      ▼      ▼
        evidenced  abandoned  superseded
           │  \        ^          ^
           │   \       │          │
           │    \──────┼──────────┘
           │           │
           ▼           │
       verified ───────┤
           │           │
           ▼           │
     contradicted ─────┘  (也可 → abandoned)

特殊：
  claimed      → verified     仅当验证事件强绑定且允许跳过 evidenced（见 R-V2）
  evidenced    → claimed      禁止（不降回 claimed；证据不足用 confidence 表达）
  contradicted → evidenced    允许：新 patch 再次提供证据（复活）
  contradicted → verified     允许：复活后再次验证闭合
  superseded   → *            禁止（终态；历史保留）
  abandoned    → evidenced    默认禁止；仅 user 显式 reopen（R-AB3）
```

### 1.3 状态图（简）

```text
                    ┌──────────────┐
                    │   claimed    │
                    └──────┬───────┘
               evidence    │     abandon / supersede
               enough      │
                    ▼      ▼
              ┌──────────┐   ┌───────────┐   ┌────────────┐
              │evidenced │──▶│ abandoned │   │ superseded │
              └────┬─────┘   └───────────┘   └────────────┘
                   │ verify                 ▲
                   ▼                        │ merge/replace
              ┌──────────┐                  │
              │ verified │──────────────────┘
              └────┬─────┘
                   │ refute / regress
                   ▼
              ┌──────────────┐
              │ contradicted │──(new evidence)──▶ evidenced ──▶ verified
              └──────────────┘
```

---

## 2. 转移规则表

约定：

- **匹配**按表顺序；同一事件可触发多条，但同一 outcome 同一 tick 只取最高优先级转移。
- **绑定**指 event 与 outcome 之间存在 `EvidenceLink`（见 §4）。
- `conf(link)` = 该 link 的 confidence；`max_support` = 所有 supports link 的 conf 最大值。

### 2.1 进入 / 创建

| ID | 触发事件 | 条件 | 动作 |
|----|----------|------|------|
| R-C1 | `claim_made` | 无法绑定到已有 open outcome（§4 匹配失败） | 新建 outcome，`status=claimed`，`confidence=C_claim` |
| R-C2 | `claim_made` | 绑定到已有 outcome | 追加 supports link；不改 status；重算 confidence |
| R-C3 | `file_change` / `test_result` / `command_result` | 无 claim，但 scope 形成清晰工作簇且无法归属 | 新建 outcome，`status=evidenced`，`type` 先标 `chore` 或待 LLM，`confidence=C_orphan_ev` |
| R-C4 | `goal_set` | 新 goal | 建/更新 Goal；**不**直接建 outcome |
| R-C5 | `decision_made` | 无法绑定 | 新建 `type=decision`，`status=claimed`；若 payload 含后续遵从 scope，待 evidence |

> **R-C3 是双刃剑**：能抓住“没喊完成但改了很多”的工作，也可能制造碎片。  
> S 档默认 **关闭**；M 档开启，并依赖 §5 merge 收束。

### 2.2 claimed → evidenced

| ID | 触发 | 条件 | 动作 |
|----|------|------|------|
| R-E1 | `file_change` | 绑定成功且 `method ∈ {structured,user,focus,time_scope}` 且 diffstat 非空（或 path 集合非空） | → evidenced；加 supports |
| R-E2 | `command_result` | 绑定成功，且命令属 mutation/build（非纯 read），exit code 有意义 | → evidenced |
| R-E3 | `test_result` | 绑定成功（哪怕仍 fail） | → evidenced（“有动作”）；**不**升 verified |
| R-E4 | 多条 weak link | `sum(conf of supports) ≥ T_evidence` 且至少 1 条 `method≠llm` | → evidenced |

**不升 evidenced 的情况：**

- 仅有 LLM 软关联（`method=llm`）→ 保持 claimed，confidence 可小幅上调
- 仅文档/注释 diff 且 type 声明为 feature/bugfix → 保持 claimed 或转 type=docs（R-T1）
- file_change 随后立刻被同 session revert，且无净 diff（R-X1 先处理）

### 2.3 → verified（核心）

验证必须**闭合**。口头“好了”不够。

| ID | 触发 | 条件 | 动作 |
|----|------|------|------|
| R-V1 | `test_result` | outcome.type=bugfix（或 problem 且 scope.commands 命中）；存在同 repro/test 的先前 fail 事件；当前 pass；两条均绑定到该 outcome | → verified；`verified_at=now`；加 verifies link |
| R-V2 | `verification_result` | `payload.verdict=pass` 且绑定 method∈{structured,user,focus}；若 actor=agent 自报，还需至少 1 条非 claim 的 supports evidence | → verified |
| R-V3 | `command_result` | outcome 声明了 repro 命令；before 输出匹配 fail 模式，after 匹配 pass 模式（启发式，见附录 B）；绑定成功 | → verified |
| R-V4 | `test_result` 集合 | type=feature/refactor；**新增或关联测试 pass**，且无 open 的 contradict；可选：build/lint clean | → verified，但 `confidence` 上限 `C_feat_verified_cap`（默认低于 bugfix 闭环） |
| R-V5 | 用户显式 | `verification_result` actor=user, verdict=pass | → verified（最高优先级，可覆盖 agent 自报） |

**明确不升 verified：**

| ID | 情形 |
|----|------|
| R-VX1 | 仅 `claim_made` 含“已完成/已修复” |
| R-VX2 | 仅有 patch/`file_change`，无测试/复现/验收 |
| R-VX3 | test pass 但与 outcome.scope 无交集且无 structured 绑定 |
| R-VX4 | verification_result.verdict=pass 但 actor=agent 且 outcome 仍无任何 file/test/command 证据 |
| R-VX5 | type=decision/spike/investigation：默认 **不走 verified**，改用 `status=evidenced` + `payload.conclusion` 或升为特殊闭合（见 R-V6） |

| ID | 触发 | 条件 | 动作 |
|----|------|------|------|
| R-V6 | `decision_made` 或 claim 含结论 | type∈{decision,spike,investigation}；有 conclusion 文本；可选：后续 file_change 遵从该 decision | → **evidenced**（结论型闭合）；若 user verification pass → verified |

> **bugfix 的 verified 金标准：fail→pass 同锚点。**  
> feature 的 verified 更弱，必须在 L2 文案上区分“测试覆盖的完成”vs“行为已观察到”。

### 2.4 → contradicted

| ID | 触发 | 条件 | 动作 |
|----|------|------|------|
| R-X1 | `file_change` | revert/rollback：净撤销该 outcome.scope 内先前变更（git revert 或 diff 反向高重叠） | 若原 verified/evidenced → contradicted；加 refutes |
| R-X2 | `test_result` | 同锚点测试由 pass 变 fail（回归） | verified/evidenced → contradicted |
| R-X3 | `verification_result` | verdict=fail，绑定成功 | → contradicted |
| R-X4 | `claim_made` | 用户/agent 明确否定先前完成声明（“没修好/打回”） | 加 refutes；若 max_support 被削弱到阈值下，evidenced→ 保持但 confidence 降；verified→contradicted 需 R-X2/X3 或 user 否定 |
| R-X5 | `blocker_found` | blocker 表明先前 verification 前提不成立 | 降 confidence；verified 不自动降，除非伴随 X2/X3 |

**复活：**

| ID | 触发 | 条件 | 动作 |
|----|------|------|------|
| R-R1 | 新 `file_change`/`test_result` | status=contradicted 且新 supports `method≠llm` | → evidenced；清空 verified_at |
| R-R2 | 再闭合验证 | 在 R-R1 之后再次满足 R-V* | → verified |

### 2.5 → abandoned

| ID | 触发 | 条件 | 动作 |
|----|------|------|------|
| R-AB1 | `goal_set` / `decision_made` | 新 goal 声明放弃旧方向，或 user 说“先不做了” | 相关 open outcomes → abandoned；`terminal_reason` 必填 |
| R-AB2 | session end | outcome 仍 `claimed`，**无任何** supports evidence（`method≠llm` 计数为 0），且 session 正常结束 | → `abandoned`；`terminal_reason="session_end_unevidenced_claim"` |
| R-AB2b | session end | outcome 为 `claimed` 但已有 evidence_links（异常：按理应已升 evidenced） | 先补升 `evidenced` 再结束；不 abandoned |
| R-AB2c | session end | `evidenced` / `verified` / `contradicted` | **不**因 session end 改变 status |
| R-AB3 | user reopen | 显式恢复已 abandoned | → claimed 或 evidenced（取决于是否仍有 evidence） |

### 2.6 → superseded（见 §5 merge/replace）

由 merge/replace 协议写入，不由零散事件直接跳转。

---

## 3. Confidence 公式

Confidence 表示：**“该 outcome 在当前 status 语义下，内容与完成度可信的程度”**，不是概率精算。  
用于排序、过滤、L2 措辞，**不单独决定 status**（status 由 §2 规则决定）。

**rules@1.2 拆分（可观测性，不改判定语义）：**

| 字段 | 含义 |
|------|------|
| `confidence_raw` | §3.2 公式输出（仅做 0..1 边界） |
| `confidence` | §3.3 clamp / cap 后的**展示值**（对外默认读这个） |
| `clamp_reason` | 本次从 raw → display 应用了哪条规则；无调整则为 `none` |

调参与回放审计看 `confidence_raw` + `clamp_reason`；L2/UI 排序仍用 `confidence`，且应 **先按 status 分区再排序**。  
**不在 1.2 删除 clamp**——等有 raw 分布数据再决定是否放宽或去掉。

### 3.1 分量

```text
S_claim   = 1 若存在 actor∈{user,agent} 的 claim supports，否则 0
S_struct  = max conf of supports where method=structured   // 0~1
S_focus   = max conf of supports where method=focus        // 0~1
S_scope   = max conf of supports where method=time_scope   // 0~1
S_llm     = max conf of supports where method=llm          // 0~1
S_user    = max conf of supports where method=user         // 0~1
R_refute  = max conf of counter_evidence / refutes         // 0~1
V_closed  = 1 若 status=verified，否则 0
N_support = min(1, count(supports with method≠llm) / 3)   // 证据条数饱和
T_fresh   = exp(-age_hours / τ)                            // 新鲜度，τ 默认 72h
```

### 3.2 合成（权重，aggregator v1.2）

```text
base = 0.10
     + 0.15 * S_claim
     + 0.30 * S_struct
     + 0.25 * S_focus          # focus 强于纯 time_scope，弱于 structured
     + 0.15 * S_scope
     + 0.05 * S_llm
     + 0.20 * S_user
     + 0.10 * N_support

# 验证加成
if V_closed:
  base = base + 0.25

# 反证惩罚（非线性）
base = base * (1 - 0.8 * R_refute)

# 新鲜度：仅 claimed 衰减（跨天任务不误伤 evidenced）
# verified / contradicted / abandoned / superseded 不因时间自动降
if status == claimed:
  base = base * (0.7 + 0.3 * T_fresh)

confidence_raw = clamp(base, 0.0, 1.0)
# 再经 §3.3 → confidence + clamp_reason
```

> 权重和仍可能 >1，最终靠 0..1 clamp 与 §3.3；这是有意保留的“饱和后靠 status 带宽”结构。  
> `S_focus` 与 `S_struct` 同时存在时各取 max，不互斥。

### 3.3 与 status 的耦合约束（防止分数和状态打架）

对 `confidence_raw` 应用下表，得到 `confidence` 与 `clamp_reason`：

| status | confidence 展示区间 | 强制规则 | clamp_reason |
|--------|---------------------|----------|--------------|
| claimed | 0.05 ~ 0.45 | 若 raw >0.45 → 0.45（有强证据应已升 evidenced） | `ceiling_claimed` |
| evidenced | 0.30 ~ 0.75 | raw <0.30 且无 refute → 0.30；raw >0.75 且未 verified → 0.75 | `floor_evidenced` / `ceiling_evidenced` |
| verified | 0.70 ~ 1.00 | 下限 0.70；若 R_refute>0.5 应先走 contradicted，而不是低分 verified | `floor_verified` |
| contradicted | 0.00 ~ 0.40 | 上限 0.40 | `ceiling_contradicted` |
| abandoned / superseded | 冻结最后一分，或标 n/a | 不再参与热更新 | 保持终态前 reason |

附加 cap：

```text
if type=feature and status=verified and confidence > C_feat_verified_cap:
  confidence = C_feat_verified_cap
  clamp_reason = feat_verified_cap   # 优先于 floor_verified 的“上限”语义
```

若仅做了 `clamp(raw,0,1)` 且未触发表内规则：`clamp_reason = none`，`confidence = confidence_raw`。

```text
recalc(O):
  raw = formula_3_2(O)
  O.confidence_raw = raw
  O.confidence, O.clamp_reason = apply_status_clamp(O.status, O.type, raw, O)
```

### 3.4 常数默认值

```text
C_claim            = 0.20
C_orphan_ev        = 0.35
C_feat_verified_cap= 0.85
C_focus_bind       = 0.90          // method=focus 的 EvidenceLink.conf
T_evidence         = 0.50          // weak links 升 evidenced 阈值
T_bind_auto        = 0.60          // 自动绑定最低 conf（time_scope）
T_bind_llm         = 0.75          // LLM 绑定采纳阈值（更高）
T_merge_sim        = 0.80          // 自动 merge 相似度
τ (tau_hours)      = 72
```

---

## 4. 事件 ↔ Outcome 绑定规则

绑定质量直接决定整套系统是否可信。  
**事后 time_scope 是最弱一环**；rules@1.2 用 session 级 `focus_outcome_id` 把“当前在做哪件”变成结构化输入，避免并行工作流下纯时间窗误绑。

### 4.0 focus_outcome_id（work-stream 焦点）

`SessionStore.focus_outcome_id`：可选，指向本 session 一个非 `superseded` 的 outcome。

**写入（热路径规则，无 LLM）：**

| 触发 | 动作 |
|------|------|
| R-C1 新建 outcome（claim） | `focus_outcome_id = new.id` |
| R-C5 新建 decision outcome | 同上 |
| `claim_made` 带 `outcome_id` 且绑定成功 | `focus_outcome_id = that id` |
| `claim_made` 带 `title_hint`/`scope_hint` 建新 outcome | focus → 新 id |
| user 显式指定（payload 或 upsert） | focus → 指定 id |
| focus 指向的 outcome → `abandoned` / `superseded` | **clear** focus |
| `session_end` | **clear** focus |
| merge  survivor = focus 源之一 | focus → survivor id |
| verified / evidenced / contradicted | **不**自动 clear（可继续挂验证/回归） |

**不是**完整 multi-agent；同一时刻一个 focus。并行两件事时，应靠新 claim / 显式切换刷新 focus；未切换时后续无 `outcome_id` 的事件会绑到旧 focus——这比 silent time_scope 误绑可解释，且可用下一次 claim 纠正。

工具/IDE 适配层应尽量在 `file_change` / `test_result` / `command_result` / `verification_result` 上填写 `payload.outcome_id`（method=structured）；focus 是 **缺省回退**，不是替代 structured。

### 4.1 方法优先级

```text
structured > user > focus > time_scope > llm
```

| method | 定义 | conf 指引 |
|--------|------|-----------|
| structured | 事件显式带 `outcome_id` / `claim_id` / `stable_key` | 0.95 ~ 1.0 |
| user | 用户指定“这是在做 X” | 0.90 ~ 1.0 |
| focus | 事件无 structured id，但 `store.focus_outcome_id` 指向仍可绑定的 outcome | `C_focus_bind`（默认 0.90） |
| time_scope | claim 后时间窗 W 内 + path/symbol 与 outcome.scope 重叠 | 见 §4.2 |
| llm | 模型建议关联 | 模型自报 × 0.6，且 ≤0.7 |

**热路径 bind 序：**

```text
bind(E):
  if E.payload.outcome_id → structured（校验 outcome 存在且可写）
  else if user 显式指定 → user
  else if store.focus_outcome_id 存在
       and focus outcome status ∈ {claimed, evidenced, verified, contradicted}
       and （可选）E 与 focus.scope 不硬冲突*
    → method=focus, conf=C_focus_bind
  else
    → time_scope（§4.2）
  // llm 仅冷路径
```

\*硬冲突（可选严模式，S 默认 **宽松**）：`file_change` 的 paths 与 focus.scope.paths 完全无前缀交集 **且** focus.scope.paths 非空 → 跳过 focus，走 time_scope。避免“焦点停在 A，却在完全无关目录大改”时盲绑。S 档可先实现宽松（总是允许 focus），M 档再开严模式。

### 4.2 time_scope 算法（规则，热路径）

仅当 structured / user / focus 均未命中时使用。**1.2 不改权重**——有 focus 后这是 fallback。

```text
输入: event E, 候选 outcomes O[]（同 session，status 非终态或 contradicted 可复活）

1. 时间窗:
   - 若 E 在某 claim 之后 W_after 内（默认 30min），候选加分
   - 若 E 在 outcome.updated_at 之后 W_idle 外（默认 2h）且无新 claim，降权

2. scope 重叠:
   overlap = |E.paths ∩ O.scope.paths| 的路径前缀匹配分
   （目录级匹配 partial credit）

3. 类型兼容:
   test fail/pass 更偏向 bugfix/problem
   新路由/API 文件偏向 feature
   纯重构路径启发式偏低 feature

4. score = 0.5*time_factor + 0.4*overlap + 0.1*type_fit

5. 若 max score < T_bind_auto → 不绑定（进 orphan 池，供 R-C3 或 LLM）
   若 top1 - top2 < 0.1 → 不自动绑定（歧义，交 LLM 或挂 pending）
   否则绑定 method=time_scope, conf=score
```

### 4.3 歧义与 orphan

- **orphan events**：高信号但未绑定 → 进入 session 级 `orphan_event_ids`。
- 触发 LLM 冷路径时，orphan 是主要输入之一。
- S 档：R-C3 **OFF**，不自动建 outcome。
- **session end 义务（rules@1.2，防黑洞）**：冷路径 / recap 对每个仍未绑定的 orphan **必须**择一落盘（经 `outcome_upsert`）：
  1. `binds`（method=llm，conf≥T_bind_llm），或
  2. `new_outcomes` 建议并创建，或
  3. 显式审计：`op=patch`/`note` 类记录 `unresolved_orphan`（保留 id 在列表或写入 session 级 note），**禁止静默丢弃**

```text
on_session_end …（在 R-AB2 之后）:
  flush_cold_path_recap()   # 必含 orphan 三选一义务
  store.focus_outcome_id = null
```

---

## 5. Merge / Split / Supersede

没有 merge，L1 会碎成不可读的碎片。

### 5.1 关系类型

| 操作 | 含义 | 结果 |
|------|------|------|
| `merge(a,b→c)` | a、b 实为同一工作 | a,b → superseded；c 继承证据并集；c.merge_of=[a,b] |
| `replace(a→c)` | c 是 a 的更正表述（改 title/type/scope） | a → superseded；c.supersede 继承 |
| `split(a→c1,c2)` | a 实为两件独立工作 | a → superseded；证据按 scope 拆分 |
| `link(a,b,rel)` | 相关但不合并（blocks/depends/relates） | 保留两者；写 relation 边 |

### 5.2 自动 merge 规则（谨慎）

| ID | 条件 | 动作 |
|----|------|------|
| R-M1 | 两 outcome 同 goal（或均无 goal）、scope.path Jaccard ≥ 0.7、type 兼容、均非 verified 冲突、综合 similarity≥T_merge_sim、无 user 锁定标题冲突 | **在线自动 merge**（热路径可在每次 scope 更新后检查） |
| R-M2 | 后 claim 是前 claim 的显式延续（“继续刚才的登录”）且 structured/user 绑定 | merge 或挂到同一 id（prefer 同一 id 追加） |
| R-M3 | 一 verified + 一 claimed 同 scope | **不自动 merge**；claimed 挂 `relates` 或标重复 |
| R-M4 | type 冲突（feature vs bugfix）且证据强烈分叉 | 不 merge；可 link |

**在线自动 merge = R-M1 + R-M2。**  
similarity 建议：`0.6 * path_jaccard + 0.2 * time_proximity + 0.2 * title_sim`，阈值 `T_merge_sim=0.80`。  
仍禁止：verified 与非 verified 盲合；type 冲突盲合。LLM 可追加建议，但不突破 R-M3/M4。

### 5.3 Supersede 写入

```text
on supersede(old → new):
  old.status = superseded
  old.superseded_by = new.id
  old.terminal_reason = "merged" | "replaced" | "split"
  new.evidence_links = dedupe(new ∪ old)  // split 时按规则切割
  new.confidence_raw, new.confidence, new.clamp_reason = recalc()
  // verified 继承：仅当 old.verified 且 new 未削弱验证锚点
  if old.status==verified and verification_anchors_subset(old, new):
    new.status = verified
    new.verified_at = old.verified_at
  else if new has enough evidence:
    new.status = evidenced
  else:
    new.status = claimed
```

### 5.4 Split 证据切割

```text
按 path 前缀 / test 名 / 时间段 将 evidence_links 分到 c1/c2
无法切割的 link：两边各复制一份，conf *= 0.5，note="shared"
```

---

## 6. Goal 进度投影（不是 outcome status）

```text
Goal.progress = {
  ratio_verified:   |outcomes verified| / |outcomes 非 abandoned/superseded|
  ratio_evidenced:  |evidenced ∪ verified| / |active|
  milestones:       从 success_criteria 匹配的 checklist（规则+LLM 标注）
  headline:         L2 生成，如 “主路径可跑，缺鉴权与部署”
}
```

**Goal.status 规则：**

| 条件 | Goal.status |
|------|-------------|
| 用户声明完成或 success_criteria 全 verified 覆盖 | achieved |
| 用户放弃 / 被新 goal supersede | abandoned / superseded |
| 否则 | open |

---

## 7. 热路径 vs 冷路径（效率边界）

### 7.1 热路径（同步，纯规则，每个 high-signal event）

1. 写入 L0 event  
2. 尝试绑定（§4，无 LLM）  
3. 应用 §2 转移规则  
4. 重算 confidence（§3）  
5. 更新 scope（path union）  
6. 更新 `summary_blob` 的**模板填充**（非 LLM）：`"{type} {title}: {status} (+{n} files)"`

**禁止：** 每事件调用 LLM；全文 diff 入库。

### 7.2 冷路径（异步，LLM assist）

**触发：**

- goal 切换  
- 连续 K 个高信号事件（默认 K=15）  
- session 空闲 N 分钟（默认 5）  
- 显式 recap / session end  
- orphan 缓冲超过阈值  

**输入（控制 token）：**

- 活跃 outcomes 的 `summary_blob` + status + scope  
- 增量 high-signal 事件摘要（kind、path diffstat、test 名、claim 文本截断）  
- orphan 列表  

**输出（结构化，校验后才写回）：**

```text
LLMAssistResult {
  renames:     { id, title }[]
  retypes:     { id, type }[]
  merges:      { sources[], title, type }[]   // 建议，按 §5 门闩
  binds:       { event_id, outcome_id, conf }[]  // method=llm
  new_outcomes:{ title, type, event_ids[] }[]
  goal_notes:  string?
}
```

写回门闩：

- binds：仅 conf≥T_bind_llm  
- merges：仅 sim 达标且过 R-M*  
- retypes：不改变 verified 的验证锚点语义（bugfix↔feature 需更严）  
- **LLM 不可直接写 status=verified**

### 7.3 Diff 存储纪律

```text
file_change.payload = {
  paths: [{ path, change, +lines, -lines, blob_ref? }]
  commit?: sha
  // 禁止默认: full_unified_diff
}
```

全文 diff 经 `blob_ref` 外置；drill-down 或争议仲裁时再取。

---

## 8. 处理时序（单事件）

```text
on_event(E):
  persist L0(E)
  if E.signal != high: return

  cands = bind(E)                     # §4（structured > user > focus > time_scope）
  if cands empty:
     orphan_buffer.add(E)
     maybe R-C3 (if enabled)
     return

  for O in cands:
     link = make_link(E, O)
     apply_transition_rules(O, E, link)  # §2
     O.scope = union_scope(O.scope, E)
     O.confidence_raw, O.confidence, O.clamp_reason = recalc(O)  # §3
     O.updated_at = E.ts
     O.aggregator_version = RULES_VER
     touch_summary_blob(O)
     maybe_update_focus(E, O)         # §4.0

  maybe_enqueue_cold_path()
```

---

## 9. L2 展示门闩（防止把状态机成果写漂）

| 用户问题 | 允许引用的 status |
|----------|-------------------|
| 实际做成了什么 | verified；evidenced 需降级措辞 |
| 声称做了什么 | claimed ∪ evidenced ∪ verified |
| 推进到哪 | Goal.progress + verified/evidenced 列表 |
| 修了什么 bug | type=bugfix 且 verified；evidenced 单列“待验证” |
| 还没做完/推翻 | abandoned、contradicted；进行中 claimed/evidenced |

**文案模板约束：**

- verified → “已完成/已修复（有验证）”  
- evidenced → “有实现证据，尚未验证”  
- claimed → “声称完成，未见状态证据”（session 中）；结束后无证据者已 abandoned  
- contradicted → “曾完成/曾修复，已被推翻”  
- abandoned（R-AB2）→ “曾声称，会话结束时仍无证据，已作废”

---

## 10. Aggregator 版本与重放

```text
RULES_VER = "rules@1.2"

重放：
  清空 L1（或写新 projection namespace）
  按 ts 顺序回放 session 内 high-signal events
  冷路径 LLM 结果：
    - 默认不重放历史 LLM 输出（避免非确定性）
    - 或持久化 LLMAssistResult 为 L0 kind=outcome_upsert (actor=system)
      重放时当结构化事件应用（推荐 M 档）
  focus_outcome_id 随 R-C1/claim/terminal/clear 规则在重放中重建
  confidence_raw / clamp_reason 每 tick 由 recalc 重算，不依赖历史展示值
```

**推荐：** 所有 LLM 写回都落成 `outcome_upsert` 事件，使 L1 重放确定性。

---

## 11. S 档裁剪（实现第一刀）

| 能力 | S 档（已锁定） |
|------|------|
| 事件 | goal_set, claim_made, file_change(diffstat), command_result, test_result, decision_made, verification_result |
| R-C3 orphan 建 outcome | **OFF** |
| `focus_outcome_id` | **ON**（§4.0）；缺省 bind 回退；非 multi-agent |
| 自动 merge | **R-M1 + R-M2 在线**；R-M3/M4 禁止项仍生效 |
| session end 无证据 claimed | **R-AB2 → abandoned** |
| session end orphan | **冷路径必处理**（bind / new_outcomes / unresolved 审计） |
| 冷路径 LLM | 仅 session end / 显式 recap |
| 跨 session stable_key | 字段预留，逻辑不做 |
| multi-agent `agent_id` | **不做**（字段可预留） |
| verified | R-V1, R-V2, R-V4, R-V5 必做；R-V3 可延后 |
| feature verified | 关联测试 pass 即可，`C_feat_verified_cap=0.85` |
| decision/spike | 结论型停 evidenced；user 验收才 verified |
| confidence | **raw + clamp 分字段**；新鲜度仅 claimed 衰减；**保留** §3.3 clamp |
| Goal.progress | 简单 ratio 即可 |

**Session end 钩子（S 必做）：**

```text
on_session_end(session_id):
  for O in outcomes(session_id) where status == claimed:
    if count_non_llm_supports(O) == 0:
      O.status = abandoned
      O.terminal_reason = "session_end_unevidenced_claim"
    else:
      O.status = evidenced   # R-AB2b 补升
      O.confidence_raw, O.confidence, O.clamp_reason = recalc(O)
  flush_cold_path_recap()    # 必含 orphan 三选一（§4.3）；非可选
  store.focus_outcome_id = null
```
---

## 附录 A — 关键 payload 形状（S）

```text
goal_set:
  { statement, success_criteria[], non_goals[], stable_key? }

claim_made:
  { text, claim_kind: completed|fixed|implemented|works_now|other,
    outcome_id?, scope_hint? }

file_change:
  { paths: [{path, change: add|mod|del, plus, minus, blob_ref?}],
    commit?, outcome_id? }

command_result:
  { cmd, exit_code, stdout_ref?, stderr_ref?, duration_ms?,
    classification: test|build|repro|other, outcome_id? }

test_result:
  { framework?, tests: [{name, status: pass|fail|skip, file?}],
    suite_status, outcome_id?, repro_key? }

decision_made:
  { decision, alternatives_rejected[], rationale?, outcome_id? }

verification_result:
  { verdict: pass|fail, method: user_accept|repro|test|ci|agent_self,
    notes?, outcome_id? }

blocker_found:
  { description, severity?, outcome_id? }

outcome_upsert:          # 系统/LLM 写回，便于重放
  { outcome_id, patch: object, source: rules|llm|user }
```

## 附录 B — repro fail/pass 启发式（R-V3 用，可延后）

```text
fail 模式: exit_code!=0 或 stdout/stderr 匹配
  /(Error|FAIL|failed|AssertionError|panic|Traceback|FAILED)/i
pass 模式: exit_code==0 且不匹配 fail 模式
锚点: cmd 规范化字符串（去路径绝对前缀、去空白）相同
```

---

## 12. 已锁定决策（v1.2）

| # | 议题 | 锁定 | 规则落点 |
|---|------|------|----------|
| Q1 | `verified → contradicted` | **开放** | §1.2 / R-X1–X3；L2 需“曾验证，后推翻”措辞 |
| Q2 | session end 纯 claimed 无证据 | **→ abandoned** | R-AB2 / §11 session end 钩子 |
| Q3 | R-C3 orphan 自动建 outcome | **S 档 OFF** | §2.1 / §4.3 / §11 |
| Q4 | feature verified 门槛 | **关联测试 pass 即可，cap 0.85** | R-V4 / `C_feat_verified_cap`；L2 措辞弱于 bugfix |
| Q5 | 自动 merge | **R-M1 + R-M2 在线** | §5.2；R-M3/M4 仍禁止盲合 |
| Q6 | decision / spike | **结论型停 evidenced**；user 验收才 verified | R-V6 / R-VX5 |
| Q7 | confidence 新鲜度 | **仅 claimed 衰减**；evidenced 不衰减 | §3.2 |
| Q8 | multi-agent `agent_id` | **S/M 前期不做** | Event 可预留字段；绑定逻辑不隔离 |
| Q9 | work-stream focus | **`focus_outcome_id` ON**；bind 序插入 focus；非 multi-agent | §4.0 / §4.1 / store 字段 |
| Q10 | confidence 可观测性 | **`confidence_raw` + `clamp_reason`**；**保留** §3.3 clamp | §3 / outcome schema |
| Q11 | session end orphan | **冷路径三选一必落盘**（bind / new_outcome / unresolved） | §4.3 / §11 |

### 实现时注意的连锁影响

1. **Q2 + Q3 + Q11：** R-C3 仍 OFF 防碎片；但 session end **不得**静默丢 orphan——必须 bind、建 outcome 建议、或 `unresolved_orphan` 审计。focus（Q9）应大幅减少 orphan 产量。  
2. **Q5 R-M1 在线：** 必须实现 type 兼容矩阵与 verified 保护（R-M3），并打 merge 审计事件（`outcome_upsert` source=rules），便于误合并回放。merge 涉及 focus 源时 focus → survivor。  
3. **Q1 开放推翻：** L2“做成了什么”默认 `status=verified` **且** 当前仍为 verified；历史 once-verified 可另区展示。  
4. **Q7：** `age_hours` 以 `updated_at` 计（有新 claim/evidence 会刷新），不是 `started_at`。  
5. **Q9：** 适配层优先写 `payload.outcome_id`；focus 是缺省回退。并行任务靠新 claim 切换 focus，不要指望 time_scope 歧义检测。  
6. **Q10：** L2/排序读 `confidence`；调参与回归读 `confidence_raw`+`clamp_reason`。删除 clamp 需另开决策，不在 1.2。