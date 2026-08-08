// Screen-AI Mobile Remote App — Refactored
// Uses ScreenAI.api (HTTP/WebSocket client) and ScreenAI.ui (toasts/modals/theme)
// instead of direct fetch() and alert()/confirm()/prompt() calls.

'use strict';

const { api, ws, session, events, device } = window.ScreenAI;
const { ui } = window.ScreenAI;
const { $, $$, clearNode, el, appendText, toast, confirm, prompt, alert } = ui;

// ─── Local State ────────────────────────────────────────────────────────────
const state = {
    cameraStream: null,
    qrScanInterval: null,
    history: [],
    approvalPollTimer: null,
};

// ─── Constants ──────────────────────────────────────────────────────────────
const COMMAND_MEMORY_KEY = 'screenai_command_memory_v1';
const COMMAND_DRAFT_KEY = 'screenai_command_draft_v1';
const RUNTIME_SNAPSHOT_KEY = 'screenai_runtime_snapshot_v1';
const LAST_TOKEN_ROTATION_KEY = 'last_token_rotation';

// ─── PWA + Service Worker + Web Worker + IndexedDB ───────────────────────────
let swRegistration = null;
let appWorker = null;
let previewTimer = null;
const _workerHandlers = new Map();
let _workerIdCounter = 0;

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/remote/sw.js', { scope: '/remote/' })
        .then((reg) => {
            swRegistration = reg;
            console.log('[ScreenAI] Service Worker registered, scope:', reg.scope);
        })
        .catch((err) => console.warn('[ScreenAI] SW registration failed:', err));

    navigator.serviceWorker.addEventListener('message', (event) => {
        if (event.data?.type === 'COMMAND_DRAFT_SAVED') {
            console.log('[ScreenAI] Offline command draft saved:', event.data.id);
        }
    });
}

if (typeof Worker !== 'undefined') {
    try {
        appWorker = new Worker('/remote/worker.js');
        appWorker.onmessage = (e) => {
            const { type, id, result, error } = e.data;
            if (error) console.warn(`[Worker] ${type} failed:`, error);
            const handler = _workerHandlers.get(id);
            if (handler) {
                _workerHandlers.delete(id);
                handler(result, error);
            }
        };
        console.log('[ScreenAI] Web Worker initialized');
    } catch (err) {
        console.warn('[ScreenAI] Worker init failed:', err);
    }
}

function postToWorker(type, payload, timeout = 5000) {
    return new Promise((resolve) => {
        if (!appWorker) { resolve(null); return; }
        const id = ++_workerIdCounter;
        const timer = setTimeout(() => {
            _workerHandlers.delete(id);
            resolve(null);
        }, timeout);
        _workerHandlers.set(id, (result, error) => {
            clearTimeout(timer);
            error ? resolve(null) : resolve(result);
        });
        appWorker.postMessage({ type, id, payload });
    });
}

// IndexedDB caching for offline command drafts and history
const IDB_NAME = 'screenai-cache';
const IDB_VERSION = 1;

function openIDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(IDB_NAME, IDB_VERSION);
        req.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv');
            if (!db.objectStoreNames.contains('offline_command_drafts')) {
                db.createObjectStore('offline_command_drafts', { keyPath: 'id', autoIncrement: true });
            }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

async function cacheForOffline(key, value) {
    try {
        const db = await openIDB();
        const tx = db.transaction('kv', 'readwrite');
        tx.objectStore('kv').put(value, key);
    } catch (err) {
        console.warn('[ScreenAI] IDB cache failed:', err);
    }
}

async function readFromCache(key) {
    try {
        const db = await openIDB();
        const tx = db.transaction('kv', 'readonly');
        const req = tx.objectStore('kv').get(key);
        return new Promise((resolve) => {
            req.onsuccess = () => resolve(req.result || null);
            req.onerror = () => resolve(null);
        });
    } catch {
        return null;
    }
}

async function saveOfflineCommandDraft(text) {
    try {
        const db = await openIDB();
        const tx = db.transaction('offline_command_drafts', 'readwrite');
        tx.objectStore('offline_command_drafts').add({
            text,
            device_id: session.deviceId,
            queued_at: Date.now(),
        });
    } catch (err) {
        console.warn('[ScreenAI] Failed to save offline command draft:', err);
    }
}

// ─── WebSocket State Sync ───────────────────────────────────────────────────
events.on('ws:state', ({ state: wsState }) => {
    const map = {
        online: ['online', 'Connected'],
        connecting: ['connecting', 'Connecting'],
        offline: ['offline', 'Offline'],
        error: ['offline', 'Socket error'],
    };
    const [badgeState, label] = map[wsState] || ['offline', 'Offline'];
    setConnectionState(badgeState, label);
});

