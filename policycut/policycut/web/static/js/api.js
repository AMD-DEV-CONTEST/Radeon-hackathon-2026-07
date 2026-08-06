/* PolicyCut — shared API client + small DOM/format helpers. Vanilla JS, no deps. */
"use strict";

/** querySelector shorthand. */
function qs(sel, root) { return (root || document).querySelector(sel); }
/** querySelectorAll shorthand -> Array. */
function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }
/** URL query parameter of the current page. */
function param(name) { return new URLSearchParams(location.search).get(name); }

/** HTML-escape untrusted strings before inserting into innerHTML. */
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** Format seconds as MM:SS.mmm */
function fmtTime(s) {
  if (!isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  const whole = Math.floor(sec);
  const ms = Math.round((sec - whole) * 1000);
  const mm = String(m).padStart(2, "0");
  const ss = String(whole).padStart(2, "0");
  const mmm = String(Math.min(ms, 999)).padStart(3, "0");
  return `${mm}:${ss}.${mmm}`;
}

/** Parse "MM:SS.mmm", "SS.mmm" or plain seconds -> float seconds (NaN if invalid). */
function parseTimecode(str) {
  const t = String(str || "").trim();
  if (!t) return NaN;
  const parts = t.split(":");
  if (parts.length === 1) return parseFloat(parts[0]);
  if (parts.length === 2) {
    const m = parseInt(parts[0], 10);
    const s = parseFloat(parts[1]);
    if (isNaN(m) || isNaN(s)) return NaN;
    return m * 60 + s;
  }
  if (parts.length === 3) {
    const h = parseInt(parts[0], 10), m = parseInt(parts[1], 10), s = parseFloat(parts[2]);
    if (isNaN(h) || isNaN(m) || isNaN(s)) return NaN;
    return h * 3600 + m * 60 + s;
  }
  return NaN;
}

/** Format a byte count for humans. */
function fmtBytes(n) {
  if (!isFinite(n) || n < 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0, v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

/** Format an ISO timestamp as a short local date/time. */
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/** Show a transient toast. kind: "info" | "success" | "error". */
function toast(msg, kind) {
  let box = qs("#toast-container");
  if (!box) {
    box = document.createElement("div");
    box.id = "toast-container";
    document.body.appendChild(box);
  }
  const el = document.createElement("div");
  el.className = "toast " + (kind || "info");
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity 0.25s";
    setTimeout(() => el.remove(), 300);
  }, 3800);
}

const API = (() => {
  const BASE = "/api/v1";

  async function request(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(BASE + path, opts);
    } catch (netErr) {
      const e = new Error("Network error — is the PolicyCut server running?");
      e.status = 0;
      throw e;
    }
    if (res.status === 204) return null;
    let data = null;
    const text = await res.text();
    if (text) {
      try { data = JSON.parse(text); } catch (_) { data = text; }
    }
    if (!res.ok) {
      let msg = `Request failed (${res.status})`;
      if (data && typeof data === "object" && data.detail) {
        msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      } else if (typeof data === "string" && data) {
        msg = data.slice(0, 200);
      }
      const e = new Error(msg);
      e.status = res.status;
      e.body = data;
      throw e;
    }
    return data;
  }

  /**
   * Multipart file upload with progress, via XHR (fetch has no upload progress).
   * onProgress receives a float 0..1.
   */
  function upload(path, file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", BASE + path);
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && onProgress) onProgress(ev.loaded / ev.total);
      };
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText || "null"); } catch (_) { data = xhr.responseText; }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data);
        } else {
          let msg = `Upload failed (${xhr.status})`;
          if (data && typeof data === "object" && data.detail) {
            msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
          }
          const e = new Error(msg);
          e.status = xhr.status;
          e.body = data;
          reject(e);
        }
      };
      xhr.onerror = () => reject(new Error("Upload failed — network error"));
      xhr.onabort = () => reject(new Error("Upload cancelled"));
      const form = new FormData();
      form.append("file", file, file.name);
      xhr.send(form);
      // expose for callers that want to cancel
      upload.lastXhr = xhr;
    });
  }

  const TERMINAL = new Set(["done", "error", "cancelled", "server_restarted"]);

  /**
   * Subscribe to a job SSE stream with auto-reconnect and a 2s polling fallback.
   * `path` is e.g. "/jobs/j_abc/events" (relative to /api/v1).
   * onMsg(job) fires on every update; onDone(job) once when terminal; onErr(err)
   * on unrecoverable transport failure (polling keeps trying, so this is rare).
   * Returns { close() }.
   */
  function sse(path, onMsg, onDone, onErr) {
    const pollPath = path.replace(/\/events\/?$/, "");
    let es = null;
    let pollTimer = null;
    let closed = false;
    let finished = false;
    let esFailures = 0;
    let lastPayload = "";

    function finish(job) {
      if (finished || closed) return;
      finished = true;
      stopAll();
      if (onDone) onDone(job);
    }

    function stopAll() {
      if (es) { try { es.close(); } catch (_) {} es = null; }
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function handleJob(job) {
      if (closed || finished || !job) return;
      const payload = JSON.stringify([job.status, job.stage, job.progress, job.message]);
      if (payload !== lastPayload) {
        lastPayload = payload;
        if (onMsg) onMsg(job);
      }
      if (TERMINAL.has(job.status)) finish(job);
    }

    function startPolling() {
      if (pollTimer || closed || finished) return;
      pollTimer = setInterval(async () => {
        if (closed || finished) return;
        try {
          const job = await request("GET", pollPath);
          handleJob(job);
        } catch (e) {
          if (e.status === 404) { stopAll(); if (onErr) onErr(e); }
          // transient network errors: keep polling
        }
      }, 2000);
    }

    function startES() {
      if (typeof EventSource === "undefined") { startPolling(); return; }
      try {
        es = new EventSource(BASE + path);
      } catch (_) {
        startPolling();
        return;
      }
      const onData = (ev) => {
        esFailures = 0;
        if (!ev.data) return;
        try { handleJob(JSON.parse(ev.data)); } catch (_) {}
      };
      es.addEventListener("progress", onData);
      es.addEventListener("message", onData);
      es.addEventListener("done", async (ev) => {
        let job = null;
        if (ev.data) { try { job = JSON.parse(ev.data); } catch (_) {} }
        if (!job) { try { job = await request("GET", pollPath); } catch (_) {} }
        if (job) handleJob(job);
        if (!finished) finish(job);
      });
      es.onopen = () => {
        esFailures = 0;
        // SSE healthy again: polling no longer needed
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      };
      es.onerror = () => {
        esFailures += 1;
        // EventSource reconnects on its own; run the polling fallback in
        // parallel so progress keeps flowing, and give up on SSE entirely
        // after repeated failures.
        startPolling();
        if (esFailures >= 5 && es) { try { es.close(); } catch (_) {} es = null; }
      };
    }

    startES();

    return {
      close() {
        closed = true;
        stopAll();
      },
    };
  }

  return {
    base: BASE,
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, b),
    patch: (p, b) => request("PATCH", p, b),
    put: (p, b) => request("PUT", p, b),
    del: (p) => request("DELETE", p),
    upload,
    sse,
  };
})();
