# S 档 JSON Schema（L0 / L1）

对应状态机：`docs/outcome-state-machine.md` · **`rules@1.2`** · envelope **`s/1.0`**

## 文件

| 文件 | 层 | 作用 |
|------|----|------|
| `common.schema.json` | 共享 | Id、枚举、Scope、EvidenceLink、ClampReason、PathChange… |
| `l0-event.schema.json` | L0 | 单条事件；`kind` 判别 payload |
| `l0-log.schema.json` | L0 | 事件流导出/落盘包 |
| `l1-goal.schema.json` | L1 | 意图锚点 Goal |
| `l1-outcome.schema.json` | L1 | OutcomeCandidate（结果真相） |
| `l1-store.schema.json` | L1 | 单 session 物化快照（可重放重建） |

## 怎么结构化（设计要点）

### 1. 两层，不是一张大表

```text
L0  Event log     只记“发生了什么”     append-only，不可变
L1  Goal/Outcome  记“这算做成了什么”   可丢、可按 rules@x 重放重建
```

- **查询主索引在 L1 Outcome**，不在 message。
- L2 recap 不进本 schema（投影，按需生成）。

### 2. L0：包络 + 判别联合（discriminated union）

每条事件固定包络：

```text
id | ts | session_id | actor | kind | signal | refs[] | payload
```

`payload` **不**做成自由 JSON：用 JSON Schema `oneOf` + `kind` const 拉齐到具体形状：

| kind | payload 要点 | 默认 signal |
|------|----------------|-------------|
| `goal_set` | statement, criteria, non_goals | high |
| `claim_made` | text, claim_kind, outcome_id? | high |
| `file_change` | paths[] diffstat + blob_ref? | high |
| `command_result` | cmd, exit_code, classification, *\_ref | 可变 |
| `test_result` | tests[], suite_status, repro_key | high |
| `decision_made` | decision, rejected[], conclusion? | high |
| `verification_result` | verdict, method, outcome_id? | high |
| `blocker_found` | description, severity | high |
| `outcome_upsert` | source/op/patch；可选 focus_outcome_id / clear_focus | high |
| `session_end` | apply_ab2（触发 R-AB2 清扫） | high |

**体积纪律：** 全文 diff / 长日志只许 `blob_ref`，payload 内最多 excerpt。

**绑定入口（优先级）：**

```text
payload.outcome_id     → structured
user 指定              → user
store.focus_outcome_id → focus          # rules@1.2
time_scope 推断        → time_scope     # fallback
冷路径 LLM             → llm
```

适配层应尽量填 `outcome_id`；`focus_outcome_id` 是缺省 work-stream，不是 multi-agent。

### 3. L1 Outcome：状态机字段 + 证据边

```text
OutcomeCandidate
  identity:  id, session_id, goal_id?, stable_key?
  meaning:   type, title, tags[]
  truth:     status, confidence, confidence_raw, clamp_reason, once_verified
  evidence:  evidence_links[], counter_evidence[]
  where:     scope { paths, symbols, services, commands }
  lifecycle: started_at, updated_at, verified_at?, terminal_reason?
  lineage:   merge_of[], superseded_by?
  replay:    aggregator_version = "rules@1.2"
  coldpath:  summary_blob
  verify:    verification_anchors[]    // fail→pass / 回归配对
```

**confidence 三件套（Q10）：**

| 字段 | 用途 |
|------|------|
| `confidence_raw` | §3.2 公式值（调参/审计） |
| `confidence` | §3.3 clamp 后展示值（L2/排序） |
| `clamp_reason` | `none` \| `ceiling_claimed` \| … \| `feat_verified_cap` |

条件约束（schema `allOf`/`if-then`）：

- `abandoned|contradicted|superseded` ⇒ 必有 `terminal_reason`
- `verified` ⇒ 必有 `verified_at`
- `superseded` ⇒ 必有 `superseded_by`

`EvidenceLink` 是 **事件→结果的边**，不是嵌事件副本：

```text
{ event_id, relation, method, confidence, note? }
relation: supports | refutes | defines | verifies | scopes
method:   structured | user | focus | time_scope | llm
```

### 4. L1 Goal：与 Outcome 分离

Goal 回答“要去哪 / 到了哪”；Outcome 回答“做成了哪几件”。

`progress` 是 **只读投影**（可算可不存）：

```text
ratio_verified, ratio_evidenced, counts, headline?
```

`progress` **不是** outcome.type。

### 5. L1 Store：一 session 一个可重放快照

