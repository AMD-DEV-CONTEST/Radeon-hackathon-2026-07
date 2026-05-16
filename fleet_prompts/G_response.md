To implement this upgrade, we are moving from a global state model to a distributed, per-agent control model. The UI is being redesigned to treat each worker as an independent micro-service instance.

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
            --border: #2d2d44;
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

        header {
            width: 100%;
            max-width: 1200px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 15px;
        }

        h1 { margin: 0; font-size: 1.5rem; letter-spacing: 2px; color: var(--accent); }

        .container { width: 100%; max-width: 1200px; }

        /* Memory Pool Section */
        .memory-pool-section {
            background: var(--card-bg);
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid var(--border);
        }
        .pool-controls { display: flex; gap: 10px; align-items: center; margin-top: 10px; }
        .pool-list { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
        .pool-tag { 
            background: var(--accent); color: var(--bg); 
            padding: 4px 12px; border-radius: 15px; font-size: 0.8rem; font-weight: bold; 
        }

        /* Worker Grid */
        .worker-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }

        .card {
            background: var(--card-bg);
            border: 2px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            transition: transform 0.2s, border-color 0.3s;
            position: relative;
        }
        .card.selected { border-color: var(--accent); }
        .card.group-1 { border-color: #00d4ff; box-shadow: 0 0 10px rgba(0, 212, 255, 0.2); }
        .card.group-2 { border-color: #4caf50; box-shadow: 0 0 10px rgba(76, 175, 80, 0.2); }
        .card.group-3 { border-color: #ff9800; box-shadow: 0 0 10px rgba(255, 152, 0, 0.2); }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 15px;
        }
        .card-title { font-size: 1.2rem; font-weight: bold; color: var(--accent); }
        .card-role { font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; }

        .control-group { margin-bottom: 15px; }
        .control-label { display: block; font-size: 0.75rem; color: var(--text-dim); margin-bottom: 5px; text-transform: uppercase; }

        select, button {
            width: 100%;
            background: #2d2d44;
            color: white;
            border: none;
            padding: 8px;
            border-radius: 4px;
            cursor: pointer;
        }

        .btn-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
        .btn-apply { background: var(--accent); color: var(--bg); font-weight: bold; margin-top: 10px; }
        .btn-start { background: var(--success); }
        .btn-stop { background: var(--danger); }

        /* Toggles */
        .toggle-container {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .switch {
            position: relative;
            display: inline-block;
            width: 40px;
            height: 20px;
        }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider {
            position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
            background-color: #444; transition: .4s; border-radius: 20px;
        }
        .slider:before {
            position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px;
            background-color: white; transition: .4s; border-radius: 50%;
        }
        input:checked + .slider { background-color: var(--success); }
        input:checked + .slider:before { transform: translateX(20px); }

        /* Backend Pill Toggle */
        .pill-toggle {
            display: flex;
            background: #0f0f1a;
            border-radius: 20px;
            padding: 2px;
            margin-top: 5px;
        }
        .pill {
            flex: 1;
            text-align: center;
            font-size: 0.7rem;
            padding: 4px 0;
            cursor: pointer;
            border-radius: 18px;
            transition: 0.2s;
        }
        .pill.active { background: var(--accent); color: var(--bg); font-weight: bold; }

        /* Corrector Panel */
        .corrector-panel {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-top: 20px;
        }
        .collapsible-header {
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .collapsible-content {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid var(--border);
        }
        .function-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
        }

        /* Checkbox for grouping */
        .group-checkbox {
            width: 18px;
            height: 18px;
            margin-right: 10px;
            accent-color: var(--accent);
        }

        .status-indicator {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 5px;
        }
        .status-on { background: var(--success); box-shadow: 0 0 5px var(--success); }
        .status-off { background: var(--danger); }

        @media (max-width: 600px) {
            .worker-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>

<header>
    <h1>CESAROPS <span style="font-weight: 100; font-size: 0.8rem; color: var(--text-dim);">CLUSTER CONTROL</span></h1>
    <div id="global-status">
        <span class="status-indicator status-on"></span> SYSTEM ONLINE
    </div>
</header>

<div class="container">
    <!-- Memory Pool Section -->
    <section class="memory-pool-section">
        <div class="control-label">Memory Pool Management</div>
        <div class="pool-list" id="pool-list-display">
            <!-- Pools injected here -->
        </div>
        <div class="pool-controls">
            <input type="text" id="new-pool-name" placeholder="Pool Name" style="flex:1; background:#0f0f1a; border:1px solid var(--border); color:white; padding:5px;">
            <button onclick="createMemoryPool()" style="width:auto; padding: 5px 15px;">Create Pool</button>
        </div>
    </section>

    <!-- Worker Grid -->
    <div class="worker-grid" id="worker-grid">
        <!-- Cards injected here -->
    </div>

    <!-- Corrector Panel -->
    <section class="corrector-panel">
        <div class="collapsible-header" onclick="toggleCorrector()">
            <div style="font-weight: bold; color: var(--accent);">CORRECTOR ENGINE CONFIGURATION</div>
            <div id="corrector-arrow">▼</div>
        </div>
        <div class="collapsible-content" id="corrector-content">
            <div id="corrector-functions-list">
                <!-- Functions injected here -->
            </div>
        </div>
    </section>
</div>

<script>
    // State
    let workers = [];
    let pools = [];
    let engines = { available: [], per_node: {} };
    let selectedWorkerIds = new Set();

    // Initialization
    async function init() {
        await fetchEngines();
        await fetchConfig();
        render();
    }

    async function fetchEngines() {
        const res = await fetch('/cluster/engines');
        engines = await res.json();
    }

    async function fetchConfig() {
        // In a real app, this would be a GET /cluster/config
        // For this demo, we assume the server provides the current state
        const res = await fetch('/cluster/config');
        const data = await res.json();
        workers = data.workers;
        pools = data.pools;
    }

    // API Calls
    async function apiPost(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        return res.json();
    }

    async function applyWorker(name) {
        const card = workers.find(w => w.name === name);
        await apiPost(`/cluster/worker/${name}/apply`, card);
        alert(`${name} settings applied.`);
    }

    async function toggleInjection(name, enabled) {
        await apiPost(`/cluster/worker/${name}/set_injection`, { enabled });
        const w = workers.find(x => x.name === name);
        w.inject_vectors = enabled;
    }

    async function setBackend(name, backend) {
        await apiPost(`/cluster/worker/${name}/set_backend`, { backend });
        const w = workers.find(x => x.name === name);
        w.backend = backend;
    }

    async function setCorrectorFunc(func, enabled) {
        await apiPost(`/cluster/corrector/set_function`, { function: func, enabled });
    }

    async function createMemoryPool() {
        const name = document.getElementById('new-pool-name').value;
        if (!name) return;
        const selected = Array.from(selectedWorkerIds);
        await apiPost('/cluster/memory_pool/create', { name, members: selected });
        document.getElementById('new-pool-name').value = '';
        init();
    }

    // UI Logic
    function toggleWorkerSelection(name) {
        if (selectedWorkerIds.has(name)) selectedWorkerIds.delete(name);
        else selectedWorkerIds.add(name);
        render();
    }

    function toggleCorrector() {
        const content = document.getElementById('corrector-content');
        const arrow = document.getElementById('corrector-arrow');
        if (content.style.display === 'none') {
            content.style.display = 'block';
            arrow.innerText = '▼';
        } else {
            content.style.display = 'none';
            arrow.innerText = '▲';
        }
    }

    function render() {
        // Render Pools
        const poolList = document.getElementById('pool-list-display');
        poolList.innerHTML = pools.map(p => `
            <div class="pool-tag">${p.name} <span style="cursor:pointer; margin-left:5px;" onclick="deletePool('${p.name}')">×</span></div>
        `).join('');

        // Render Workers
        const grid = document.getElementById('worker-grid');
        grid.innerHTML = workers.map(w => {
            const isSelected = selectedWorkerIds.has(w.name);
            const poolClass = w.memory_pool ? `group-${getPoolColorIndex(w.memory_pool)}` : '';
            
            // Determine available engines for this node
            // Logic: if local, show all. If remote, show node-specific.
            const nodeEngines = engines.per_node[w.node_ip] || engines.available;

            return `
                <div class="card ${isSelected ? 'selected' : ''} ${poolClass}">
                    <div class="card-header">
                        <div>
                            <input type="checkbox" class="group-checkbox" ${isSelected ? 'checked' : ''} 
                                onclick="event.stopPropagation(); toggleWorkerSelection('${w.name}')">
                            <span class="card-title">${w.name}</span>
                        </div>
                        <span class="card-role">${w.role}</span>
                    </div>

                    <div class="control-group">
                        <label class="control-label">Inference Engine</label>
                        <select onchange="updateEngine('${w.name}', this.value)">
                            ${nodeEngines.map(e => `<option value="${e}" ${w.engine === e ? 'selected' : ''}>${e}</option>`).join('')}
                        </select>
                    </div>

                    <div class="control-group">
                        <label class="control-label">Backend</label>
                        <div class="pill-toggle">
                            <div class="pill ${w.backend === 'cuda' ? 'active' : ''}" onclick="setBackend('${w.name}', 'cuda')">CUDA</div>
                            <div class="pill ${w.backend === 'vulkan' ? 'active' : ''}" onclick="setBackend('${w.name}', 'vulkan')">VULKAN</div>
                            ${w.node_ip === '127.0.0.1' ? `<div class="pill ${w.backend === 'cpu' ? 'active' : ''}" onclick="setBackend('${w.name}', 'cpu')">CPU</div>` : ''}
                        </div>
                    </div>

                    <div class="control-group">
                        <div class="toggle-container">
                            <span class="control-label" style="margin:0">Vector Injection</span>
                            <label class="switch">
                                <input type="checkbox" ${w.inject_vectors ? 'checked' : ''} onchange="toggleInjection('${w.name}', this.checked)">
                                <span class="slider"></span>
                            </label>
                        </div>
                    </div>

                    <div class="btn-row">
                        <button class="btn-start" onclick="startWorker('${w.name}')">START</button>
                        <button class="btn-stop" onclick="stopWorker('${w.name}')">STOP</button>
                    </div>
                    <button class="btn-apply" onclick="applyWorker('${w.name}')">APPLY CHANGES</button>
                </div>
            `;
        }).join('');

        // Render Corrector Functions
        const corrList = document.getElementById('corrector-functions-list');
        const functions = [
            { id: 'json_fixer', label: 'JSON Fixer' },
            { id: 'loop_detector', label: 'Loop Detector' },
            { id: 'translator', label: 'Translator' },
            { id: 'think_harder', label: 'Think Harder' },
            { id: 'auto_remember', label: 'Auto-Remember' }
        ];
        
        // We assume the server provides the current corrector state in a global config object
        // For demo, we use a local mock if not provided
        const currentFuncs = workers[0]?.corrector_functions || {}; 

        corrList.innerHTML = functions.map(f => `
            <div class="function-row">
                <span>${f.label}</span>
                <label class="switch">
                    <input type="checkbox" ${currentFuncs[f.id] ? 'checked' : ''} onchange="setCorrectorFunc('${f.id}', this.checked)">
                    <span class="slider"></span>
                </label>
            </div>
        `).join('');
    }

    function getPoolColorIndex(name) {
        const colors = ['1', '2', '3'];
        const idx = pools.findIndex(p => p.name === name);
        return colors[idx % 3] || '1';
    }

    // Placeholder for missing functions
    async function updateEngine(name, val) {
        const w = workers.find(x => x.name === name);
        w.engine = val;
    }
    async function startWorker(name) { await apiPost(`/cluster/worker/${name}/start`, {}); }
    async function stopWorker(name) { await apiPost(`/cluster/worker/${name}/stop`, {}); }

    window.onload = init;
</script>
</body>
</html>
```

```rust
// === FILE: src/main.rs (new routes to add) ===

// Note: These handlers assume you have a shared State containing your cluster config and engine probe logic.

async fn get_available_engines(State(state): State<AppState>) -> Json<serde_json::Value> {
    // 1. Check binaries
    let mut available = Vec::new();
    if std::path::Path::new("bin/koboldcpp").exists() { available.push("koboldcpp".to_string()); }
    if std::path::Path::new("bin/cesarops-inference").exists() { available.push("cesarops-inference".to_string()); }
    
    // 2. Check port 11434 (Ollama)
    if TcpStream::connect("127.0.0.1:11434").await.is_ok() {
        available.push("ollama".to_string());
    }

    // 3. Check llama.cpp
    if std::path::Path::new("bin/llama-server").exists() { available.push("llama.cpp".to_string()); }

    // 4. Per-node logic (simplified)
    let mut per_node = serde_json::Map::new();
    // In real implementation, iterate through your known nodes and probe them
    per_node.insert("100.102.158.111".to_string(), serde_json::to_value(vec!["koboldcpp"]).unwrap());

    Json(serde_json::json!({
        "available": available,
        "per_node": per_node
    }))
}

async fn apply_worker_config(
    Path(name): Path<String>,
    State(state): State<AppState>,
    Json(payload): Json<serde_json::Value>
) -> StatusCode {
    let mut config = state.config.lock().await;
    if let Some(worker) = config.workers.iter_mut().find(|w| w.name == name) {
        // Update worker fields from payload
        if let Some(engine) = payload.get("engine").and_then(|v| v.as_str()) { worker.engine = engine.to_string(); }
        if let Some(backend) = payload.get("backend").and_then(|v| v.as_str()) { worker.backend = backend.to_string(); }
        if let Some(inject) = payload.get("inject_vectors").and_then(|v| v.as_bool()) { worker.inject_vectors = inject; }
        // ... apply other fields
        
        // Trigger actual process restart/reload logic here
        return StatusCode::OK;
    }
    StatusCode::NOT_FOUND
}

async fn set_injection(
    Path(name): Path<String>,
    State(state): State<AppState>,
    Json(payload): Json<serde_json::Value>
) -> StatusCode {
    let mut config = state.config.lock().await;
    if let Some(worker) = config.workers.iter_mut().find(|w| w.name == name) {
        worker.inject_vectors = payload["enabled"].as_bool().unwrap_or(false);
        return StatusCode::OK;
    }
    StatusCode::NOT_FOUND
}

async fn set_backend(
    Path(name): Path<String>,
    State(state): State<AppState>,
    Json(payload): Json<serde_json::Value>
) -> StatusCode {
    let mut config = state.config.lock().await;
    if let Some(worker) = config.workers.iter_mut().find(|w| w.name == name) {
        worker.backend = payload["backend"].as_str().unwrap_or("vulkan").to_string();
        return StatusCode::OK;
    }
    StatusCode::NOT_FOUND
}

async fn set_corrector_function(
    State(state): State<AppState>,
    Json(payload): Json<serde_json::Value>
) -> StatusCode {
    let func = payload["function"].as_str().unwrap_or("");
    let enabled = payload["enabled"].as_bool().unwrap_or(false);
    
    let mut config = state.config.lock().await;
    // Assuming we apply to a global corrector config or the first worker
    if let Some(worker) = config.workers.iter_mut().find(|w| w.role == "corrector") {
        worker.corrector_functions.insert(func.to_string(), enabled);
        return StatusCode::OK;
    }
    StatusCode::NOT_FOUND
}

async fn create_memory_pool(
    State(state): State<AppState>,
    Json(payload): Json<serde_json::Value>
) -> StatusCode {
    let name = payload["name"].as_str().unwrap_or("new_pool").to_string();
    let members = payload["members"].as_array().unwrap().iter()
        .map(|v| v.as_str().unwrap().to_string()).collect::<Vec<String>>();

    let mut config = state.config.lock().await;
    config.pools.push(MemoryPool { name, members });
    StatusCode::CREATED
}

// Registration in main():
// .route("/cluster/engines", get(get_available_engines))
// .route("/cluster/worker/:name/apply", post(apply_worker_config))
// .route("/cluster/worker/:name/set_injection", post(set_injection))
// .route("/cluster/worker/:name/set_backend", post(set_backend))
// .route("/cluster/corrector/set_function", post(set_corrector_function))
// .route("/cluster/memory_pool/create", post(create_memory_pool))
```

```toml
# === FILE: cluster_config.toml (updated schema) ===

[[worker]]
name = "Coder"
role = "code"
gpu = 0
model = "deepseek-coder-33b"
port = 5001
engine = "koboldcpp"
backend = "vulkan"
inject_vectors = true
memory_pool = "pool1"
# Note: corrector_functions is used by the corrector role
corrector_functions = { json_fixer = true, loop_detector = true, translator = false, think_harder = true, auto_remember = true }

[[worker]]
name = "Thinker"
role = "think"
gpu = 1
model = "llama-3-70b"
port = 5002
engine = "ollama"
backend = "cuda"
inject_vectors = true
memory_pool = "pool1"
corrector_functions = {}

[[worker]]
name = "Corrector"
role = "corrector"
gpu = 0
model = "mistral-7b-instruct"
port = 5003
engine = "cesarops-inference"
backend = "vulkan"
inject_vectors = false
memory_pool = ""
corrector_functions = { json_fixer = true, loop_detector = true, translator = true, think_harder = false, auto_remember = true }

[[memory_pool]]
name = "pool1"
members = ["Coder", "Thinker"]
```