ws.onMessage((data) => {
    if (!data || !data.type) return;
    if (data.type === 'command_result') {
        renderProgress([
            { label: 'Realtime command event received', status: 'success' },
            { label: 'History and approvals refreshed', status: 'success' },
        ]);
        loadHistory();
        loadApprovals();
    } else if (data.type === 'progress') {
        renderProgress(data.steps || [{ label: data.message || 'Agent progress update', status: data.status || 'running' }]);
    }
});

// ─── Initialization ─────────────────────────────────────────────────────────
init();

async function init() {
    if (session.hasSession()) {
        showMainScreen();
        ws.connect();
        loadHistory();
        loadApprovals();
        checkTrustStatus();
        scheduleTokenRotation();
    } else {
        showLoginScreen();
        setConnectionState('offline', 'Offline');
    }

    setupEventListeners();
    setupThemeToggle();
}

function setupEventListeners() {
    $$('.method-tab').forEach(tab => {
        tab.addEventListener('click', () => switchLoginMethod(tab.dataset.method));
    });

    $('#start-camera')?.addEventListener('click', startQRScanner);
    $('#stop-camera')?.addEventListener('click', stopQRScanner);
    $('#pair-button')?.addEventListener('click', pairWithCode);
    $('#check-trusted')?.addEventListener('click', checkTrustedDevice);

    $('#send-command')?.addEventListener('click', sendCommand);
    $('#preview-command')?.addEventListener('click', previewCurrentCommand);
    $('#restore-draft')?.addEventListener('click', restoreCommandDraft);
    $('#emergency-stop')?.addEventListener('click', emergencyStop);
    $('#unpair-button')?.addEventListener('click', unpairDevice);
    $('#rotate-token-btn')?.addEventListener('click', rotateTokenNow);

    $$('.tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    const codeInput = $('#pairing-code');
    if (codeInput) {
        codeInput.addEventListener('input', (e) => {
            e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6);
        });
    }

    const commandText = $('#command-text');
    if (commandText) {
        commandText.value = localStorage.getItem(COMMAND_DRAFT_KEY) || '';
        commandText.addEventListener('input', () => {
            const value = commandText.value;
            localStorage.setItem(COMMAND_DRAFT_KEY, value);
            renderCommandMemory(value);
            renderLocalRouteHint(value);
            clearTimeout(previewTimer);
            if (value.trim().length >= 8) {
                previewTimer = setTimeout(previewCurrentCommand, 650);
            } else {
                renderPlanPreview(null);
            }
        });
        renderCommandMemory(commandText.value);
        renderLocalRouteHint(commandText.value);
    }
}

function setupThemeToggle() {
    const btn = $('#theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
        const next = ui.theme.cycle();
        toast(`Theme: ${next}`, 'info', 1500);
    });
}

// ─── Login Methods ──────────────────────────────────────────────────────────
function switchLoginMethod(method) {
    $$('.method-tab').forEach(t => t.classList.remove('active'));
    $$('.method-content').forEach(t => t.classList.remove('active'));

    $(`[data-method="${method}"]`)?.classList.add('active');
    $(`#${method}-method`)?.classList.add('active');

    if (method !== 'qr') stopQRScanner();
}

// ─── QR Code Pairing ────────────────────────────────────────────────────────
async function startQRScanner() {
    try {
        if (typeof jsQR === 'undefined') {
            setStatus('qr-status', 'QR scanner library did not load. Use Enter Code fallback.', 'error');
            return;
        }
        if (!navigator.mediaDevices?.getUserMedia) {
            setStatus('qr-status', 'Camera API unavailable. Use Enter Code fallback.', 'error');
            return;
        }

        const video = document.createElement('video');
        video.setAttribute('playsinline', '');
        video.setAttribute('autoplay', '');

        const stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment' }
        });

        state.cameraStream = stream;
        video.srcObject = stream;

        const qrFrame = $('.qr-frame');
        clearNode(qrFrame);
        qrFrame.appendChild(video);

        const canvas = document.createElement('canvas');
        canvas.style.display = 'none';
        qrFrame.appendChild(canvas);

        $('#start-camera').classList.add('hidden');
        $('#stop-camera').classList.remove('hidden');

        state.qrScanInterval = setInterval(() => scanQRCode(video, canvas), 500);

        setStatus('qr-status', 'Camera started. Point at QR code.', 'info');
    } catch (error) {
        setStatus('qr-status', `Camera error: ${error.message}`, 'error');
    }
}

function stopQRScanner() {
    if (state.cameraStream) {
        state.cameraStream.getTracks().forEach(track => track.stop());
        state.cameraStream = null;
    }
    if (state.qrScanInterval) {
        clearInterval(state.qrScanInterval);
        state.qrScanInterval = null;
    }

    const qrFrame = $('.qr-frame');
    if (qrFrame) {
        qrFrame.innerHTML = `
            <div class="qr-corner tl"></div>
            <div class="qr-corner tr"></div>
            <div class="qr-corner bl"></div>
            <div class="qr-corner br"></div>
            <p class="qr-hint">Point camera at QR code on PC</p>
        `;
    }

    $('#start-camera')?.classList.remove('hidden');
    $('#stop-camera')?.classList.add('hidden');
}

