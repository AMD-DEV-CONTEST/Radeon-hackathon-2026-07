// api.js — Screen-AI API client
// Centralized HTTP/WebSocket client with retry, error handling, and event hooks.
// Replaces direct fetch() calls scattered throughout app.js.

'use strict';

(function (global) {
    const API_BASE = global.location.origin;
    const WS_SCHEME = global.location.protocol === 'https:' ? 'wss:' : 'ws:';

    // ─── Event Bus ──────────────────────────────────────────────────────────
    // Lightweight pub/sub so UI components can react to API events
    // without tight coupling.
    const listeners = new Map();

    function on(event, handler) {
        if (!listeners.has(event)) listeners.set(event, new Set());
        listeners.get(event).add(handler);
        return () => listeners.get(event).delete(handler);
    }

    function emit(event, payload) {
        const set = listeners.get(event);
        if (!set) return;
        for (const handler of set) {
            try { handler(payload); } catch (e) { console.warn(`[api] listener for ${event} threw:`, e); }
        }
    }

    // ─── Token + Device State ───────────────────────────────────────────────
    const tokenStore = {
        get deviceId() { return sessionStorage.getItem('device_id') || null; },
        get token() { return sessionStorage.getItem('token') || null; },
        get devicePublicKey() { return localStorage.getItem('device_public_key') || null; },
        get trustUntil() { return localStorage.getItem('trust_until') || null; },
        get lastDeviceId() { return localStorage.getItem('last_device_id') || null; },
        set(deviceId, token, publicKey, trustUntil) {
            if (deviceId) sessionStorage.setItem('device_id', deviceId);
            if (token) sessionStorage.setItem('token', token);
            if (deviceId) localStorage.setItem('last_device_id', deviceId);
            if (publicKey) localStorage.setItem('device_public_key', publicKey);
            if (trustUntil) localStorage.setItem('trust_until', trustUntil);
            emit('session:changed', { deviceId, token });
        },
        clear() {
            sessionStorage.removeItem('device_id');
            sessionStorage.removeItem('token');
            localStorage.removeItem('last_device_id');
            localStorage.removeItem('device_public_key');
            localStorage.removeItem('trust_until');
            emit('session:cleared', null);
        },
        hasSession() {
            return !!(sessionStorage.getItem('device_id') && sessionStorage.getItem('token'));
        },
    };

    // ─── HTTP Helpers ───────────────────────────────────────────────────────
    async function request(path, options = {}) {
        const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
        const headers = {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        };
        if (tokenStore.token && !options.skipAuth) {
            headers['Authorization'] = `Bearer ${tokenStore.token}`;
        }

        const controller = new AbortController();
        const timeoutMs = options.timeoutMs ?? 30000;
        const timer = setTimeout(() => controller.abort(), timeoutMs);

        try {
            const response = await fetch(url, {
                ...options,
                headers,
                signal: controller.signal,
            });
            clearTimeout(timer);

            const contentType = response.headers.get('content-type') || '';
            const isJson = contentType.includes('application/json');
            const data = isJson ? await response.json() : await response.text();

            if (!response.ok) {
                const error = new Error(
                    (data && data.detail) || response.statusText || `HTTP ${response.status}`
                );
                error.status = response.status;
                error.data = data;
                emit('api:error', { path, status: response.status, error });
                throw error;
            }

            emit('api:success', { path, status: response.status, data });
            return data;
        } catch (err) {
            clearTimeout(timer);
            if (err.name === 'AbortError') {
                const error = new Error(`Request to ${path} timed out after ${timeoutMs}ms`);
                error.status = 0;
                emit('api:error', { path, status: 0, error });
                throw error;
            }
            emit('api:error', { path, status: err.status || 0, error: err });
            throw err;
        }
    }

    function get(path, options = {}) { return request(path, { ...options, method: 'GET' }); }
    function post(path, body, options = {}) {
        return request(path, {
            ...options,
            method: 'POST',
            body: body == null ? undefined : JSON.stringify(body),
        });
    }

    // ─── Retry Wrapper ──────────────────────────────────────────────────────
    async function withRetry(fn, { attempts = 3, baseDelayMs = 400, shouldRetry } = {}) {
        let lastError;
        for (let i = 0; i < attempts; i++) {
            try {
                return await fn(i);
            } catch (err) {
                lastError = err;
                const retry = shouldRetry ? shouldRetry(err, i) : (err.status >= 500 || err.status === 0);
                if (!retry || i === attempts - 1) throw err;
                const delay = baseDelayMs * Math.pow(2, i);
                await new Promise(r => setTimeout(r, delay));
            }
        }
        throw lastError;
    }

    // ─── Pairing API ────────────────────────────────────────────────────────
    const pairing = {
        async pairWithCode(code, deviceName, trust = false) {
            const data = await post('/pair', { code, device_name: deviceName });
            tokenStore.set(data.device_id, data.token, getOrCreateDevicePublicKey(), null);
            if (trust) {
                try {
                    await post(`/pair/trust?device_id=${data.device_id}&days=30`);
                    tokenStore.trustUntil && (() => {})();
                    localStorage.setItem('trust_until',
                        new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString());
                } catch (e) { console.warn('[api] trust request failed:', e); }
            }
            emit('pair:success', data);
            return data;
        },

        async getPairingCode() {
            return get('/pair/code');
        },

        async createQRSession() {
            return get('/pair/qr');
        },

        async completeQRSession(pairingId, deviceName, trust = true) {
            const devicePublicKey = getOrCreateDevicePublicKey();
            const data = await post('/pair/qr/complete', {
                pairing_id: pairingId,
                device_public_key: devicePublicKey,
                device_name: deviceName,
                trust_device: trust,
            });
            if (!data.token) throw new Error('Pairing response did not include a session token');
            tokenStore.set(data.device_id, data.token, devicePublicKey, data.trust_until);
            emit('pair:success', data);
            return data;
        },

        async trustDevice(deviceId, days = 30) {
            return post(`/pair/trust?device_id=${deviceId}&days=${days}`);
        },

        async reconnectTrusted() {
            const deviceId = tokenStore.lastDeviceId;
            const devicePublicKey = tokenStore.devicePublicKey;
            if (!deviceId || !devicePublicKey) {
                throw new Error('No trusted device found. Pair first.');
            }
            const data = await post('/pair/trusted', {
                device_id: deviceId,
                device_public_key: devicePublicKey,
            });
            if (!data.token) throw new Error('Trusted reconnect did not return a token');
            tokenStore.set(
                data.device_id,
                data.token,
                devicePublicKey,
                data.trust_until || tokenStore.trustUntil
            );
            emit('pair:success', data);
            return data;
        },

        async rotateToken() {
            if (!tokenStore.deviceId || !tokenStore.token) {
                throw new Error('No active session to rotate');
            }
            const data = await post('/auth/rotate', {
                device_id: tokenStore.deviceId,
                old_token: tokenStore.token,
            });
            sessionStorage.setItem('token', data.new_token);
            emit('session:rotated', { token: data.new_token });
            return data;
        },

        async biometricChallenge() {
            return post('/auth/biometric/challenge', {});
        },

        async verifyBiometric(challengeId, response) {
            return post('/auth/biometric/verify', {
                challenge_id: challengeId,
                response,
            });
        },
    };

    // ─── Command API ────────────────────────────────────────────────────────
    const commands = {
        async send(text) {
            if (!text || !text.trim()) throw new Error('Command text is empty');
            return post('/command', {
                text: text.trim(),
                device_id: tokenStore.deviceId,
            }, { timeoutMs: 310000 });
        },

        async preview(text) {
            if (!text || !text.trim()) throw new Error('Command text is empty');
            return post('/command/preview', {
                text: text.trim(),
                device_id: tokenStore.deviceId,
            }, { timeoutMs: 60000 });
        },

        async emergencyStop() {
            return post(`/emergency/stop?device_id=${encodeURIComponent(tokenStore.deviceId || '')}`);
        },
    };

    // ─── Approvals API ──────────────────────────────────────────────────────
    const approvals = {
        async pending() {
            return get(`/approvals/pending?device_id=${encodeURIComponent(tokenStore.deviceId || '')}`);
        },
        async resolve(approvalId, approved, masterKey = null) {
            return post(`/approvals/resolve?device_id=${encodeURIComponent(tokenStore.deviceId || '')}`, {
                approval_id: approvalId,
                approved,
                master_key: masterKey,
            });
        },
    };

    // ─── History API ────────────────────────────────────────────────────────
    const history = {
        async list(limit = 50) {
            return get(`/history?limit=${limit}&device_id=${encodeURIComponent(tokenStore.deviceId || '')}`);
        },
    };

    // ─── Runtime + Status API ────────────────────────────────────────────────
    const runtime = {
        async status() { return get('/status'); },
        async runtime() { return get('/runtime'); },
    };

    // ─── Skills API ─────────────────────────────────────────────────────────
    const skills = {
        async list(domain = null) {
            const qs = domain ? `?domain=${encodeURIComponent(domain)}` : '';
            return get(`/skills${qs}`);
        },
        async execute(skillId, inputs = {}) {
            return post('/skills/execute', { skill_id: skillId, inputs });
        },
        async metrics(skillId) {
            return get(`/skills/${encodeURIComponent(skillId)}/metrics`);
        },
    };

    // ─── Tasks API ──────────────────────────────────────────────────────────
    const tasks = {
        async create(spec) { return post('/tasks', spec); },
        async get(taskId) { return get(`/tasks/${encodeURIComponent(taskId)}`); },
        async cancel(taskId) { return post(`/tasks/${encodeURIComponent(taskId)}/cancel`, {}); },
    };

    // ─── Memory API ─────────────────────────────────────────────────────────
    const memory = {
        async remember(key, value, tags = []) {
            return post('/memory/remember', { key, value, tags });
        },
        async recall(key) { return get(`/memory/recall?key=${encodeURIComponent(key)}`); },
        async search(query) { return get(`/memory/search?q=${encodeURIComponent(query)}`); },
    };

    // ─── Workflows API ──────────────────────────────────────────────────────
    const workflows = {
        async save(name, steps) { return post('/workflows', { name, steps }); },
        async list() { return get('/workflows'); },
        async match(command) { return get(`/workflows/match?command=${encodeURIComponent(command)}`); },
    };

    // ─── WebSocket Manager ──────────────────────────────────────────────────
    const wsManager = {
        socket: null,
        reconnectTimer: null,
        intentionalClose: false,
        listeners: new Set(),

        connect() {
            if (!tokenStore.deviceId || !tokenStore.token) {
                emit('ws:state', { state: 'offline' });
                return;
            }
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
            }
            if (this.socket &&
                (this.socket.readyState === WebSocket.OPEN ||
                 this.socket.readyState === WebSocket.CONNECTING)) {
                return;
            }

            try {
                emit('ws:state', { state: 'connecting' });
                const params = new URLSearchParams({
                    device_id: tokenStore.deviceId || '',
                    token: tokenStore.token || '',
                });
                this.socket = new WebSocket(`${WS_SCHEME}//${global.location.host}/ws?${params.toString()}`);

                this.socket.onopen = () => {
                    emit('ws:state', { state: 'online' });
                    for (const fn of this.listeners) { try { fn({ type: 'open' }); } catch {} }
                };

                this.socket.onmessage = (event) => {
                    let data;
                    try { data = JSON.parse(event.data); } catch { return; }
                    emit('ws:message', data);
                    for (const fn of this.listeners) { try { fn(data); } catch {} }
                };

                this.socket.onclose = () => {
                    this.socket = null;
                    emit('ws:state', { state: 'offline' });
                    if (this.intentionalClose || !tokenStore.hasSession()) return;
                    this.reconnectTimer = setTimeout(() => this.connect(), 5000);
                };

                this.socket.onerror = () => {
                    emit('ws:state', { state: 'error' });
                };
            } catch (err) {
                emit('ws:state', { state: 'offline' });
                console.error('[api] WebSocket connect failed:', err);
            }
        },

        disconnect() {
            this.intentionalClose = true;
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
            }
            if (this.socket) {
                this.socket.onclose = null;
                this.socket.close();
                this.socket = null;
            }
            emit('ws:state', { state: 'offline' });
        },

        onMessage(handler) {
            this.listeners.add(handler);
            return () => this.listeners.delete(handler);
        },
    };

    // ─── Device Key Helper ──────────────────────────────────────────────────
    function getOrCreateDevicePublicKey() {
        let key = localStorage.getItem('device_public_key');
        if (key) return key;

        const bytes = new Uint8Array(32);
        const browserCrypto = global.crypto || global.msCrypto;
        if (browserCrypto?.getRandomValues) {
            browserCrypto.getRandomValues(bytes);
        } else {
            for (let i = 0; i < bytes.length; i++) {
                bytes[i] = Math.floor(Math.random() * 256);
            }
        }

        let binary = '';
        for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        key = btoa(binary);
        localStorage.setItem('device_public_key', key);
        return key;
    }

    // ─── Public API ─────────────────────────────────────────────────────────
    global.ScreenAI = {
        api: {
            request, get, post, withRetry,
            pairing, commands, approvals, history, runtime,
            skills, tasks, memory, workflows,
        },
        ws: wsManager,
        session: tokenStore,
        events: { on, emit },
        device: {
            getOrCreateDevicePublicKey,
            getName() {
                const ua = navigator.userAgent;
                if (/iPhone/.test(ua)) return 'iPhone';
                if (/iPad/.test(ua)) return 'iPad';
                if (/Android/.test(ua)) return 'Android Phone';
                return 'Mobile Device';
            },
        },
        constants: { API_BASE, WS_SCHEME },
    };
})(window);