```text
SessionStore {
  goals[], outcomes[],
  orphan_event_ids[],     // R-C3 OFF：只挂着；session end 必处理（Q11）
  active_goal_id?,
  focus_outcome_id?,      // rules@1.2 work-stream 焦点（Q9）
  constants: {
    r_c3_enabled:false, online_merge_rm1:true,
    C_focus_bind:0.90, ...
  }
}
```

实现上：热路径改 Store；需要审计/升规则版本时从 L0 重放覆盖 Store。  
`focus_outcome_id` 随 claim/create 设置，terminal/session_end 清除；重放可重建。

### 6. 写回也是事件（确定性）

LLM/规则对 L1 的修改应再 append 一条 L0 `outcome_upsert`：

```text
source: rules|llm|user
op:     create|patch|merge|split|supersede|session_end_sweep
patch:  允许的部分字段（LLM 禁止直接 patch status=verified —— 规则层强制）
focus_outcome_id? / clear_focus?   // 焦点审计
```

这样 L1 重放不依赖“当时 LLM 又想了什么”。

### 7. 与锁定决策的对应

| 决策 | Schema 体现 |
|------|-------------|
| Q1 verified 可推翻 | `once_verified` + status 仍可→contradicted |
| Q2 end 无证据 claimed→abandoned | `session_end` + `outcome_upsert.op=session_end_sweep` + terminal_reason |
| Q3 R-C3 OFF | `constants.r_c3_enabled: false`；orphan 只存 id |
| Q4 feature cap 0.85 | 逻辑层；constants 记录 `C_feat_verified_cap`；`clamp_reason=feat_verified_cap` |
| Q5 R-M1 在线 | `constants.online_merge_rm1: true`；merge 走 upsert |
| Q7 仅 claimed 衰减 | `updated_at` 作文龄基点（文档约定，非 schema 能表达） |
| Q8 多 agent 暂缓 | Event 可选 `agent_id`，绑定忽略 |
| Q9 focus work-stream | `focus_outcome_id`；`BindMethod` 含 `focus`；`C_focus_bind` |
| Q10 confidence 可观测 | `confidence_raw` + `clamp_reason`；保留 clamp 语义 |
| Q11 orphan 必处理 | store 描述 + 状态机 §4.3；非静默丢弃 |

---

## 最小示例（故事线）

### L0 事件流（节选）

```json
{
  "schema_version": "s/1.0",
  "events": [
    {
      "id": "evt_01",
      "ts": "2026-07-28T04:00:00.000Z",
      "session_id": "ses_01",
      "actor": "user",
      "kind": "goal_set",
      "signal": "high",
      "refs": [],
      "payload": {
        "statement": "修复登录页 500，并补回归测试",
        "success_criteria": ["复现消失", "相关测试绿"]
      }
    },
    {
      "id": "evt_02",
      "ts": "2026-07-28T04:05:00.000Z",
      "session_id": "ses_01",
      "actor": "agent",
      "kind": "claim_made",
      "signal": "high",
      "refs": [],
      "payload": {
        "text": "我会修 AuthController 空指针并加测试",
        "claim_kind": "other",
        "type_hint": "bugfix",
        "title_hint": "Fix login NPE",
        "scope_hint": { "paths": ["src/auth/"] }
      }
    },
    {
      "id": "evt_03",
      "ts": "2026-07-28T04:06:00.000Z",
      "session_id": "ses_01",
      "actor": "tool",
      "kind": "test_result",
      "signal": "high",
      "refs": [{ "kind": "test", "value": "test_login_ok" }],
      "payload": {
        "framework": "pytest",
        "suite_status": "fail",
        "repro_key": "pytest tests/test_auth.py::test_login_ok",
        "tests": [
          {
            "name": "test_login_ok",
            "status": "fail",
            "file": "tests/test_auth.py",
            "message": "500 Internal Server Error"
          }
        ]
      }
    },
    {
      "id": "evt_04",
      "ts": "2026-07-28T04:12:00.000Z",
      "session_id": "ses_01",
      "actor": "tool",
      "kind": "file_change",
      "signal": "high",
      "refs": [{ "kind": "file", "value": "src/auth/controller.py" }],
      "payload": {
        "paths": [
          {
            "path": "src/auth/controller.py",
            "change": "mod",
            "plus": 8,
            "minus": 2,
            "blob_ref": "blob:sha256:deadbeef"
          },
          {
            "path": "tests/test_auth.py",
            "change": "mod",
            "plus": 15,
            "minus": 0
          }
        ]
      }
    },
    {
      "id": "evt_05",
      "ts": "2026-07-28T04:13:00.000Z",
      "session_id": "ses_01",
      "actor": "tool",
      "kind": "test_result",
      "signal": "high",
      "refs": [],
      "payload": {
        "framework": "pytest",
        "suite_status": "pass",
        "repro_key": "pytest tests/test_auth.py::test_login_ok",
        "tests": [
          { "name": "test_login_ok", "status": "pass", "file": "tests/test_auth.py" }
        ]
      }
    },
    {
      "id": "evt_06",
      "ts": "2026-07-28T04:20:00.000Z",
      "session_id": "ses_01",
      "actor": "system",
      "kind": "session_end",
      "signal": "high",
      "refs": [],
      "payload": { "reason": "normal", "apply_ab2": true }
    }
  ]
}
```