function scanQRCode(video, canvas) {
    if (video.readyState !== video.HAVE_ENOUGH_DATA) return;
    if (typeof jsQR === 'undefined') return;

    const ctx = canvas.getContext('2d');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = jsQR(imageData.data, imageData.width, imageData.height);

    if (code) {
        stopQRScanner();
        handleQRData(code.data);
    }
}

async function handleQRData(qrData) {
    try {
        const payload = JSON.parse(qrData);

        if (payload.v !== 1 || !payload.pid || !payload.pk) {
            setStatus('qr-status', 'Invalid QR code', 'error');
            return;
        }

        if (payload.exp && payload.exp < Date.now() / 1000) {
            setStatus('qr-status', 'QR code expired', 'error');
            return;
        }

        setStatus('qr-status', 'QR code scanned! Pairing...', 'info');

        await api.pairing.completeQRSession(payload.pid, device.getName(), true);

        setStatus('qr-status', 'Paired successfully. Opening command console...', 'pair-success');
        toast('Paired successfully', 'success');
        openRemoteConsoleAfterPair();

    } catch (error) {
        setStatus('qr-status', `Error: ${error.message}`, 'error');
        toast(`Pairing failed: ${error.message}`, 'error');
    }
}

// ─── Code Entry Pairing ─────────────────────────────────────────────────────
async function pairWithCode() {
    const code = $('#pairing-code').value.trim();
    const name = $('#device-name').value.trim() || device.getName();
    const trust = $('#trust-device')?.checked || false;

    if (code.length !== 6) {
        $('#pair-error').textContent = 'Please enter a 6-digit code';
        return;
    }

    try {
        await api.pairing.pairWithCode(code, name, trust);
        $('#pair-error').textContent = '';
        setStatus('pair-error', 'Paired successfully. Opening command console...', 'pair-success');
        toast('Paired successfully', 'success');
        openRemoteConsoleAfterPair(500);
    } catch (error) {
        $('#pair-error').textContent = error.message || 'Pairing failed';
        toast(error.message || 'Pairing failed', 'error');
    }
}

// ─── Trusted Device Re-Pairing ──────────────────────────────────────────────
async function checkTrustedDevice() {
    setStatus('trusted-status', 'Checking trust status...', 'info');

    try {
        await api.pairing.reconnectTrusted();
        setStatus('trusted-status', 'Re-paired successfully. Opening command console...', 'pair-success');
        toast('Re-paired successfully', 'success');
        openRemoteConsoleAfterPair();
    } catch (error) {
        setStatus('trusted-status', error.message, 'error');
        toast(error.message, 'error');
    }
}

// ─── Status Helpers ─────────────────────────────────────────────────────────
function setStatus(elementId, message, type) {
    const el = $(`#${elementId}`);
    if (el) {
        el.textContent = message;
        el.className = `status ${type}`;
    }
}

function setConnectionState(status, label) {
    const badge = $('#connection-badge');
    const text = $('#connection-label');
    if (!badge || !text) return;
    badge.dataset.state = status;
    text.textContent = label;
}

function emptyMessage(text) {
    return el('p', { class: 'empty-message', text });
}

function appendChatMessage(direction, text, label = '') {
    const thread = $('#chat-thread');
    if (!thread || !text) return null;
    const row = el('div', { class: `message-row ${direction === 'outgoing' ? 'outgoing' : 'incoming'}` });
    const bubble = el('div', { class: 'message-bubble' });
    appendText(bubble, 'div', text, 'message-text');
    appendText(bubble, 'div', label || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), 'message-time');
    row.appendChild(bubble);
    thread.appendChild(row);
    scrollChatToBottom();
    return row;
}

function scrollChatToBottom() {
    const thread = $('#chat-thread');
    if (!thread) return;
    requestAnimationFrame(() => {
        thread.scrollTop = thread.scrollHeight;
    });
}

function parseJsonSafe(value) {
    if (!value) return null;
    try { return JSON.parse(value); } catch { return value; }
}

// ─── Command Memory ─────────────────────────────────────────────────────────
function loadCommandMemory() {
    try {
        return JSON.parse(localStorage.getItem(COMMAND_MEMORY_KEY) || '[]');
    } catch {
        return [];
    }
}

function saveCommandToMemory(text) {
    const normalized = " ".concat(text || "").trim();
    if (!normalized) return;
    const memory = loadCommandMemory().filter(item => item.text !== normalized);
    memory.unshift({ text: normalized, used_at: Date.now() });
    localStorage.setItem(COMMAND_MEMORY_KEY, JSON.stringify(memory.slice(0, 12)));
    renderCommandMemory('');
}

