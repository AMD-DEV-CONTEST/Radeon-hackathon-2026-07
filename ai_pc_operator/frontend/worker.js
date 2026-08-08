/* ================================================================
 * worker.js — Screen-AI Web Worker
 *
 * Offloads CPU-intensive work from the main thread:
 *   - Fuzzy text search over cached command history
 *   - JSON parsing and filtering
 *   - LocalIndexedDB caching
 *   - Progress event debouncing
 *   - Crypto operations for device key management
 * ================================================================ */

/* ─── Message Handler ──────────────────────────────────────── */

self.onmessage = async function (e) {
  const { type, id, payload } = e.data;

  try {
    switch (type) {
      case 'FUZZY_SEARCH':
        self.postMessage({ type, id, result: fuzzySearch(payload.query, payload.items) });
        break;

      case 'FILTER_HISTORY':
        self.postMessage({ type, id, result: filterHistory(payload.history, payload.filters) });
        break;

      case 'PARSE_COMMANDS':
        self.postMessage({ type, id, result: parseCommands(payload.raw) });
        break;

      case 'DEBOUNCE_PROGRESS':
        debounceProgress(type, id, payload);
        break;

      case 'GENERATE_DEVICE_KEY':
        self.postMessage({ type, id, result: await generateDeviceKey(payload.deviceId) });
        break;

      case 'ENCRYPT_TOKEN':
        self.postMessage({ type, id, result: await encryptPayload(payload.token, payload.key) });
        break;

      case 'COMPUTE_SHA256':
        self.postMessage({ type, id, result: await computeSHA256(payload.data) });
        break;

      case 'INDEXEDDB_CACHE':
        await indexedDBCache(payload);
        self.postMessage({ type, id, result: { ok: true } });
        break;

      case 'INDEXEDDB_READ':
        const cached = await indexedDBRead(payload.key);
        self.postMessage({ type, id, result: cached });
        break;

      case 'BATCH_REDACT':
        self.postMessage({ type, id, result: batchRedact(payload.texts, payload.patterns) });
        break;

      case 'MODEL_ROUTE_HINT':
        self.postMessage({ type, id, result: modelRouteHint(payload.text, payload.memory || []) });
        break;

      case 'MEMORY_SCORE_COMMAND':
        self.postMessage({ type, id, result: scoreCommandMemory(payload.text, payload.memory || []) });
        break;

      default:
        self.postMessage({ type, id, error: `Unknown type: ${type}` });
    }
  } catch (err) {
    self.postMessage({ type, id, error: err.message });
  }
};

/* ─── Fuzzy Text Search ────────────────────────────────────── */

function fuzzySearch(query, items) {
  if (!query || !items || !items.length) return [];

  const q = query.toLowerCase().trim();
  const scored = [];

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const text = (item.input_text || item.command || item.text || '').toLowerCase();
    const score = computeFuzzyScore(q, text);
    if (score > 0.1) {
      scored.push({ ...item, _score: score });
    }
  }

  scored.sort((a, b) => b._score - a._score);
  return scored.slice(0, 50);
}

function computeFuzzyScore(query, target) {
  if (!query || !target) return 0;
  if (query === target) return 1.0;

  // Exact substring
  if (target.includes(query)) return 0.95;

  // Prefix match
  if (target.startsWith(query)) return 0.90;

  // All query characters in order (subsequence)
  let qi = 0;
  let matched = 0;
  let lastPos = -1;
  for (let ti = 0; ti < target.length && qi < query.length; ti++) {
    if (target[ti] === query[qi]) {
      matched++;
      lastPos = ti;
      qi++;
    }
  }
  if (qi === query.length) {
    const spread = lastPos - (lastPos - matched + 1);
    const spreadPenalty = Math.min(spread / 20, 0.3);
    return Math.max(0.1, (matched / query.length) * (1 - spreadPenalty));
  }

  // Character overlap
  const qSet = new Set(query);
  let overlap = 0;
  for (const c of qSet) {
    if (target.includes(c)) overlap++;
  }
  return (overlap / qSet.size) * 0.3;
}

/* ─── History Filtering ────────────────────────────────────── */

function filterHistory(history, filters) {
  if (!history) return [];

  let result = history;

  if (filters.status) {
    result = result.filter((h) => h.status === filters.status);
  }
  if (filters.intent) {
    const intentLower = filters.intent.toLowerCase();
    result = result.filter((h) =>
      (h.intent || '').toLowerCase().includes(intentLower)
    );
  }
  if (filters.device_id) {
    result = result.filter((h) => h.device_id === filters.device_id);
  }
  if (filters.from_date) {
    const from = new Date(filters.from_date).getTime();
    result = result.filter((h) => new Date(h.created_at).getTime() >= from);
  }
  if (filters.to_date) {
    const to = new Date(filters.to_date).getTime();
    result = result.filter((h) => new Date(h.created_at).getTime() <= to);
  }
  if (filters.search) {
    const s = filters.search.toLowerCase();
    result = result.filter(
      (h) =>
        (h.input_text || '').toLowerCase().includes(s) ||
        (h.result || '').toLowerCase().includes(s)
    );
  }

  return result;
}

/* ─── Command Parsing ──────────────────────────────────────── */

