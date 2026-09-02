# XAI 数字员工平台 · 六维实弹验收报告（LIVE）

> **日期**：2026-07-28
> **方法**：六维全景验收（Verification Lens）+ 五角度思维旁注（Design Lens）
> **框架**：project-dev-framework v3.1
> **样本**：XAI 数字员工 / 数字分身平台（双核融合 + 8 层记忆 + Guardian + 控制台）
> **性质**：**本表为实弹（LIVE）验收**——所有证据来自本次真实运行的命令输出，非模拟。上游 `XAI项目模拟验收报告.md` 为同方法模拟版，已被本表以真实数据校准并升级判定。

---

## 0. 能力定位回顾：五角度设计思维 × 六维验收全景

- **设计透镜（五角度）**：组织理论 / 工程 / 统计 / 经济 / 产品——建造期防膨胀、防做错。
- **验收透镜（六维）**：功能 / 性能 / 安全 / 数据 / 运维 / 诚实治理——交付期防漏项。
- 两者闭环 = 我们的方法论资产（剧本 + 剧场）。

---

## 1. 六维验收评分总表（LIVE）

| 维度 | 结论 | 关键实弹证据 | 主要缺口 |
|------|------|--------------|----------|
| 一 功能与需求 | ✅ 强 | smoke 38/38 · pytest 117P+4S · honesty 13/13 · KB recall@3=100% | RTM 未显式建；边界用例散 |
| 二 性能质量 | ⚠️ 部分（升级自模拟❌） | /api/status 单请求 1–38ms；并发 200@20→1562 RPS / 0 错 | 仅轻端点；核心推理接口压测 / 资源上限未验 |
| 三 安全验收 | ⚠️ 部分 | Guardian P0/P1/P2 门 + 端点齐；core 密钥 0 命中；依赖仅 MIT | 无 SAST/DAST / 依赖漏洞 / 渗透报告 |
| 四 数据与状态 | ✅（升级自模拟⚠️） | project_id 双路径隔离；备份 7 DB 全 OK + 恢复演练 integrity=OK | 幂等/竞态未系统测；恢复仅 sqlite 层 |
| 五 运维就绪 | ⚠️→接近✅（升级自模拟⚠️） | start_xai.sh + xai-snapshot 回滚基线 + launchd 备份 + Tracer 代码 | observability 未暴露端点；无告警；RTO/RPO 未定义 |
| 六 诚实·价值·治理 | ✅ 独有强 | honesty 13/13；HANDOFF+宪法+踩坑+方法论齐 | success_metric 未常态化回看 |

**总体判定**：☐ 可交付（外部发行级） ☑ **可交付（内部产品级 · 带运行层埋点缺口）** ☐ 不可交付

> 说明：ACCEPTANCE_CHECKLIST 铁律「任一维 ❌ = 不可交付」。本次实弹后**无 ❌ 维**（原模拟判 ❌ 的性能维已被并发基线补成 ⚠️），故系统**已达内部可交付标准**。剩余缺口全部属「运行层工具链」，非架构错误。

---

## 2. 逐维实弹证据

### 维度一 · 功能与需求 ✅

**命令与输出（本次真实运行）**
```
$ python3 scripts/smoke_test.py
总计 38 | ✅ 38 | ⚠️ 0 | ❌ 0
结论：全绿，契约面无假能力/静默 stub。

$ python3 -m pytest tests/ -q
117 passed, 4 skipped in 7.43s

$ python3 scripts/honesty_check.py
审计完成。13/13 ALL PASS（节点映射 / KB对齐 / 网关诚实 / 沙箱诚实 / KB召回）
KB recall@3 = 3.00（avg overlap=3/3，100%）
```
- **RTM 追溯**：smoke 覆盖 38 端点契约、pytest 117 用例、honesty 13 项声明验证，三闸合并门（功能真做 / 自测通过 / 回归不破）已落地。
- **UAT**：真实业务方（老大）持续日常使用，等价 UAT 通过。
- **缺口**：需求→用例→代码单一 RTM 矩阵未显式建；边界/异常/负面用例有但未系统编目。

### 维度二 · 性能质量 ⚠️（升级自模拟 ❌）