function renderCommandMemory(filterText = '') {
    const box = $('#command-memory');
    if (!box) return;
    const lower = (filterText || '').toLowerCase().trim();
    const memory = loadCommandMemory()
        .filter(item => !lower || item.text.toLowerCase().includes(lower) || fuzzyMemoryScore(lower, item.text) > 0.32)
        .slice(0, 6);
    clearNode(box);
    if (memory.length === 0) {
        box.classList.add('hidden');
        return;
    }
    appendText(box, 'div', 'Recent instruction memory', 'memory-title');
    const list = el('div', { class: 'memory-list' });
    memory.forEach(item => {
        const btn = el('button', {
            class: 'memory-item',
            type: 'button',
            text: item.text,
            onclick: () => {
                const input = $('#command-text');
                input.value = item.text;
                localStorage.setItem(COMMAND_DRAFT_KEY, item.text);
                previewCurrentCommand();
            },
        });
        list.appendChild(btn);
    });
    box.appendChild(list);
    box.classList.remove('hidden');
}

function fuzzyMemoryScore(query, target) {
    if (!query || !target) return 0;
    const q = query.toLowerCase();
    const t = target.toLowerCase();
    if (t.includes(q)) return 1;
    let qi = 0;
    for (let i = 0; i < t.length && qi < q.length; i++) {
        if (t[i] === q[qi]) qi++;
    }
    return qi / Math.max(1, q.length);
}

function restoreCommandDraft() {
    const draft = localStorage.getItem(COMMAND_DRAFT_KEY) || '';
    const input = $('#command-text');
    input.value = draft;
    renderCommandMemory(draft);
    if (draft.trim()) previewCurrentCommand();
}

// ─── Token Rotation ─────────────────────────────────────────────────────────
async function rotateTokenNow() {
    if (!session.deviceId || !session.token) return;

    try {
        await api.pairing.rotateToken();
        toast('Token rotated successfully', 'success');
        checkTrustStatus();
    } catch (error) {
        toast(`Token rotation failed: ${error.message}`, 'error');
    }
}

function scheduleTokenRotation() {
    const lastRotation = localStorage.getItem(LAST_TOKEN_ROTATION_KEY);
    const now = Date.now();

    if (!lastRotation || now - parseInt(lastRotation) > 24 * 60 * 60 * 1000) {
        setTimeout(() => {
            rotateTokenNow();
            localStorage.setItem(LAST_TOKEN_ROTATION_KEY, now.toString());
        }, 5000);
    }
}

async function checkTrustStatus() {
    const trustUntil = localStorage.getItem('trust_until');
    const display = $('#trust-status-display');

    if (trustUntil) {
        const expiry = new Date(trustUntil);
        const now = new Date();
        if (expiry > now) {
            const days = Math.ceil((expiry - now) / (1000 * 60 * 60 * 24));
            display.textContent = `Trusted (${days} days left)`;
            display.style.color = '#00aa44';
        } else {
            display.textContent = 'Expired';
            display.style.color = '#ff4444';
        }
    } else {
        display.textContent = 'Not trusted';
        display.style.color = '#888';
    }

    const lastRotation = localStorage.getItem(LAST_TOKEN_ROTATION_KEY);
    if (lastRotation) {
        const expiry = new Date(parseInt(lastRotation) + 24 * 60 * 60 * 1000);
        $('#token-expiry-display').textContent = expiry.toLocaleString();
    }
}

// ─── Screen Navigation ──────────────────────────────────────────────────────
function showLoginScreen() {
    const login = $('#login-screen');
    const main = $('#main-screen');
    login.classList.add('active', 'entering');
    main.classList.remove('active', 'entering', 'leaving');
    setConnectionState('offline', 'Offline');
    setTimeout(() => login.classList.remove('entering'), 320);
}

function showMainScreen() {
    const login = $('#login-screen');
    const main = $('#main-screen');
    login.classList.remove('active', 'entering');
    main.classList.add('active', 'entering');
    setTimeout(() => main.classList.remove('entering'), 320);

    $('#device-name-display').textContent = device.getName();
    $('#device-id-display').textContent =
        session.deviceId ? session.deviceId.substring(0, 8) + '...' : '-';
    checkTrustStatus();
}

function openRemoteConsoleAfterPair(delayMs = 900) {
    setTimeout(() => {
        showMainScreen();
        setConnectionState('connecting', 'Connecting');
        ws.connect();
        loadHistory();
        loadApprovals();
        scheduleTokenRotation();
    }, delayMs);
}

function switchTab(tabName) {
    $$('.tab').forEach(t => t.classList.remove('active'));
    $$('.tab-content').forEach(t => t.classList.remove('active'));

    $(`[data-tab="${tabName}"]`)?.classList.add('active');
    $(`#${tabName}-tab`)?.classList.add('active');

    if (tabName === 'history') loadHistory();
    if (tabName === 'approvals') loadApprovals();
    if (tabName === 'settings') checkTrustStatus();
}

