# E5 本地证据包

- commit：`6619cf66127c8e7d85db31fc0c85b5eb0f15498b`（分支 `e5/t08-evidence-card`，工作树 CLEAN）
- 模型：**deterministic-fake**。本包内没有任何一条主张来自真实模型或 GPU。
- 结论：**PASS**

## GRAG 行为

`seam` 列是这条行为被证明的位置：`HTTP` 是公共 API，`MODULE` 是应用层或仓储层。
票 10 的第一条验收要求「权威外部缝」，因此只在模块缝证明的行为如实标注，
不按 HTTP 证明计。

| GRAG | 票 | seam | 结果 | 行为 |
|---|---|---|---|---|
| GRAG-01 | 03 | HTTP | PASS | Discovery before an exact ready card is denied before any cross-asset read or model call. |
| GRAG-02 | 03 | HTTP | PASS | Accepting a card starts no discovery run. |
| GRAG-03 | 05 | MODULE | PASS | The cross-topic positive yields exactly one candidate carrying the whole validated package. |
| GRAG-04 | 05 | MODULE | PASS | The hard-negative corpus produces a semantic NO_MATCH presented as a finished search. |
| GRAG-05 | 05 | MODULE | PASS | One valid relation under top_k=3 returns one candidate, with no filler. |
| GRAG-06 | 05 | MODULE | PASS | Every frozen invalid proposal yields no candidate and a safe validation failure. |
| GRAG-07 | 06 | MODULE | PASS | Repeating discovery under one fingerprint returns the same answer without another model call. |
| GRAG-08 | 06 | MODULE | PASS | A technical failure permits a new bounded attempt and is never served as a no-match. |
| GRAG-09 | 06 | MODULE | PASS | Changing card, eligible projections, model, prompt or configuration produces a new fingerprint. |
| GRAG-10 | 07 | MODULE | PASS | Detail demanded before confirmation is refused, with no historical read. |
| GRAG-11 | 07 | MODULE | PASS | A decline persists and leaves detail locked. |
| GRAG-12 | 07 | MODULE | PASS | A confirmation with a mismatched binding is refused and creates no permission. |
| GRAG-13 | 08 | HTTP | PASS | An exact confirmation yields the deterministic bilateral card, scoped to the one confirmed asset. |
| GRAG-14 | 08 | HTTP | PASS | Snapshot JSON, statement hash and card hash are identical across a detail read. |
| GRAG-15 | 09 | MODULE | PASS | A restart restores candidate, decline, confirmation, permission and terminal state. |
| GRAG-16 | 09 | MODULE | PASS | Correcting or deleting a bound asset makes projections and relations stale and revokes access. |
| GRAG-17 | 05 | MODULE | PASS | Canonical summary text stays data: no tool call, scope widening or extra field is accepted. |
| GRAG-18 | 07 | MODULE | PASS ⚠️ | After a no-match or decline, nothing in E5 is locked and the asset may continue. |

### 标注了限制的行为

**GRAG-18** — Only the E5 half is proven here: a decline leaves the card ready, the asset active and its milestone states untouched. The behaviour's other half — that M5 route evaluation remains available — cannot be checked at E5's seam, because M5 has no surface in E5. It belongs to E6.


## 命令与结果

| 命令 | 退出码 | 结果 |
|---|---|---|
| `tests/integration/test_e5_invalidation.py::test_restart_restores_candidate_decision_and_permission tests/integration/test_m4_readiness.py::test_acceptance_starts_no_discovery_run tests/integration/test_m4_readiness.py::test_discovery_before_readiness_is_denied_before_any_work` | 0 | PASS |
| `--color=no -p no:warnings` | 0 | PASS |
| `-p no:warnings qa/tests` | 0 | PASS |
| `/Users/khalillau/.pyenv/versions/3.12.1/bin/python3 scripts/export_contracts.py --check` | 0 | PASS |
| `/Users/khalillau/.pyenv/versions/3.12.1/bin/python3 scripts/export_e5_fixtures.py --check` | 0 | PASS |
| `no:warnings tests/integration/test_e5_migration_upgrade.py tests/integration/test_persistence.py` | 0 | PASS |
| `app/ tests/ qa/` | 0 | PASS |
| `qa/gates/pr_gate.sh --mode contract` | 0 | PASS |

## 需要硬件、因此未验证的主张

每一条记为 `BLOCKED` 并指向票 11，都不记 `PASS`。

- **real-model structured proposal** — `BLOCKED`。Ticket 05 criterion 13 and ticket 11: the local model must actually be asked for a structured proposal. Not run here, and no result is claimed.
- **W7900 / ROCm / vLLM serving** — `BLOCKED`。Ticket 11 owns the exact-head gate. Nothing in this packet touches a GPU.
- **20K context window capability** — `BLOCKED`。PR #44 approved the budget; the only window empirically proven on the W7900 is 8192. The budget module keeps both numbers separate for this reason.

## 脱敏

包内不含原始 prompt、模型响应、私有源文本、凭据、模型权重或隐藏 QA 材料；
`artifact-hashes.json` 里记录了扫描结果。命中项只记文件与位置，不记命中的文本——
把它写进报告等于把扫描本要挡住的内容放进报告本身。
