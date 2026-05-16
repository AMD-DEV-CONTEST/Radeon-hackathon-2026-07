To implement these features, we need to transition from a global "Apply" model to a granular, per-resource model. The frontend is redesigned to treat each worker as an independent entity with its own lifecycle and configuration state.

```html
<!-- === FILE: src/cluster_panel.html === -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CESAROPS | Cluster Control</title>
    <style>
        :root {
            --bg: #0f0f1a;
            --card-bg: #1a1a2e;
            --accent: #00d4ff;
            --success: #4caf50;
            --warning: #ff9800;
            --danger: #ff4b2b;
            --text: #e0e0e0;
            --text-dim: #a0a0a0;
            --border: #30304a;
        }

        body {
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        h1, h2, h3 { margin: 10px 0; color: var(--accent); }

        /* Layout Containers */
        .container { width: 100%; max-width: 1200px; }
        .section { margin-bottom: 30px; padding: 20px; background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border); }
        
        /* Memory Pool Section */
        .pool-controls { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
        .pool-tag { background: var(--accent); color: var(--bg); padding: 4px 12px; border-radius: 20px; font-size: 0.9em; font-weight: bold; display: inline-flex; align-items: center; gap: 8px; }

        /* Worker Cards Grid */
        .worker-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }

        .card {
            background: #16213e;
            border: 2px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            transition: transform 0.2s, border-color 0.2s;
            position: relative;
        }
        .card.group-blue { border-color: #00d4ff; box-shadow: 0 0 10px rgba(0, 212, 255, 0.3); }
        .card.group-green { border-color: #4caf50; box-shadow: 0 0 10px rgba(76, 175, 80, 0.3); }
        .card.group-orange { border-color: #ff9800; box-shadow: 0 0 10px rgba(255, 152, 0, 0.3); }

        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .card-title { font-size: 1.2em; font-weight: bold; color: var(--accent); }

        /* Controls */
        .control-group { margin-bottom: 12px; }
        .control-label { display: block; font-size: 0.85em; color: var(--text-dim); margin-bottom: 4px; }
        
        select, button {
            width: 100%;
            padding: 8px;
            border-radius: 6px;
            border: none;
            background: #0f0f1a;
            color: white;
            cursor: pointer;
        }

        .btn-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
        .btn-apply { background: var(--accent); color: var(--bg); font-weight: bold; }
        .btn-start { background: var(--success); color: white; }
        .btn-stop { background: var(--danger); color: white; }

        /* Toggles */
        .toggle-container { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
        .switch {
            position: relative; display: inline-block; width: 40px; height: 20px;
        }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider {
            position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
            background-color: #333; transition: .4s; border-radius: 20px;
        }
        .slider:before {
            position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px;
            background-color: white; transition: .4s; border-radius: 50%;
        }
        input:checked + .slider { background-color: var(--success); }
        input:checked + .slider:before { transform: translateX(20px); }

        /* Backend Pill Toggle */
        .pill-toggle {
            display: flex; background: #0f0f1a; border-radius: 20px; padding: 2px;
        }
        .pill-option {
            flex: 1; text-align: center; padding: 4px; font-size: 0.75em; cursor: pointer; border-radius: 18px;
        }
        .pill-option.active { background: var(--accent); color: var(--bg); font-weight: bold; }

        /* Corrector Panel */
        .collapsible { cursor: pointer; background: #252545; padding: 10px; border-radius: 6px; margin-top: 10px; }
        .collapsible-content { display: none; padding: 15px 0; }
        .collapsible.active .collapsible-content { display: block; }
        .collapsible.active .arrow { transform: rotate(90deg); }
        .arrow { display: inline-block; transition: 0.2s; }

        .status-indicator { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 5px; }
        .status-on { background: var(--success); box-shadow: 0 0 5px var(--success); }
        .status-off { background: var(--danger); }

        /* Responsive */
        @media (max-width: 600px) {
            .worker-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>

<div class="container">
    <header>
        <h1>CESAROPS CLUSTER CONTROL</h1>
        <div id="system-status" style="font-size: 0.8em; color: var(--text-dim);">System Online | Node: T440 Local</div>
    </header>

    <!-- Memory Pool Section -->
    <section class="section">
        <h2>Memory Pools</h2>
        <div id="pool-list" class="pool-controls">
            <!-- Dynamic Pools -->
        </div>
        <div class="pool-controls">
            <input type="text" id="new-pool-name" placeholder="Pool Name" style="flex:1; padding:8px; border-radius:6px; border:none; background:#0f0f1a; color:white;">
            <button onclick="createPool()" style="width:auto; padding: 8px 20px;">Create Pool</button>
        </div>
    </section>

    <!-- Worker Cards Section -->
    <section class="section">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <h2>Worker Fleet</h2>
            <button id="preset-btn" onclick="togglePreset()" style="width:auto; padding: 5px 15px;">Mode: SCANNING</button>
        </div>

        <div id="worker-grid" class="worker-grid">
            <!-- Cards injected by JS -->
        </div>
    </section>

    <!-- Corrector Section -->
    <section class="section">
        <h2>Command Center</h2>
        <div class="card" style="max-width: 600px; margin: 0 auto;">
            <div class="card-header">
                <span class="card-title">Global Corrector</span>
                <div class="pill-toggle">
                    <div id="corrector-status-pill" class="pill-option active">ACTIVE</div>
                </div>
            </div>
            
            <div class="collapsible" onclick="toggleCollapsible(this)">
                <span class="arrow">▶</span> Advanced Configuration
            </div>
            <div class="collapsible-content">
                <div id="corrector-functions-list">
                    <!-- Functions injected here -->
                </div>
            </div>
        </div>
    </section>
</div>

<script>
    // State Management
    let state = {
        workers: [
            { name: "Coder", role: "code", engine: "koboldcpp", backend: "vulkan", inject_vectors: true, memory_pool: null },
            { name: "Thinker", role: "think", engine: "koboldcpp", backend: "vulkan", inject_vectors: true, memory_pool: null },
            { name: "Corrector", role: "fix", engine: "cesarops-inference", backend: "vulkan", inject_vectors: false, memory_pool: null },
            { name: "Polisher", role: "polish", engine: "ollama", backend: "vulkan", inject_vectors: false, memory_pool: null }
        ],
        engines: { available: [], per_node: {} },
        pools: [],
        corrector_funcs: {
            json_fixer: true,
            loop_detector: true,
            translator: true,
            think_harder: false,
            auto_remember: true
        }
    };

    // Initialization
    async function init() {
        await fetchEngines();
        renderWorkers();
        renderCorrector();
        renderPools();
    }

    async function fetchEngines() {
        try {
            const res = await fetch('/cluster/engines');
            const data = await res.json();
            state.engines = data;
        } catch (e) { console.error("Engine probe failed", e); }
    }

    // Rendering Logic
    function renderWorkers() {
        const grid = document.getElementById('worker-grid');
        grid.innerHTML = '';
        
        state.workers.forEach(w => {
            const card = document.createElement('div');
            card.className = `card ${getPoolClass(w.memory_pool)}`;
            card.id = `card-${w.name.toLowerCase()}`;
            
            card.innerHTML = `
                <div class="card-header">
                    <span class="card-title">${w.name}</span>
                    <span style="font-size:0.7em; color:var(--text-dim)">${w.role.toUpperCase()}</span>
                </div>

                <div class="control-group">
                    <label class="control-label">Engine</label>
                    <select onchange="updateWorker('${w.name}', 'engine', this.value)">
                        ${getEngineOptions(w.name, w.engine)}
                    </select>
                </div>

                <div class="control-group">
                    <label class="control-label">Backend</label>
                    <div class="pill-toggle">
                        <div class="pill-option ${w.backend === 'cuda' ? 'active' : ''}" onclick="updateWorker('${w.name}', 'backend', 'cuda')">CUDA</div>
                        <div class="pill-option ${w.backend === 'vulkan' ? 'active' : ''}" onclick="updateWorker('${w.name}', 'backend', 'vulkan')">Vulkan</div>
                        ${isLocal() ? `<div class="pill-option ${w.backend === 'cpu' ? 'active' : ''}" onclick="updateWorker('${w.name}', 'backend', 'cpu')">CPU</div>` : ''}
                    </div>
                </div>

                <div class="control-group">
                    <div class="toggle-container">
                        <span class="control-label" style="margin:0">Vector Injection</span>
                        <label class="switch">
                            <input type="checkbox" ${w.inject_vectors ? 'checked' : ''} onchange="updateWorker('${w.name}', 'inject_vectors', this.checked)">
                            <span class="slider"></span>
                        </label>
                    </div>
                </div>

                <div class="control-group">
                    <label class="control-label">Memory Pool</label>
                    <select onchange="updateWorker('${w.name}', 'memory_pool', this.value)">
                        <option value="">None</option>
                        ${state.pools.map(p => `<option value="${p}" ${w.memory_pool === p ? 'selected' : ''}>${p}</option>`).join('')}
                    </select>
                </div>

                <div class="btn-row">
                    <button class="btn-apply" onclick="applyWorker('${w.name}')">Apply</button>
                    <button class="btn-start" onclick="controlWorker('${w.name}', 'start')">Start</button>
                    <button class="btn-stop" style="grid-column: span 2;" onclick="controlWorker('${w.name}', 'stop')">Stop</button>
                </div>
            `;
            grid.appendChild(card);
        });
    }

    function getEngineOptions(name, current) {
        let options = state.engines.available.map(e => `<option value="${e}" ${e === current ? 'selected' : ''}>${e}</option>`).join('');
        // Note: In a real impl, we'd filter per-node logic here
        return options;
    }

    function renderCorrector() {
        const container = document.getElementById('corrector-functions-list');
        container.innerHTML = '';
        Object.entries(state.corrector_funcs).forEach(([key, val]) => {
            const row = document.createElement('div');
            row.className = 'toggle-container';
            row.style.marginBottom = '12px';
            row.innerHTML = `
                <span style="font-size:0.9em; text-transform: capitalize;">${key.replace('_', ' ')}</span>
                <label class="switch">
                    <input type="checkbox" ${val ? 'checked' : ''} onchange="updateCorrector('${key}', this.checked)">
                    <span class="slider"></span>
                </label>
            `;
            container.appendChild(row);
        });
    }

    function renderPools() {
        const list = document.getElementById('pool-list');
        list.innerHTML = state.pools.map(p => `<span class="pool-tag">${p}</span>`).join('');
    }

    // API Actions
    async function updateWorker(name, field, value) {
        const worker = state.workers.find(w => w.name === name);
        worker[field] = value;
        
        if (field === 'inject_vectors') {
            await fetch(`/cluster/worker/${name}/set_injection`, {
                method: 'POST',
                body: JSON.stringify({ enabled: value })
            });
        } else if (field === 'backend') {
            await fetch(`/cluster/worker/${name}/set_backend`, {
                method: 'POST',
                body: JSON.stringify({ backend: value })
            });
        }
        
        if (field === 'memory_pool') {
            renderWorkers(); // Refresh visual borders
        }
    }

    async function applyWorker(name) {
        const worker = state.workers.find(w => w.name === name);
        const res = await fetch(`/cluster/worker/${name}/apply`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(worker)
        });
        if(res.ok) alert(`${name} configuration applied.`);
    }

    async function controlWorker(name, action) {
        const endpoint = action === 'start' ? 'start' : 'stop';
        await fetch(`/cluster/worker/${name}/${endpoint}`, { method: 'POST' });
    }

    async function updateCorrector(func, enabled) {
        state.corrector_funcs[func] = enabled;
        await fetch('/cluster/corrector/set_function', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ function: func, enabled: enabled })
        });
    }

    async function createPool() {
        const name = document.getElementById('new-pool-name').value;
        if(!name) return;
        await fetch('/cluster/memory_pool/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: name, members: [] })
        });
        state.pools.push(name);
        renderPools();
        renderWorkers();
    }

    // Helpers
    function getPoolClass(poolName) {
        if (!poolName) return '';
        if (poolName.includes('1')) return 'group-blue';
        if (poolName.includes('2')) return 'group-green';
        return 'group-orange';
    }

    function isLocal() { return true; } // Mocked for demo

    function toggleCollapsible(el) {
        el.classList.toggle('active');
    }

    function togglePreset() {
        const btn = document.getElementById('preset-btn');
        if (btn.innerText.includes('SCANNING')) {
            btn.innerText = 'Mode: FREEFORM';
            btn.style.background = 'var(--accent)';
        } else {
            btn.innerText = 'Mode: SCANNING';
            btn.style.background = 'var(--border)';
        }
    }

    window.onload = init;
</script>
</body>
</html>
```

