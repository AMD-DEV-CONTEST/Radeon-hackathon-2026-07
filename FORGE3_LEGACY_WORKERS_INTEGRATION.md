# Forge 3 - Legacy Worker Integration Guide

## Overview
Old Forge v2 had specialized workers running on different nodes. These need to be wired into Forge 3's role system.

## Legacy Workers Found

### 1. **Corrector** (14B Coder on Marvin - 1070 GPU)
- **URL**: `http://100.102.158.111:5555`
- **Role**: Fixes malformed tool calls, JSON errors
- **Current Status**: Already partially integrated in `loop_engine.rs`
- **Function**: Routes bad JSON to corrector, gets fixed output back

### 2. **WSO Search** (Wayfinder/Semantic Search)
- **URL**: `http://127.0.0.1:5010/search`
- **Role**: Semantic code search (the Qdrant/Wayfinder we discussed!)
- **Function**: Vector similarity search over codebase

### 3. **Nautivecs** (Vector Memory)
- **URL**: `http://127.0.0.1:5003/query`
- **Role**: Stores corrections, patterns, learnings
- **Function**: Remember/recall system for injecting context

### 4. **Coder** (35B on P100s)
- **URL**: `http://127.0.0.1:5001`
- **Current**: Qwen3.6 35B
- **Role**: Thomas Translator / Primary coder

### 5. **Thinker** (R1 on Xeon CPU)
- **URL**: `http://127.0.0.1:5557`
- **Current**: DeepSeek-R1 7B
- **Role**: Architecture, reasoning, planning

---

## Current Integration (Forge V2 → V3)

### ✅ Already Wired:
```rust
// In old forge v2 - src/main.rs
pub struct ForgeConfig {
    pub coder_url: String,        // 35B on P100s
    pub thinker_url: String,      // R1 on Xeon
    pub corrector_url: String,    // 14B on 1070 (Marvin)
    pub nautivecs_url: String,    // Vector memory
    pub wso_url: String,          // WSO Search = Wayfinder!
}
```

### ✅ Corrector Already Working:
```rust
// In loop_engine.rs
if matches!(failure_type, FailureType::MalformedToolCall) {
    info!("Routing malformed tool call to 14B Corrector (Marvin)");
    let corrected = correct_and_execute(&raw_output, &normalized.content, state).await;
    // Corrector fixes JSON, returns valid tool call
}
```

---

## What Needs To Be Done

### 1. Wire WSO Search as Available Tool

**Add to system prompts:**
```rust
pub fn get_tools_for_role(role: ForgeRole) -> Vec<ToolDescriptor> {
    vec![
        ToolDescriptor {
            name: "wso_search".to_string(),
            endpoint: "http://127.0.0.1:5010/search".to_string(),
            description: "Semantic code search via Qdrant/Wayfinder".to_string(),
            when_to_use: vec![
                "Finding function definitions".to_string(),
                "Understanding code architecture".to_string(),
                "Locating similar patterns".to_string(),
            ],
            parameters: json!({
                "query": "string",
                "limit": "number (optional, default 5)"
            })
        },
        ToolDescriptor {
            name: "nautivecs_remember".to_string(),
            endpoint: "http://127.0.0.1:5003/remember".to_string(),
            description: "Store a learning/correction for future use".to_string(),
            parameters: json!({
                "content": "string",
                "tags": "string (comma-separated)"
            })
        },
        ToolDescriptor {
            name: "nautivecs_recall".to_string(),
            endpoint: "http://127.0.0.1:5003/query".to_string(),
            description: "Retrieve relevant past learnings".to_string(),
            parameters: json!({
                "query": "string",
                "limit": "number (optional)"
            })
        }
    ]
}
```

### 2. Add Tool Execution Handler

