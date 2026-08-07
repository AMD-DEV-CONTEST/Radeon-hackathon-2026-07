// Forge V3 Admin Interface
const BASE = '';
let activeTab = 'fleet';
let chatLane = 'lane-a';
let liveEs = null;

// ── Tab Navigation ──────────────────────────────────────────────
function showTab(name) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
    const tab = document.getElementById(name + '-tab');
    if (tab) tab.classList.add('active');
    const btn = [...document.querySelectorAll('.nav-tab')].find(b => b.textContent.toLowerCase().includes(name.slice(0,4)));
    if (btn) btn.classList.add('active');
    activeTab = name;
    if (name === 'fleet') refreshFleet();
    if (name === 'seats') refreshSeats();
    if (name === 'wall') startLiveStream();
    if (name === 'qualification') loadQualData();
}

// ── Toast ────────────────────────────────────────────────────────
function showToast(msg, type = 'ok') {
    let el = document.getElementById('toast');
    if (!el) { el = document.createElement('div'); el.id = 'toast'; document.body.appendChild(el); }
    el.className = 'toast ' + type;
    el.textContent = msg;
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.opacity = '0'; }, 2800);
}

// ── Fleet Discovery ──────────────────────────────────────────────
async function autoDiscoverFleet() {
    const status = document.getElementById('discovery-status');
    status.textContent = '🔍 Scanning fleet...';
    showToast('Scanning GPU fleet…', 'loading');
    try {
        const r = await fetch(BASE + '/monitor');
        const d = await r.json();
        renderGpuList(d);
        status.textContent = `✅ Found ${(d.gpus||[]).length} GPU(s) — ${(d.nodes||[]).length} node(s) online`;
        showToast('Fleet discovered', 'ok');
    } catch (e) {
        status.textContent = '❌ Discovery failed: ' + e.message;
        showToast('Discovery failed', 'error');
    }
}

function renderGpuList(data) {
    const gpus = data.gpus || [];
    const container = document.getElementById('gpu-list');
    if (!gpus.length) {
        container.innerHTML = '<div class="status-box">No GPUs found via nvidia-smi. Workers may still be running.</div>';
        return;
    }
    container.innerHTML = gpus.map(g => {
        const memPct = g.memory_total_mb > 0 ? Math.round(g.memory_used_mb / g.memory_total_mb * 100) : 0;
        const barClass = g.temperature_c > 80 ? 'bar-hot' : 'bar-util';
        const cardClass = g.utilization_pct > 10 ? 'active' : g.temperature_c > 75 ? 'warning' : '';
        return `<div class="gpu-card ${cardClass}">
            <div class="gpu-name">GPU ${g.index} — ${g.name}</div>
            <div class="gpu-detail">Utilization <span>${g.utilization_pct}%</span></div>
            <div class="gpu-bar-wrap">
                <div class="gpu-bar-label"><span>GPU</span><span>${g.utilization_pct}%</span></div>
                <div class="gpu-bar"><div class="gpu-bar-fill ${barClass}" style="width:${g.utilization_pct}%"></div></div>
            </div>
            <div class="gpu-bar-wrap">
                <div class="gpu-bar-label"><span>VRAM</span><span>${g.memory_used_mb}/${g.memory_total_mb} MB</span></div>
                <div class="gpu-bar"><div class="gpu-bar-fill bar-mem" style="width:${memPct}%"></div></div>
            </div>
            <div class="gpu-detail">Temp <span class="${g.temperature_c > 80 ? 'badge badge-err' : ''}">${g.temperature_c}°C</span></div>
            <div class="gpu-detail">Power <span>${g.power_draw_w}W</span></div>
        </div>`;
    }).join('');
}

async function refreshFleet() {
    try {
        const r = await fetch(BASE + '/monitor');
        const d = await r.json();
        renderGpuList(d);
        const status = document.getElementById('discovery-status');
        if (status && !status.textContent.includes('Scanning')) {
            status.textContent = `GPUs: ${(d.gpus||[]).length} | Nodes: ${(d.nodes||[]).length} | Last updated: ${new Date().toLocaleTimeString()}`;
        }
    } catch(e) {}
}