**实弹数据**
```
$ 单请求 authed /api/status（5x）：38ms / 1.2ms / 1.0ms / 2.7ms / 1.8ms
$ 并发探针（本地 urllib 线程池）：
   N=50  workers=10 → 0.066s, 758 RPS, 200=50/50
   N=200 workers=20 → 0.128s, 1562 RPS, 200=200/200（0 错误）
```
- **已有**：轻量状态接口在 200 并发下 ≈1.5k RPS、零错误，单请求延迟个位数~数十 ms。
- **缺口**：仅覆盖 `/api/status` 轻端点；核心推理接口（`/api/chat` 走模型推理）未压测；资源上限线性度 / 内存泄漏未验证；无持续性能监控面板。
- **结论**：从「无数据」升级为「有并发基线」，但距上线压测 Gate 仍缺核心接口与资源验证。

### 维度三 · 安全验收 ⚠️

**实弹证据**
```
$ grep -rn "resolve_approval|pending_approvals|/api/guardian|/api/approvals" (core + server)
  → guardian_bridge.resolve_approval / pending_approvals
  → /api/guardian/pending · /api/guardian/approve · /api/approvals
  → /api/guardian/grok-write/request（写操作转审批工单）
$ grep 密钥正则 (core/**) → 0 命中（无 sk-/AKIA-/ghp_/xox-/PRIVATE KEY 硬编码）
$ requirements.txt → 仅可选 PyYAML>=6.0（MIT），无 GPL/传染许可
$ curl /api/status（无 token）→ HTTP 401（鉴权门生效）
```
- **已有**：Guardian P0/P1/P2 风险分级 + 二次确认 + 审批端点齐全；无硬编码密钥；依赖许可证面干净；未授权访问被 401 拦截。
- **缺口**：无 SAST/DAST 报告；无依赖漏洞扫描（CVE）；关键路径（鉴权、路径穿越、注入面）未做渗透测试。
- **结论**：治理闸门 + 密钥 + 许可三项扎实，独立安全工具链待补。

### 维度四 · 数据与状态 ✅（升级自模拟 ⚠️）

**实弹证据**
```
$ grep project_id core/memory_core.py
  → query() 与 recall() 均带 project_id 过滤（L112-117, 162-187），实现项目隔离
$ python3 xai-backup.py --verify（真恢复演练）
  [OK] app.db / xai.db / knowledge.db / projects.db / memory.db / sessions.db / grok_history.db
  配置JSON已备份: models.json, loop_safety.json, grok_pref.json, connectors.json
  [verify] 演练 <最新.bak> -> 还原 integrity=OK
  [xai-backup] 完成 ✅
```
- **已有**：
  - 记忆 `project_id` 在 `query` + `recall` 双路径隔离（防串项目）。
  - `xai-backup.py` 用 SQLite `backup()` 做在线原子拷贝（非 `cp` 活库）+ `PRAGMA integrity_check`；`verify_recovery()` **真还原到临时库并校验**，本回合实跑通过。
  - launchd `com.xai.backup.plist` 自动化备份；`test_migrations` 存在。
- **缺口**：幂等/竞态（重复提交、双写、分布式锁失效）未系统测；恢复演练仅 sqlite 层，未含前端态/会话态一致性。

### 维度五 · 运维就绪 ⚠️→接近✅（升级自模拟 ⚠️）

**实弹证据**
```
$ ls xai/*.sh → setup.sh · start_xai.sh · xai-snapshot.sh · xai_go.sh
$ xai-snapshot.sh：git tag + 源码 tar + 数据 tar + 恢复指令（一行命令留回滚基线）
$ launchd com.xai.backup.plist（备份守护）
$ grep observability server_xai.py:55 → from core.observability import global_tracer
  observability.py：Tracer/span/ duration_ms 真实埋点管线（P1-O2）
```
- **已有**：一键启动（start_xai.sh）；一键回滚基线（xai-snapshot.sh）；备份自动化（launchd）；可观测性埋点代码已接入 server。
- **缺口**：observability 未暴露 HTTP 端点（`/api/metrics`、`/api/trace` 均不存在）；无告警；RTO/RPO 未定义；无运维监控面板。
- **结论**：从「能启动能看」升级为「有启动/回滚/备份/埋点四件套」，距「能运营」差暴露层与告警。