// ─── Commands ───────────────────────────────────────────────────────────────
async function sendCommand() {
    const text = $('#command-text').value.trim();
    if (!text) return;

    const responseDiv = $('#command-response');
    const startTime = performance.now();
    responseDiv.textContent = 'Working...';
    appendChatMessage('outgoing', text);
    const workingMessage = appendChatMessage('incoming', 'Working on it...', 'Screen-AI');
    renderProgress([
        { label: 'Command received from phone', status: 'success' },
        { label: 'Planning, risk check, and model budget selection', status: 'running' },
        { label: 'Waiting for tool execution result', status: 'pending' },
    ]);

    try {
        if (!navigator.onLine) {
            await saveOfflineCommandDraft(text);
            renderProgress([
                { label: 'Command received from phone', status: 'success' },
                { label: 'Saved as draft for manual resend', status: 'pending' },
            ]);
            const offlineText = 'Offline. I saved this as a draft, but I will not auto-run it later. Reconnect and press Send again.';
            responseDiv.textContent = offlineText;
            if (workingMessage) workingMessage.querySelector('.message-text').textContent = offlineText;
            scrollChatToBottom();
            return;
        }

        startApprovalPolling();
        const data = await api.commands.send(text);
        stopApprovalPolling();
        const elapsed = Math.round(performance.now() - startTime);

        if (data.requires_approval) {
            renderProgress([
                { label: 'Command received from phone', status: 'success' },
                { label: 'Risk check requires mobile approval', status: 'running' },
                { label: `Approval request ${data.approval_id}`, status: 'pending' },
            ]);
            const approvalText = `Waiting for approval...\nApproval ID: ${data.approval_id}`;
            responseDiv.textContent = approvalText;
            if (workingMessage) workingMessage.querySelector('.message-text').textContent = approvalText;
            scrollChatToBottom();
            loadApprovals();
        } else {
            const doneStatus = data.status !== 'failed' ? 'success' : 'failed';

            const progressSteps = [
                { label: 'Command received from phone', status: 'success' },
                { label: summarizeRuntime(data), status: 'success' },
            ];

            const telemetry = data?.telemetry;
            if (telemetry) {
                progressSteps.push({
                    label: `⚡ ${telemetry.pipeline_ms || elapsed}ms · ${telemetry.tools_succeeded || 0}/${telemetry.tools_executed || 0} tools`,
                    status: 'success',
                });
            }

            progressSteps.push({ label: `Tool execution finished (${elapsed}ms)`, status: doneStatus });
            renderProgress(progressSteps);

            let responseText = data.result || JSON.stringify(data, null, 2);
            if (telemetry) {
                responseText += `\n\n── Telemetry ──`;
                responseText += `\nPipeline: ${telemetry.pipeline_ms}ms`;
                responseText += `\nTools: ${telemetry.tools_succeeded}/${telemetry.tools_executed} succeeded`;
                const strategy = telemetry.strategy;
                if (strategy?.circuit_breaker && Object.keys(strategy.circuit_breaker).length > 0) {
                    responseText += `\nCircuit: ${Object.keys(strategy.circuit_breaker).length} tool(s) had issues`;
                }
            }
            responseDiv.textContent = responseText;
            if (workingMessage) workingMessage.querySelector('.message-text').textContent = responseText;
            scrollChatToBottom();
        }

        $('#command-text').value = '';
        localStorage.removeItem(COMMAND_DRAFT_KEY);
        saveCommandToMemory(text);
        renderPlanPreview(null);

        cacheForOffline(`last_command_${Date.now()}`, {
            text, result: data.result, status: data.status, time: Date.now()
        });

    } catch (error) {
        stopApprovalPolling();
        const elapsed = Math.round(performance.now() - startTime);

        if (!navigator.onLine) {
            await saveOfflineCommandDraft(text);
            renderProgress([
                { label: 'Command received from phone', status: 'success' },
                { label: 'Saved as draft for manual resend', status: 'pending' },
            ]);
            const offlineText = 'Offline. Draft saved locally; reconnect and press Send again.';
            responseDiv.textContent = offlineText;
            if (workingMessage) workingMessage.querySelector('.message-text').textContent = offlineText;
            scrollChatToBottom();
        } else {
            renderProgress([
                { label: 'Command received from phone', status: 'success' },
                { label: `Network error after ${elapsed}ms`, status: 'failed' },
            ]);
            const errorText = 'Error: ' + error.message;
            responseDiv.textContent = errorText;
            if (workingMessage) workingMessage.querySelector('.message-text').textContent = errorText;
            scrollChatToBottom();
            toast(`Command failed: ${error.message}`, 'error');
        }
    }
}

function startApprovalPolling() {
    stopApprovalPolling();
    loadApprovals({ inlineOnly: true });
    state.approvalPollTimer = setInterval(() => {
        loadApprovals({ inlineOnly: true });
    }, 1600);
}

function stopApprovalPolling() {
    if (state.approvalPollTimer) {
        clearInterval(state.approvalPollTimer);
        state.approvalPollTimer = null;
    }
}