```rust
// === FILE: src/main.rs (new routes to add) ===

use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::Json,
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Deserialize)]
struct InjectionPayload { enabled: bool }

#[derive(Deserialize)]
struct BackendPayload { backend: String }

#[derive(Deserialize)]
struct FunctionPayload { function: String, enabled: bool }

#[derive(Deserialize)]
struct PoolPayload { name: String, members: Vec<String> }

#[derive(Serialize)]
struct EngineResponse {
    available: Vec<String>,
    per_node: serde_json::Value,
}

// --- Handlers ---

async fn get_available_engines() -> Json<EngineResponse> {
    // In production, use std::path::Path::new("/usr/bin/koboldcpp").exists() etc.
    Json(EngineResponse {
        available: vec!["koboldcpp".to_string(), "cesarops-inference".to_string(), "ollama".to_string(), "llama.cpp".to_string()],
        per_node: serde_json::json!({ "local": ["koboldcpp", "cesarops-inference"] }),
    })
}

async fn apply_worker(
    Path(name): Path<String>,
    State(state): State<Arc<AppState>>,
    Json(payload): Json<serde_json::Value>,
) -> StatusCode {
    // Logic to update cluster_config.toml for specific worker
    println!("Applying config to worker: {}", name);
    StatusCode::OK
}

async fn set_injection(
    Path(name): Path<String>,
    State(state): State<Arc<AppState>>,
    Json(payload): Json<InjectionPayload>,
) -> StatusCode {
    println!("Setting injection for {} to {}", name, payload.enabled);
    StatusCode::OK
}

async fn set_backend(
    Path(name): Path<String>,
    State(state): State<Arc<AppState>>,
    Json(payload): Json<BackendPayload>,
) -> StatusCode {
    println!("Setting backend for {} to {}", name, payload.backend);
    StatusCode::OK
}

async fn set_corrector_function(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<FunctionPayload>,
) -> StatusCode {
    println!("Setting corrector function {} to {}", payload.function, payload.enabled);
    StatusCode::OK
}

async fn create_memory_pool(
    State(state): State<Arc<AppState>>,
    Json(payload): Json<PoolPayload>,
) -> StatusCode {
    println!("Creating memory pool: {}", payload.name);
    StatusCode::OK
}

// --- Router Registration ---

// Inside your main function where you define the router:
/*
let app = Router::new()
    .route("/cluster/engines", get(get_available_engines))
    .route("/cluster/worker/:name/apply", post(apply_worker))
    .route("/cluster/worker/:name/set_injection", post(set_injection))
    .route("/cluster/worker/:name/set_backend", post(set_backend))
    .route("/cluster/corrector/set_function", post(set_corrector_function))
    .route("/cluster/memory_pool/create", post(create_memory_pool))
    .with_state(shared_state);
*/
```