### 聚合后 L1 Outcome（R-V1 闭合）

```json
{
  "schema_version": "s/1.0",
  "id": "out_01",
  "session_id": "ses_01",
  "goal_id": "goal_01",
  "type": "bugfix",
  "title": "Fix login NPE",
  "status": "verified",
  "confidence": 0.92,
  "confidence_raw": 0.92,
  "clamp_reason": "none",
  "once_verified": true,
  "evidence_links": [
    {
      "event_id": "evt_02",
      "relation": "defines",
      "method": "focus",
      "confidence": 0.9
    },
    {
      "event_id": "evt_03",
      "relation": "supports",
      "method": "focus",
      "confidence": 0.9
    },
    {
      "event_id": "evt_04",
      "relation": "supports",
      "method": "focus",
      "confidence": 0.9
    },
    {
      "event_id": "evt_05",
      "relation": "verifies",
      "method": "focus",
      "confidence": 0.9
    }
  ],
  "counter_evidence": [],
  "scope": {
    "paths": ["src/auth/controller.py", "tests/test_auth.py"],
    "symbols": [],
    "services": [],
    "commands": ["pytest tests/test_auth.py::test_login_ok"]
  },
  "started_at": "2026-07-28T04:05:00.000Z",
  "updated_at": "2026-07-28T04:13:00.000Z",
  "verified_at": "2026-07-28T04:13:00.000Z",
  "merge_of": [],
  "aggregator_version": "rules@1.2",
  "summary_blob": "bugfix Fix login NPE: verified (+2 files, test_login_ok pass)",
  "tags": ["auth"],
  "verification_anchors": [
    {
      "kind": "test",
      "key": "test_login_ok",
      "event_id": "evt_05"
    }
  ]
}
```

故事线补充：`claim_made`(evt_02) 创建 outcome 后 `store.focus_outcome_id=out_01`；后续无 `outcome_id` 的 test/file 事件以 `method=focus` 绑定，不必依赖 time_scope。

### 对照：空口完成 → session_end 后

```text
claim_made(completed)  →  Outcome status=claimed
（无 file/test）
session_end(apply_ab2) →  status=abandoned
                           terminal_reason="session_end_unevidenced_claim"
```

L2 **不得**把它写进“实际做成了什么”。

---

## 存储建议（实现提示，非 schema 强制）

```text
.airecap/
  sessions/{session_id}/
    events.jsonl          # 每行一个 L0 Event
    store.json            # L1 SessionStore 快照
    blobs/{hash}          # diff/stdout 外置
```

- `events.jsonl`：唯一事实源  
- `store.json`：热读缓存；`aggregator_version` 变了就重放  
- 校验：写入前用本目录 schema 做 validate（CI 可对 examples 跑）

## 校验

可用任意 Draft 2020-12 实现，例如：

```bash
# 需本地装 ajv-cli 时
npx ajv validate -s docs/schemas/s/l0-event.schema.json -d event.json -c ajv-formats \
  --spec=draft2020 -r docs/schemas/s/common.schema.json
```

（`$ref` 相对文件名解析；实现时把 `common.schema.json` 放同一目录。）

## 刻意不放进 S schema 的

- 全文 transcript / token 流  
- L2 recap 文档结构  
- 跨 session stable_key 解析表  
- multi-agent 绑定隔离（`focus_outcome_id` 是单焦点，不是 agent 隔离）  
- R-C3 自动建 outcome 的 orphan→outcome 映射（session end 冷路径建议/审计另走 upsert）  

`rules@1.2` 相对 1.1 为**兼容扩展**（新字段 + 新 bind method）；envelope 仍 `schema_version: s/1.0`。若日后删除 clamp 或改 status 语义再升 `s/1.1` / `s/2.0`。