async function previewCurrentCommand() {
    const input = $('#command-text');
    const text = input?.value.trim();
    if (!text || !session.deviceId || !session.token) {
        renderPlanPreview(null);
        return;
    }
    renderLocalRouteHint(text);
    if (!navigator.onLine) {
        renderPlanPreview({ status: 'offline', message: 'Offline. Plan preview needs the local PC server.' });
        return;
    }
    try {
        const data = await api.commands.preview(text);
        cacheRuntimeSnapshot(data);
        renderPlanPreview(data);
    } catch (error) {
        renderPlanPreview({ status: 'failed', message: error.message });
    }
}

async function renderLocalRouteHint(text) {
    const clean = (text || '').trim();
    if (!clean || clean.length < 3) return;
    const hint = await postToWorker('MODEL_ROUTE_HINT', {
        text: clean,
        memory: loadCommandMemory(),
    }, 650);
    if (!hint) return;
    renderPlanPreview({
        status: 'local',
        intent: 'typing',
        risk_level: 0,
        requires_approval: false,
        step_count: 0,
        message: 'Local phone memory is preparing the model route...',
        model_plan: {
            budget_mode: 'phone-preview',
            model_budget_mb: 0,
            recommended: hint.recommended,
            lanes: hint.lanes,
            prefetch: [],
            teacher_fallback: {
                enabled_by_default: false,
                why: 'server decides teacher fallback after budget check',
            },
        },
        memory_matches: hint.memory_matches,
    });
}

function cacheRuntimeSnapshot(data) {
    if (!data) return;
    const snapshot = {
        cached_at: Date.now(),
        runtime: data.runtime || null,
        ssd_tier: data.ssd_tier || null,
        model_plan: data.model_plan || null,
    };
    localStorage.setItem(RUNTIME_SNAPSHOT_KEY, JSON.stringify(snapshot));
    cacheForOffline(RUNTIME_SNAPSHOT_KEY, snapshot);
}

function renderPlanPreview(data) {
    const box = $('#plan-preview');
    if (!box) return;
    clearNode(box);
    if (!data) {
        box.classList.add('hidden');
        return;
    }
    const meta = el('div', { class: 'meta' });
    const risk = Number(data.risk_level || 0);
    const riskClass = risk >= 3 ? 'risk-high' : (risk >= 2 ? 'risk-medium' : 'risk-low');
    [
        `intent: ${data.intent || data.status || 'unknown'}`,
        `risk: ${risk}`,
        data.requires_approval ? 'mobile approval needed' : 'no approval needed',
        `${data.step_count || 0} step(s)`,
    ].forEach((label, index) => {
        const chip = el('span', {
            class: `plan-chip ${index === 1 ? riskClass : ''}`,
            text: label,
        });
        meta.appendChild(chip);
    });
    box.appendChild(meta);
    appendText(box, 'div', data.message || 'Plan preview ready.');
    if (data.plan) {
        const pre = el('pre', { text: JSON.stringify(data.plan, null, 2) });
        box.appendChild(pre);
    }
    renderPlanActionControls(box, data);
    if (data.model_plan) {
        const plan = data.model_plan;
        const modelBox = el('div', { class: 'model-route' });
        appendText(modelBox, 'div', 'Model route', 'memory-title');
        const chips = el('div', { class: 'meta' });
        [
            `budget: ${plan.budget_mode || 'auto'}`,
            `model MB: ${plan.model_budget_mb || 0}`,
            ...(plan.recommended || []).slice(0, 6).map(name => `model: ${name}`),
        ].forEach(label => {
            const chip = el('span', { class: 'plan-chip', text: label });
            chips.appendChild(chip);
        });
        modelBox.appendChild(chips);
        (plan.lanes || []).forEach(lane => {
            const laneModels = (lane.models || []).join(' + ');
            const row = el('div', {
                class: 'progress-step pending',
                text: `${lane.lane || 'lane'}: ${laneModels} (${lane.mode || 'auto'})`,
            });
            modelBox.appendChild(row);
        });
        if (plan.teacher_fallback) {
            appendText(
                modelBox,
                'div',
                `Teacher fallback: ${plan.teacher_fallback.enabled_by_default ? 'on' : 'off'} - ${plan.teacher_fallback.why || ''}`,
                'empty-message'
            );
        }
        box.appendChild(modelBox);
    }
    if (data.execution_graph?.nodes?.length) {
        const graphBox = el('div', { class: 'model-route execution-route' });
        appendText(graphBox, 'div', 'Execution graph', 'memory-title');
        data.execution_graph.nodes.slice(0, 8).forEach(node => {
            const row = el('div', {
                class: `progress-step ${node.type === 'approval' ? 'pending' : 'success'}`,
                text: `${node.type || 'node'}: ${node.objective || node.id || 'step'}`
            });
            graphBox.appendChild(row);
        });
        const validation = data.execution_graph.validation;
        if (validation && validation.ok === false) {
            appendText(
                graphBox,
                'div',
                `Graph warning: ${(validation.errors || []).join('; ')}`,
                'empty-message'
            );
        }
        box.appendChild(graphBox);
    }
    if (data.memory_matches?.length) {
        const memoryBox = el('div', { class: 'command-memory' });
        appendText(memoryBox, 'div', 'Parallel memory matches', 'memory-title');
        data.memory_matches.slice(0, 3).forEach(item => {
            appendText(memoryBox, 'div', item.text || item.command || item.input_text || '', 'memory-item');
        });
        box.appendChild(memoryBox);
    }
    box.classList.remove('hidden');
    scrollChatToBottom();
}