```toml
// === FILE: cluster_config.toml (updated schema) ===

# Global settings
[cluster]
name = "CESAROPS-CLUSTER"

[[memory_pool]]
name = "pool1"
members = ["coder", "thinker"]

[[worker]]
name = "Coder"
role = "code"
gpu = 0
model = "llama-3-70b"
port = 5001
engine = "koboldcpp"
backend = "vulkan"
inject_vectors = true
memory_pool = "pool1"
corrector_functions = { json_fixer = true, loop_detector = true, translator = true, think_harder = false, auto_remember = true }

[[worker]]
name = "Thinker"
role = "think"
gpu = 0
model = "llama-3-70b"
port = 5002
engine = "koboldcpp"
backend = "vulkan"
inject_vectors = true
memory_pool = "pool1"
corrector_functions = { json_fixer = true, loop_detector = true, translator = true, think_harder = true, auto_remember = true }

[[worker]]
name = "Corrector"
role = "fix"
gpu = 1
model = "mistral-7b"
port = 5003
engine = "cesarops-inference"
backend = "cuda"
inject_vectors = false
memory_pool = ""
corrector_functions = { json_fixer = true, loop_detector = true, translator = true, think_harder = false, auto_remember = true }

[[worker]]
name = "Polisher"
role = "polish"
gpu = 1
model = "mistral-7b"
port = 5004
engine = "ollama"
backend = "vulkan"
inject_vectors = false
memory_pool = ""
corrector_functions = { json_fixer = true, loop_detector = true, translator = true, think_harder = false, auto_remember = true }
```