function parseCommands(raw) {
  if (!raw) return [];

  try {
    const lines = raw.split('\n').filter(Boolean);
    return lines.map((line, idx) => {
      const parts = line.split('|').map((p) => p.trim());
      return {
        index: idx,
        text: parts[0] || '',
        status: parts[1] || 'unknown',
        timestamp: parts[2] || null,
      };
    });
  } catch {
    return [];
  }
}

/* ─── Local Model Route + Memory Hints ─────────────────────── */

function modelRouteHint(text, memory) {
  const lower = (text || '').toLowerCase();
  const lanes = [];
  const models = new Set(['rule-planner', 'native-core']);

  if (/\b(screen|button|click|window|ui|ocr|read|scan)\b/.test(lower)) {
    lanes.push({
      lane: 'fast-perception',
      models: ['ocr-det-v3', 'ocr-rec-english'],
      mode: 'parallel',
    });
    models.add('ocr-mobile');
    models.add('ui-detector-int8');
  }

  if (/\b(chrome|browser|search|website|webpage|download|research|google)\b/.test(lower)) {
    lanes.push({
      lane: 'browser-tools',
      models: ['browser-warmup'],
      mode: 'warm-import',
    });
    models.add('browser-warmup');
  }

  if (/\b(login|password|passkey|credential|vault|unlock)\b/.test(lower)) {
    lanes.push({
      lane: 'secure-vault',
      models: ['vault-crypto'],
      mode: 'resident',
    });
    models.add('vault-crypto');
  }

  if (/\b(plan|compare|analyze|summarize|decide|complex|unknown)\b/.test(lower)) {
    lanes.push({
      lane: 'reasoning',
      models: ['qwen-1.5b-q4'],
      mode: 'ssd-mmap-on-demand',
    });
    models.add('qwen-1.5b-q4');
  }

  const memoryMatches = scoreCommandMemory(text, memory).slice(0, 3);
  return {
    source: 'phone-worker',
    lanes: lanes.length ? lanes : [{ lane: 'tier0-rules', models: ['rule-planner'], mode: 'resident' }],
    recommended: Array.from(models),
    memory_matches: memoryMatches,
  };
}

function scoreCommandMemory(text, memory) {
  const query = (text || '').trim().toLowerCase();
  if (!query || !Array.isArray(memory)) return [];
  return memory
    .map((item) => {
      const target = (item.text || item.command || item.input_text || '').toLowerCase();
      return { ...item, _score: computeFuzzyScore(query, target) };
    })
    .filter((item) => item._score > 0.2)
    .sort((a, b) => b._score - a._score)
    .slice(0, 8);
}

/* ─── Debounced Progress ───────────────────────────────────── */

const _progressTimers = {};

function debounceProgress(type, id, payload) {
  if (_progressTimers[id]) clearTimeout(_progressTimers[id]);

  _progressTimers[id] = setTimeout(() => {
    self.postMessage({ type: 'PROGRESS_UPDATE', id, result: payload });
    delete _progressTimers[id];
  }, payload.delay || 100);
}

/* ─── Crypto Operations ────────────────────────────────────── */

async function generateDeviceKey(deviceId) {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    enc.encode(deviceId),
    { name: 'PBKDF2' },
    false,
    ['deriveKey']
  );

  const key = await crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: enc.encode('screenai-device-salt-v1'),
      iterations: 100000,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    true,
    ['encrypt', 'decrypt']
  );

  const rawKey = await crypto.subtle.exportKey('raw', key);
  return btoa(String.fromCharCode(...new Uint8Array(rawKey)));
}

async function encryptPayload(data, keyB64) {
  const enc = new TextEncoder();
  const rawKey = Uint8Array.from(atob(keyB64), (c) => c.charCodeAt(0));

  const key = await crypto.subtle.importKey(
    'raw',
    rawKey,
    { name: 'AES-GCM' },
    false,
    ['encrypt']
  );

  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    enc.encode(data)
  );

  return {
    iv: btoa(String.fromCharCode(...iv)),
    data: btoa(String.fromCharCode(...new Uint8Array(encrypted))),
  };
}

async function computeSHA256(data) {
  const enc = new TextEncoder();
  const hash = await crypto.subtle.digest('SHA-256', enc.encode(data));
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

/* ─── IndexedDB Cache ──────────────────────────────────────── */

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('screenai-cache', 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('kv')) {
        db.createObjectStore('kv');
      }
      if (!db.objectStoreNames.contains('commands')) {
        db.createObjectStore('commands', { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function indexedDBCache(payload) {
  const db = await openDB();
  const tx = db.transaction('kv', 'readwrite');
  tx.objectStore('kv').put(payload.value, payload.key);
  return new Promise((resolve) => { tx.oncomplete = resolve; });
}

async function indexedDBRead(key) {
  const db = await openDB();
  const tx = db.transaction('kv', 'readonly');
  const req = tx.objectStore('kv').get(key);
  return new Promise((resolve) => {
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => resolve(null);
  });
}

/* ─── Batch Redaction (off main thread) ────────────────────── */

function batchRedact(texts, patterns) {
  if (!texts || !patterns) return texts;

  const regexes = patterns.map((p) => new RegExp(p.pattern, p.flags || 'gi'));

  return texts.map((text) => {
    let result = text;
    for (const rx of regexes) {
      result = result.replace(rx, '[REDACTED]');
    }
    return result;
  });
}