```rust
// In forge/src/tools.rs or similar

pub async fn execute_wso_search(query: &str, limit: Option<usize>) -> Result<Vec<SearchResult>> {
    let client = reqwest::Client::new();
    let response = client
        .post("http://127.0.0.1:5010/search")
        .json(&json!({
            "query": query,
            "limit": limit.unwrap_or(5)
        }))
        .send()
        .await?;
    
    let results: Vec<SearchResult> = response.json().await?;
    Ok(results)
}

pub async fn nautivecs_remember(content: &str, tags: &str) -> Result<()> {
    let client = reqwest::Client::new();
    client
        .post("http://127.0.0.1:5003/remember")
        .json(&json!({
            "content": content,
            "tags": tags
        }))
        .send()
        .await?;
    Ok(())
}

pub async fn nautivecs_recall(query: &str) -> Result<Vec<Memory>> {
    let client = reqwest::Client::new();
    let response = client
        .post("http://127.0.0.1:5003/query")
        .json(&json!({"query": query}))
        .send()
        .await?;
    
    let memories: Vec<Memory> = response.json().await?;
    Ok(memories)
}
```

### 3. Update System Prompts

**For ALL roles, add to system message:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVAILABLE TOOLS (call these by name in your responses):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 wso_search
   Semantic code search powered by Qdrant/Wayfinder
   Args: query (string), limit (optional number)
   Example: wso_search("paddler routing dispatch")
   
💾 nautivecs_remember
   Store a correction/learning for future use
   Args: content (string), tags (string)
   Example: nautivecs_remember("Correct tool format: {...}", "tool_call,fix")
   
🧠 nautivecs_recall
   Retrieve relevant past learnings/corrections
   Args: query (string), limit (optional)
   Example: nautivecs_recall("tool call format examples")
   
📝 read_file
   Read file contents
   Args: path (string)
   
🔧 cargo_check
   Validate Rust compilation
   
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**IMPORTANT**: Before writing code, use wso_search to find existing implementations!
```

### 4. Make Corrector Multi-Modal

Current corrector only fixes JSON. Expand it:

```rust
pub enum CorrectorMode {
    FixJSON,           // Current: fix malformed tool calls
    NudgeLoop,         // New: nudge stuck thinking loops
    SuggestTool,       // New: suggest using wso_search
    EscalateTimeout,   // New: escalate on timeout
}

