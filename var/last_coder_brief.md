## Coder Brief
### Problem (2–3 sentences)
[mission_id: mb2_multibody_size_specialist]

### Files / paths / APIs (max 5)
- core/forge-gate3/src/specialists/historic_wreck.rs — primary target
- core/forge-gate3/src/specialists/drift_modeling.rs — primary target
- core/forge-gate3/src/specialists/car_ferry_multibody.rs — primary target
- specialists/mod.rs — primary target
- tests/car_ferry_multibody_specialist.rs — primary target

### Works vs broken
- Broken: task not yet implemented

### Acceptance criteria (testable)
- [ ] write_file on core/forge-gate3/src/specialists/historic_wreck.rs
- [ ] cargo check -p core

### Out of scope
- Other slices/tasks in the mission plan

### Tool budget
- max_tool_rounds: 6
- prefer: head, targeted rg/search_text, partial reads
- forbid: repo-wide find, full-file dumps

### Context budget
- coder n_ctx may be 4096–8192; keep reads and tool results short