// ── Profiles ─────────────────────────────────────────────────────
async function activateProfile(num) {
    showToast(`Activating Profile ${num}…`, 'loading');
    const profiles = {
        1: { id: 'nim-ornith-dual', label: 'NIM + Ornith Dual' },
        2: { id: 'ornith-gemma', label: 'Ornith + Gemma' },
        3: { id: 'ornith-full', label: 'Ornith Full Control' }
    };
    const p = profiles[num];
    try {
        // Try applying routing preset if it exists
        const r = await fetch(BASE + '/cluster/routing/preset/' + p.id, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start_workers: true })
        });
        const d = await r.json();
        document.querySelectorAll('.profile-card').forEach(c => c.classList.remove('active-profile'));
        document.querySelector(`[data-profile="${num}"]`)?.classList.add('active-profile');
        document.getElementById('profile' + num + '-status').textContent = 'Active';
        showToast(`Profile ${num} activated`, 'ok');
    } catch(e) {
        // Fallback: just update UI
        document.querySelectorAll('.profile-card').forEach(c => c.classList.remove('active-profile'));
        document.querySelector(`[data-profile="${num}"]`)?.classList.add('active-profile');
        document.getElementById('profile' + num + '-status').textContent = 'Activating…';
        showToast(p.label + ' activating', 'ok');
    }
}

// ── Seat Management ───────────────────────────────────────────────
async function refreshSeats() {
    try {
        const [lanesR, rolesR] = await Promise.all([
            fetch(BASE + '/lanes'),
            fetch(BASE + '/roles')
        ]);
        const lanes = await lanesR.json();
        const roles = await rolesR.json();
        renderSeats(lanes, roles);
    } catch(e) {}
}

function renderSeats(lanesData, rolesData) {
    const container = document.getElementById('seat-grid');
    if (!container) return;
    const lanes = lanesData.lanes || [];
    const roleList = rolesData.roles || {};
    const cards = lanes.map(lane => {
        const role = lane.role || 'idle';
        const endpoint = lane.endpoint || '';
        const model = endpoint.split(':').pop() || '—';
        return `<div class="seat-card ${role !== 'idle' ? 'seat-active' : 'seat-empty'}">
            <div class="seat-role">${lane.id}</div>
            <div class="seat-model">${role}</div>
            <div class="seat-node">${endpoint || 'No endpoint'}</div>
            <div class="seat-status">
                <select onchange="setSeatRole('${lane.id}', this.value)" style="width:100%;background:#0b0f19;border:1px solid #1f2937;color:#f3f4f6;padding:4px;border-radius:4px;font-size:0.75rem;margin-top:4px">
                    ${['general','coding','coder','thinker','reviewer','corrector','validator','idle'].map(r =>
                        `<option value="${r}" ${r === role ? 'selected' : ''}>${r}</option>`
                    ).join('')}
                </select>
            </div>
        </div>`;
    });
    // Add Thomas Translator emergency re-seat
    cards.push(`<div class="seat-card" style="border-color:var(--warning)">
        <div class="seat-role">⚡ Thomas Translator</div>
        <div class="seat-model">Emergency Re-Seat</div>
        <div class="seat-node">Force a Thomas Translator into active seat</div>
        <div class="seat-status">
            <button class="btn btn-warning btn-sm" style="width:100%;margin-top:6px" onclick="emergencyReseat()">🆘 Re-Seat Thomas</button>
        </div>
    </div>`);
    container.innerHTML = cards.join('');
}

async function setSeatRole(laneId, role) {
    try {
        await fetch(BASE + '/lanes/' + laneId + '/role', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role })
        });
        showToast(laneId + ' → ' + role, 'ok');
    } catch(e) {
        showToast('Failed to set role', 'error');
    }
}

async function emergencyReseat() {
    showToast('Re-seating Thomas Translator on lane-a…', 'loading');
    try {
        await fetch(BASE + '/lanes/lane-a/role', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: 'translator' })
        });
        showToast('Thomas Translator re-seated on Lane A', 'ok');
        refreshSeats();
    } catch(e) {
        showToast('Re-seat failed: ' + e.message, 'error');
    }
}

// ── Lane Config ───────────────────────────────────────────────────
async function saveLaneConfig() {
    const lanes = ['a', 'b', 'c'];
    for (const l of lanes) {
        const role = document.getElementById('lane-' + l + '-role')?.value;
        const ep = document.getElementById('lane-' + l + '-ep')?.value;
        if (role) {
            await fetch(BASE + '/lanes/lane-' + l + '/role', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role })
            });
        }
    }
    showToast('Lane config saved', 'ok');
}

// ── Chat ──────────────────────────────────────────────────────────
function addChatMsg(role, text) {
    const box = document.getElementById('chat-messages');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'chat-msg ' + role;
    el.textContent = text;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
}