pub async fn corrector_intervene(
    mode: CorrectorMode,
    context: &str,
    model_output: &str,
    config: &ForgeConfig
) -> Option<CorrectorResult> {
    match mode {
        CorrectorMode::FixJSON => {
            // Current implementation
            fix_malformed_json(model_output, config).await
        },
        CorrectorMode::NudgeLoop => {
            // "You're stuck. Try using wso_search to find relevant code."
            nudge_with_tool_suggestion(context, config).await
        },
        CorrectorMode::SuggestTool => {
            // "Have you considered using wso_search?"
            suggest_tool_use(context, config).await
        },
        CorrectorMode::EscalateTimeout => {
            // "STOP. Call a tool NOW or I'm killing this task."
            escalate_timeout(context, config).await
        }
    }
}
```

---

## Migration Checklist

### Phase 1: Expose Existing Workers
- [ ] Add WSO search endpoint to Forge 3 config
- [ ] Add Nautivecs endpoints to Forge 3 config
- [ ] Test connectivity to all old workers
- [ ] Document which workers are on which nodes/GPUs

### Phase 2: Make Tools Callable
- [ ] Add tool descriptors to system prompts
- [ ] Implement tool execution handlers
- [ ] Add tool call detection in loop_engine
- [ ] Route tool calls to appropriate endpoints

### Phase 3: Expand Corrector
- [ ] Add multi-modal corrector modes
- [ ] Implement escalation ladder (suggest → demand → kill)
- [ ] Add corrector-with-context (inject wso_search results)
- [ ] Track corrector effectiveness in scorecards

### Phase 4: Scorecard Integration
- [ ] Add `tools_used` field to v1 scorecard
- [ ] Track which tools were requested
- [ ] Track success rate with/without tools
- [ ] Add `corrector_mode` field

---

## Node/GPU Mapping (Current)

| Worker | Node | GPU | Model | Port |
|--------|------|-----|-------|------|
| **Coder** | T440 | 2x P100 | Qwen3.6-35B / Ornith-35B | 5001 |
| **Thinker** | ? | Xeon CPU | DeepSeek-R1-7B | 5557 |
| **Corrector** | Marvin | GTX 1070 | 14B Coder | 5555 (tailscale) |
| **WSO Search** | Local | - | Qdrant | 5010 |
| **Nautivecs** | Local | - | Vector DB | 5003 |

---

## Example: Model Using WSO Search

**Before (model guessing):**
```
Model: "I need to modify the paddler routing logic..."
[searches filesystem manually, maybe finds it, maybe doesn't]
```

**After (model using tools):**
```
Model: "Let me search for paddler routing first."
Tool Call: wso_search("paddler routing dispatch")
Result: [
  {file: "forge/src/agent_dispatch.rs", line: 45, snippet: "pub fn dispatch_to_role..."},
  {file: "forge/src/paddler.rs", line: 120, snippet: "fn route_mission..."}
]
Model: "Found it! Now I'll modify forge/src/agent_dispatch.rs line 45..."
```

---

## Notes for Implementation

1. **WSO Search = Wayfinder** - Same thing, different names
2. **Corrector already exists** - Just needs expansion beyond JSON fixing
3. **Nautivecs is memory** - Models should remember corrections
4. **All workers are HTTP endpoints** - Easy to integrate
5. **Tool calls need parsing** - Models must format: `tool_name(arg1, arg2)`

---

## Testing Connectivity

Before wiring in, verify all legacy endpoints are reachable:

```bash
# Test WSO Search (Wayfinder/Qdrant)
curl -X POST http://127.0.0.1:5010/search \
  -H "Content-Type: application/json" \
  -d '{"query": "paddler routing", "limit": 3}'

# Test Nautivecs Memory
curl -X POST http://127.0.0.1:5003/query \
  -H "Content-Type: application/json" \
  -d '{"query": "tool call format", "top_k": 3}'

# Test Corrector (Marvin Tailscale)
curl -X POST http://100.102.158.111:5555/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Fix this JSON: {\"name\": \"test\"", "max_length": 256}'

# Test Coder
curl -X POST http://127.0.0.1:5001/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "max_length": 50}'

# Test Thinker
curl -X POST http://127.0.0.1:5557/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Think about this problem", "max_length": 100}'
```

---

## Scorecard V1 Tool Tracking Extension

Add to existing v1 scorecard format:

```json
{
  "tool_usage": {
    "tools_requested": ["wso_search", "nautivecs_recall"],
    "tools_provided": ["wso_search", "nautivecs_recall"],
    "wso_calls": 2,
    "nautivecs_calls": 1,
    "corrector_interventions": 1,
    "corrector_modes": ["FixJSON"],
    "success_after_tools": true,
    "latency_without_tools_ms": 551,
    "latency_with_tools_ms": 1240,
    "tool_overhead_ms": 689
  }
}
```

---

## Implementation Priority

### Phase 1: WSO Search (Highest ROI)
**Impact**: Models can search codebase before guessing  
**Complexity**: Low - just HTTP endpoint  
**Time**: 2 hours

### Phase 2: Nautivecs Memory  
**Impact**: Models learn from corrections  
**Complexity**: Low - HTTP endpoint + local file append  
**Time**: 1 hour

### Phase 3: Expand Corrector
**Impact**: Unstuck models, suggest tools  
**Complexity**: Medium - multi-modal routing logic  
**Time**: 3 hours

### Phase 4: Scorecard Tool Tracking
**Impact**: Measure tool effectiveness  
**Complexity**: Low - extend JSON schema  
**Time**: 1 hour

---

**Status**: Documentation complete. Ready for implementation.

**Next Action**: Test connectivity, then implement Phase 1 (WSO Search integration).
