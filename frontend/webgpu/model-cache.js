/**
 * Fetch a weight blob once and keep it in IndexedDB.
 *
 * Weights are the only large download in this app and they never change without the
 * URL changing, so refetching them on every page load is pure waste — 313 KiB for the
 * VAD, 14.6 MiB for Whisper. The Cache API would also work, but IndexedDB stores the
 * ArrayBuffer directly and does not need a service worker to be useful.
 *
 * Every failure path here is non-fatal. Private browsing, a full quota and a disabled
 * storage backend all surface as exceptions from `indexedDB.open`, and none of them
 * are a reason to refuse to run the model — the fallback is simply a slower load.
 */

const DB_NAME = "graphvoice-models";
const STORE = "weights";

function idbOpen() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbGet(key) {
  try {
    const db = await idbOpen();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly").objectStore(STORE).get(key);
      tx.onsuccess = () => resolve(tx.result ?? null);
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    return null; // private browsing / storage disabled — just refetch
  }
}

async function idbPut(key, value) {
  try {
    const db = await idbOpen();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite").objectStore(STORE).put(value, key);
      tx.onsuccess = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    /* non-fatal: the model still runs, it just downloads again next time */
  }
}

/**
 * Download `url` as an ArrayBuffer, caching it under `key`.
 *
 * Streams the body so `onProgress` can report bytes rather than a spinner. A 14 MiB
 * download on a slow connection is long enough that "loading..." with no number looks
 * like a hang.
 */
export async function fetchCachedBlob(url, { key, label = "weights", onProgress } = {}) {
  const cached = key ? await idbGet(key) : null;
  if (cached) {
    onProgress?.({ stage: "cache", loaded: 1, total: 1 });
    return cached;
  }

  const res = await fetch(url);
  if (!res.ok) throw new Error(`failed to fetch ${label}: ${res.status}`);

  const total = Number(res.headers.get("content-length")) || 0;
  const reader = res.body?.getReader();
  if (!reader) {
    const buf = await res.arrayBuffer();
    if (key) await idbPut(key, buf);
    return buf;
  }

  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.byteLength;
    onProgress?.({ stage: "download", loaded, total });
  }

  const buf = new Uint8Array(loaded);
  let off = 0;
  for (const c of chunks) {
    buf.set(c, off);
    off += c.byteLength;
  }
  if (key) await idbPut(key, buf.buffer);
  return buf.buffer;
}
