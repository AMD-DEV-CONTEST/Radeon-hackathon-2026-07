# ADR-0009: Audit Third Parties on Adoption

## Status

Accepted — 2026-07-23

## Context

Broad audits of frameworks and assets that are not used consume time without changing the release artifact.

## Decision

第三方依赖采用“实际采用时审计”，而不是“可能使用时提前全面审计”。

Current status:

| 项目 | 当前状态 | 当前用途 | 是否进入代码 | 后续触发条件 |
|---|---|---|---|---|
| HoloAgent-0 | Reference only / Closed | 学术与架构参考 | 否 | 实际采用前审计 |
| LangChain | To be determined | 可能用于工具和结构化输出 | 否 | 正式接入时审计 |
| LangGraph | To be determined | 可能用于状态图和 HITL | 否 | 正式接入时审计 |
| OpenClaw | Reference / experimental | 尚无明确正式用途 | 否 | 分发或正式依赖前审计 |

An adoption-triggered review must identify the exact package, version/commit, use, modification, distribution mode and assets.

## Consequences

- References remain lightweight and do not imply dependencies.
- No framework is added to make the architecture appear complete.
- The existing license register remains a release gate for artifacts actually included.