function renderPlanActionControls(box, data) {
    const input = $('#command-text');
    const text = input?.value.trim() || '';
    const steps = data.plan?.steps || [];
    if (!text || !steps.length || data.status === 'local' || data.status === 'failed') return;

    const actions = el('div', { class: 'plan-actions' });
    const label = data.requires_approval ? 'Approve and send' : 'Send this plan';
    const button = el('button', {
        class: data.requires_approval ? 'approve-btn' : 'primary-btn',
        type: 'button',
        text: label,
        onclick: async () => {
            toast(
                data.requires_approval
                    ? 'Sending. Approval card will appear here when the backend requests it.'
                    : 'Sending approved plan to action.',
                'info',
                2400
            );
            await sendCommand();
        },
    });
    actions.appendChild(button);

    if (data.requires_approval) {
        appendText(
            actions,
            'div',
            'This does not bypass safety. It starts the command, then the backend pauses for the inline Approve/Reject card.',
            'plan-action-note'
        );
    } else {
        appendText(actions, 'div', 'Runs the exact command text currently in the composer.', 'plan-action-note');
    }
    box.appendChild(actions);
}

function summarizeRuntime(data) {
    const runtime = data?.runtime;
    const telemetry = data?.telemetry;
    if (!runtime && !telemetry) return 'Planning and safety checks finished';

    let parts = [];
    if (runtime) {
        const tier = runtime.tier || runtime.mode || 'auto';
        const reason = runtime.reason || '';
        parts.push(reason ? `${tier}: ${reason}` : tier);
    }
    if (telemetry) {
        parts.push(`${telemetry.pipeline_ms || 0}ms`);
    }
    const ssdTier = data?.ssd_tier;
    if (ssdTier?.mode) {
        parts.push(`placement: ${ssdTier.mode}`);
    }
    return parts.join(' · ') || 'Planning and safety checks finished';
}

function renderProgress(steps) {
    const box = $('#command-progress');
    if (!box) return;
    clearNode(box);
    if (!steps || steps.length === 0) {
        box.classList.add('hidden');
        return;
    }
    steps.forEach(step => {
        const row = el('div', {
            class: `progress-step ${step.status || 'pending'}`,
            text: step.label || '',
        });
        box.appendChild(row);
    });
    box.classList.remove('hidden');
    scrollChatToBottom();
}

// ─── Approvals ──────────────────────────────────────────────────────────────
async function loadApprovals(options = {}) {
    try {
        const data = await api.approvals.pending();
        const list = $('#approvals-list');
        const approvals = data.approvals || [];
        renderInlineApprovals(approvals);

        if (options.inlineOnly) return approvals;

        clearNode(list);

        if (approvals.length === 0) {
            list.appendChild(emptyMessage('No pending approvals'));
            return approvals;
        }

        approvals.forEach(approval => {
            const card = el('div', { class: 'approval-card' });
            appendText(card, 'h3', approval.action_type);
            appendText(card, 'p', approval.description, 'description');

            if (approval.impact_summary) {
                const impact = el('div', { class: 'impact' });
                appendText(impact, 'strong', 'Impact:');
                appendText(
                    impact,
                    'pre',
                    JSON.stringify(parseJsonSafe(approval.impact_summary), null, 2)
                );
                card.appendChild(impact);
            }

            const actions = el('div', { class: 'approval-actions' });
            const approve = el('button', {
                class: 'approve-btn',
                text: 'Approve',
                onclick: () => resolveApproval(approval.id, true),
            });
            const reject = el('button', {
                class: 'reject-btn',
                text: 'Reject',
                onclick: () => resolveApproval(approval.id, false),
            });
            actions.append(approve, reject);
            card.appendChild(actions);
            list.appendChild(card);
        });
        return approvals;

    } catch (error) {
        console.error('Failed to load approvals:', error);
        return [];
    }
}

