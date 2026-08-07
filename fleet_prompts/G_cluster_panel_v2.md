You are an expert web developer (HTML/CSS/JS) and Rust/Axum backend developer. I need a major upgrade to a cluster control panel for a multi-GPU LLM inference cluster.

## Current state
The cluster panel is a single HTML file (792 lines) served by an Axum web server. It has:
- A "CESAROPS" preset button that toggles between scanning mode and freeform mode
- Freeform mode shows 4 role cards (Coder, Thinker, Corrector, Polisher) with a SINGLE "Apply Changes" button that applies all at once
- A configure view with P100 allocation mode and remote node role dropdowns
- A corrector ON/OFF toggle button in the command center
- An agent fleet table (static, read-only)

## What needs to change — full spec

### 1. Per-card individual Apply buttons
REMOVE the single "Apply Changes" button at the bottom of freeform mode.
ADD an "Apply" button to EACH card individually. Each card applies only its own settings.
Each card also gets a "Start" and "Stop" button.
API: POST /cluster/worker/{name}/apply, POST /cluster/worker/{name}/start, POST /cluster/worker/{name}/stop

### 2. Per-card vector injection toggle
Each card gets a toggle: "Vector Inject: ON/OFF"
When ON: the forge injects nautivecs context into that worker's prompts (think_harder results prepended)
When OFF: raw prompts only, no vector injection
Store per-card in cluster_config.toml as [[worker]] inject_vectors = true/false
API: POST /cluster/worker/{name}/set_injection { "enabled": bool }

### 3. Memory pool grouping
Add a "Memory Pool" section above the worker cards.
Users can drag cards into groups OR use a multi-select checkbox per card + "Group Selected" button.
Groups share KV cache and context window across their members.
Visual: grouped cards get a colored border (group 1 = blue, group 2 = green, etc.)
Store as [[memory_pool]] in cluster_config.toml: name, members: ["coder", "thinker"]
API: POST /cluster/memory_pool/create { "name": "pool1", "members": ["coder", "thinker"] }

### 4. Per-card inference engine selection
Each card gets an "Engine" dropdown that is DYNAMICALLY POPULATED by probing what's installed.
Probe logic (called once at page load via GET /cluster/engines):
- Check if koboldcpp binary exists → add "koboldcpp"
- Check if our cesarops-inference binary exists → add "cesarops-inference"  
- Check if ollama is running (port 11434) → add "ollama"
- Check if llama.cpp server binary exists → add "llama.cpp"
The T440 CPU option is ONLY shown for the T440 node (local), not remote nodes.
API: GET /cluster/engines → { "available": ["koboldcpp", "cesarops-inference"], "per_node": {...} }

### 5. Per-card CUDA vs Vulkan toggle
Each card gets a "Backend" toggle: CUDA | Vulkan | CPU
- CPU only shown for T440 local node
- CUDA shown if nvidia-smi shows CUDA capability
- Vulkan always shown (our default)
Visual: pill toggle, selected option highlighted
Store as [[worker]] backend = "cuda" | "vulkan" | "cpu"
API: POST /cluster/worker/{name}/set_backend { "backend": "cuda" }

### 6. Corrector configuration panel
The corrector card gets an expanded config section (collapsible, default collapsed):
Toggle switches for each major function:
- "JSON Fixer" ON/OFF — fixes malformed tool call JSON
- "Loop Detector" ON/OFF — judges whether repeated tool calls are justified  
- "Translator" ON/OFF — translates between model output formats
- "Think Harder" ON/OFF — corrector can invoke think_harder before fixing
- "Auto-Remember" ON/OFF — corrector saves successful fixes to nautivecs
Each toggle calls: POST /cluster/corrector/set_function { "function": "json_fixer", "enabled": bool }
Visual: each function as a labeled toggle row with a status indicator

### 7. Dynamic engine probe (Rust backend)
Add to main.rs:
```rust
async fn get_available_engines() -> Json<serde_json::Value> {
    // Check binaries and running services
    // Return { "available": [...], "per_node": { "local": [...], "100.102.158.111": [...] } }
}
```

### 8. Worker config persistence
All per-card settings (injection, backend, engine, memory_pool) must persist to cluster_config.toml.
The [[worker]] section gains new fields:
```toml
[[worker]]
name = "Coder"
role = "code"
gpu = 0
model = "..."
port = 5001
engine = "koboldcpp"
backend = "vulkan"
inject_vectors = true
memory_pool = "pool1"
corrector_functions = { json_fixer = true, loop_detector = true, translator = true, think_harder = false, auto_remember = true }
```

## Design constraints
- Dark theme, same color palette (#1a1a2e background, #00d4ff accent, #4caf50 green, #ff9800 orange)
- Mobile-friendly (flex layout, wraps on small screens)
- Each card is self-contained — no global state dependencies
- Accessibility: all controls have aria-labels
- No external JS libraries (vanilla JS only)
- The HTML file is served via include_str! in Rust, so it must be a single self-contained file

## OUTPUT FORMAT
Provide:

```html
<!-- === FILE: src/cluster_panel.html === -->
<!-- Complete replacement HTML file, all 800+ lines -->
```

```rust
// === FILE: src/main.rs (new routes to add) ===
// Just the new route handlers and route registrations, not the full file
// Routes needed:
// POST /cluster/worker/{name}/apply
// POST /cluster/worker/{name}/set_injection
// POST /cluster/worker/{name}/set_backend
// POST /cluster/corrector/set_function
// GET  /cluster/engines
// POST /cluster/memory_pool/create
```

```toml
// === FILE: cluster_config.toml (updated schema) ===
// Show the updated [[worker]] section with all new fields
```

Be complete. The HTML must be fully functional, not a skeleton. Include all the JavaScript for the new features.