### 维度六 · 诚实·价值·治理 ✅（独有强项）

**实弹证据**
```
$ python3 scripts/honesty_check.py → 13/13 ALL PASS
  - 节点映射完整性（无缺失 handler）
  - KB/embeddings 对齐（dense_available=true, 463 chunks）
  - 网关/引擎能力诚实（6 真实工具 vs 6 模拟项隔离）
  - 沙箱诚实标注（note 字段）
  - KB 召回 paraphrase recall@3=100%
```
- **已有**：honesty 13/13 真测；文档链完整（HANDOFF + 架构宪法 + 踩坑清单 + 方法论 v3.1）；需求闸门 `success_metric` 机制存在。
- **缺口**：XAI 自身未 formal 回看 `success_metric`（机制在，使用未常态化）。
- **结论**：外部 AI-OOS 文档压根未提的维，我们已领先且可验证。

---

## 3. 五角度思维旁注（为什么长这样）

| 角度 | 建造期体现 | 验收回响 |
|------|------------|----------|
| 组织理论 | 未堆 Council，5 能力槽位恒定 | 验收不要求多角色签字，S/A/C 直通道控税 |
| 工程 | 记忆挂 memory_core 单一事实源 | 维度四隔离+备份恢复均落地，远超模拟预期 |
| 统计 | 置信度先记账后校准 | 维度二曾有「无数据不能断言」→ 现补并发基线 |
| 经济 | 任务分级直通道 | 维度二/三/五「补工具链」本质是流程税权衡 |
| 产品 | 需求闸门逼问 | 维度六 success_metric 应回看，目前未常态化 |

**洞察**：实弹后缺口（性能核心压测 / 安全扫描链 / 幂等竞态 / 可观测暴露）全部是「运行层埋点」，无一触碰架构正确性——印证五角度设计透镜生效，骨架健康。

---

## 4. 总体判定与补强清单（30 天实证期首批埋点）

**判定：可交付（内部产品级）**——数字员工已在真实日常使用中，六维无 ❌，骨架与治理领先。

必须补的运行层埋点（按优先级，建议进入 v3.1 30 天实证期）：
1. **P0 核心接口压测**（维度二）：对 `/api/chat`、`/api/intent` 做约定并发压测，出延迟/吞吐/错误率 + 资源上限报告。
2. **P0 安全扫描链**（维度三）：接 SAST/DAST + 依赖 CVE 扫描；对鉴权/路径穿越/注入面至少一次渗透。
3. **P1 幂等/竞态用例**（维度四）：重复提交、双写、重启一致性系统编目。
4. **P1 可观测暴露**（维度五）：将 Tracer 暴露为 `/api/metrics` + 基础告警 + RTO/RPO 定义。
5. **P2 RTM 矩阵**（维度一）：建需求→用例→代码单一追溯矩阵。
6. **P2 success_metric 回看**（维度六）：验收时 formal 回看需求闸门指标，常态化。

---

## 5. 与 v3.1 框架映射

| 验收维 | v3.1 已覆盖 | 本回合实弹增量 | 仍待补 |
|--------|-------------|----------------|--------|
| 一 功能 | smoke/pytest/三闸 | 全绿复测通过 | RTM 矩阵 |
| 二 性能 | 未内置 | **并发基线 1.5k RPS/0错** | 核心接口压测 |
| 三 安全 | Guardian 门 | 密钥0命中+许可干净+401实测 | SAST/DAST/渗透 |
| 四 数据 | 迁移测试 | **备份7DB全OK+恢复演练OK** | 幂等/竞态 |
| 五 运维 | start/控制台 | **snapshot回滚+备份守护+Tracer接入** | 暴露/告警/RTO |
| 六 诚实 | honesty 13/13 | 复测 13/13 | success_metric 回看 |

**结论**：实弹验收将模拟报告的「条件交付( Beta )」校准为「**可交付（内部产品级）**」——缺口从「架构风险」降级为「运行层埋点」，正好落入 v3.1「先刹车、再记录、发现错误、生成改进、验证价值」闭环的下一个实证目标。建议把上述 6 项作为 30 天实证期首批埋点。
