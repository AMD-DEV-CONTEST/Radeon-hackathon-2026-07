# Making Non-Thinking Roles Aware of Qdrant/Wayfinder

## The Problem
Roles like **Corrector**, **Cargo Build**, **Validator** need to know: "Should I use Wayfinder to search the codebase before acting?"

## Solution: Tool Introspection System

### Before Each Task, Ask the Model:
```json
{
  "pre_task_check": {
    "question": "To complete this task successfully, do you need any of these tools?",
    "available_tools": [
      {
        "name": "wayfinder_search",
        "description": "Qdrant-powered semantic code search. Use when you need to find where a function is defined, understand code structure, or locate relevant files.",
        "when_to_use": [
          "Finding function definitions",
          "Understanding code architecture",
          "Locating similar patterns",
          "Dependency tracing"
        ]
      },
      {
        "name": "cargo_check",
        "description": "Validates Rust compilation without building. Use before dispatching code missions.",
        "when_to_use": ["Validate syntax", "Check dependencies", "Pre-flight validation"]
      },
      {
        "name": "grep_codebase",
        "description": "Fast text search. Use for exact string matches.",
        "when_to_use": ["Find exact text", "Locate error messages", "Quick lookups"]
      }
    ],
    "your_response": {
      "needs_tools": true/false,
      "which_tools": ["wayfinder_search"],
      "reasoning": "I need to find where the Paddler routing logic lives before I can correct this loop"
    }
  }
}
```

### Tool Response Format:
```json
{
  "tool_decision": {
    "needs_wayfinder": true,
    "search_query": "paddler routing dispatch logic",
    "why": "Model is stuck in mission loop - need to understand routing code structure"
  }
}
```

### Integration Points:

#### 1. **Corrector Role**
```rust
// Before nudging a stuck model
let tool_check = check_tool_needs(
    role: "corrector",
    situation: "model stuck in think loop",
    available: ["wayfinder_search", "grep_codebase"]
);

if tool_check.needs_wayfinder {
    let context = wayfinder.search(tool_check.query);
    corrector.nudge_with_context(context);
}
```

#### 2. **Cargo Build Role**
```rust
// Before validating Rust code
let tool_check = check_tool_needs(
    role: "cargo_validator",
    situation: "about to validate mission code",
    available: ["wayfinder_search", "cargo_check"]
);

if tool_check.needs_wayfinder {
    // Find related code first to understand context
    let deps = wayfinder.find_dependencies(mission.files);
}
```

#### 3. **Validator/Judge Role**  
```rust
// Before judging code quality
let tool_check = check_tool_needs(
    role: "validator",
    situation: "reviewing code submission",
    available: ["wayfinder_search", "git_diff"]
);

if tool_check.needs_wayfinder {
    // Check if similar patterns exist
    let patterns = wayfinder.find_similar(submission.code);
}
```

## Implementation in Forge

### Add to Mission Spec:
```rust
pub struct MissionContext {
    pub role: ForgeRole,
    pub available_tools: Vec<ToolDescriptor>,
    pub wayfinder_enabled: bool,
}

pub struct ToolDescriptor {
    pub name: String,
    pub description: String,
    pub when_to_use: Vec<String>,
    pub cost_ms: u64, // Latency cost
}
```

### Pre-Task Tool Check:
```rust
async fn run_tool_introspection(
    model: &Model,
    task: &Task,
    tools: &[ToolDescriptor]
) -> ToolDecision {
    let prompt = format!(
        "Task: {}\n\nAvailable tools:\n{}\n\nWhich tools do you need?",
        task.description,
        format_tool_list(tools)
    );
    
    let response = model.query(prompt).await;
    parse_tool_decision(response)
}
```

### Corrector Integration:
```rust
if model_is_stuck() {
    let tool_decision = run_tool_introspection(
        &model,
        &current_task,
        &[WAYFINDER, GREP, CARGO]
    ).await;
    
    if tool_decision.needs_wayfinder {
        let context = qdrant.search(&tool_decision.query).await;
        corrector.nudge_with_context(&context);
    } else {
        corrector.nudge_simple();
    }
}
```

## Scorecard Addition

Track tool usage in v1 scorecard:
```json
{
  "tool_introspection": {
    "asked_for_tools": true,
    "requested_tools": ["wayfinder_search"],
    "tools_provided": ["wayfinder_search"],
    "success_after_tools": true,
    "latency_with_tools_ms": 1240
  }
}
```

## Benefits

1. **Models request what they need** (not guessing)
2. **Tracks tool effectiveness** (did wayfinder help?)
3. **Role-specific tool awareness** (Corrector knows it can search)
4. **Cost/benefit analysis** (tool latency vs success rate)
5. **Learning signal** (models that ask for tools = smarter?)

---

**Next Step**: Add `tool_introspection_prompt` to each role's system message, track in scorecard v1 format.
