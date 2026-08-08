/* ================================================================
 * sw.js — Screen-AI Service Worker
 *
 * Strategy: Network-first for API calls, Cache-first for static assets.
 * Offline fallback: serve cached shell so the app loads even without server.
 * Commands are saved as drafts only; they are never replayed automatically.
 * ================================================================ */

const CACHE_VERSION = 'screenai-v8-lab-approve-button';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const API_CACHE = `${CACHE_VERSION}-api`;
const OFFLINE_URL = '/remote/offline.html';

const STATIC_ASSETS = [
  '/remote/index.html',
  '/remote/styles.css',
  '/remote/api.js',
  '/remote/app.js',
  '/remote/ui.js',
  '/remote/manifest.json',
  '/remote/login.html',
  '/remote/lab.html',
  '/remote/links.html',
  '/remote/pair.html',
  '/remote/sw.js',
  '/remote/worker.js',
  OFFLINE_URL,
];

/* ─── Install: Pre-cache static assets ─────────────────────── */

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

/* ─── Activate: Clean old caches ───────────────────────────── */

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== STATIC_CACHE && key !== API_CACHE)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

/* ─── Fetch: Network-first for API, Cache-first for assets ── */

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET and WebSocket
  if (event.request.method !== 'GET') return;
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  // API calls: Network-first with cache fallback
  if (url.pathname.startsWith('/command') ||
      url.pathname.startsWith('/approvals') ||
      url.pathname.startsWith('/history') ||
      url.pathname.startsWith('/status') ||
      url.pathname.startsWith('/runtime') ||
      url.pathname.startsWith('/emergency') ||
      url.pathname.startsWith('/auth') ||
      url.pathname.startsWith('/pair')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Static assets: network-first so UI updates ship immediately.
  if (url.pathname.startsWith('/remote/')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Everything else: Network-first
  event.respondWith(networkFirst(event.request));
});

/* ─── Offline Draft Messages ───────────────────────────────── */

self.addEventListener('sync', (event) => {
  if (event.tag === 'screenai-sync-commands') {
    event.waitUntil(Promise.resolve());
  }
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SAVE_COMMAND_DRAFT') {
    saveCommandDraft(event.data.payload);
  }
});

/* ─── Strategies ───────────────────────────────────────────── */

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return caches.match(OFFLINE_URL);
  }
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(API_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;

    // Return offline JSON for API calls
    return new Response(
      JSON.stringify({
        error: 'Offline',
        message: 'Server unreachable. Command saved as a draft for manual resend.',
        offline: true,
      }),
      { headers: { 'Content-Type': 'application/json' }, status: 503 }
    );
  }
}

/* ─── Command Draft Store ──────────────────────────────────── */

const QUEUE_DB = 'screenai-command-drafts';

function openQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(QUEUE_DB, 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('drafts')) {
        db.createObjectStore('drafts', { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function saveCommandDraft(payload) {
  try {
    const db = await openQueueDB();
    const tx = db.transaction('drafts', 'readwrite');
    const req = tx.objectStore('drafts').add({
      ...payload,
      queued_at: Date.now(),
    });
    req.onsuccess = async () => {
      const clients = await self.clients.matchAll();
      clients.forEach((c) =>
        c.postMessage({ type: 'COMMAND_DRAFT_SAVED', id: req.result })
      );
    };
  } catch (err) {
    console.warn('Failed to save command draft:', err);
  }
}
