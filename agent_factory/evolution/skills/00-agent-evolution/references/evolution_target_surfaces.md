# Evolution Target Surfaces

Use this reference only when deciding where a requested evolution belongs.

| User request type | Primary target surface | Preferred write action |
| --- | --- | --- |
| Add or change executable behavior | `tools/<tool_id>/tool.py`, ToolSpec, dependencies, assembly exposure | `create_agent_authoring(action="upsert_package_tool")` |
| Change only dependency metadata | `contracts/dependencies.json` | `create_agent_authoring(action="configure_dependencies")` |
| Change per-Agent temperature or output-token override | `contracts/model.json` | `create_agent_authoring(action="configure_model_bindings")` |
| Change context-window, compression, or cross-session memory policy | `contracts/context.json` | No current authoring action; report the authoring gap |
| Change plan/executor/final answer behavior | `assembly_spec.json` | `create_agent_authoring(action="configure_pattern_assembly")` |
| Change package identity text | `agent_package.json`, `assembly_spec.json` | `create_agent_authoring(action="set_identity")` |
| Add explicitly requested, sourced package knowledge | `knowledge/*` | `create_agent_authoring(action="upsert_knowledge_file", knowledge_purpose=..., knowledge_source=...)` |
| Remove invalid or obsolete package knowledge | `knowledge/*`, `.factory/knowledge_sources.json` | `create_agent_authoring(action="remove_knowledge_file", knowledge_path=...)` |
| Add runtime resources | `resources.json`, `contracts/resources.json` | `create_agent_authoring(action="upsert_resources")` |
| Add scheduler seed | `contracts/scheduler_seed.json` | `create_agent_authoring(action="upsert_scheduler_seed")` |
| Repair malformed current scaffold contract | `contracts/{context,dependencies,model,resources,scheduler,scheduler_seed,tools}.json` | `create_agent_authoring(action="reset_contract", contract_key=...)` |

If no authoring action can represent the needed managed-surface change, stop and report the missing authoring capability. Do not bypass managed file protection with generic filesystem tools.

Package knowledge is opt-in. Generic requests mentioning documents, knowledge bases, persona, prompts, or future user uploads do not authorize bundling files into `knowledge/`. Require authoritative, distributable source evidence and keep mutable material in runtime knowledge sources or tools.
The source registry is maintained by create_agent_authoring; never edit it directly.