function renderInlineApprovals(approvals = []) {
    const box = $('#inline-approvals');
    if (!box) return;
    clearNode(box);
    if (!approvals.length) {
        box.classList.add('hidden');
        return;
    }

    appendText(box, 'div', 'Approval needed', 'inline-approval-title');
    approvals.forEach(approval => {
        const card = el('div', { class: 'inline-approval-card' });
        appendText(card, 'div', approval.action_type || 'Action', 'inline-approval-action');
        appendText(card, 'div', approval.description || 'Approve this action to continue.', 'inline-approval-description');
        if (approval.impact_summary) {
            appendText(card, 'pre', JSON.stringify(parseJsonSafe(approval.impact_summary), null, 2), 'inline-approval-impact');
        }
        const actions = el('div', { class: 'inline-approval-actions' });
        actions.append(
            el('button', {
                class: 'approve-btn',
                type: 'button',
                text: 'Approve',
                onclick: () => resolveApproval(approval.id, true, { source: 'inline' }),
            }),
            el('button', {
                class: 'reject-btn',
                type: 'button',
                text: 'Reject',
                onclick: () => resolveApproval(approval.id, false, { source: 'inline' }),
            })
        );
        card.appendChild(actions);
        box.appendChild(card);
    });
    box.classList.remove('hidden');
    scrollChatToBottom();
}

async function resolveApproval(approvalId, approved, options = {}) {
    let masterKey = null;

    if (approved) {
        masterKey = await prompt('Enter master key (if required):', {
            title: 'Master Key',
            placeholder: 'Master key',
            secure: true,
        });
        if (masterKey === null) return;
    }

    try {
        await api.approvals.resolve(approvalId, approved, masterKey);
        toast(approved ? 'Approval granted' : 'Approval rejected', approved ? 'success' : 'info');
        appendChatMessage(
            'incoming',
            approved ? `Approved request ${approvalId}. Continuing...` : `Rejected request ${approvalId}.`,
            'Approval'
        );
        await loadApprovals(options.source === 'inline' ? { inlineOnly: true } : {});
    } catch (error) {
        toast(`Failed to resolve approval: ${error.message}`, 'error');
    }
}

// ─── History ────────────────────────────────────────────────────────────────
async function loadHistory() {
    try {
        const data = await api.history.list(50);
        state.history = data.history || [];
        renderHistory(state.history);
    } catch (error) {
        console.error('Failed to load history:', error);
        try {
            const cached = await readFromCache('last_history');
            if (cached) renderHistory(cached);
        } catch {}
    }
}

function renderHistory(items) {
    const list = $('#history-list');
    clearNode(list);

    if (!items || items.length === 0) {
        list.appendChild(emptyMessage('No history yet'));
        return;
    }

    const searchBox = el('input', {
        type: 'text',
        placeholder: '🔍 Search history...',
        class: 'history-search',
    });
    let searchTimer = null;
    searchBox.addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(async () => {
            const q = e.target.value.trim();
            if (!q) { renderHistory(state.history); return; }
            const filtered = await postToWorker('FUZZY_SEARCH', {
                query: q,
                items: items.map(h => ({ ...h, input_text: h.input_text || h.command || '' })),
            }, 2000);
            if (filtered && filtered.length > 0) {
                renderHistoryList(list, filtered);
            } else {
                const lower = q.toLowerCase();
                const fallback = items.filter(h =>
                    (h.input_text || '').toLowerCase().includes(lower) ||
                    (h.result || '').toLowerCase().includes(lower)
                );
                renderHistoryList(list, fallback);
            }
        }, 250);
    });
    list.appendChild(searchBox);

    renderHistoryList(list, items);
}

function renderHistoryList(container, items) {
    const searchBox = container.querySelector('.history-search');
    container.innerHTML = '';
    if (searchBox) container.appendChild(searchBox);

    items.forEach(item => {
        const row = el('div', { class: 'history-item' });
        appendText(row, 'div', item.input_text, 'command');
        appendText(
            row,
            'div',
            `${item.status} - ${new Date(item.created_at).toLocaleString()}`,
            `status ${item.status}`
        );
        if (item.result) {
            appendText(row, 'div', item.result, 'history-result');
        }
        if (item._score !== undefined) {
            appendText(row, 'div', `Relevance: ${Math.round(item._score * 100)}%`, 'history-score');
        }
        container.appendChild(row);
    });
}

// ─── Emergency Stop ─────────────────────────────────────────────────────────
async function emergencyStop() {
    const ok = await confirm('EMERGENCY STOP\n\nThis will halt all operations. Continue?', {
        title: 'Emergency Stop',
        confirmLabel: 'STOP NOW',
        cancelLabel: 'Cancel',
        danger: true,
    });
    if (!ok) return;

    try {
        await api.commands.emergencyStop();
        toast('Emergency stop activated', 'warning');
    } catch (error) {
        toast(`Error: ${error.message}`, 'error');
    }
}

// ─── Unpair ─────────────────────────────────────────────────────────────────
async function unpairDevice() {
    const ok = await confirm('Unpair this device? You will need to pair again to use it.', {
        title: 'Unpair Device',
        confirmLabel: 'Unpair',
        cancelLabel: 'Cancel',
        danger: true,
    });
    if (!ok) return;

    session.clear();
    ws.disconnect();
    renderProgress([]);

    showLoginScreen();
    toast('Device unpaired', 'info');
}
