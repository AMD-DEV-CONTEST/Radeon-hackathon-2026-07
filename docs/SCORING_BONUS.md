# Scoring Bonus Map · Track 2

How PrivateLocalAgent covers official example apps and judging criteria.

## Example applications → where shown

| Example | Coverage | Demo entry |
|---------|----------|------------|
| RAG local knowledge assistant | Core | Ask policy/FAQ; `kb_search` |
| Personal productivity assistant | Core | Memory notes/facts + chat continuity |
| Enterprise copiloting | Strengthened | `data/sample_docs/enterprise_copilot_playbook.md` + IT/leave QA |
| Workflow automation agent | Added | 「帮我跑入职IT开通工作流」→ `WorkflowAgent` |
| Developer productivity agent | Added | 「如何确认 ROCm 可用？」+ `dev_productivity.md` + `DeveloperAgent` |
| Multi-agent system | Added | `src/agent/multi_agent.py` routes: rag/memory/workflow/developer/general |

## Judging alignment

### Functionality & value (~60)
- Private RAG + tool calling + memory + planning (`build_task_plan`)
- Orchestrated specialists + office workflows
- Tunnel-free visual notebook UX

### AMD Radeon / ROCm (~40)
- `llm.backend: local_transformers` on GPU
- `python scripts/verify_rocm.py`
- `python scripts/bench_rocm.py` → paste metrics into `AMD_ROCM_OPTIMIZATION.md`
- FP16 + RAG shorter context + `max_steps` bound

## Suggested demo questions

1. 请假需要提前几天申请？（RAG）
2. 帮我跑入职IT开通工作流（Workflow / automation）
3. 记住我喜欢简洁中文回答（Memory / productivity）
4. 如何确认 ROCm 可用？（Developer）
5. 涉密文档可以用哪些 AI 工具？（Enterprise copiloting / privacy）