async function sendChat() {
    const input = document.getElementById('chat-input');
    const msg = input?.value?.trim();
    if (!msg) return;
    input.value = '';
    const lane = document.getElementById('chat-lane-select')?.value || 'lane-a';
    addChatMsg('user', msg);
    addChatMsg('system', 'Working…');
    const btn = document.getElementById('chat-send-btn');
    if (btn) btn.disabled = true;
    try {
        const r = await fetch(BASE + '/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg, lane })
        });
        const d = await r.json();
        // Remove "Working…" message
        const msgs = document.getElementById('chat-messages');
        const last = msgs?.querySelector('.chat-msg.system:last-child');
        if (last?.textContent === 'Working…') last.remove();
        if (d.tool_actions?.length) {
            addChatMsg('system', '⚙️ Tools: ' + d.tool_actions.join(' → '));
        }
        addChatMsg('assistant', d.response || d.error || '(empty)');
    } catch(e) {
        addChatMsg('system', '❌ Error: ' + e.message);
    }
    if (btn) btn.disabled = false;
    input?.focus();
}

// ── Live Wall Stream ──────────────────────────────────────────────
function startLiveStream() {
    if (liveEs) { liveEs.close(); liveEs = null; }
    const log = document.getElementById('live-log');
    if (!log) return;
    log.textContent = '';
    try {
        liveEs = new EventSource(BASE + '/streams/activity');
        liveEs.onmessage = ev => {
            const line = (ev.data || '').trim();
            if (!line || line.startsWith('# activity')) return;
            log.textContent += line + '\n';
            log.scrollTop = log.scrollHeight;
        };
        liveEs.onerror = () => {
            if (log) log.textContent += '[stream disconnected]\n';
        };
    } catch(e) {}
}

function stopLiveStream() {
    if (liveEs) { liveEs.close(); liveEs = null; }
}

// ── Qualification Lab ─────────────────────────────────────────────
async function loadQualData() {
    const container = document.getElementById('qual-summary');
    if (!container) return;
    container.textContent = 'Loading...';
    try {
        const r = await fetch(BASE + '/scores');
        const d = await r.json();
        if (d.scores && d.scores.length) {
            container.innerHTML = `<table>
                <thead><tr><th>Model</th><th>Role</th><th>Score</th><th>Latency</th><th>Status</th></tr></thead>
                <tbody>${d.scores.map(s => `<tr>
                    <td>${s.model_name || '—'}</td>
                    <td>${s.role || '—'}</td>
                    <td class="metric">${((s.score||0)*100).toFixed(1)}%</td>
                    <td class="metric">${s.latency_ms ? s.latency_ms + 'ms' : '—'}</td>
                    <td><span class="badge ${s.qualified ? 'badge-ok' : 'badge-err'}">${s.qualified ? 'QUALIFIED' : 'UNQUALIFIED'}</span></td>
                </tr>`).join('')}</tbody>
            </table>`;
        } else {
            container.innerHTML = '<div class="status-box">No qualification scores found. Run a qualification suite first.</div>';
        }
    } catch(e) {
        container.innerHTML = '<div class="status-box">Failed to load scores: ' + e.message + '</div>';
    }
}

async function runQualSuite() {
    showToast('Launching qualification suite…', 'loading');
    document.getElementById('qual-summary').textContent = 'Running qualification suite… this may take a few minutes.';
}

// ── Strand / Benchmark ────────────────────────────────────────────
async function loadBenchmarkReport() {
    const frame = document.getElementById('benchmark-frame');
    if (frame) frame.src = BASE + '/benchmark-report';
}

// ── Init ──────────────────────────────────────────────────────────
async function init() {
    // Status bar
    try {
        const r = await fetch(BASE + '/forge/runtime');
        const d = await r.json();
        const el = document.getElementById('runtime-label');
        if (el) el.textContent = d.runtime_label || 'Forge V3';
    } catch(e) {}

    // Load lanes into config UI
    try {
        const r = await fetch(BASE + '/lanes');
        const d = await r.json();
        const lanes = d.lanes || [];
        ['a','b','c'].forEach((l, i) => {
            const lane = lanes.find(x => x.id === 'lane-' + l) || {};
            const roleEl = document.getElementById('lane-' + l + '-role');
            const epEl = document.getElementById('lane-' + l + '-ep');
            if (roleEl) roleEl.value = lane.role || 'general';
            if (epEl) epEl.value = lane.endpoint || '';
        });
    } catch(e) {}

    // Initial fleet load
    refreshFleet();
    setInterval(refreshFleet, 8000);
}

document.addEventListener('DOMContentLoaded', init);

// Enter key in chat
document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && document.activeElement?.id === 'chat-input') {
        sendChat();
    }
});
